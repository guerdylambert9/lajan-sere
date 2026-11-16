"""Forex short selling, pairs with the dollar first (USD/MXN), the two pair sets, and the
dashboard's choices: the stop-loss, the pairs and short selling, each with its warnings."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from tests.helpers import ConstantWeights, MutableClock, make_ctx
from tests.test_forex import (
    ACCOUNT,
    FOUR_PAIRS,
    FRIDAY,
    PAIRS,
    THURSDAY,
    FakeOanda,
    approve_pending,
    forex_ctx,
    ny,
    pair_frame,
    stops,
)
from trader import ledger, money, preferences
from trader.api.app import create_app
from trader.assets import AssetRules, price_decimals
from trader.backtest import BacktestConfig, run_backtest
from trader.broker.fake import FakeBroker
from trader.broker.oanda_broker import OandaBroker, OandaClient
from trader.config import PAIR_SETS, Settings
from trader.models import AccountState, IntentKind, OrderIntent, Position, ProposalStatus, Side
from trader.planner import plan_intents
from trader.risk.engine import RiskContext, check_order
from trader.risk.limits import RiskLimits
from trader.services.execution import submit_approved
from trader.services.pipeline import run_nightly
from trader.services.recommendations import build_recommendations
from trader.services.reconcile import reconcile
from trader.strategies import TrendFollowing, get_strategy

SHORTS = RiskLimits.from_settings(
    Settings(_env_file=None, asset_class="forex", allow_shorts=True, **FOUR_PAIRS)
)
EXOTIC = PAIR_SETS["exotic"]["universe"].split(",")


def account(cash: float = 100_000, **positions: Position) -> AccountState:
    return AccountState(
        equity=100_000,
        cash=cash,
        buying_power=cash,
        day_start_equity=100_000,
        peak_equity=100_000,
        positions=positions,
    )


def risk_ctx() -> RiskContext:
    return RiskContext(now=ny(FRIDAY, 9, 50), universe=set(PAIRS) | {"USD/MXN", "USD/JPY"})


def codes(intent: OrderIntent, state: AccountState, limits: RiskLimits = SHORTS) -> set[str]:
    return {v.code for v in check_order(intent, state, limits, risk_ctx()).violations}


def short_entry(symbol: str = "EUR/USD", qty: float = 20_000, limit: float = 1.1, stop: float | None = 1.133):
    return OrderIntent(
        symbol=symbol,
        side=Side.SELL,
        kind=IntentKind.ENTRY,
        qty=qty,
        limit_price=limit,
        stop_price=stop,
        client_order_id=f"tpF-20261112-{symbol.replace('/', '')}-short",
    )


# --------------------------------------------------------------------- counting in dollars


def test_dollars_for_pairs_either_way_round():
    # EUR/USD: a unit is a euro, priced in dollars.
    assert money.value("EUR/USD", 10_000, 1.10, 1.12) == pytest.approx(11_200)
    assert money.pnl("EUR/USD", -10_000, 1.10, 1.12) == pytest.approx(-200)  # a short loses as it rises
    assert money.value("EUR/USD", -10_000, 1.10, 1.08) == pytest.approx(11_200)  # and gains as it falls
    # USD/MXN: a unit is a dollar, priced in pesos; the profit comes in pesos.
    assert money.notional("USD/MXN", 10_000, 18.0) == 10_000
    assert money.pnl("USD/MXN", 10_000, 18.0, 18.9) == pytest.approx(10_000 * 0.9 / 18.9)
    assert money.value("USD/MXN", -10_000, 18.0, 18.9) == pytest.approx(10_000 * 18.0 / 18.9)
    assert money.loss_at("USD/MXN", 10_000, 18.0, 17.1) == pytest.approx(10_000 * 0.9 / 17.1)
    # Shares and coins are untouched: qty x price.
    assert money.value("SPY", 3, 400, 410) == 1_230 and money.unit_cost("BTC/USD", 50_000) == 50_000
    position = Position(symbol="USD/JPY", qty=-1_000, avg_entry_price=150.0, current_price=145.0)
    assert position.is_short and position.exposure == 1_000 and position.cost_basis == 1_000
    assert position.unrealized_pl == pytest.approx(1_000 * 5 / 145)


def test_dollar_first_pairs_and_their_price_steps():
    rules = AssetRules(forex=True)
    assert rules.lot("USD/JPY").price_tick == 0.001 and rules.lot("USD/CZK").price_tick == 0.0001
    assert rules.lot("USD/MXN").price_tick == 0.00001 and price_decimals("USD/HUF") == 3
    assert rules.price_up("USD/JPY", 150.12345) == 150.124
    Settings(_env_file=None, asset_class="forex", universe="USD/MXN,EUR/USD", benchmark="USD/MXN")
    with pytest.raises(ValueError, match="US dollar on one side"):
        Settings(_env_file=None, asset_class="forex", universe="EUR/GBP")


# --------------------------------------------------------------------- the strategy and the planner


def test_trend_sells_short_below_its_average_only_when_asked():
    frame = pair_frame()
    long_only = TrendFollowing(20).target_weights(frame).iloc[-1]
    both = TrendFollowing(20, shorts=True).target_weights(frame).iloc[-1]
    assert long_only["AUD/USD"] == 0 and both["AUD/USD"] == -0.25  # AUD slides
    assert long_only["EUR/USD"] == both["EUR/USD"] == 0.25
    assert both.abs().sum() <= 1
    assert TrendFollowing(200, shorts=True).params() == {"window": 200, "shorts": True}
    assert TrendFollowing(200).params() == {"window": 200}  # old reports keep matching
    assert all(v.shorts for v in TrendFollowing(200, shorts=True).variants())
    assert "sell it short" in TrendFollowing(200, shorts=True).rule_text()
    with pytest.raises(ValueError, match="only buys"):
        get_strategy("momentum", shorts=True)


def test_planner_opens_shorts_with_stops_above():
    prices = {"EUR/USD": 1.10, "GBP/USD": 1.31}
    targets = {"EUR/USD": -0.25, "GBP/USD": 0.25}
    intents = plan_intents(
        targets, prices, account(), SHORTS, PAIRS, THURSDAY, "tpF", rules=AssetRules(forex=True)
    )
    short, buy = intents
    assert (short.side, short.kind, short.action) == (Side.SELL, IntentKind.ENTRY, "short")
    assert short.limit_price == 1.0989 and short.stop_price == pytest.approx(1.0989 * 1.03, abs=1e-5)
    assert short.stop_price > short.limit_price and short.client_order_id == "tpF-20261112-EURUSD-short"
    assert short.qty == 22_750 and short.notional <= 25_000  # a quarter of the account, fully paid for
    assert buy.side == Side.BUY and buy.stop_price < buy.limit_price

    skipped: dict[str, str] = {}
    off = RiskLimits.from_settings(Settings(_env_file=None, asset_class="forex", **FOUR_PAIRS))
    assert (
        plan_intents(targets, prices, account(), off, PAIRS, THURSDAY, "tpF", skipped=skipped)[0].side
        == Side.BUY
    )
    assert skipped["EUR/USD"] == "Short selling is off."


def test_planner_covers_shorts_and_closes_before_turning():
    short = Position(symbol="EUR/USD", qty=-20_000, avg_entry_price=1.10, current_price=1.08)
    long = Position(symbol="GBP/USD", qty=10_000, avg_entry_price=1.30, current_price=1.31)
    state = account(cash=69_000, **{"EUR/USD": short, "GBP/USD": long})
    targets = {"EUR/USD": 0.0, "GBP/USD": -0.25}  # the short's signal ends; the long's turns short
    intents = plan_intents(targets, {"EUR/USD": 1.08, "GBP/USD": 1.31}, state, SHORTS, PAIRS, FRIDAY, "tpF")
    cover, sell = sorted(intents, key=lambda i: i.symbol)
    assert (cover.action, cover.qty, cover.limit_price) == ("cover", 20_000, 1.08108)
    assert cover.client_order_id == "tpF-20261113-EURUSD-cover"
    assert (sell.action, sell.qty) == ("sell", 10_000)  # the short opens on a later day
    assert [i.kind for i in intents] == [IntentKind.EXIT, IntentKind.EXIT]


def test_planner_sizes_dollar_first_pairs_in_dollars_and_inside_the_risk_limit():
    rules = AssetRules(forex=True)
    intents = plan_intents(
        {"USD/MXN": 0.25}, {"USD/MXN": 18.0}, account(), SHORTS, ["USD/MXN"], THURSDAY, "tpF", rules=rules
    )
    [buy] = intents
    assert buy.qty == 25_000 and buy.notional == 25_000  # a unit of USD/MXN is one dollar
    # A 10% stop on a long USD/MXN loses 10% of the pesos, worth more dollars at the lower price,
    # so the order shrinks to keep the loss at the stop inside the 1% limit.
    wide = RiskLimits(stop_loss_pct=10, max_position_pct=25, risk_per_trade_pct=1, allow_shorts=True)
    [sized] = plan_intents(
        {"USD/MXN": 0.25}, {"USD/MXN": 18.0}, account(), wide, ["USD/MXN"], THURSDAY, "tpF", rules=rules
    )
    loss = money.loss_at("USD/MXN", sized.qty, sized.limit_price, sized.stop_price)
    assert loss <= 1_000 + 1e-6 and sized.qty < 10_000  # 1% of 100k; 10% of equity alone would be 10k
    assert check_order(sized, account(), wide, risk_ctx()).approved


# --------------------------------------------------------------------- the risk engine


def test_risk_engine_rules_for_shorts():
    state = account()
    assert codes(short_entry(), state) == set()
    off = RiskLimits.from_settings(Settings(_env_file=None, asset_class="forex", **FOUR_PAIRS))
    assert "no_shorting" in codes(short_entry(), state, off)
    assert "invalid_stop" in codes(short_entry(stop=1.09), state)  # a short's stop sits above
    assert "missing_stop" in codes(short_entry(stop=None), state)
    assert "risk_per_trade" in codes(short_entry(stop=1.2), state)
    assert "position_size" in codes(short_entry(qty=30_000), state)
    held_long = account(
        **{"EUR/USD": Position(symbol="EUR/USD", qty=1_000, avg_entry_price=1.1, current_price=1.1)}
    )
    assert "opposite_position" in codes(short_entry(), held_long)

    cover = OrderIntent(
        symbol="EUR/USD", side=Side.BUY, kind=IntentKind.EXIT, qty=5_000, limit_price=1.1, client_order_id="c"
    )
    held_short = account(
        **{"EUR/USD": Position(symbol="EUR/USD", qty=-5_000, avg_entry_price=1.1, current_price=1.1)}
    )
    assert codes(cover, held_short) == set()
    assert codes(cover, held_long) == {"exit_too_large"}  # buying back can't open a long
    sell = cover.model_copy(update={"side": Side.SELL})
    assert codes(sell, held_short) == {"no_shorting"}  # and an exit sell can't open a short


# --------------------------------------------------------------------- the fake OANDA


def test_fake_broker_shorts_are_paid_for_stopped_and_covered():
    broker = FakeBroker(cash=100_000, prices={"EUR/USD": 1.10}, forex=True, always_open=True)
    order = broker.submit_limit_order(short_entry(limit=1.0999, stop=1.133))
    assert order.status == "filled" and broker.cash == pytest.approx(100_000 - 22_000)
    [position] = broker.get_positions()
    assert position.qty == -20_000 and position.is_short
    [stop] = stops(broker, "EUR/USD")
    assert stop.side == Side.BUY and stop.stop_price == 1.133 and stop.protects(position.qty)

    broker.set_prices({"EUR/USD": 1.08})  # the pair falls: the short gains
    assert broker.get_account().equity == pytest.approx(100_000 + 20_000 * 0.02)
    broker.set_prices({"EUR/USD": 1.135})  # then jumps past the stop
    [filled] = broker.trigger_stops()
    assert filled.side == Side.BUY and broker.get_positions() == []
    assert broker.cash == pytest.approx(100_000 - 20_000 * 0.035)

    broker.set_prices({"EUR/USD": 1.10})
    broker.submit_limit_order(
        short_entry(limit=1.0999, stop=1.133).model_copy(update={"client_order_id": "b"})
    )
    cover = OrderIntent(
        symbol="EUR/USD",
        side=Side.BUY,
        kind=IntentKind.EXIT,
        qty=20_000,
        limit_price=1.1011,
        client_order_id="c",
    )
    broker.set_prices({"EUR/USD": 1.09})
    assert broker.submit_limit_order(cover).status == "filled"
    assert broker.get_positions() == [] and stops(broker, "EUR/USD") == []  # the cover took the stop along
    with pytest.raises(ValueError, match="insufficient qty"):
        broker.submit_limit_order(cover.model_copy(update={"client_order_id": "d"}))  # nothing left to cover


def test_fake_broker_counts_dollar_first_pairs_in_dollars():
    broker = FakeBroker(
        cash=50_000, prices={"USD/MXN": 18.0}, forex=True, always_open=True, financing_bps=365
    )
    broker.submit_limit_order(
        OrderIntent(
            symbol="USD/MXN",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=10_000,
            limit_price=18.02,
            stop_price=17.1,
            client_order_id="m",
        )
    )
    assert broker.cash == pytest.approx(40_000)  # $10,000 of dollars bought with pesos
    broker.set_prices({"USD/MXN": 18.9})
    assert broker.get_account().equity == pytest.approx(50_000 + 10_000 * 0.9 / 18.9)


# --------------------------------------------------------------------- the backtester


def falling(days: int = 320) -> pd.DataFrame:
    index = pd.bdate_range(end=pd.Timestamp(FRIDAY), periods=days)
    t = np.arange(days, dtype=float)
    return pd.DataFrame({"EUR/USD": 1.20 - 0.0005 * t, "USD/MXN": 17.0 + 0.004 * t}, index=index)


def test_backtests_profit_from_a_fall_with_shorts_on():
    closes = falling()
    rules = AssetRules(forex=True)
    config = BacktestConfig(cost_bps=3)
    limits = RiskLimits(stop_loss_pct=3, max_position_pct=25, max_open_positions=4, allow_shorts=True)
    shorted = run_backtest(closes[["EUR/USD"]], TrendFollowing(50, shorts=True), limits, config, rules=rules)
    long_only = run_backtest(closes[["EUR/USD"]], TrendFollowing(50), limits, config, rules=rules)
    assert shorted.equity.iloc[-1] > 100_000 and long_only.equity.iloc[-1] == pytest.approx(100_000)
    [trade] = shorted.trades.to_dict("records")
    assert trade["qty"] < 0 and trade["return_pct"] > 0 and trade["exit_reason"] == "open"
    assert set(shorted.fills["side"]) == {"sell"}
    # USD/MXN climbs: a long in dollars. Its size is counted in dollars, never pesos.
    bought = run_backtest(closes[["USD/MXN"]], TrendFollowing(50), limits, config, rules=rules)
    assert bought.exposure.max() <= 0.26 and bought.equity.iloc[-1] > 100_000


def test_backtest_shorts_hit_their_stops_above():
    index = pd.bdate_range(end=pd.Timestamp(FRIDAY), periods=120)
    prices = np.r_[np.linspace(1.2, 1.1, 60), np.full(60, 1.25)]  # a fall, then a jump up
    closes = pd.DataFrame({"EUR/USD": prices}, index=index)
    limits = RiskLimits(stop_loss_pct=3, max_position_pct=25, allow_shorts=True)
    result = run_backtest(
        closes,
        TrendFollowing(20, shorts=True),
        limits,
        BacktestConfig(cost_bps=0),
        rules=AssetRules(forex=True),
    )
    assert "stop" in set(result.trades["exit_reason"])
    stopped = result.trades[result.trades["exit_reason"] == "stop"].iloc[0]
    assert stopped["qty"] < 0 and stopped["return_pct"] < 0


# --------------------------------------------------------------------- the whole loop


def test_a_short_from_signal_to_cover():
    clock = MutableClock(ny(THURSDAY, 17, 15))
    weights = {"AUD/USD": -0.25}
    ctx = forex_ctx(clock=clock, strategy=ConstantWeights(weights), allow_shorts=True)
    run_nightly(ctx)
    with ctx.session() as session:
        [row] = ledger.list_proposals(session, "F", status="pending")
        assert (row.side, row.kind, row.stop_price > row.limit_price) == ("sell", "entry", True)
    lines = [text for text, _ in ctx.notifier.sent]
    assert any("SELL SHORT" in line and "AUD/USD" in line for line in lines)
    with ctx.session() as session:
        [item] = [i for i in build_recommendations(ctx, session)["items"] if i["symbol"] == "AUD/USD"]
        assert item["call"] == "short" and item["proposal"]["action"] == "short"
        assert item["proposal"]["risk_dollars"] > 0

    approve_pending(ctx)
    clock.set(FRIDAY, 9, 50)
    assert len(submit_approved(ctx).submitted) == 1
    [position] = ctx.broker.get_positions()
    assert position.qty < 0
    clock.set(FRIDAY, 17, 5)
    assert reconcile(ctx).ok  # the short has its buy stop above it
    with ctx.session() as session:
        [item] = [i for i in build_recommendations(ctx, session)["items"] if i["symbol"] == "AUD/USD"]
        assert item["call"] == "hold_short" and item["position"]["side"] == "short"
        assert item["position"]["at_risk"] > 0

    clock.set(FRIDAY, 17, 15)
    weights["AUD/USD"] = 0.0
    run_nightly(ctx)
    with ctx.session() as session:
        [row] = ledger.list_proposals(session, "F", status="pending")
        assert (row.side, row.kind) == ("buy", "exit")
    approve_pending(ctx)
    clock.set(FRIDAY + timedelta(days=3), 9, 50)
    assert len(submit_approved(ctx).submitted) == 1
    assert ctx.broker.get_positions() == [] and stops(ctx.broker, "AUD/USD") == []
    client = TestClient(create_app(make_ctx(), start_background=False, forex_ctx=ctx))
    assert [o["action"] for o in client.get("/api/forex/orders").json()] == ["cover", "short"]


def test_the_ai_veto_reads_a_short_the_other_way_round():
    from tests.test_pipeline_execution import StubResearcher

    weights = {"EUR/USD": -0.25, "GBP/USD": -0.25}
    ctx = forex_ctx(
        strategy=ConstantWeights(weights), allow_shorts=True, ai_mode="veto", ai_max_calls_per_day=10
    )
    ctx.researcher = StubResearcher({"EUR/USD": "buy", "GBP/USD": "sell"})
    run_nightly(ctx)
    with ctx.session() as session:
        rows = {r.symbol: r for r in ledger.list_proposals(session, "F")}
    assert rows["EUR/USD"].status == "blocked"  # the AI expects it to rise: no short
    assert any(v["code"] == "ai_veto" for v in rows["EUR/USD"].violations)
    assert rows["GBP/USD"].status == "pending"  # a bearish view backs the short


def test_reconcile_wants_a_stop_on_the_right_side():
    ctx = forex_ctx(allow_shorts=True)
    ctx.broker.prices["EUR/USD"] = 1.1
    ctx.broker.positions["EUR/USD"] = {"qty": -1_000.0, "avg_price": 1.1}
    clock_now = ny(FRIDAY, 17, 5)
    ctx.now_fn = lambda: clock_now
    result = reconcile(ctx)
    assert {m["type"] for m in result.mismatches} == {"unprotected_position"}
    assert "a short of 1000 units" in result.mismatches[0]["message"]


# --------------------------------------------------------------------- OANDA


class ShortOanda(FakeOanda):
    """The same account, holding a short EUR/USD trade and a USD/MXN short waiting to fill."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix(ACCOUNT)
        if request.method == "GET" and path == "/openTrades":
            self.requests.append(request)
            trade = {"id": "41", "instrument": "EUR_USD", "price": "1.10250", "currentUnits": "-20000"}
            return httpx.Response(200, json={"trades": [trade | {"initialUnits": "-20000"}]})
        if request.method == "GET" and path == "/pendingOrders":
            self.requests.append(request)
            orders = [
                {"id": "42", "type": "STOP_LOSS", "state": "PENDING", "tradeID": "41", "price": "1.13600"},
                {
                    "id": "44",
                    "type": "LIMIT",
                    "state": "PENDING",
                    "instrument": "USD_MXN",
                    "units": "-10000",
                    "price": "18.00000",
                    "positionFill": "OPEN_ONLY",
                },
                {
                    "id": "45",
                    "type": "LIMIT",
                    "state": "PENDING",
                    "instrument": "EUR_USD",
                    "units": "20000",
                    "price": "1.09",
                    "positionFill": "REDUCE_ONLY",
                },
            ]
            return httpx.Response(200, json={"orders": orders})
        return super().__call__(request)


def test_oanda_short_entries_covers_and_their_stops():
    server = ShortOanda()
    broker = OandaBroker("t", "101-001-1-001", client=OandaClient("t", transport=httpx.MockTransport(server)))
    [position] = broker.get_positions()
    assert position.qty == -20_000 and position.current_price == pytest.approx(1.10316)  # marked at the ask
    stop = next(o for o in broker.get_open_orders() if o.is_protective_stop)
    assert stop.side == Side.BUY and stop.protects(position.qty)
    # Held: $22,050. Waiting: the USD/MXN short ($10,000; a unit is a dollar). A cover frees money.
    assert broker.get_account().buying_power == pytest.approx(100_250.50 - 22_050 - 10_000)

    broker.submit_limit_order(short_entry("USD/MXN", 10_000, 18.0, 18.54))
    body = json.loads(server.sent("POST", "/orders").content)["order"]
    assert (body["units"], body["positionFill"], body["stopLossOnFill"]["price"]) == (
        "-10000",
        "OPEN_ONLY",
        "18.54",
    )
    broker.submit_limit_order(
        OrderIntent(
            symbol="EUR/USD",
            side=Side.BUY,
            kind=IntentKind.EXIT,
            qty=20_000,
            limit_price=1.09,
            client_order_id="c",
        )
    )
    body = json.loads(server.sent("POST", "/orders").content)["order"]
    assert (body["units"], body["positionFill"]) == ("20000", "REDUCE_ONLY") and "stopLossOnFill" not in body


# --------------------------------------------------------------------- pair sets and the dashboard's choices


def test_pair_sets_bring_their_own_risk_settings():
    exotic = Settings(_env_file=None, asset_class="forex", pair_set="exotic")
    assert exotic.universe_list == EXOTIC and exotic.benchmark_symbol == "USD/MXN"
    assert (exotic.stop_loss_pct, exotic.max_position_pct, exotic.max_open_positions) == (5, 10, 6)
    assert (exotic.cost_bps, exotic.financing_bps_per_year) == (15, 600)
    assert "USD/TRY" not in exotic.universe_list
    standard = Settings(_env_file=None, asset_class="forex")
    assert preferences.pair_set_of(standard) == "standard" and preferences.pair_set_of(exotic) == "exotic"
    assert (
        preferences.pair_set_of(Settings(_env_file=None, asset_class="forex", universe="EUR/USD")) == "custom"
    )
    assert preferences.recommended_stop(exotic) == 5 and preferences.stop_range(standard) == (1, 9)


def majors_ctx(**settings: Any):
    frame = pd.DataFrame(
        {s: 1.0 + 0.001 * np.arange(320) for s in PAIR_SETS["standard"]["universe"].split(",")},
        index=pd.bdate_range(end=pd.Timestamp(FRIDAY), periods=320),
    )
    values = {
        "universe": PAIR_SETS["standard"]["universe"],
        "max_position_pct": 14.0,
        "max_open_positions": 7,
    }
    return forex_ctx(frame=frame, **(values | settings))


def test_a_wider_stop_warns_and_waits_for_your_ok():
    ctx = forex_ctx(strategy=ConstantWeights({"EUR/USD": 0.25}))
    run_nightly(ctx)  # one proposal waiting, sized on the 3% stop
    view = preferences.view(ctx)
    assert (view["stop_loss_pct"], view["recommended_stop_loss_pct"], view["stop_source"]) == (
        3,
        3,
        "recommended",
    )

    result = preferences.update(ctx, {"stop_loss_pct": 6})
    assert result.status == "needs_confirm" and ctx.settings.stop_loss_pct == 3
    [warning] = result.notices
    assert warning.level == "warning" and "Wider stop-loss: 6%" in warning.title
    text = " ".join(warning.lines)
    # At 6% the 1% limit per trade caps a position at a sixth of the account: 1/6 x 6% = 1%.
    assert "1.00% of the account per position, up from 0.75%" in text
    assert "at most 17% of the account each instead of 25%" in text
    assert "keep the stop they have" in text and "trader gate1" in text

    result = preferences.update(ctx, {"stop_loss_pct": 6}, confirm=True)
    assert result.status == "applied" and len(result.expired) == 1
    assert ctx.settings.stop_loss_pct == 6 and ctx.limits.stop_loss_pct == 6
    assert preferences.view(ctx)["stop_source"] == "dashboard"
    assert any("Wider stop-loss" in note["title"] for note in preferences.view(ctx)["notes"])
    with ctx.session() as session:
        assert ledger.get_state(session, preferences.PREFS_KEY)["stop_loss_pct"] == 6
        [row] = ledger.list_proposals(session, "F", status="expired")
        assert "settings changed" in row.error

    assert preferences.update(ctx, {"stop_loss_pct": 2}).status == "applied"  # tighter: no question asked
    assert preferences.update(ctx, {"stop_loss_pct": 10}).status == "invalid"  # past 3 x the recommended 3%
    assert preferences.update(ctx, {"stop_loss_pct": None}).status == "applied"
    assert ctx.settings.stop_loss_pct == 3


def test_short_selling_and_exotic_pairs_need_confirming():
    ctx = majors_ctx()
    assert ctx.strategy_from_settings and not ctx.settings.allow_shorts
    result = preferences.update(ctx, {"allow_shorts": True})
    assert result.status == "needs_confirm" and "no ceiling" in " ".join(result.notices[0].lines)
    assert preferences.update(ctx, {"allow_shorts": True}, confirm=True).status == "applied"
    assert ctx.settings.allow_shorts and ctx.limits.allow_shorts and ctx.strategy.shorts

    result = preferences.update(ctx, {"pair_set": "exotic"})
    assert result.status == "needs_confirm"
    titles = [n.title for n in result.notices]
    assert any("Mexican peso" in t for t in titles) and "Turkish lira" in " ".join(result.notices[0].lines)
    assert preferences.update(ctx, {"pair_set": "exotic"}, confirm=True).status == "applied"
    assert ctx.settings.universe_list == EXOTIC and ctx.settings.stop_loss_pct == 5
    assert ctx.rules.lot("USD/HUF").price_tick == 0.001

    assert preferences.update(ctx, {"pair_set": "standard", "allow_shorts": False}).status == "applied"
    assert preferences.pair_set_of(ctx.settings) == "standard" and not ctx.strategy.shorts


def test_switching_pairs_waits_until_the_old_ones_are_closed():
    ctx = majors_ctx()
    ctx.broker.prices["EUR/USD"] = 1.1
    ctx.broker.positions["EUR/USD"] = {"qty": 1_000.0, "avg_price": 1.1}
    result = preferences.update(ctx, {"pair_set": "exotic"}, confirm=True)
    assert result.status == "blocked" and "Close your EUR/USD position first" in result.message
    assert preferences.pair_set_of(ctx.settings) == "standard"


def test_only_forex_has_pairs_and_shorts():
    ctx = make_ctx()
    assert preferences.update(ctx, {"allow_shorts": True}).status == "invalid"
    assert preferences.view(ctx)["forex"] is None and preferences.view(ctx)["recommended_stop_loss_pct"] == 8
    result = preferences.update(ctx, {"stop_loss_pct": 12})
    assert result.status == "needs_confirm"
    text = " ".join(result.notices[0].lines)
    assert "new positions get smaller: at most 8% of the account each instead of 10%" in text


def test_choices_survive_a_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'forex.db'}"
    ctx = forex_ctx(database_url=url)
    preferences.update(ctx, {"stop_loss_pct": 4.5, "allow_shorts": True}, confirm=True)
    again = forex_ctx(database_url=url)
    assert again.settings.stop_loss_pct == 4.5 and again.settings.allow_shorts and again.strategy.shorts
    assert again.base_settings.stop_loss_pct == 3
    assert preferences.effective(again.base_settings).stop_loss_pct == 4.5  # what backtests use


def test_the_dashboard_api_asks_before_a_riskier_choice():
    client = TestClient(create_app(make_ctx(), start_background=False, forex_ctx=forex_ctx()))
    view = client.get("/api/forex/preferences").json()
    assert view["forex"]["pair_set"] == "custom" and set(view["forex"]["pair_sets"]) == {"standard", "exotic"}
    reply = client.put("/api/forex/preferences", json={"allow_shorts": True})
    assert reply.status_code == 409 and reply.json()["detail"]["status"] == "needs_confirm"
    assert reply.json()["detail"]["notices"][0]["level"] == "warning"
    reply = client.put("/api/forex/preferences", json={"allow_shorts": True, "confirm": True})
    assert reply.status_code == 200 and reply.json()["preferences"]["forex"]["allow_shorts"] is True
    assert client.put("/api/forex/preferences", json={"stop_loss_pct": 50}).status_code == 400
    assert client.put("/api/preferences", json={"pair_set": "exotic"}).status_code == 400  # stocks
    assert client.get("/api/preferences").json()["forex"] is None


def test_the_settings_command(monkeypatch, tmp_path):
    from trader.cli import app
    from trader.config import get_settings

    for key, value in {
        "ASSET_CLASS": "forex",
        "BROKER": "fake",
        "DATA_SOURCE": "synthetic",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'forex.db'}",
        "FAKE_BROKER_STATE": str(tmp_path / "fx.json"),
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    runner = CliRunner()
    shown = runner.invoke(app, ["settings"], env={"COLUMNS": "200"})
    assert shown.exit_code == 0 and "stop-loss 3%" in shown.output and "Short selling: off" in shown.output
    refused = runner.invoke(app, ["settings", "--stop", "5"], input="n\n", env={"COLUMNS": "200"})
    assert refused.exit_code == 1 and "Wider stop-loss" in refused.output
    done = runner.invoke(app, ["settings", "--stop", "5", "--shorts", "--yes"], env={"COLUMNS": "200"})
    assert done.exit_code == 0, done.output
    assert "stop-loss 5% (set on the dashboard; recommended 3%" in done.output
    assert "Short selling: on" in done.output
    get_settings.cache_clear()


def test_reports_note_a_proposal_that_was_sized_before_a_change():
    ctx = forex_ctx(strategy=ConstantWeights({"EUR/USD": 0.25}))
    run_nightly(ctx)
    approve_pending(ctx)
    preferences.update(ctx, {"stop_loss_pct": 2})
    with ctx.session() as session:
        assert ledger.list_proposals(session, "F", status=ProposalStatus.APPROVED) == []

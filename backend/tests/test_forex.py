"""The forex book (Phase 7): currency pairs through OANDA, no leverage.

These tests run the book on four pairs quoted in dollars, a quarter of the account each.
Short selling, the dollar-first pairs and the pair sets have their own tests in
tests/test_forex_shorts.py.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.helpers import ConstantWeights, MutableClock, make_ctx, make_settings
from tests.test_crypto import crypto_ctx
from trader import forex as fx
from trader import ledger
from trader.assets import (
    AssetRules,
    fmt_price,
    fmt_quote,
    is_crypto_symbol,
    is_forex_symbol,
    price_decimals,
)
from trader.backtest import BacktestConfig, run_backtest
from trader.broker.fake import FakeBroker
from trader.broker.oanda_broker import OandaBroker, OandaClient, OandaError
from trader.config import AssetClass, Settings
from trader.data.base import FrameBarSource
from trader.data.oanda_source import OandaBarSource
from trader.data.synthetic import SyntheticBarSource
from trader.models import AccountInfo, AccountState, IntentKind, OrderIntent, ProposalStatus, Side
from trader.notify.telegram import LogNotifier
from trader.planner import plan_intents
from trader.risk.engine import RiskContext, check_order
from trader.risk.limits import RiskLimits
from trader.services.account import load_account_state
from trader.services.approvals import decide_proposal
from trader.services.context import build_context, extra_book_settings, forex_book_settings
from trader.services.execution import submit_approved
from trader.services.pipeline import run_nightly
from trader.services.reconcile import reconcile
from trader.services.replay import replay
from trader.strategies import TrendFollowing
from trader.utils import NY

PAIRS = ["EUR/USD", "GBP/USD", "AUD/USD", "NZD/USD"]
MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD", "NZD/USD"]
THURSDAY = date(2026, 11, 12)
FRIDAY = date(2026, 11, 13)
FOUR_PAIRS = {"universe": ",".join(PAIRS), "max_position_pct": 25.0, "max_open_positions": 4}
FOREX_LIMITS = RiskLimits.from_settings(Settings(_env_file=None, asset_class="forex", **FOUR_PAIRS))


def ny(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=NY).astimezone(UTC)


def pair_frame(end: date = FRIDAY, days: int = 320) -> pd.DataFrame:
    """Weekdays only. EUR and GBP climb against the dollar, AUD slides, NZD wobbles."""
    index = pd.bdate_range(end=pd.Timestamp(end), periods=days)
    t = np.arange(days, dtype=float)
    return pd.DataFrame(
        {
            "EUR/USD": 1.00 + 0.0004 * t,
            "GBP/USD": 1.20 + 0.0003 * t,
            "AUD/USD": 0.75 - 0.0002 * t,
            "NZD/USD": 0.60 + 0.01 * np.sin(t / 9),
        },
        index=index,
    )


def forex_ctx(
    clock: MutableClock | None = None,
    broker: FakeBroker | None = None,
    strategy: Any = None,
    frame: pd.DataFrame | None = None,
    **settings: Any,
):
    clock = clock or MutableClock(ny(THURSDAY, 17, 15))
    broker = broker or FakeBroker(cash=100_000, now_fn=clock, forex=True)
    values = {"asset_class": "forex", "benchmark": "EUR/USD", **FOUR_PAIRS} | settings
    return build_context(
        make_settings(**values),
        broker=broker,
        bars=FrameBarSource(frame if frame is not None else pair_frame()),
        strategy=strategy,
        notifier=LogNotifier(),
        now_fn=clock,
    )


def approve_pending(ctx) -> list[int]:
    with ctx.session() as session:
        rows = ledger.list_proposals(session, ctx.label, status="pending")
        for row in rows:
            decide_proposal(session, row.id, True, by="test")
        return [row.id for row in rows]


def stops(broker: FakeBroker, symbol: str):
    return [o for o in broker.get_open_orders(symbol) if o.is_protective_stop]


# --------------------------------------------------------------------- pairs, units, settings


def test_pairs_tell_forex_from_crypto():
    assert is_forex_symbol("EUR/USD") and not is_crypto_symbol("EUR/USD")
    assert is_crypto_symbol("BTC/USD") and not is_forex_symbol("BTC/USD")
    assert not is_forex_symbol("SPY") and not is_crypto_symbol("SPY")
    rules = AssetRules.for_symbols(PAIRS)
    assert (rules.kind, rules.unit, rules.whole_units()) == ("forex", "unit", True)
    assert rules.floor_qty("EUR/USD", 22_123.7) == 22_123
    assert rules.price_up("EUR/USD", 1.123451) == 1.12346
    assert rules.price_down("EUR/USD", 1.123459) == 1.12345
    assert (fmt_price(1.08423, "EUR/USD"), fmt_price(1234.5, "SPY")) == ("1.08423", "1,234.50")
    assert (fmt_quote(1.1, "EUR/USD"), fmt_quote(5, "SPY")) == ("1.10000", "$5.00")
    assert price_decimals("USD/JPY") == 3


def test_forex_settings_start_from_their_own_defaults():
    settings = Settings(_env_file=None, asset_class="forex")
    assert settings.account_label == "F" and settings.universe_list == MAJORS
    assert (settings.stop_loss_pct, settings.max_position_pct, settings.max_open_positions) == (3, 14, 7)
    assert settings.financing_bps_per_year == 250 and settings.database_url == "sqlite:///./forex-demo.db"
    assert (settings.pair_set, settings.allow_shorts) == ("standard", False)
    # A 3% stop with a 1% loss limit would allow a third of the account; the 14% cap is lower,
    # and seven pairs at 14% stay inside the account.
    assert RiskLimits.from_settings(settings).max_entry_fraction() == pytest.approx(0.14)
    # Anything set by hand wins over the pair set.
    mine = Settings(_env_file=None, asset_class="forex", universe="EUR/USD", stop_loss_pct=2)
    assert (mine.universe_list, mine.stop_loss_pct, mine.max_position_pct) == (["EUR/USD"], 2, 14)

    with pytest.raises(ValueError, match="US dollar on one side"):
        Settings(_env_file=None, asset_class="forex", universe="EUR/USD,EUR/GBP")
    with pytest.raises(ValueError, match="forex book only"):
        Settings(_env_file=None, allow_shorts=True)
    with pytest.raises(ValueError, match="STRATEGY=trend"):
        Settings(_env_file=None, asset_class="forex", allow_shorts=True, strategy="momentum")
    with pytest.raises(ValueError, match="BROKER=oanda"):
        Settings(_env_file=None, asset_class="forex", broker="alpaca")
    with pytest.raises(ValueError, match="BROKER=alpaca"):
        Settings(_env_file=None, broker="oanda")
    with pytest.raises(ValueError, match="DATA_SOURCE=oanda"):
        Settings(_env_file=None, asset_class="forex", data_source="alpaca")
    with pytest.raises(ValueError, match="BROKER=oanda"):
        Settings(
            _env_file=None,
            asset_class="forex",
            trading_mode="live",
            live_trading_confirmed=True,
            broker="fake",
        )


def test_the_forex_week_and_its_days():
    saturday, sunday, monday = (
        FRIDAY + timedelta(days=1),
        FRIDAY + timedelta(days=2),
        FRIDAY + timedelta(days=3),
    )
    assert fx.is_open(ny(FRIDAY, 16, 59)) and not fx.is_open(ny(FRIDAY, 17, 0))
    assert not fx.is_open(ny(saturday, 12)) and not fx.is_open(ny(sunday, 16, 59))
    assert fx.is_open(ny(sunday, 17, 0)) and fx.is_open(ny(monday, 3))
    clock = fx.clock(ny(saturday, 12))
    assert clock.next_open == datetime.combine(sunday, time(17), tzinfo=NY)
    assert clock.next_close == datetime.combine(FRIDAY + timedelta(days=7), time(17), tzinfo=NY)
    # A day is named for its 5 pm close; the session that opens Sunday evening is Monday's.
    assert fx.bar_date(ny(THURSDAY, 17, 15)) == THURSDAY
    assert fx.bar_date(ny(THURSDAY, 10)) == THURSDAY - timedelta(days=1)
    assert fx.bar_date(ny(saturday, 12)) == FRIDAY
    assert fx.bar_date(ny(sunday, 18)) == FRIDAY
    assert fx.bar_date(ny(monday, 9)) == FRIDAY and fx.bar_date(ny(monday, 17, 1)) == monday
    assert fx.in_rollover(ny(FRIDAY, 16, 50)) and not fx.in_rollover(ny(FRIDAY, 17, 20))


# --------------------------------------------------------------------- sizing without leverage


def test_planner_sizes_whole_units_and_never_borrows():
    account = AccountState(
        equity=100_000, cash=100_000, buying_power=100_000, day_start_equity=100_000, peak_equity=100_000
    )
    prices = {"EUR/USD": 1.10, "GBP/USD": 1.31, "AUD/USD": 0.66, "NZD/USD": 0.59}
    intents = plan_intents(
        dict.fromkeys(PAIRS, 0.25),
        prices,
        account,
        FOREX_LIMITS,
        PAIRS,
        THURSDAY,
        "tpF",
        rules=AssetRules(forex=True),
    )
    assert [i.symbol for i in intents] == PAIRS
    assert all(float(i.qty).is_integer() for i in intents)
    assert sum(i.notional for i in intents) <= 100_000  # four quarters fill the account, never more
    eur = intents[0]
    assert eur.limit_price == 1.1011 and eur.stop_price == pytest.approx(1.06807, abs=1e-5)
    assert eur.qty == 22_704 and eur.client_order_id == "tpF-20261112-EURUSD-buy"


def test_risk_engine_refuses_borrowed_money_and_odd_units():
    account = AccountState(
        equity=100_000, cash=20_000, buying_power=20_000, day_start_equity=100_000, peak_equity=100_000
    )
    intent = OrderIntent(
        symbol="EUR/USD",
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        qty=22_000,
        limit_price=1.1,
        stop_price=1.067,
        client_order_id="tpF-x",
    )
    ctx = RiskContext(now=ny(FRIDAY, 9, 50), universe=set(PAIRS))
    codes = {v.code for v in check_order(intent, account, FOREX_LIMITS, ctx).violations}
    assert codes == {"buying_power"}
    odd = intent.model_copy(update={"qty": 100.5})
    assert "whole_shares" in {v.code for v in check_order(odd, account, FOREX_LIMITS, ctx).violations}


# --------------------------------------------------------------------- the fake OANDA


def test_an_exit_closes_the_trade_and_takes_its_stop_along():
    broker = FakeBroker(cash=100_000, prices={"EUR/USD": 1.1}, forex=True, always_open=True)
    entry = broker.submit_limit_order(
        OrderIntent(
            symbol="EUR/USD",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=10_000,
            limit_price=1.1011,
            stop_price=1.0681,
            client_order_id="tpF-1-EURUSD-buy",
        )
    )
    assert entry.status == "filled" and len(stops(broker, "EUR/USD")) == 1
    # No need to cancel the stop first: OANDA holds nothing back for it.
    exit_ = broker.submit_limit_order(
        OrderIntent(
            symbol="EUR/USD",
            side=Side.SELL,
            kind=IntentKind.EXIT,
            qty=10_000,
            limit_price=1.0989,
            client_order_id="tpF-2-EURUSD-sell",
        )
    )
    assert exit_.status == "filled" and broker.get_positions() == []
    assert stops(broker, "EUR/USD") == []


def test_held_positions_pay_financing_every_night():
    clock = MutableClock(ny(THURSDAY, 17, 15))
    broker = FakeBroker(cash=100_000, prices={"EUR/USD": 1.0}, now_fn=clock, forex=True, financing_bps=3650)
    broker.submit_limit_order(
        OrderIntent(
            symbol="EUR/USD",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=10_000,
            limit_price=1.0,
            stop_price=0.97,
            client_order_id="tpF-1",
        )
    )
    broker.end_of_day()  # Thursday: the first close only starts the count
    clock.set(FRIDAY, 17, 15)
    broker.end_of_day()  # one night: 10,000 x 36.5% / 365
    assert broker.financing_paid == pytest.approx(10.0)
    clock.set(FRIDAY + timedelta(days=3), 17, 15)
    broker.end_of_day()  # Monday: three more nights, the weekend included
    assert broker.financing_paid == pytest.approx(40.0)
    assert broker.get_account().equity == pytest.approx(100_000 - 40.0)


# --------------------------------------------------------------------- the forex day, end to end


def test_signal_to_stop_to_exit():
    clock = MutableClock(ny(THURSDAY, 17, 15))
    weights = {"EUR/USD": 0.25}
    ctx = forex_ctx(clock=clock, strategy=ConstantWeights(weights))
    assert run_nightly(ctx).as_of == THURSDAY
    approve_pending(ctx)

    clock.set(FRIDAY, 9, 50)
    result = submit_approved(ctx)
    assert len(result.submitted) == 1
    [position] = ctx.broker.get_positions()
    assert position.symbol == "EUR/USD" and float(position.qty).is_integer()
    [stop] = stops(ctx.broker, "EUR/USD")
    assert stop.stop_price == pytest.approx(position.avg_entry_price * 0.97, rel=2e-3)

    clock.set(FRIDAY, 17, 15)
    weights["EUR/USD"] = 0.0  # the signal turns: sell
    run_nightly(ctx)
    approve_pending(ctx)
    clock.set(FRIDAY + timedelta(days=3), 9, 50)
    assert len(submit_approved(ctx).submitted) == 1
    assert ctx.broker.get_positions() == [] and stops(ctx.broker, "EUR/USD") == []


def test_reconcile_clears_waiting_orders_but_keeps_stops():
    clock = MutableClock(ny(THURSDAY, 17, 15))
    ctx = forex_ctx(clock=clock, strategy=ConstantWeights({"EUR/USD": 0.25}))
    run_nightly(ctx)
    approve_pending(ctx)
    clock.set(FRIDAY, 9, 50)
    submit_approved(ctx)
    waiting = ctx.broker.submit_limit_order(
        OrderIntent(
            symbol="GBP/USD",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=1_000,
            limit_price=1.0,
            stop_price=0.97,
            client_order_id="tpF-20261113-GBPUSD-buy",
        )
    )
    assert waiting.status == "new"  # priced below the market, so it waits

    clock.set(FRIDAY, 17, 5)
    result = reconcile(ctx)
    assert result.canceled_stale_entries == 1
    assert len(stops(ctx.broker, "EUR/USD")) == 1
    assert {m["type"] for m in result.mismatches} == {"unknown_order"}  # placed outside the app
    with ctx.session() as session:
        assert [row.as_of for row in ledger.equity_history(session, "F")] == [FRIDAY]


def test_orders_wait_out_the_weekend_and_the_daily_close():
    clock = MutableClock(ny(FRIDAY + timedelta(days=1), 10))
    ctx = forex_ctx(clock=clock)
    assert submit_approved(ctx).skipped_reason == "The market is closed."
    clock.set(FRIDAY, 16, 50)
    assert "5 pm New York" in (submit_approved(ctx).skipped_reason or "")


def test_replay_runs_the_forex_clock_with_financing():
    clock = MutableClock(ny(FRIDAY, 17, 15))
    broker = FakeBroker(cash=100_000, now_fn=clock, forex=True, financing_bps=250)
    ctx = forex_ctx(clock=clock, broker=broker)
    start = FRIDAY - timedelta(days=41)
    result = replay(ctx, start, FRIDAY, leave_last_pending=True)
    assert result.days == len(pd.bdate_range(start, FRIDAY)) and result.submitted > 0
    assert broker.financing_paid > 0
    with ctx.session() as session:
        days = [row.as_of for row in ledger.equity_history(session, "F")]
        assert days and all(day.weekday() < 5 for day in days)


def test_backtests_charge_financing_for_every_night_held():
    closes = pair_frame()
    strategy = ConstantWeights({"EUR/USD": 0.25})
    free = run_backtest(closes, strategy, FOREX_LIMITS, BacktestConfig(cost_bps=0), PAIRS)
    paid = run_backtest(
        closes, strategy, FOREX_LIMITS, BacktestConfig(cost_bps=0, financing_bps_per_year=250), PAIRS
    )
    assert paid.equity.iloc[-1] < free.equity.iloc[-1]
    charges = paid.financing
    mondays = charges[(charges.index.day_of_week == 0) & (charges > 0)]
    tuesdays = charges[(charges.index.day_of_week == 1) & (charges > 0)]
    assert mondays.mean() / tuesdays.mean() == pytest.approx(3, rel=0.05)  # the weekend's three nights


def test_made_up_currency_prices_look_like_currencies():
    closes = SyntheticBarSource(forex=True).get_closes(PAIRS, date(2024, 1, 1), date(2024, 12, 31))
    assert (closes.index.day_of_week < 5).all()
    assert closes.min().min() > 0.2 and closes.max().max() < 5
    daily = closes.pct_change().dropna().std()
    assert ((daily > 0.002) & (daily < 0.012)).all()


def test_day_start_falls_back_to_the_last_recorded_equity():
    class NoYesterday(FakeBroker):
        def get_account(self) -> AccountInfo:
            return super().get_account().model_copy(update={"last_equity": 0.0})

    ctx = forex_ctx(broker=NoYesterday(cash=98_000, forex=True))
    with ctx.session() as session:
        ledger.record_equity(session, THURSDAY - timedelta(days=1), 100_000, 100_000, None, "F")
        assert load_account_state(ctx, session).day_pnl_pct == pytest.approx(-2.0)


def test_trend_reasons_quote_pairs_without_dollar_signs():
    reasons = TrendFollowing(20).explain(pair_frame()[["EUR/USD"]])
    assert reasons["EUR/USD"].startswith("Closed at 1.") and "$" not in reasons["EUR/USD"]


# --------------------------------------------------------------------- OANDA's REST API, mocked


ACCOUNT = "/v3/accounts/101-001-1-001"


class FakeOanda:
    """Answers the OANDA v20 calls the adapter makes, and records what it was sent."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.cancel_next = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix(ACCOUNT)
        routes: dict[tuple[str, str], Any] = {
            ("GET", "/summary"): {
                "account": {"NAV": "100250.50", "balance": "100000", "positionValue": "22050"}
            },
            ("GET", "/openTrades"): {
                "trades": [
                    {
                        "id": "41",
                        "instrument": "EUR_USD",
                        "price": "1.10250",
                        "currentUnits": "20000",
                        "initialUnits": "20000",
                    }
                ]
            },
            ("GET", "/pendingOrders"): {
                "orders": [
                    {
                        "id": "44",
                        "type": "LIMIT",
                        "state": "PENDING",
                        "instrument": "GBP_USD",
                        "units": "10000",
                        "price": "1.30000",
                        "createTime": "2026-11-13T14:50:00.123456789Z",
                        "clientExtensions": {"id": "tpF-20261112-GBPUSD-buy"},
                    },
                    {
                        "id": "42",
                        "type": "STOP_LOSS",
                        "state": "PENDING",
                        "tradeID": "41",
                        "price": "1.06900",
                        "createTime": "2026-11-12T14:50:01Z",
                        "clientExtensions": {"id": "tpF-20261111-EURUSD-buy-stop"},
                    },
                ]
            },
            ("GET", "/pricing"): {
                "prices": [
                    {
                        "instrument": "EUR_USD",
                        "bids": [{"price": "1.10300"}],
                        "asks": [{"price": "1.10316"}],
                        "tradeable": True,
                    }
                ]
            },
            ("GET", "/orders/50"): {
                "order": {
                    "id": "50",
                    "type": "LIMIT",
                    "state": "FILLED",
                    "instrument": "EUR_USD",
                    "units": "20000",
                    "price": "1.104",
                    "fillingTransactionID": "51",
                    "createTime": "2026-11-13T14:50:00Z",
                    "clientExtensions": {"id": "tpF-20261112-EURUSD-buy"},
                }
            },
            ("GET", "/transactions/51"): {
                "transaction": {
                    "id": "51",
                    "type": "ORDER_FILL",
                    "instrument": "EUR_USD",
                    "units": "20000",
                    "fullVWAP": "1.10316",
                }
            },
            ("GET", "/instruments"): {
                "instruments": [
                    {
                        "name": "EUR_USD",
                        "displayPrecision": 5,
                        "tradeUnitsPrecision": 0,
                        "minimumTradeSize": "1",
                    }
                ]
            },
            ("PUT", "/orders/44/cancel"): {"orderCancelTransaction": {"id": "60"}},
        }
        if (request.method, path) == ("POST", "/orders"):
            if self.cancel_next:
                return httpx.Response(
                    201,
                    json={
                        "orderCreateTransaction": {"id": "50"},
                        "orderCancelTransaction": {"reason": "INSUFFICIENT_MARGIN"},
                    },
                )
            return httpx.Response(
                201, json={"orderCreateTransaction": {"id": "50"}, "orderFillTransaction": {"id": "51"}}
            )
        if path.startswith("/orders/@"):
            return httpx.Response(
                404, json={"errorCode": "ORDER_DOESNT_EXIST", "errorMessage": "The order doesn't exist"}
            )
        if (request.method, path) in routes:
            return httpx.Response(200, json=routes[(request.method, path)])
        return httpx.Response(404, json={"errorMessage": f"no route for {request.method} {path}"})

    def sent(self, method: str, path: str) -> httpx.Request:
        return next(r for r in reversed(self.requests) if r.method == method and r.url.path == ACCOUNT + path)


def oanda() -> tuple[OandaBroker, FakeOanda]:
    server = FakeOanda()
    client = OandaClient("token", transport=httpx.MockTransport(server))
    return OandaBroker("token", "101-001-1-001", client=client), server


def test_oanda_account_positions_and_orders():
    broker, server = oanda()
    account = broker.get_account()
    assert account.equity == 100_250.50 and account.last_equity == 0.0
    assert account.buying_power == pytest.approx(100_250.50 - 22_050 - 13_000)  # held and on order
    assert server.requests[0].headers["Authorization"] == "Bearer token"
    assert str(server.requests[0].url).startswith("https://api-fxpractice.oanda.com")

    [position] = broker.get_positions()
    assert (position.symbol, position.qty) == ("EUR/USD", 20_000)
    assert position.avg_entry_price == pytest.approx(1.1025) and position.current_price == pytest.approx(
        1.103
    )
    entry, stop = sorted(broker.get_open_orders(), key=lambda o: o.side)
    assert (entry.symbol, entry.side, entry.qty, entry.limit_price) == ("GBP/USD", Side.BUY, 10_000, 1.3)
    assert entry.submitted_at == datetime(2026, 11, 13, 14, 50, 0, 123456, tzinfo=UTC)
    assert stop.is_protective_stop and (stop.symbol, stop.qty, stop.stop_price) == ("EUR/USD", 20_000, 1.069)
    assert stop.parent_id == "trade-41" and stop.client_order_id.endswith("-stop")
    assert broker.latest_price("EUR/USD") == pytest.approx(1.10308)
    assert broker.lots(["EUR/USD"])["EUR/USD"].price_tick == 0.00001
    assert broker.get_order_by_client_id("missing") is None
    broker.cancel_order("44")
    assert server.sent("PUT", "/orders/44/cancel")


def test_oanda_entries_carry_their_stop_and_exits_only_reduce():
    broker, server = oanda()
    order = broker.submit_limit_order(
        OrderIntent(
            symbol="EUR/USD",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=20_000,
            limit_price=1.104,
            stop_price=1.06927,
            client_order_id="tpF-20261112-EURUSD-buy",
        )
    )
    body = json.loads(server.sent("POST", "/orders").content)["order"]
    assert body == {
        "type": "LIMIT",
        "instrument": "EUR_USD",
        "units": "20000",
        "price": "1.104",
        "timeInForce": "GTC",
        "positionFill": "OPEN_ONLY",
        "clientExtensions": {"id": "tpF-20261112-EURUSD-buy", "tag": "lajan-sere"},
        "stopLossOnFill": {
            "price": "1.06927",
            "timeInForce": "GTC",
            "clientExtensions": {"id": "tpF-20261112-EURUSD-buy-stop", "tag": "lajan-sere"},
        },
    }
    assert (order.status, order.filled_qty, order.filled_avg_price) == ("filled", 20_000, 1.10316)

    broker.submit_limit_order(
        OrderIntent(
            symbol="EUR/USD",
            side=Side.SELL,
            kind=IntentKind.EXIT,
            qty=20_000,
            limit_price=1.10199,
            client_order_id="tpF-20261113-EURUSD-sell",
        )
    )
    body = json.loads(server.sent("POST", "/orders").content)["order"]
    assert (
        body["units"] == "-20000" and body["positionFill"] == "REDUCE_ONLY" and "stopLossOnFill" not in body
    )

    server.cancel_next = True
    with pytest.raises(OandaError, match="INSUFFICIENT_MARGIN"):
        broker.submit_limit_order(
            OrderIntent(
                symbol="EUR/USD",
                side=Side.BUY,
                kind=IntentKind.ENTRY,
                qty=1,
                limit_price=1.1,
                stop_price=1.067,
                client_order_id="tpF-x",
            )
        )


def test_oanda_candles_are_named_for_their_new_york_close(monkeypatch):
    opens = [datetime.combine(date(2026, 11, d), time(17), tzinfo=NY) for d in (8, 9, 10, 11, 12)]
    candles = [
        {
            "time": f"{moment.astimezone(UTC):%Y-%m-%dT%H:%M:%S}.000000000Z",
            "complete": moment.day != 12,  # Thursday evening's candle is still forming
            "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": f"1.1{moment.day:02d}0"},
        }
        for moment in opens
    ]
    seen: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlparse(str(request.url)).query)
        seen.append(query)
        start = pd.Timestamp(query["from"][0])
        page = [c for c in candles if pd.Timestamp(c["time"]) >= start][: int(query["count"][0])]
        return httpx.Response(200, json={"instrument": "EUR_USD", "granularity": "D", "candles": page})

    monkeypatch.setattr("trader.data.oanda_source.PAGE", 2)
    source = OandaBarSource(client=OandaClient("token", transport=httpx.MockTransport(handler)))
    closes = source.get_closes(["EUR/USD"], date(2026, 11, 9), date(2026, 11, 13))
    assert [d.date() for d in closes.index] == [date(2026, 11, d) for d in (9, 10, 11, 12)]
    assert closes["EUR/USD"].tolist() == [1.108, 1.109, 1.110, 1.111]
    assert len(seen) == 3  # two full pages of two, then the last
    first = seen[0]
    assert (first["granularity"], first["price"], first["dailyAlignment"]) == (["D"], ["M"], ["17"])
    assert first["alignmentTimezone"] == ["America/New_York"] and first["from"] == ["2026-11-08T22:00:00Z"]


# --------------------------------------------------------------------- three books, one dashboard


def test_one_dashboard_serves_three_books():
    from trader.api.app import create_app

    stocks = make_ctx(api_token="secret")
    app = create_app(stocks, start_background=False, crypto_ctx=crypto_ctx(), forex_ctx=forex_ctx())
    client = TestClient(app)
    auth = {"Authorization": "Bearer secret"}
    assert client.get("/api/forex/status").status_code == 401
    books = client.get("/api/books", headers=auth).json()
    assert [(b["id"], b["label"], b["path"], b["account_label"]) for b in books] == [
        ("stocks", "Stocks", "/api", "A"),
        ("crypto", "Crypto", "/api/crypto", "C"),
        ("forex", "Forex", "/api/forex", "F"),
    ]
    status = client.get("/api/forex/status", headers=auth).json()
    assert status["asset_class"] == "forex" and status["universe"] == PAIRS
    protect = client.post("/api/forex/jobs/protect", headers=auth).json()
    assert "forex" in protect["result"]["skipped_reason"]


def test_the_forex_book_beside_the_stock_book(tmp_path):
    demo = make_settings(
        database_url=f"sqlite:///{tmp_path / 'trader.db'}", fake_broker_state=str(tmp_path / "b.json")
    )
    extra = forex_book_settings(demo)
    assert extra is not None and extra.is_forex and extra.broker == "fake"
    assert extra.database_url == f"sqlite:///{tmp_path / 'forex-demo.db'}"
    assert extra.fake_broker_state == str(tmp_path / "fake_broker_forex.json")
    assert list(extra_book_settings(demo)) == [AssetClass.CRYPTO, AssetClass.FOREX]

    env = tmp_path / ".env.forex"
    env.write_text("ASSET_CLASS=forex\nBROKER=oanda\nOANDA_API_TOKEN=t\nOANDA_ACCOUNT_ID=101-001-1-001\n")
    real = make_settings(broker="alpaca", forex_env_file=str(env))
    loaded = forex_book_settings(real)
    assert loaded is not None and loaded.is_forex and loaded.account_label == "F"
    assert loaded.database_url == "sqlite:///./forex.db" and loaded.universe_list == MAJORS
    env.write_text("BROKER=oanda\n")
    with pytest.raises(ValueError, match="BROKER=alpaca"):  # a stock book can't use OANDA
        forex_book_settings(real)
    env.write_text("ASSET_CLASS=crypto\n")
    with pytest.raises(ValueError, match="ASSET_CLASS=forex"):
        forex_book_settings(real)
    assert forex_book_settings(make_settings(broker="alpaca")) is None


def test_a_proposal_reads_like_a_currency_trade():
    ctx = forex_ctx(strategy=ConstantWeights({"EUR/USD": 0.25}))
    run_nightly(ctx)
    lines = [text for text, _ in ctx.notifier.sent]
    assert any("EUR/USD @ 1.1" in line and "stop 1.0" in line for line in lines)
    with ctx.session() as session:
        [row] = ledger.list_proposals(session, "F", status="pending")
    assert row.status == ProposalStatus.PENDING and float(row.qty).is_integer()

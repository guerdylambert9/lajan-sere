"""Phase 6: the crypto book. Fractional sizes, stop-limits after the fill, a 24/7 clock."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.helpers import MutableClock, make_ctx, make_settings
from trader import ledger
from trader.assets import AssetRules, code_symbol, floor_to, fmt_qty, pair_symbol, price_down, price_up
from trader.backtest import run_backtest
from trader.backtest.metrics import periods_per_year
from trader.broker.fake import FakeBroker
from trader.config import DEFAULT_UNIVERSE, Settings
from trader.data.alpaca_crypto_source import finished_bars
from trader.data.base import FrameBarSource
from trader.models import AccountState, IntentKind, OrderIntent, ProposalStatus, Side
from trader.notify.telegram import LogNotifier, TelegramPoller
from trader.planner import plan_intents
from trader.risk.engine import RiskContext, check_order
from trader.risk.limits import RiskLimits
from trader.services.approvals import decide_proposal, handle_telegram_callback
from trader.services.context import build_context, crypto_book_settings
from trader.services.execution import submit_approved
from trader.services.pipeline import run_nightly
from trader.services.protect import protect
from trader.services.reconcile import reconcile
from trader.services.replay import replay
from trader.strategies import TrendFollowing
from trader.utils import CT

DAY = date(2026, 11, 12)  # the last finished crypto day in these tests
PAIRS = ["BTC/USD", "ETH/USD"]
CRYPTO_LIMITS = RiskLimits(
    stop_loss_pct=15,
    stop_limit_band_pct=5,
    max_position_pct=5,
    max_open_positions=2,
    entry_limit_buffer_pct=0.5,
)


def chicago(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=CT).astimezone(UTC)


def coin_frame(end: date = DAY, days: int = 320) -> pd.DataFrame:
    """Every calendar day. BTC trends up; ETH trends down."""
    index = pd.date_range(end=pd.Timestamp(end), periods=days, freq="D")
    t = np.arange(days, dtype=float)
    return pd.DataFrame({"BTC/USD": 40_000 + 60 * t, "ETH/USD": 4_000 - 3 * t}, index=index)


def crypto_ctx(clock: MutableClock | None = None, broker: FakeBroker | None = None, **settings: Any):
    clock = clock or MutableClock(chicago(DAY + timedelta(days=1), 0, 15))
    broker = broker or FakeBroker(cash=100_000, now_fn=clock, crypto=True, fee_bps=25)
    values = {"asset_class": "crypto", "universe": ",".join(PAIRS), "benchmark": "BTC/USD"} | settings
    return build_context(
        make_settings(**values),
        broker=broker,
        bars=FrameBarSource(coin_frame()),
        notifier=LogNotifier(),
        now_fn=clock,
    )


def approve_pending(ctx) -> None:
    with ctx.session() as session:
        for row in ledger.list_proposals(session, ctx.label, status="pending"):
            decide_proposal(session, row.id, True, by="test")


def entered(ctx):
    run_nightly(ctx)
    approve_pending(ctx)
    return submit_approved(ctx)


def open_stops(broker: FakeBroker, symbol: str = "BTC/USD"):
    return [o for o in broker.get_open_orders(symbol) if o.is_protective_stop]


# --------------------------------------------------------------------- units and rounding


def test_symbols_and_rounding():
    assert pair_symbol("BTCUSD") == "BTC/USD"
    assert pair_symbol("ETHUSDT") == "ETH/USDT"
    assert pair_symbol("BTC/USD") == "BTC/USD"
    assert code_symbol("BTC/USD") == "BTCUSD"
    assert floor_to(0.0003, 0.0001) == 0.0003
    assert floor_to(0.08412599, 0.0001) == 0.0841
    assert price_up(91_234.2, 1.0) == 91_235.0
    assert price_down(91_234.9, 1.0) == 91_234.0
    assert price_up(100.001, 0.01) == 100.01
    assert fmt_qty(10.0) == "10" and fmt_qty(0.01230000) == "0.0123"


def test_asset_rules_tell_stocks_from_coins():
    stocks, coins = AssetRules.for_symbols(["SPY", "QQQ"]), AssetRules.for_symbols(PAIRS)
    assert not stocks.crypto and coins.crypto
    assert stocks.floor_qty("SPY", 7.9) == 7
    assert coins.floor_qty("BTC/USD", 0.084125) == 0.0841
    assert coins.floor_qty("BTC/USD", 0.00005) == 0.0  # below the smallest order
    assert coins.is_dust("BTC/USD", 0.00008975) and not coins.is_dust("BTC/USD", 0.0838)


def test_crypto_settings_start_from_their_own_defaults():
    crypto = Settings(_env_file=None, asset_class="crypto", broker="alpaca")
    assert crypto.universe_list == PAIRS and crypto.benchmark_symbol == "BTC/USD"
    assert crypto.account_label == "C" and crypto.stop_loss_pct == 15 and crypto.stop_limit_band_pct == 5
    assert crypto.database_url == "sqlite:///./crypto.db" and crypto.cost_bps == 35
    assert Settings(_env_file=None, asset_class="crypto").database_url == "sqlite:///./crypto-demo.db"
    assert Settings(_env_file=None, asset_class="crypto", stop_loss_pct=10).stop_loss_pct == 10
    stocks = Settings(_env_file=None)
    assert stocks.universe == DEFAULT_UNIVERSE and stocks.stop_limit_band_pct == 0 and not stocks.is_crypto


def test_the_band_below_the_stop_shrinks_each_position():
    assert CRYPTO_LIMITS.worst_exit_loss() == pytest.approx(1 - 0.85 * 0.95)
    assert CRYPTO_LIMITS.max_entry_fraction() == pytest.approx(0.05)
    wide = RiskLimits(stop_loss_pct=15, stop_limit_band_pct=5, max_position_pct=50)
    assert wide.max_entry_fraction() == pytest.approx(0.01 / 0.1925)
    assert RiskLimits().max_entry_fraction() == pytest.approx(0.10)  # stocks unchanged


# --------------------------------------------------------------------- planner and risk checks


def test_planner_buys_a_slice_of_a_coin():
    account = AccountState(
        equity=100_000, cash=100_000, buying_power=100_000, day_start_equity=100_000, peak_equity=100_000
    )
    intents = plan_intents(
        {"BTC/USD": 0.5, "ETH/USD": 0.0},
        {"BTC/USD": 59_140.0, "ETH/USD": 3_043.0},
        account,
        CRYPTO_LIMITS,
        PAIRS,
        DAY,
        "tpC",
    )
    assert len(intents) == 1
    buy = intents[0]
    assert buy.client_order_id == "tpC-20261112-BTCUSD-buy"
    assert buy.limit_price == 59_435.7 and buy.qty == 0.0841
    assert buy.stop_price == 50_520.35
    worst = buy.qty * (buy.limit_price - buy.stop_price * 0.95) / 100_000
    assert worst <= 0.01
    risk = RiskContext(now=chicago(DAY, 9, 0), universe=set(PAIRS), whole_units=False)
    assert check_order(buy, account, CRYPTO_LIMITS, risk).approved


def test_risk_engine_counts_the_stop_limit_band():
    account = AccountState(
        equity=100_000, cash=100_000, buying_power=100_000, day_start_equity=100_000, peak_equity=100_000
    )
    intent = OrderIntent(
        symbol="BTC/USD",
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        qty=0.1,
        limit_price=60_000,
        stop_price=51_000,
        client_order_id="tpC-x",
    )
    risk = RiskContext(now=chicago(DAY, 9, 0), universe=set(PAIRS), whole_units=False)
    loose = RiskLimits(stop_loss_pct=15, max_position_pct=10)
    assert check_order(intent, account, loose, risk).approved  # 0.9% to the stop
    banded = RiskLimits(stop_loss_pct=15, stop_limit_band_pct=5, max_position_pct=10)
    codes = {v.code for v in check_order(intent, account, banded, risk).violations}
    assert codes == {"risk_per_trade"}  # 1.16% if it fills at the limit


def test_stock_orders_stay_whole_shares():
    account = AccountState(
        equity=100_000, cash=100_000, buying_power=100_000, day_start_equity=100_000, peak_equity=100_000
    )
    intent = OrderIntent(
        symbol="SPY",
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        qty=2.5,
        limit_price=400,
        stop_price=370,
        client_order_id="tpA-x",
    )
    risk = RiskContext(now=chicago(DAY, 9, 0), universe={"SPY"})
    assert "whole_shares" in {v.code for v in check_order(intent, account, RiskLimits(), risk).violations}


# --------------------------------------------------------------------- fake broker


def test_fake_crypto_broker_has_no_oto_and_takes_its_fee_in_coins():
    broker = FakeBroker(cash=10_000, prices={"BTC/USD": 50_000}, crypto=True, fee_bps=25)
    order = broker.submit_limit_order(
        OrderIntent(
            symbol="BTC/USD",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=0.1,
            limit_price=50_100,
            stop_price=42_000,
            client_order_id="tpC-1",
        )
    )
    assert order.status == "filled" and order.order_class == "simple"
    assert broker.get_open_orders() == []
    assert broker.positions["BTC/USD"]["qty"] == pytest.approx(0.09975)
    stop = broker.submit_protective_stop("BTC/USD", 0.0997, 42_000, 39_900, "tpC-1-stop")
    assert stop.order_type == "stop_limit" and stop.is_protective_stop
    broker.set_prices({"BTC/USD": 39_000})  # below the limit: the stop can't fill
    assert broker.trigger_stops() == [] and stop.is_open
    broker.set_prices({"BTC/USD": 41_000})
    assert [o.id for o in broker.trigger_stops()] == [stop.id]


# --------------------------------------------------------------------- the live path


def test_entry_fills_and_gets_its_stop_limit_right_away():
    ctx = crypto_ctx()
    assert ctx.bar_date() == DAY and ctx.market_open()
    result = entered(ctx)
    assert len(result.submitted) == 1
    stops = open_stops(ctx.broker)
    assert len(stops) == 1
    stop = stops[0]
    assert stop.qty == 0.0838  # what the fee left, rounded down to the step
    assert stop.stop_price == 50_520.35 and stop.limit_price == 47_994.33
    assert "/" not in stop.client_order_id and stop.client_order_id.endswith("-stop")
    with ctx.session() as session:
        filled = ledger.list_proposals(session, ctx.label, status="filled")
        assert [row.symbol for row in filled] == ["BTC/USD"]
        assert filled[0].qty == 0.0841
    check = reconcile(ctx)
    assert check.ok, check.mismatches
    with ctx.session() as session:
        assert ledger.equity_history(session, ctx.label)[-1].as_of == DAY


def test_dust_left_by_a_stop_is_ignored():
    ctx = crypto_ctx()
    entered(ctx)
    ctx.broker.set_prices({"BTC/USD": 49_000})
    assert len(ctx.broker.trigger_stops()) == 1
    assert ctx.broker.positions["BTC/USD"]["qty"] < 0.0001  # the fee's leftover
    assert reconcile(ctx).ok
    from trader.services.account import load_account_state

    with ctx.session() as session:
        assert load_account_state(ctx, session).positions == {}


def test_protect_replaces_a_short_stop_and_sells_through_a_missed_one():
    ctx = crypto_ctx()
    entered(ctx)
    broker = ctx.broker
    for order in open_stops(broker):
        broker.cancel_order(order.id)
    broker.submit_protective_stop("BTC/USD", 0.01, 50_520.35, 47_994.33, "manual-small-stop")
    result = protect(ctx)
    assert result.replaced == ["BTC/USD"]
    assert [o.qty for o in open_stops(broker)] == [0.0838]

    for order in open_stops(broker):
        broker.cancel_order(order.id)
    broker.set_prices({"BTC/USD": 50_000})  # already under the 50,520.35 stop
    result = protect(ctx)
    assert result.sold == ["BTC/USD"] and not open_stops(broker)
    assert broker.positions["BTC/USD"]["qty"] < 0.0001


def test_protect_cancels_stale_orders_and_warns_about_a_stuck_stop():
    clock = MutableClock(chicago(DAY + timedelta(days=1), 9, 0))
    ctx = crypto_ctx(clock=clock)
    entered(ctx)
    ctx.broker.submit_limit_order(
        OrderIntent(
            symbol="ETH/USD",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=0.01,
            limit_price=1.0,
            client_order_id="tpC-20261112-ETHUSD-buy",
        )
    )
    clock.moment += timedelta(minutes=ctx.settings.entry_ttl_minutes + 1)
    ctx.broker.set_prices({"BTC/USD": 47_000})  # under the stop's 47,994.33 limit
    result = protect(ctx)
    assert result.canceled_orders == 1
    assert len(result.alerts) == 1 and "can't sell" in result.alerts[0]
    assert len(protect(ctx).alerts) == 0  # once per stop
    assert any("can't sell" in text for text, _ in ctx.notifier.sent)


def test_nightly_replaces_yesterdays_unsent_proposals():
    clock = MutableClock(chicago(DAY, 0, 15))
    ctx = crypto_ctx(clock=clock)
    run_nightly(ctx, as_of=DAY - timedelta(days=1))
    clock.moment = chicago(DAY + timedelta(days=1), 0, 15)
    run_nightly(ctx)
    with ctx.session() as session:
        rows = ledger.list_proposals(session, ctx.label, status=None)
    assert {row.as_of: row.status for row in rows} == {
        DAY - timedelta(days=1): ProposalStatus.EXPIRED,
        DAY: ProposalStatus.PENDING,
    }


def test_replay_runs_the_crypto_clock_end_to_end():
    ctx = crypto_ctx()
    result = replay(ctx, DAY - timedelta(days=40), DAY)
    assert result.days == 41 and result.submitted >= 1
    assert reconcile(ctx).ok


# --------------------------------------------------------------------- backtests and data


def test_backtest_trades_fractions_on_a_seven_day_calendar():
    frame = coin_frame(days=500)
    result = run_backtest(frame, TrendFollowing(200), CRYPTO_LIMITS)
    buys = result.fills[result.fills["side"] == "buy"]
    assert len(buys) >= 1 and not float(buys["qty"].iloc[0]).is_integer()
    assert periods_per_year(result.equity.index) == 365
    assert periods_per_year(pd.bdate_range("2024-01-01", periods=30)) == 252


def test_only_finished_crypto_days_are_used():
    index = pd.DatetimeIndex(["2026-11-11 06:00", "2026-11-12 06:00", "2026-11-13 06:00"], tz=UTC)
    closes = pd.DataFrame({"BTC/USD": [1.0, 2.0, 3.0]}, index=index)
    kept = finished_bars(closes, chicago(DAY + timedelta(days=1), 0, 20))
    assert list(kept["BTC/USD"]) == [1.0, 2.0]


# --------------------------------------------------------------------- Alpaca adapter, offline


class FakeTrading:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    def submit_order(self, order_data: Any) -> Any:
        self.sent.append(order_data)
        return SimpleNamespace(
            id="1",
            client_order_id=order_data.client_order_id,
            symbol=order_data.symbol,
            side=order_data.side,
            qty=order_data.qty,
            status="new",
            filled_qty=0,
            filled_avg_price=None,
            limit_price=getattr(order_data, "limit_price", None),
            stop_price=getattr(order_data, "stop_price", None),
            order_type=order_data.type,
            type=order_data.type,
            order_class=None,
            submitted_at=None,
            asset_class="crypto",
        )

    def get_all_positions(self) -> list[Any]:
        return [
            SimpleNamespace(
                symbol="BTCUSD",
                qty="0.0838",
                avg_entry_price="59140",
                current_price="60000",
                asset_class="crypto",
            ),
            SimpleNamespace(
                symbol="SPY", qty="10", avg_entry_price="500", current_price="510", asset_class="us_equity"
            ),
        ]


def test_alpaca_crypto_orders_and_positions():
    from trader.broker.alpaca_broker import AlpacaBroker

    broker = AlpacaBroker("key", "secret", crypto=True)
    broker.trading = FakeTrading()  # type: ignore[assignment]
    positions = broker.get_positions()
    assert [(p.symbol, p.qty) for p in positions] == [("BTC/USD", 0.0838)]
    broker.submit_limit_order(
        OrderIntent(
            symbol="BTC/USD",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=0.0841,
            limit_price=59_435.7,
            stop_price=50_520.35,
            client_order_id="tpC-20261112-BTCUSD-buy",
        )
    )
    entry = broker.trading.sent[-1]
    assert entry.time_in_force.value == "gtc" and entry.order_class is None and entry.stop_loss is None
    stop = broker.submit_protective_stop(
        "BTC/USD", 0.0838, 50_520.35, 47_994.33, "tpC-20261112-BTCUSD-buy-stop"
    )
    request = broker.trading.sent[-1]
    assert request.type.value == "stop_limit" and request.time_in_force.value == "gtc"
    assert stop.symbol == "BTC/USD" and stop.is_protective_stop

    stocks = AlpacaBroker("key", "secret")
    stocks.trading = FakeTrading()  # type: ignore[assignment]
    assert [p.symbol for p in stocks.get_positions()] == ["SPY"]


# --------------------------------------------------------------------- two books, one dashboard


def test_one_dashboard_serves_both_books_with_one_token():
    stocks = make_ctx(api_token="secret")
    coins = crypto_ctx()
    client = TestClient(create_app_with(stocks, coins))
    auth = {"Authorization": "Bearer secret"}
    assert client.get("/api/crypto/status").status_code == 401
    books = client.get("/api/books", headers=auth).json()
    assert [(b["id"], b["path"], b["account_label"]) for b in books] == [
        ("stocks", "/api", "A"),
        ("crypto", "/api/crypto", "C"),
    ]
    status = client.get("/api/crypto/status", headers=auth).json()
    assert status["asset_class"] == "crypto" and status["universe"] == PAIRS
    assert client.post("/api/crypto/jobs/protect", headers=auth).json()["job"] == "protect"


def create_app_with(main, extra):
    from trader.api.app import create_app

    return create_app(main, start_background=False, crypto_ctx=extra)


def test_telegram_buttons_name_their_account():
    coins = crypto_ctx(telegram_chat_id="42")
    run_nightly(coins)
    with coins.session() as session:
        row = ledger.list_proposals(session, coins.label, status="pending")[0]
    press = {"data": f"approve:C:{row.id}", "message": {"chat": {"id": 42}}}
    assert handle_telegram_callback(coins, press).startswith("Approved")
    other = {"data": f"approve:A:{row.id}", "message": {"chat": {"id": 42}}}
    assert "belongs to account A" in handle_telegram_callback(coins, other)
    stocks = make_ctx()
    poller = TelegramPoller(stocks, notifier=None)  # type: ignore[arg-type]
    poller.add_book(coins)
    assert poller._book_for("approve:C:1") is coins and poller._book_for("approve:1") is stocks
    assert any(buttons and buttons[0][0][1].startswith("approve:C:") for _, buttons in coins.notifier.sent)


def test_the_crypto_book_beside_the_stock_book(tmp_path):
    demo = make_settings(
        database_url=f"sqlite:///{tmp_path / 'trader.db'}", fake_broker_state=str(tmp_path / "b.json")
    )
    extra = crypto_book_settings(demo)
    assert extra is not None and extra.is_crypto and extra.broker == "fake"
    assert extra.database_url == f"sqlite:///{tmp_path / 'crypto-demo.db'}"
    assert extra.fake_broker_state == str(tmp_path / "fake_broker_crypto.json")

    env = tmp_path / ".env.crypto"
    env.write_text("ASSET_CLASS=crypto\nBROKER=alpaca\nALPACA_API_KEY=k\nALPACA_SECRET_KEY=s\n")
    real = make_settings(broker="alpaca", crypto_env_file=str(env))
    loaded = crypto_book_settings(real)
    assert loaded is not None and loaded.is_crypto and loaded.account_label == "C"
    env.write_text("BROKER=alpaca\n")
    with pytest.raises(ValueError, match="ASSET_CLASS=crypto"):
        crypto_book_settings(real)
    assert crypto_book_settings(make_settings(broker="alpaca")) is None


def test_the_ledger_follows_stops_that_end_at_the_broker():
    ctx = crypto_ctx()
    entered(ctx)
    first = open_stops(ctx.broker)[0]
    ctx.broker.cancel_order(first.id)
    protect(ctx)  # the position is bare again, so a fresh stop goes in
    with ctx.session() as session:
        rows = {row.client_order_id: row.status for row in ledger.recent_orders(session, ctx.label)}
    assert rows[first.client_order_id] == "canceled"
    assert rows[f"{first.client_order_id}2"] == "new"


def test_the_crypto_file_beats_the_stock_books_environment(tmp_path, monkeypatch):
    # Docker hands the stock book's .env to the process as variables; none may reach the crypto book.
    for key, value in {
        "UNIVERSE": "SPY,QQQ",
        "DATABASE_URL": "sqlite:///stock.db",
        "ACCOUNT_LABEL": "A",
    }.items():
        monkeypatch.setenv(key, value)
    env = tmp_path / ".env.crypto"
    env.write_text("ASSET_CLASS=crypto\nBROKER=alpaca\nALPACA_API_KEY=k\nALPACA_SECRET_KEY=s\nCOST_BPS=40\n")
    loaded = crypto_book_settings(make_settings(broker="alpaca", crypto_env_file=str(env)))
    assert loaded is not None
    assert loaded.universe_list == PAIRS and loaded.account_label == "C"
    assert loaded.database_url == "sqlite:///./crypto.db" and loaded.cost_bps == 40

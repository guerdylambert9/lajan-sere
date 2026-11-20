"""spy-trend: one fully invested name, SPY above its average and BIL below it.

Prices in these tests are built in memory. Nothing here reads the market, and nothing runs
Gate 1 or a 2016–2022 backtest.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from tests.helpers import TODAY, UNIVERSE, MutableClock, at, make_ctx, trending_frame
from trader import ledger
from trader.api.app import create_app
from trader.backtest import BacktestConfig, run_backtest
from trader.broker.fake import FakeBroker
from trader.cli import app
from trader.config import DEFAULT_WATCHLIST, Settings, TradingMode
from trader.data.base import FrameBarSource
from trader.models import AccountState, IntentKind, OrderIntent, ProposalStatus, Side
from trader.notify.telegram import LogNotifier
from trader.planner import plan_intents
from trader.risk import RiskContext, RiskLimits, check_order
from trader.services.approvals import decide_proposal
from trader.services.context import build_context
from trader.services.execution import submit_approved
from trader.services.pipeline import run_nightly
from trader.services.reconcile import reconcile
from trader.strategies import SpyTrend, TrendFollowing, get_strategy
from trader.strategies.spy_trend import BIL, SPY

WINDOW = 20
runner = CliRunner()


def account() -> AccountState:
    return AccountState(
        equity=100_000.0,
        cash=100_000.0,
        buying_power=100_000.0,
        day_start_equity=100_000.0,
        peak_equity=100_000.0,
        positions={},
    )


def prices() -> pd.DataFrame:
    """A rise, a 9% dip that stays above the average, a break below it, then a recovery."""
    rising = [100.0 + 2.0 * t for t in range(40)]
    dip = rising[-1] * 0.91
    crashed = [50.0] * (WINDOW + 5)
    recovered = [80.0] * 3
    spy = [*rising, dip, *crashed, *recovered]
    index = pd.bdate_range("2020-01-01", periods=len(spy))
    count = len(spy)
    return pd.DataFrame(
        {
            SPY: spy,
            "QQQ": [90.0 + t for t in range(count)],
            "IWM": [70.0 + 0.5 * t for t in range(count)],
            BIL: 100.0,
        },
        index=index,
    )


def active(row: pd.Series) -> list[str]:
    return [symbol for symbol, weight in row.items() if weight > 0]


def regimes(weights: pd.DataFrame) -> list[str]:
    names: list[str] = []
    for _, row in weights.iterrows():
        held = active(row)
        name = held[0] if held else "CASH"
        if not names or names[-1] != name:
            names.append(name)
    return names


def held_on(trades: pd.DataFrame, day: pd.Timestamp) -> list[str]:
    still_open = trades.exit_date.isna() | (trades.exit_date > day)
    return trades.loc[(trades.entry_date <= day) & still_open, "symbol"].tolist()


def test_above_the_average_is_fully_invested_in_spy_and_below_it_is_bil():
    closes = prices()
    weights = SpyTrend(WINDOW).target_weights(closes)
    assert list(weights.columns[:4]) == [SPY, "QQQ", "IWM", BIL]
    assert (weights.sum(axis=1).isin([0.0, 1.0])).all()
    assert (weights.gt(0).sum(axis=1) <= 1).all()
    assert (weights[["QQQ", "IWM"]] == 0).all().all()

    # The window is not full yet, so the account is still waiting.
    assert (weights.iloc[: WINDOW - 1] == 0).all().all()

    rising = weights.iloc[WINDOW - 1 : 40]
    assert (rising[SPY] == 1).all()
    assert (rising[BIL] == 0).all()

    dip = weights.iloc[40]
    assert closes[SPY].iloc[40] < closes[SPY].iloc[39] * 0.92  # more than an 8% stop
    assert dip[SPY] == 1 and dip[BIL] == 0  # still above the average, so the account stays in SPY

    defensive = weights.iloc[41 : 41 + WINDOW]
    assert (defensive[BIL] == 1).all()
    assert (defensive[SPY] == 0).all()

    assert weights.iloc[-1][SPY] == 1 and weights.iloc[-1][BIL] == 0
    assert regimes(weights) == ["CASH", SPY, BIL, SPY]


def test_a_close_equal_to_the_average_holds_bil():
    index = pd.bdate_range("2021-01-01", periods=8)
    closes = pd.DataFrame({SPY: [100.0] * 6 + [130.0, 90.0], "QQQ": 50.0, BIL: 100.0}, index=index)
    weights = SpyTrend(5).target_weights(closes)
    assert active(weights.iloc[4]) == [BIL]  # 100 against an average of 100
    assert active(weights.iloc[5]) == [BIL]
    assert active(weights.iloc[6]) == [SPY]
    assert active(weights.iloc[7]) == [BIL]
    assert (weights["QQQ"] == 0).all()


def test_bil_is_a_position_and_the_account_cap_does_not_apply():
    strategy = get_strategy("spy-trend")
    assert isinstance(strategy, SpyTrend)
    assert strategy.cash_park() is None
    assert strategy.position_cap() == 1.0
    assert strategy.uses_stops() is False
    assert strategy.extra_symbols() == (SPY, BIL)
    assert [variant.window for variant in strategy.variants()] == [160, 240]
    assert all(
        variant.position_cap() == 1.0 and variant.uses_stops() is False for variant in strategy.variants()
    )
    assert "SPY" in strategy.rule_text() and "BIL" in strategy.rule_text()
    with pytest.raises(ValueError, match="only buys"):
        get_strategy("spy-trend", shorts=True)

    for name in ("trend", "momentum", "trend-bil"):
        other = get_strategy(name)
        assert other.position_cap() is None
        assert other.uses_stops() is True


def test_the_planner_buys_one_full_position_and_still_caps_everyone_else():
    limits = RiskLimits()
    capped = plan_intents({"SPY": 1.0}, {"SPY": 100.0}, account(), limits, ["SPY"], date(2020, 1, 2), "bt")
    assert len(capped) == 1
    assert capped[0].stop_price is not None
    assert capped[0].notional <= 0.10 * 100_000 * 1.001

    strategy = SpyTrend()
    full = plan_intents(
        {"SPY": 1.0},
        {"SPY": 100.0, BIL: 100.0},
        account(),
        limits,
        ["QQQ", SPY, BIL],
        date(2020, 1, 2),
        "bt",
        position_cap=strategy.position_cap(),
        use_stops=strategy.uses_stops(),
    )
    assert [intent.symbol for intent in full] == [SPY]
    assert full[0].stop_price is None
    assert full[0].notional > 0.9 * 100_000


def test_backtest_switches_both_ways_and_stays_about_fully_invested():
    closes = prices()
    strategy = SpyTrend(WINDOW)
    weights = strategy.target_weights(closes)
    result = run_backtest(closes, strategy, RiskLimits(), BacktestConfig(cost_bps=0), universe=["QQQ", "IWM"])

    assert set(result.fills.symbol) == {SPY, BIL}
    assert (result.trades.exit_reason != "stop").all()
    signaled = weights.sum(axis=1) == 1
    assert (result.open_positions.loc[signaled] == 1).all()
    assert (result.exposure.loc[signaled] > 0.9).all()
    for day in weights.index[signaled]:
        assert held_on(result.trades, day) == active(weights.loc[day])
    buys = result.fills[result.fills.side == "buy"]
    for _, fill in buys.iterrows():
        assert fill.notional > 0.9 * result.equity.loc[fill.date]

    # The same prices under the trend rule still use the 10% cap.
    trend = run_backtest(
        closes, TrendFollowing(WINDOW), RiskLimits(), BacktestConfig(cost_bps=0), ["SPY", "QQQ", "IWM"]
    )
    trend_buys = trend.fills[trend.fills.side == "buy"]
    assert (
        trend_buys.notional.to_numpy() <= 0.10 * trend.equity.loc[trend_buys.date].to_numpy() * 1.001
    ).all()


def test_backtest_refuses_to_run_without_bil_prices():
    closes = prices().drop(columns=[BIL])
    with pytest.raises(ValueError, match="BIL"):
        run_backtest(closes, SpyTrend(WINDOW), RiskLimits(), universe=["SPY"])


def test_a_full_position_without_a_stop_passes_only_when_the_strategy_asks():
    intent = OrderIntent(
        symbol=SPY,
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        qty=990,
        limit_price=100.0,
        client_order_id="bt-20200102-SPY-buy",
    )
    usual = check_order(intent, account(), RiskLimits(), RiskContext(now=at(TODAY, 10, 30), universe={SPY}))
    assert {item.code for item in usual.violations} >= {"position_size", "missing_stop"}

    allowed = check_order(
        intent,
        account(),
        RiskLimits(),
        RiskContext(now=at(TODAY, 10, 30), universe={SPY, BIL}, position_cap=1.0, require_stops=False),
    )
    assert allowed.approved


def test_the_live_path_proposes_one_full_spy_position():
    frame = trending_frame()
    frame[BIL] = 100.0
    ctx = make_ctx(frame=frame, strategy=SpyTrend(50))
    result = run_nightly(ctx)
    assert result.skipped_reason is None
    with ctx.session() as session:
        rows = ledger.list_proposals(session, ctx.label)
    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == SPY and row.kind == IntentKind.ENTRY
    assert row.status == ProposalStatus.PENDING
    assert row.stop_price is None
    assert row.qty * row.limit_price > 50_000

    with ctx.session() as session:
        decide_proposal(session, row.id, True, by="test")
    ctx.now_fn.set(TODAY + timedelta(days=1), 10, 0)
    submitted = submit_approved(ctx)
    assert submitted.submitted and not submitted.blocked
    positions = ctx.broker.get_positions()
    assert [position.symbol for position in positions] == [SPY]
    assert positions[0].market_value > 50_000
    assert ctx.broker.get_open_orders() == []

    ctx.now_fn.set(TODAY + timedelta(days=1), 16, 30)
    check = reconcile(ctx)
    assert check.ok, check.mismatches


def test_explain_names_the_holding():
    closes = prices()
    reasons = SpyTrend(WINDOW).explain(closes)
    assert "holds SPY" in reasons[SPY]
    assert "holds SPY" in reasons[BIL]
    assert "only SPY or BIL" in reasons["QQQ"]


def _desk_frame(spy_up: bool) -> pd.DataFrame:
    """Fixture closes only. SPY either climbs through its average or falls through it."""
    index = pd.bdate_range(end=pd.Timestamp(TODAY), periods=320)
    step = pd.Series(range(320), dtype=float).to_numpy()
    spy = 400 + 0.5 * step if spy_up else 500 - step
    return pd.DataFrame(
        {
            "SPY": spy,
            "QQQ": 300 + 0.6 * step,
            "IWM": 200.0,
            "EFA": 80.0,
            "TLT": 100.0,
            "GLD": 180 + 0.2 * step,
            BIL: 100.0,
            "XLB": 50 + 0.3 * step,
            "XLC": 40 + 0.05 * step,
            "XLE": 70 - 0.1 * step,
        },
        index=index,
    )


def _stock_desk(frame: pd.DataFrame, **overrides: object):
    """A stock book on fixture prices. Strategy is the stock default unless overrides name one."""
    clock = MutableClock(at(TODAY, 17, 15))
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        universe=",".join(UNIVERSE),
        benchmark="SPY",
        broker="fake",
        data_source="synthetic",
        fake_broker_state="",
        telegram_bot_token="",
        telegram_chat_id="",
        api_token="",
        watchlist="XLB,XLC,XLE",
        **overrides,
    )
    return build_context(
        settings,
        broker=FakeBroker(cash=100_000, now_fn=clock),
        bars=FrameBarSource(frame),
        notifier=LogNotifier(),
        now_fn=clock,
    )


def _rows(ctx):
    with ctx.session() as session:
        return ledger.list_proposals(session, ctx.label)


def test_the_stock_book_defaults_to_spy_trend_and_stays_on_paper():
    stocks = Settings(_env_file=None)
    assert stocks.strategy == "spy-trend"
    assert stocks.watchlist == DEFAULT_WATCHLIST
    assert stocks.trading_mode == TradingMode.PAPER
    assert stocks.live_trading_confirmed is False
    assert stocks.auto_approve is False

    paper = Settings(_env_file=None, broker="alpaca")
    assert paper.strategy == "spy-trend"
    assert paper.trading_mode == TradingMode.PAPER
    assert paper.live_trading_confirmed is False
    assert paper.auto_approve is False
    assert paper.mode_label == "PAPER"

    assert Settings(_env_file=None, asset_class="crypto").strategy == "trend"
    assert Settings(_env_file=None, asset_class="forex").strategy == "trend"
    for name in ("trend", "momentum", "trend-bil"):
        chosen = Settings(_env_file=None, strategy=name)
        assert chosen.strategy == name
        rule = get_strategy(name)
        assert rule.name == name
        assert rule.position_cap() is None
        assert rule.uses_stops() is True


def test_the_paper_desk_proposes_one_pending_spy_or_bil_order():
    above = _stock_desk(_desk_frame(spy_up=True))
    assert above.strategy.name == "spy-trend" and above.strategy.params()["window"] == 200
    assert above.settings.trading_mode == TradingMode.PAPER
    assert above.settings.auto_approve is False
    held = run_nightly(above)
    assert held.skipped_reason is None
    assert held.targets[SPY] == 1 and held.targets[BIL] == 0
    assert held.targets["QQQ"] == 0
    rows = _rows(above)
    assert len(rows) == 1
    order = rows[0]
    assert order.symbol == SPY and order.kind == IntentKind.ENTRY
    assert order.status == ProposalStatus.PENDING
    assert order.stop_price is None
    assert order.qty * order.limit_price > 0.9 * 100_000

    client = TestClient(create_app(above, start_background=False))
    status = client.get("/api/status").json()
    assert status["strategy"] == {"name": "spy-trend", "window": 200}
    assert status["trading_mode"] == "paper" and status["auto_approve"] is False
    recs = client.get("/api/recommendations").json()
    assert "SPY" in recs["rule"] and "BIL" in recs["rule"]
    buys = [item for item in recs["items"] if item["call"] == "buy"]
    assert [item["symbol"] for item in buys] == [SPY]
    assert buys[0]["proposal"]["status"] == "pending"
    assert buys[0]["proposal"]["stop_price"] is None
    assert buys[0]["proposal"]["notional"] > 0.9 * 100_000
    scan = client.get("/api/scan").json()
    assert scan["tested"] is False and "STRATEGY=momentum" in scan["how_to_test"]
    assert {row["symbol"] for row in scan["rows"]} == {"XLB", "XLC", "XLE"}
    idea = next(row for row in scan["rows"] if row["label"] == "buy_idea")
    assert idea["stop"] is not None
    assert idea["qty"] * idea["entry"] <= 0.10 * 100_000 + 1e-6
    assert {row.symbol for row in rows}.isdisjoint({"XLB", "XLC", "XLE", "QQQ"})

    below = _stock_desk(_desk_frame(spy_up=False))
    defensive = run_nightly(below, scan=False)
    assert defensive.skipped_reason is None
    assert defensive.targets[BIL] == 1 and defensive.targets[SPY] == 0
    parked = _rows(below)
    assert len(parked) == 1
    assert parked[0].symbol == BIL and parked[0].status == ProposalStatus.PENDING
    assert parked[0].stop_price is None
    assert parked[0].qty * parked[0].limit_price > 0.9 * 100_000


def test_an_approved_spy_trend_bil_buy_is_not_rejected_for_the_ticker_list():
    """Send approved orders must accept the defensive BIL buy spy-trend already proposed."""
    below = _stock_desk(_desk_frame(spy_up=False))
    result = run_nightly(below, scan=False)
    assert result.skipped_reason is None
    assert result.targets[BIL] == 1 and result.targets[SPY] == 0
    (row,) = _rows(below)
    assert row.symbol == BIL and row.kind == IntentKind.ENTRY
    assert row.status == ProposalStatus.PENDING
    with below.session() as session:
        decide_proposal(session, row.id, True, by="test")
    below.now_fn.set(TODAY + timedelta(days=1), 10, 0)
    submitted = submit_approved(below)
    saved = _rows(below)
    messages = [
        violation.get("message", "")
        for proposal in saved
        for violation in (proposal.violations or [])
        if isinstance(violation, dict)
    ]
    assert not any("not on the approved ticker list" in message for message in messages)
    assert not any(
        violation.get("code") == "not_in_universe"
        for proposal in saved
        for violation in (proposal.violations or [])
        if isinstance(violation, dict)
    )
    assert submitted.submitted == [row.id]
    assert not submitted.blocked
    assert [position.symbol for position in below.broker.get_positions()] == [BIL]


def test_naming_another_strategy_keeps_its_capped_orders():
    frame = _desk_frame(spy_up=True)
    for name in ("trend", "momentum", "trend-bil"):
        ctx = _stock_desk(frame, strategy=name)
        assert ctx.strategy.name == name
        result = run_nightly(ctx, scan=False)
        assert result.skipped_reason is None, name
        entries = [row for row in _rows(ctx) if row.kind == IntentKind.ENTRY and row.symbol != BIL]
        assert entries, name
        assert all(row.stop_price is not None for row in entries)
        assert all(row.qty * row.limit_price <= 0.10 * 100_000 * 1.001 for row in entries)
        assert all(row.status == ProposalStatus.PENDING for row in _rows(ctx))
        assert not any(row.symbol == SPY and row.qty * row.limit_price > 0.5 * 100_000 for row in entries)


@pytest.fixture
def env(monkeypatch, tmp_path):
    values = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'trader.db'}",
        "FAKE_BROKER_STATE": str(tmp_path / "fake_broker.json"),
        "REPORTS_DIR": str(tmp_path / "reports"),
        "UNIVERSE": "SPY,QQQ,TLT,GLD",
        "BROKER": "fake",
        "DATA_SOURCE": "synthetic",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    from trader.config import get_settings

    get_settings.cache_clear()
    return tmp_path


def test_cli_accepts_spy_trend_on_synthetic_prices(env):
    result = runner.invoke(
        app, ["backtest", "--strategy", "spy-trend", "--start", "2020-06-01", "--end", "2020-09-30"]
    )
    assert result.exit_code == 0, result.output
    reports = list((env / "reports").glob("backtest-spy-trend-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text())
    assert report["strategy"]["name"] == "spy-trend"
    assert report["window"]["start"] == "2020-06-01"
    assert report["avg_exposure"] > 0.8

"""spy-trend: one fully invested name, SPY above its average and BIL below it.

Prices in these tests are built in memory. Nothing here reads the market, and nothing runs
Gate 1 or a 2016–2022 backtest.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import pytest
from typer.testing import CliRunner

from tests.helpers import TODAY, at, make_ctx, trending_frame
from trader import ledger
from trader.backtest import BacktestConfig, run_backtest
from trader.cli import app
from trader.models import AccountState, IntentKind, OrderIntent, ProposalStatus, Side
from trader.planner import plan_intents
from trader.risk import RiskContext, RiskLimits, check_order
from trader.services.approvals import decide_proposal
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

"""Explained recommendations, the watchlist scanner and Learn progress."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.helpers import TODAY, UNIVERSE, MutableClock, at, make_ctx, make_settings, trending_frame
from trader import ledger
from trader.api.app import create_app
from trader.models import AccountState, Position
from trader.planner import plan_intents
from trader.risk.limits import RiskLimits
from trader.services.approvals import decide_proposal
from trader.services.execution import submit_approved
from trader.services.pipeline import run_nightly
from trader.services.recommendations import build_recommendations, save_gate1, save_track_record
from trader.services.scanner import scan_closes
from trader.strategies.momentum import Momentum
from trader.strategies.trend import TrendFollowing


def calls(ctx):
    with ctx.session() as session:
        data = build_recommendations(ctx, session)
    return data, {item["symbol"]: item for item in data["items"]}


def approve_all(ctx):
    with ctx.session() as session:
        for row in ledger.list_proposals(session, ctx.label, status="pending"):
            decide_proposal(session, row.id, True, by="test")


# ---------------------------------------------------------------- explanations


def test_trend_explains_each_symbol_against_its_average():
    reasons = TrendFollowing(200).explain(trending_frame())
    assert reasons["SPY"].startswith("Closed at $") and "above its 200-day average" in reasons["SPY"]
    assert "below its 200-day average" in reasons["EFA"]
    short = TrendFollowing(200).explain(trending_frame(days=50))
    assert short["SPY"].startswith("Not enough history")


def test_momentum_explains_the_rank_at_the_last_rebalance():
    reasons = Momentum().explain(trending_frame())
    assert "rebalance" in reasons["QQQ"] and " of 6" in reasons["QQQ"]
    assert "Next rebalance: the first trading day of December" in reasons["QQQ"]
    assert "−" in reasons["TLT"]  # a falling asset reads with a real minus sign


def test_planner_says_why_a_buy_signal_got_no_order():
    account = AccountState(
        equity=100_000,
        cash=50_000,
        buying_power=50_000,
        day_start_equity=100_000,
        peak_equity=100_000,
        positions={"SPY": Position(symbol="SPY", qty=10, avg_entry_price=400, current_price=410)},
    )
    limits = RiskLimits.from_settings(make_settings(max_open_positions=1))
    skipped: dict[str, str] = {}
    intents = plan_intents(
        {"SPY": 0.1, "QQQ": 0.1},
        {"SPY": 410, "QQQ": 300},
        account,
        limits,
        ["SPY", "QQQ"],
        TODAY,
        "tpA",
        skipped=skipped,
    )
    assert intents == []
    assert skipped == {"QQQ": "The one position slot is full."}

    small = account.model_copy(update={"equity": 1_000, "cash": 1_000, "positions": {}})
    skipped = {}
    plan_intents({"QQQ": 0.1}, {"QQQ": 300}, small, limits, ["QQQ"], TODAY, "tpA", skipped=skipped)
    assert skipped["QQQ"].startswith("One share costs $300.60, more than the $100")


# ---------------------------------------------------------------- recommendations


def test_every_symbol_gets_a_call_with_its_order_and_numbers():
    ctx = make_ctx()
    run_nightly(ctx)
    data, by_symbol = calls(ctx)
    assert data["as_of"] == TODAY.isoformat()
    assert set(by_symbol) == set(UNIVERSE)
    assert by_symbol["SPY"]["call"] == "buy"
    proposal = by_symbol["SPY"]["proposal"]
    assert proposal["status"] == "pending"
    assert proposal["risk_dollars"] == pytest.approx(
        proposal["qty"] * (proposal["limit_price"] - proposal["stop_price"])
    )
    assert proposal["risk_pct"] <= 0.01 + 1e-9  # the 1% rule
    assert by_symbol["EFA"]["call"] == "stay_out" and by_symbol["EFA"]["proposal"] is None
    assert [item["call"] for item in data["items"]] == sorted(
        (item["call"] for item in data["items"]), key=["buy", "sell", "hold", "stay_out"].index
    )


def test_a_filled_buy_becomes_a_hold_with_its_stop():
    ctx = make_ctx()
    run_nightly(ctx)
    approve_all(ctx)
    ctx.now_fn.set(TODAY + timedelta(days=1), 10, 0)
    submit_approved(ctx)
    _, by_symbol = calls(ctx)
    held = by_symbol["SPY"]
    assert held["call"] == "hold"
    assert held["position"]["stop_price"] is not None
    assert held["position"]["at_risk"] == pytest.approx(
        held["position"]["qty"] * (held["position"]["current_price"] - held["position"]["stop_price"])
    )


def test_a_buy_without_an_order_says_why():
    ctx = make_ctx(max_open_positions=1)
    run_nightly(ctx)
    _, by_symbol = calls(ctx)
    buys = [item for item in by_symbol.values() if item["call"] == "buy"]
    with_order = [item for item in buys if item["proposal"]]
    without = [item for item in buys if not item["proposal"]]
    assert len(with_order) == 1 and without
    assert all(item["detail"] == "The one position slot is full." for item in without)


def test_track_record_and_gate1_show_only_for_the_current_strategy():
    ctx = make_ctx()
    report = {
        "strategy": ctx.strategy.describe(),
        "window": {"start": "2016-01-04", "end": "2022-12-30"},
        "config": {"lag": 1, "cost_bps": 5.0},
        "trades": {"round_trips": 40, "win_rate": 0.45, "avg_win_pct": 6.0, "avg_loss_pct": -2.0},
        "performance": {"cagr": 0.07, "max_drawdown": -0.12},
        "benchmark": {"symbol": "SPY", "cagr": 0.1, "max_drawdown": -0.34},
    }
    other = report | {"strategy": Momentum().describe()}

    class Report:
        strategy = ctx.strategy.describe()
        passed = True

    with ctx.session() as session:
        save_track_record(session, report, "alpaca")
        save_track_record(session, other, "alpaca")
        save_gate1(session, Report(), TODAY, "alpaca")
    data, _ = calls(ctx)
    assert data["track_record"]["backtest"]["win_rate"] == 0.45
    assert data["track_record"]["backtest"]["strategy"]["name"] == "trend"
    assert data["track_record"]["gate1"]["passed"] is True

    ctx.strategy = TrendFollowing(150)  # different parameters: the old records no longer apply
    data, _ = calls(ctx)
    assert data["track_record"]["backtest"] is None and data["track_record"]["gate1"] is None


# ---------------------------------------------------------------- scanner


def test_scan_ranks_by_momentum_and_labels_the_top_ideas():
    rows = scan_closes(trending_frame(), top_n=2)
    ranked = [row for row in rows if row["rank"] is not None]
    assert [row["rank"] for row in ranked] == list(range(1, len(ranked) + 1))
    momentum = [row["momentum"] for row in ranked]
    assert momentum == sorted(momentum, reverse=True)
    for row in ranked:
        if row["momentum"] <= 0:
            assert row["label"] == "skip"
        elif row["rank"] <= 2:
            assert row["label"] == "buy_idea"
        else:
            assert row["label"] == "watch"
    assert sum(row["label"] == "buy_idea" for row in ranked) == 2
    assert all("52-week high" in row["reason"] for row in ranked)


def test_scan_runs_nightly_and_sizes_ideas_with_the_risk_rules():
    ctx = make_ctx(watchlist=",".join(UNIVERSE))
    run_nightly(ctx)
    client = TestClient(create_app(ctx, start_background=False))
    scan = client.get("/api/scan").json()
    assert scan["as_of"] == TODAY.isoformat() and scan["tested"] is False
    idea = next(row for row in scan["rows"] if row["label"] == "buy_idea")
    assert idea["stop"] == pytest.approx(round(idea["entry"] * 0.92 + 0.004999, 2), abs=0.011)
    assert idea["risk_dollars"] == pytest.approx(idea["qty"] * (idea["entry"] - idea["stop"]))
    assert idea["qty"] * idea["entry"] <= 0.10 * 100_000 + 1e-6  # the position cap
    rerun = client.post("/api/jobs/scan").json()
    assert rerun["result"]["rows"]


def test_scan_with_too_little_history_says_so():
    rows = scan_closes(trending_frame(days=120), top_n=3)
    assert {row["label"] for row in rows} == {"no_data"}


# ---------------------------------------------------------------- API


def test_recommendations_api_after_the_nightly_job():
    ctx = make_ctx()
    client = TestClient(create_app(ctx, start_background=False))
    empty = client.get("/api/recommendations").json()
    assert empty["items"] == [] and empty["rule"].startswith("Own each symbol")
    client.post("/api/jobs/nightly")
    body = client.get("/api/recommendations").json()
    assert {item["call"] for item in body["items"]} >= {"buy", "stay_out"}
    assert body["lesson"] == "trend-following"


def test_learn_progress_is_saved_and_validated():
    ctx = make_ctx(clock=MutableClock(at(TODAY, 12, 0)))
    client = TestClient(create_app(ctx, start_background=False))
    assert client.get("/api/learn/progress").json() == {"lessons": {}, "quizzes": {}}
    done = client.post("/api/learn/lessons/stop-orders", json={"done": True}).json()
    assert "stop-orders" in done["lessons"]
    client.post("/api/learn/quizzes/risk", json={"score": 3, "total": 4})
    client.post("/api/learn/quizzes/risk", json={"score": 2, "total": 4})
    progress = client.get("/api/learn/progress").json()
    assert progress["quizzes"]["risk"] == {
        "score": 2,
        "total": 4,
        "best": 3,
        "at": progress["quizzes"]["risk"]["at"],
    }
    undone = client.post("/api/learn/lessons/stop-orders", json={"done": False}).json()
    assert "stop-orders" not in undone["lessons"]
    assert client.post("/api/learn/lessons/Bad%20Id", json={"done": True}).status_code == 400
    assert client.post("/api/learn/quizzes/risk", json={"score": 5, "total": 4}).status_code == 422

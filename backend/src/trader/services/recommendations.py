"""Today's recommendations: a call on every symbol, each with its reason and its numbers.

The nightly job saves a snapshot: the targets, the closes, the strategy's reason for each
symbol, and why any buy signal got no order. The dashboard turns that snapshot and the live
account into calls, so a fill during the day turns a Buy into a Hold without a new run.

Calls come only from the strategy's rules. An AI note, when there is one, rides along on the
order it reviewed; it never creates a call. With forex short selling on, a target below zero
is a Sell short call, a held short is a Hold short, and one whose signal ends is a Buy to cover.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from trader import ledger, money
from trader.db import ProposalRow
from trader.models import BrokerOrder, IntentKind, Position, ProposalStatus, Side, action_of

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from trader.backtest.gates import GateReport
    from trader.services.context import AppContext
    from trader.strategies.base import Strategy

SNAPSHOT_KEY = "recommendations"


def track_record_key(strategy_name: str) -> str:
    return f"track_record:{strategy_name}"


def gate1_key(strategy_name: str) -> str:
    return f"gate1_result:{strategy_name}"


CALL_ORDER = {"buy": 0, "short": 1, "sell": 2, "cover": 3, "hold": 4, "hold_short": 5, "stay_out": 6}
# Which proposal each call looks for: (side, kind).
CALL_ORDERS = {
    "buy": (Side.BUY, IntentKind.ENTRY),
    "short": (Side.SELL, IntentKind.ENTRY),
    "sell": (Side.SELL, IntentKind.EXIT),
    "cover": (Side.BUY, IntentKind.EXIT),
}
OPEN_PROPOSALS = {ProposalStatus.PENDING, ProposalStatus.APPROVED, ProposalStatus.SUBMITTED}


def save_snapshot(
    session: Session,
    *,
    as_of: date,
    strategy: Strategy,
    targets: dict[str, float],
    prices: dict[str, float],
    reasons: dict[str, str],
    skipped: dict[str, str],
) -> None:
    ledger.set_state(
        session,
        SNAPSHOT_KEY,
        {
            "as_of": as_of.isoformat(),
            "strategy": strategy.describe(),
            "rule": strategy.rule_text(),
            "lesson": strategy.lesson,
            "targets": targets,
            "prices": prices,
            "reasons": reasons,
            "skipped": skipped,
        },
    )


def save_track_record(session: Session, report: dict[str, Any], data_source: str) -> None:
    """Keep the latest backtest's headline numbers so every call can show its rule's record."""
    trades, performance, benchmark = report["trades"], report["performance"], report["benchmark"]
    ledger.set_state(
        session,
        track_record_key(report["strategy"]["name"]),
        {
            "strategy": report["strategy"],
            "start": report["window"]["start"],
            "end": report["window"]["end"],
            "data_source": data_source,
            "lag": report["config"].get("lag"),
            "cost_bps": report["config"].get("cost_bps"),
            "round_trips": trades["round_trips"],
            "win_rate": trades["win_rate"],
            "avg_win_pct": trades["avg_win_pct"],
            "avg_loss_pct": trades["avg_loss_pct"],
            "cagr": performance["cagr"],
            "max_drawdown": performance["max_drawdown"],
            "benchmark": {
                "symbol": benchmark["symbol"],
                "cagr": benchmark["cagr"],
                "max_drawdown": benchmark["max_drawdown"],
            },
        },
    )


def save_gate1(session: Session, report: GateReport, day: date, data_source: str) -> None:
    ledger.set_state(
        session,
        gate1_key(report.strategy["name"]),
        {
            "strategy": report.strategy,
            "passed": report.passed,
            "on": day.isoformat(),
            "data_source": data_source,
        },
    )


def _proposal_view(row: ProposalRow, equity: float, ctx: AppContext) -> dict[str, Any]:
    entry = row.kind == IntentKind.ENTRY
    short = row.side == Side.SELL and entry
    # Crypto stops are stop-limits: the worst case is a fill at the limit, below the stop.
    floor = None
    if row.stop_price is not None and ctx.limits.stop_limit_band_pct > 0 and not short:
        floor = ctx.rules.price_down(row.symbol, ctx.limits.stop_limit_price(row.stop_price))
    worst = floor if floor is not None else row.stop_price
    risk = None
    if worst is not None:
        risk = money.loss_at(row.symbol, -row.qty if short else row.qty, row.limit_price, worst)
    action = action_of(row.side, row.kind)
    return {
        "id": row.id,
        "as_of": row.as_of.isoformat(),
        "status": row.status,
        "side": row.side,
        "action": action,
        "qty": row.qty,
        "limit_price": row.limit_price,
        "stop_price": row.stop_price,
        "stop_limit_price": floor,
        "notional": money.notional(row.symbol, row.qty, row.limit_price),
        "risk_dollars": risk,
        "risk_pct": risk / equity if risk is not None and equity > 0 else None,
        "violations": [v.get("message", "") for v in (row.violations or []) if isinstance(v, dict)],
        "ai_rating": row.ai_rating,
        "ai_summary": row.ai_summary,
    }


def _position_view(position: Position, stop_order: BrokerOrder | None) -> dict[str, Any]:
    cost = position.cost_basis
    stop = stop_order.stop_price if stop_order else None
    floor = stop_order.limit_price if stop_order and stop_order.order_type == "stop_limit" else None
    worst = floor if floor is not None else stop
    at_risk = None
    if worst is not None:
        at_risk = money.loss_at(position.symbol, position.qty, position.current_price, worst)
    return {
        "side": "short" if position.is_short else "long",
        "qty": position.qty,
        "avg_entry_price": position.avg_entry_price,
        "current_price": position.current_price,
        "market_value": position.market_value,
        "unrealized_pl": position.unrealized_pl,
        "unrealized_pct": position.unrealized_pl / cost if cost else None,
        "stop_price": stop,
        "stop_limit_price": floor,
        "at_risk": at_risk,
    }


def _proposals_by_symbol(
    session: Session, label: str, as_of: date
) -> dict[tuple[str, str, str], ProposalRow]:
    """Today's proposal for each symbol, side and kind, or an older one still open."""
    rows = session.scalars(
        select(ProposalRow)
        .where(ProposalRow.account_label == label)
        .where((ProposalRow.as_of == as_of) | ProposalRow.status.in_([str(s) for s in OPEN_PROPOSALS]))
        .order_by(ProposalRow.as_of, ProposalRow.id)
    ).all()
    found: dict[tuple[str, str, str], ProposalRow] = {}
    for row in rows:
        found[(row.symbol, row.side, row.kind)] = row  # later rows win: today's over older open ones
    return found


def _account_record(session: Session, label: str) -> dict[str, Any] | None:
    history = ledger.equity_history(session, label)
    if len(history) < 2 or history[0].equity <= 0:
        return None
    first, last = history[0], history[-1]
    benchmark = None
    if first.benchmark_price and last.benchmark_price:
        benchmark = last.benchmark_price / first.benchmark_price - 1
    return {
        "since": first.as_of.isoformat(),
        "days": len(history),
        "return": last.equity / first.equity - 1,
        "benchmark_return": benchmark,
    }


def build_recommendations(ctx: AppContext, session: Session) -> dict[str, Any]:
    snapshot = ledger.get_state(session, SNAPSHOT_KEY)
    strategy = ctx.strategy.describe()
    track = ledger.get_state(session, track_record_key(ctx.strategy.name))
    gate1 = ledger.get_state(session, gate1_key(ctx.strategy.name))
    base: dict[str, Any] = {
        "as_of": None,
        "strategy": strategy,
        "rule": ctx.strategy.rule_text(),
        "lesson": ctx.strategy.lesson,
        "data_source": str(ctx.settings.data_source),
        "benchmark": ctx.settings.benchmark_symbol,
        "track_record": {
            "backtest": track if track and track.get("strategy") == strategy else None,
            "gate1": gate1 if gate1 and gate1.get("strategy") == strategy else None,
            "account": _account_record(session, ctx.label),
        },
        "items": [],
    }
    if not snapshot or snapshot.get("strategy") != strategy:
        return base

    as_of = date.fromisoformat(snapshot["as_of"])
    positions = {
        p.symbol: p
        for p in ctx.broker.get_positions()
        if (p.qty > 0 or (ctx.is_forex and p.qty < 0)) and not ctx.rules.is_dust(p.symbol, abs(p.qty))
    }
    open_orders = ctx.broker.get_open_orders()
    stops = {
        symbol: next((o for o in open_orders if o.symbol == symbol and o.protects(p.qty)), None)
        for symbol, p in positions.items()
    }
    equity = ctx.broker.get_account().equity
    proposals = _proposals_by_symbol(session, ctx.label, as_of)

    items = []
    for symbol, weight in snapshot["targets"].items():
        target = weight if weight is not None else 0.0
        position = positions.get(symbol)
        if position is None:
            call = "buy" if target > 0 else "short" if target < 0 else "stay_out"
        elif position.qty > 0:
            call = "hold" if target > 0 else "sell"  # a long whose signal turned short closes first
        else:
            call = "hold_short" if target < 0 else "cover"

        item: dict[str, Any] = {
            "symbol": symbol,
            "call": call,
            "reason": snapshot["reasons"].get(symbol, ""),
            "detail": None,
            "price": snapshot["prices"].get(symbol),
            "target_weight": weight,
            "proposal": None,
            "position": _position_view(position, stops.get(symbol)) if position else None,
        }
        wanted = CALL_ORDERS.get(call)
        proposal = proposals.get((symbol, str(wanted[0]), str(wanted[1]))) if wanted else None
        if proposal is not None:
            item["proposal"] = _proposal_view(proposal, equity, ctx)
            if proposal.status == ProposalStatus.BLOCKED:
                item["detail"] = "Blocked by the risk checks: " + "; ".join(item["proposal"]["violations"])
        elif call in ("buy", "short"):
            item["detail"] = snapshot["skipped"].get(symbol) or "No order was made for it."
        elif call == "sell":
            item["detail"] = "No sell order was made for it yet."
        elif call == "cover":
            item["detail"] = "No buy-back order was made for it yet."
        items.append(item)

    items.sort(key=lambda i: (CALL_ORDER[i["call"]], -abs(i["target_weight"] or 0), i["symbol"]))
    return base | {"as_of": snapshot["as_of"], "items": items}

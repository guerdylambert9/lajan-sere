"""Reconciliation: does what the ledger says match what the broker holds?

Checks: every submitted order exists at the broker; no unknown orders carry our prefix;
every position has a protective stop; no positions outside the universe. It also cancels
entries that didn't fill, records the day's equity, and engages the kill switch when the
drawdown limit is hit.

Stocks run it after the close. Crypto never closes, so the crypto book runs it once a day,
just after Alpaca's crypto day ends at midnight Chicago time; the protect job handles unfilled
entries and missing stops every few minutes in between. Forex runs it just after the 5 pm New
York close on weekdays; any of its entries or exits still waiting are canceled then (the stops
stay), and the next signal plans them afresh.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from trader import ledger
from trader.assets import fmt_qty
from trader.models import BrokerOrder, ProposalStatus, Side
from trader.services import killswitch
from trader.services.account import PEAK_KEY

if TYPE_CHECKING:
    from trader.services.context import AppContext

log = logging.getLogger(__name__)

DONE_AT_BROKER = {"canceled", "expired", "rejected", "done_for_day", "stopped", "suspended"}


@dataclass
class ReconcileResult:
    ok: bool
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    canceled_stale_entries: int = 0
    kill_switch_engaged: bool = False
    equity: float | None = None


def sync_submitted(
    ctx: AppContext, session: Session, broker_orders: Iterable[BrokerOrder]
) -> list[dict[str, Any]]:
    """Copy the broker's view of every submitted proposal into the ledger. Returns mismatches."""
    by_client_id = {o.client_order_id: o for o in broker_orders}
    mismatches: list[dict[str, Any]] = []
    for row in ledger.proposals_with_status(session, ctx.label, {ProposalStatus.SUBMITTED}):
        order = by_client_id.get(row.client_order_id) or ctx.broker.get_order_by_client_id(
            row.client_order_id
        )
        if order is None:
            mismatches.append(
                {
                    "type": "missing_at_broker",
                    "proposal_id": row.id,
                    "message": f"Proposal #{row.id} ({row.client_order_id}) was submitted but the broker has no such order.",
                }
            )
            continue
        ledger.upsert_order(session, order, ctx.label, proposal_id=row.id)
        if order.status == "filled":
            row.status = ProposalStatus.FILLED
        elif order.status in DONE_AT_BROKER:
            row.status = ProposalStatus.CANCELED
            row.error = f"Broker status: {order.status}"
    return mismatches


def sync_open_orders(ctx: AppContext, session: Session, broker_orders: Iterable[BrokerOrder]) -> None:
    """Refresh orders the ledger still shows as working, such as crypto stops, which have no
    proposal of their own, so the dashboard never lists a canceled stop as working."""
    by_client_id = {o.client_order_id: o for o in broker_orders}
    for row in ledger.open_order_rows(session, ctx.label):
        order = by_client_id.get(row.client_order_id) or ctx.broker.get_order_by_client_id(
            row.client_order_id
        )
        if order is not None:
            ledger.upsert_order(session, order, ctx.label)


def reconcile(ctx: AppContext) -> ReconcileResult:
    settings = ctx.settings
    prefix = settings.client_order_prefix + "-"
    now = ctx.now()
    canceled = 0
    engaged_now = False

    if ctx.is_crypto:  # place any missing stop and clear stale entries before checking
        from trader.services.protect import protect

        try:
            canceled += protect(ctx).canceled_orders
        except Exception:
            log.exception("The crypto protection pass failed during reconciliation")

    with ctx.session() as session:
        broker_orders = ctx.broker.get_orders_since(now - timedelta(days=10))
        submitted_ids = {
            row.client_order_id
            for row in ledger.proposals_with_status(session, ctx.label, {ProposalStatus.SUBMITTED})
        }
        mismatches = sync_submitted(ctx, session, broker_orders)
        sync_open_orders(ctx, session, broker_orders)

        known = ledger.used_client_order_ids(session) | submitted_ids
        for order in broker_orders:
            if (
                order.parent_id is None
                and order.client_order_id.startswith(prefix)
                and order.client_order_id not in known
            ):
                mismatches.append(
                    {
                        "type": "unknown_order",
                        "client_order_id": order.client_order_id,
                        "message": f"Broker order {order.client_order_id} ({order.side} {fmt_qty(order.qty)} "
                        f"{order.symbol}) is not in the ledger.",
                    }
                )

        open_orders = ctx.broker.get_open_orders()
        universe = set(settings.universe_list)
        unit = f"{ctx.rules.unit}s"
        for position in ctx.broker.get_positions():
            if position.qty < 0 and not ctx.is_forex:  # only the forex book may sell short
                mismatches.append(
                    {
                        "type": "short_position",
                        "symbol": position.symbol,
                        "message": f"{position.symbol}: a short of {fmt_qty(-position.qty)} {unit} that the app "
                        "didn't open (this book never sells short).",
                    }
                )
                continue
            if position.qty == 0 or (ctx.is_crypto and ctx.rules.is_dust(position.symbol, position.qty)):
                continue
            # A long needs a sell stop under it, a short a buy stop over it.
            if not any(o.symbol == position.symbol and o.protects(position.qty) for o in open_orders):
                held = (
                    f"{fmt_qty(position.qty)} {unit}"
                    if position.qty > 0
                    else (f"a short of {fmt_qty(-position.qty)} {unit}")
                )
                mismatches.append(
                    {
                        "type": "unprotected_position",
                        "symbol": position.symbol,
                        "message": f"{position.symbol}: {held} with no protective stop at the broker.",
                    }
                )
            if position.symbol not in universe:
                mismatches.append(
                    {
                        "type": "unmanaged_position",
                        "symbol": position.symbol,
                        "message": f"{position.symbol} is held but is not in the strategy's universe.",
                    }
                )

        stale: list[BrokerOrder] = []
        if ctx.is_forex:  # entries and exits are good for one session; the stops stay
            stale = [
                o for o in open_orders if not o.is_protective_stop and o.client_order_id.startswith(prefix)
            ]
        elif not ctx.is_crypto and not ctx.broker.clock().is_open:
            stale = [o for o in open_orders if o.side == Side.BUY and o.client_order_id.startswith(prefix)]
        for order in stale:
            ctx.broker.cancel_order(order.id)
            canceled += 1
            ledger.audit(session, "stale_entry_canceled", client_order_id=order.client_order_id)

        info = ctx.broker.get_account()
        peak = max(float(ledger.get_state(session, PEAK_KEY, info.equity) or info.equity), info.equity)
        ledger.set_state(session, PEAK_KEY, peak)
        try:
            benchmark_price: float | None = ctx.broker.latest_price(settings.benchmark_symbol)
        except Exception:
            benchmark_price = None
        ledger.record_equity(session, ctx.bar_date(), info.equity, info.cash, benchmark_price, ctx.label)

        drawdown = (peak - info.equity) / peak * 100 if peak > 0 else 0.0
        if drawdown >= settings.max_drawdown_pct and not killswitch.is_engaged(session):
            killswitch.engage(
                ctx,
                session,
                reason=f"Drawdown of {drawdown:.1f}% reached the {settings.max_drawdown_pct:g}% limit",
                by="reconcile",
            )
            engaged_now = True

        ok = not mismatches
        ledger.record_reconciliation(session, ok, mismatches, ctx.label, at=now)
        ledger.set_state(
            session, "last_reconcile_run", {"at": now.isoformat(), "ok": ok, "mismatches": len(mismatches)}
        )

    if mismatches:
        ctx.notify(
            f"[{settings.mode_label} {ctx.label}] Reconciliation found {len(mismatches)} problem(s):\n"
            + "\n".join(m["message"] for m in mismatches[:10])
        )
    return ReconcileResult(
        ok=not mismatches,
        mismatches=mismatches,
        canceled_stale_entries=canceled,
        kill_switch_engaged=engaged_now,
        equity=info.equity,
    )

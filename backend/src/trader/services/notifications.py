"""Message text for proposals and job results."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from trader.assets import fmt_price, fmt_qty
from trader.db import ProposalRow
from trader.models import ProposalStatus, action_of

if TYPE_CHECKING:
    from trader.services.context import AppContext

ACTION_WORDS = {"buy": "BUY", "sell": "SELL", "short": "SELL SHORT", "cover": "BUY TO COVER"}


def action_word(row: ProposalRow) -> str:
    """BUY, SELL, or for a forex short SELL SHORT and BUY TO COVER."""
    return ACTION_WORDS[action_of(row.side, row.kind)]


def proposal_line(row: ProposalRow) -> str:
    stop = f", stop {fmt_price(row.stop_price, row.symbol)}" if row.stop_price else ""
    price = fmt_price(row.limit_price, row.symbol)
    return f"#{row.id} {action_word(row)} {fmt_qty(row.qty)} {row.symbol} @ {price}{stop} ({row.kind})"


def notify_proposals(ctx: AppContext, rows: Sequence[ProposalRow]) -> None:
    pending = [r for r in rows if r.status == ProposalStatus.PENDING]
    approved = [r for r in rows if r.status == ProposalStatus.APPROVED]
    blocked = [r for r in rows if r.status == ProposalStatus.BLOCKED]
    if not rows:
        return
    head = f"[{ctx.settings.mode_label} {ctx.label}] Signals for {rows[0].as_of}"
    summary = f"{len(pending)} waiting for approval, {len(approved)} auto-approved, {len(blocked)} blocked."
    ctx.notify(f"{head}: {summary}")
    for row in pending:
        ai = f"\nAI: {row.ai_rating}" if row.ai_rating and row.ai_rating != "no_opinion" else ""
        ctx.notify(
            f"{proposal_line(row)}\n{row.reason}{ai}",
            buttons=[
                [("Approve", f"approve:{ctx.label}:{row.id}"), ("Reject", f"reject:{ctx.label}:{row.id}")]
            ],
        )
    if blocked:
        lines = [
            f"{proposal_line(r)}: " + ", ".join(v.get("code", "?") for v in (r.violations or []))
            for r in blocked
        ]
        ctx.notify("Blocked by risk checks:\n" + "\n".join(lines))

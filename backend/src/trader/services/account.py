"""Account state as the risk engine sees it: broker balances plus the stored equity peak."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from trader import ledger
from trader.models import AccountState

if TYPE_CHECKING:
    from trader.services.context import AppContext

PEAK_KEY = "peak_equity"


def load_account_state(ctx: AppContext, session: Session) -> AccountState:
    info = ctx.broker.get_account()
    # Forex can hold shorts (qty below zero); the other books only ever hold what they bought.
    positions = {p.symbol: p for p in ctx.broker.get_positions() if p.qty > 0 or (ctx.is_forex and p.qty < 0)}
    if ctx.is_crypto:  # a crypto fee can leave a sliver too small to sell; it isn't a position
        positions = {s: p for s, p in positions.items() if not ctx.rules.is_dust(s, p.qty)}
    stored_peak = ledger.get_state(session, PEAK_KEY, info.equity)
    peak = max(float(stored_peak or info.equity), info.equity)
    # A broker that doesn't report the previous close's equity (OANDA) starts the day at the
    # equity the last reconciliation recorded.
    day_start = info.last_equity or ledger.latest_equity(session, ctx.label) or info.equity
    return AccountState(
        equity=info.equity,
        cash=info.cash,
        buying_power=min(info.cash, info.buying_power) if info.cash > 0 else info.buying_power,
        day_start_equity=day_start,
        peak_equity=peak,
        positions=positions,
    )

"""Submission: send approved proposals to the broker, after a fresh risk check.

Each order is re-priced from the latest trade, re-sized to the current limits, and checked
again. Exits go first and cancel their protective stop before selling, since the broker holds
those shares for the stop. Stocks go out in the morning, inside the trading window; crypto goes
out within minutes of your approval, at any hour, and gets its stop-limit as soon as it fills.
Forex goes out in the morning too, while the London and New York sessions overlap; its exits
leave the stop-loss in place, since OANDA cancels it when the exit closes the trade. A forex
short is re-priced the same way, mirrored: it sells a little below the price, stops above it,
and is held back if the price has already fallen too far from the close it was sized on.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from trader import forex, ledger, money
from trader.assets import fmt_price
from trader.db import ProposalRow
from trader.models import AccountState, IntentKind, OrderIntent, ProposalStatus, Side, Violation
from trader.planner import cap_by_risk, entry_prices
from trader.risk.engine import RiskContext, check_order
from trader.services import killswitch
from trader.services.account import load_account_state

if TYPE_CHECKING:
    from trader.broker import Broker
    from trader.services.context import AppContext

log = logging.getLogger(__name__)


@dataclass
class SubmitResult:
    submitted: list[int] = field(default_factory=list)
    blocked: list[int] = field(default_factory=list)
    dry_run: list[int] = field(default_factory=list)
    errors: list[int] = field(default_factory=list)
    expired: list[int] = field(default_factory=list)
    skipped_reason: str | None = None


def _cash_symbols(ctx: AppContext) -> frozenset[str]:
    park = ctx.strategy.cash_park()
    return frozenset({park.symbol}) if park is not None else frozenset()


def refresh_intent(
    ctx: AppContext, row: ProposalRow, account: AccountState
) -> tuple[OrderIntent | None, Violation | None]:
    """Re-price and re-size a proposal at the current market price."""
    settings = ctx.settings
    limits = ctx.limits
    rules = ctx.rules
    buffer = limits.entry_limit_buffer_pct / 100
    price = ctx.broker.latest_price(row.symbol)
    parking = row.symbol in _cash_symbols(ctx)

    if row.kind == IntentKind.EXIT:
        position = account.positions.get(row.symbol)
        long = row.side == Side.SELL  # a sell closes a long, a buy closes a short
        held = (position.qty if long else -position.qty) if position is not None else 0.0
        # A cash-fund sale resizes or funds an entry: it sells the planned shares, not the whole lot.
        qty = rules.floor_qty(row.symbol, min(row.qty, held) if parking else held) if held > 0 else 0.0
        if qty <= 0:
            return None, Violation(
                code="no_position",
                message=f"No {row.symbol} left to sell (a stop may have closed it)."
                if long
                else f"No {row.symbol} short left to buy back (a stop may have closed it).",
            )
        limit = (
            rules.price_down(row.symbol, price * (1 - buffer))
            if long
            else rules.price_up(row.symbol, price * (1 + buffer))
        )
        return (
            OrderIntent(
                symbol=row.symbol,
                side=Side(row.side),
                kind=IntentKind.EXIT,
                qty=qty,
                limit_price=limit,
                source=row.source,
                reason=row.reason,
                client_order_id=row.client_order_id,
            ),
            None,
        )

    short = row.side == Side.SELL
    gap = settings.max_gap_pct / 100
    if not short and price > row.est_price * (1 + gap):
        return None, Violation(
            code="gap_too_large",
            message=f"{row.symbol} is at {fmt_price(price, row.symbol)}, more than {settings.max_gap_pct:g}% "
            f"above the {fmt_price(row.est_price, row.symbol)} close it was sized on.",
        )
    if short and price < row.est_price * (1 - gap):
        return None, Violation(
            code="gap_too_large",
            message=f"{row.symbol} is at {fmt_price(price, row.symbol)}, more than {settings.max_gap_pct:g}% "
            f"below the {fmt_price(row.est_price, row.symbol)} close the short was sized on.",
        )
    limit, stop = entry_prices(rules, limits, row.symbol, price, short)
    unit = money.unit_cost(row.symbol, limit)
    cap_by_cash = rules.floor_qty(row.symbol, account.buying_power / unit)
    if parking:
        # No 10% cap and no stop: the cash fund is not a risk position.
        stop = None
        qty = min(float(row.qty), cap_by_cash)
    else:
        cap = ctx.strategy.position_cap()
        fraction = limits.max_entry_fraction() if cap is None else cap
        if not ctx.strategy.uses_stops():
            stop = None
        cap_by_limits = rules.floor_qty(row.symbol, fraction * account.equity / unit)
        qty = min(float(row.qty), cap_by_limits, cap_by_cash)
        if ctx.strategy.uses_stops():
            qty = cap_by_risk(rules, limits, row.symbol, qty, limit, stop, account.equity, short)
    if qty <= 0:
        wanted = f"the smallest {row.symbol} order" if rules.crypto else f"one {row.symbol} {rules.unit}"
        return None, Violation(code="insufficient_cash", message=f"Not enough buying power for {wanted}.")
    return (
        OrderIntent(
            symbol=row.symbol,
            side=Side.SELL if short else Side.BUY,
            kind=IntentKind.ENTRY,
            qty=qty,
            limit_price=limit,
            stop_price=stop,
            source=row.source,
            reason=row.reason,
            client_order_id=row.client_order_id,
        ),
        None,
    )


def cancel_symbol_orders(broker: Broker, symbol: str, wait_seconds: float = 5.0) -> int:
    """Cancel open orders for one symbol (its protective stop) and wait for the broker to release the shares."""
    orders = broker.get_open_orders(symbol)
    for order in orders:
        broker.cancel_order(order.id)
    deadline = time.monotonic() + wait_seconds
    while orders and broker.get_open_orders(symbol) and time.monotonic() < deadline:
        time.sleep(0.25)
    return len(orders)


def submit_approved(ctx: AppContext) -> SubmitResult:
    settings = ctx.settings
    result = SubmitResult()
    crypto_entries: list[str] = []
    with ctx.session() as session:
        if killswitch.is_engaged(session):
            result.skipped_reason = "The kill switch is engaged."
            return result
        clock = None if ctx.is_crypto else ctx.broker.clock()
        if clock is not None and not clock.is_open:
            result.skipped_reason = "The market is closed."
            return result
        if ctx.is_forex and forex.in_rollover(ctx.now()):
            result.skipped_reason = (
                "Spreads widen around the 5 pm New York close; approved orders wait until 5:15 pm."
            )
            return result

        today = ctx.today()
        if ctx.is_crypto:  # each daily run replaces the one before
            result.expired = ledger.expire_stale(
                session, ctx.label, ctx.bar_date(), max_age_days=1, reason="Replaced by a newer daily signal."
            )
        else:
            result.expired = ledger.expire_stale(session, ctx.label, today)
        proposals = ledger.approved_unsubmitted(session, ctx.label)
        if not proposals:
            result.skipped_reason = "Nothing approved to submit."
            return result

        used_ids = ledger.used_client_order_ids(session)
        sent_today = ledger.orders_submitted_on(session, today, ctx.tz, ctx.label)
        account = load_account_state(ctx, session)
        new_entries: set[str] = set()
        cash_symbols = _cash_symbols(ctx)

        for row in proposals:
            try:
                intent, problem = refresh_intent(ctx, row, account)
                violations = [problem] if problem else []
                if intent is not None:
                    # The nightly check uses the names this strategy holds. spy-trend adds BIL
                    # beside SPY; the configured list alone does not.
                    risk_ctx = RiskContext(
                        now=ctx.now(),
                        universe=set(ctx.strategy.traded_universe(settings.universe_list)),
                        kill_switch_engaged=False,
                        orders_submitted_today=sent_today,
                        used_client_order_ids=used_ids,
                        enforce_time_window=clock is not None and not ctx.is_forex,
                        session_open=clock.session_open if clock else None,
                        session_close=clock.session_close if clock else None,
                        pending_new_positions=len(new_entries - account.held_symbols()),
                        whole_units=ctx.rules.whole_units(),
                        cash_symbols=cash_symbols,
                        position_cap=ctx.strategy.position_cap(),
                        require_stops=ctx.strategy.uses_stops(),
                    )
                    violations = list(check_order(intent, account, ctx.limits, risk_ctx).violations)
                if violations or intent is None:
                    row.status = ProposalStatus.BLOCKED
                    row.violations = [v.model_dump() for v in violations]
                    result.blocked.append(row.id)
                    continue
                if settings.dry_run:
                    row.status = ProposalStatus.DRY_RUN
                    row.limit_price, row.stop_price, row.qty = (
                        intent.limit_price,
                        intent.stop_price,
                        intent.qty,
                    )
                    ledger.audit(session, "dry_run_order", proposal_id=row.id, intent=intent)
                    result.dry_run.append(row.id)
                    continue
                if intent.kind == IntentKind.EXIT and not ctx.is_forex:  # OANDA drops the stop with the trade
                    cancel_symbol_orders(ctx.broker, intent.symbol)
                order = ctx.broker.submit_limit_order(intent)
                row.status = ProposalStatus.SUBMITTED
                row.submitted_at = ctx.now()
                row.broker_order_id = order.id
                row.limit_price, row.stop_price, row.qty = intent.limit_price, intent.stop_price, intent.qty
                order_row = ledger.upsert_order(session, order, ctx.label, proposal_id=row.id)
                if order_row.stop_price is None:
                    order_row.stop_price = intent.stop_price  # the stop that guards this entry
                ledger.audit(session, "order_submitted", proposal_id=row.id, order_id=order.id, intent=intent)
                result.submitted.append(row.id)
                sent_today += 1
                used_ids.add(intent.client_order_id)
                if intent.kind == IntentKind.ENTRY and intent.symbol not in cash_symbols:
                    new_entries.add(intent.symbol)
                    if ctx.is_crypto:
                        crypto_entries.append(intent.client_order_id)
                account = load_account_state(ctx, session)
            except Exception as exc:
                log.exception("Submitting proposal #%s failed", row.id)
                row.status = ProposalStatus.ERROR
                row.error = str(exc)[:500]
                ledger.audit(session, "order_error", proposal_id=row.id, error=str(exc))
                result.errors.append(row.id)

        ledger.set_state(
            session,
            "last_submit_run",
            {"at": ctx.now().isoformat(), "submitted": len(result.submitted), "blocked": len(result.blocked)},
        )
    if result.submitted or result.blocked or result.errors or result.dry_run:
        ctx.notify(
            f"[{settings.mode_label} {ctx.label}] Submitted {len(result.submitted)}, blocked {len(result.blocked)}, "
            f"dry run {len(result.dry_run)}, errors {len(result.errors)}."
        )
    if crypto_entries:  # crypto has no OTO: put the stop-limit in as soon as the entry fills
        from trader.services.protect import protect

        try:
            protect(ctx, wait_for=crypto_entries)
        except Exception:
            log.exception("Placing stops after the crypto entries failed; the protect job will retry")
    return result

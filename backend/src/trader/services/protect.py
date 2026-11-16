"""Crypto protection: a stop-limit sell under every crypto position the app opened.

Alpaca's crypto desk takes no OTO orders, so a crypto entry can't carry its stop the way a
stock entry does. This pass places the stop as soon as the entry fills (submission calls it
straight away) and runs every few minutes after that as a backstop. It also:

- replaces a stop that covers less than the position (an entry that kept filling),
- cancels entries and exits that haven't filled within ENTRY_TTL_MINUTES (crypto never closes),
- sells at once if the price is already below the stop by the time the entry fills,
- warns you when the price is below a stop's limit, where the stop can't fill.

A stop belongs to the entry that opened the position: its stop price is the one the risk
checks approved, and its limit sits STOP_LIMIT_BAND_PCT lower.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from trader import ledger
from trader.assets import fmt_qty
from trader.models import BrokerOrder, IntentKind, OrderIntent, Side
from trader.services.reconcile import sync_open_orders, sync_submitted
from trader.utils import as_utc

if TYPE_CHECKING:
    from trader.services.context import AppContext

log = logging.getLogger(__name__)

ALERTS_KEY = "stop_alerts"


@dataclass
class ProtectResult:
    placed: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    sold: list[str] = field(default_factory=list)
    canceled_orders: int = 0
    alerts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


def _wait_for(ctx: AppContext, client_order_ids: Iterable[str], seconds: float) -> None:
    """Give fresh entries a moment to fill, so the stop can follow right away."""
    waiting = set(client_order_ids)
    deadline = time.monotonic() + seconds
    while waiting and time.monotonic() < deadline:
        for cid in list(waiting):
            order = ctx.broker.get_order_by_client_id(cid)
            if order is None or not order.is_open:
                waiting.discard(cid)
        if waiting:
            time.sleep(0.5)


def _cancel_and_wait(ctx: AppContext, orders: list[BrokerOrder], seconds: float = 5.0) -> None:
    ids = {o.id for o in orders}
    for order in orders:
        ctx.broker.cancel_order(order.id)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and any(o.id in ids for o in ctx.broker.get_open_orders()):
        time.sleep(0.25)


def protect(ctx: AppContext, wait_for: Iterable[str] = (), wait_seconds: float = 10.0) -> ProtectResult:
    result = ProtectResult()
    if not ctx.is_crypto:
        result.skipped_reason = "Stock and forex entries carry their stop with them."
        return result
    wait_for = list(wait_for)
    if wait_for:
        _wait_for(ctx, wait_for, wait_seconds)

    settings = ctx.settings
    limits = ctx.limits
    rules = ctx.rules
    prefix = settings.client_order_prefix + "-"
    now = ctx.now()
    tag = f"[{settings.mode_label} {ctx.label}]"

    with ctx.session() as session:
        recent = ctx.broker.get_orders_since(now - timedelta(days=10))
        sync_submitted(ctx, session, recent)
        sync_open_orders(ctx, session, recent)

        # Entries and exits that sat unfilled too long: the next daily run plans them afresh.
        ttl = timedelta(minutes=settings.entry_ttl_minutes)
        for order in ctx.broker.get_open_orders():
            if order.is_protective_stop or not order.client_order_id.startswith(prefix):
                continue
            submitted = as_utc(order.submitted_at)
            if submitted is not None and now - submitted > ttl:
                ctx.broker.cancel_order(order.id)
                result.canceled_orders += 1
                ledger.audit(session, "stale_order_canceled", client_order_id=order.client_order_id)

        open_orders = ctx.broker.get_open_orders()
        stops: dict[str, list[BrokerOrder]] = {}
        for order in open_orders:
            if order.is_protective_stop:
                stops.setdefault(order.symbol, []).append(order)
        selling = {o.symbol for o in open_orders if o.side == Side.SELL and not o.is_protective_stop}

        for position in ctx.broker.get_positions():
            symbol = position.symbol
            if rules.is_dust(symbol, position.qty) or symbol in selling:
                continue  # nothing to protect, or an exit is already on its way
            entry = ledger.latest_entry(session, ctx.label, symbol)
            if entry is None or entry.stop_price is None:
                continue  # not opened by the app; reconciliation reports it
            qty = rules.floor_qty(symbol, position.qty)
            if qty <= 0:
                continue
            existing = stops.get(symbol, [])
            covered = sum(o.qty - o.filled_qty for o in existing)
            if existing and covered >= qty - rules.lot(symbol).qty_step / 2:
                continue
            try:
                if existing:
                    _cancel_and_wait(ctx, existing)
                    result.replaced.append(symbol)
                stop = float(entry.stop_price)
                try:
                    price = ctx.broker.latest_price(symbol)
                except Exception:
                    price = position.current_price
                if price <= stop:
                    buffer = limits.entry_limit_buffer_pct / 100
                    intent = OrderIntent(
                        symbol=symbol,
                        side=Side.SELL,
                        kind=IntentKind.EXIT,
                        qty=qty,
                        limit_price=rules.price_down(symbol, price * (1 - buffer)),
                        reason=f"{symbol} was already below its {stop:,.2f} stop when protection was placed",
                        client_order_id=ledger.free_client_order_id(session, f"{entry.client_order_id}-exit"),
                    )
                    order = ctx.broker.submit_limit_order(intent)
                    ledger.upsert_order(session, order, ctx.label, proposal_id=entry.id)
                    ledger.audit(session, "stop_breached_sell", symbol=symbol, price=price, stop=stop)
                    result.sold.append(symbol)
                    continue
                limit = rules.price_down(symbol, limits.stop_limit_price(stop))
                cid = ledger.free_client_order_id(session, f"{entry.client_order_id}-stop")
                order = ctx.broker.submit_protective_stop(symbol, qty, stop, limit, cid)
                ledger.upsert_order(session, order, ctx.label, proposal_id=entry.id)
                ledger.audit(session, "stop_placed", symbol=symbol, qty=qty, stop=stop, limit=limit)
                result.placed.append(symbol)
            except Exception as exc:
                log.exception("Could not protect %s", symbol)
                result.errors.append(f"{symbol}: {exc}")

        # A stop-limit below its limit can't fill: say so once per stop.
        warned = dict(ledger.get_state(session, ALERTS_KEY, {}) or {})
        for symbol, orders in stops.items():
            for order in orders:
                if order.limit_price is None or order.id in warned:
                    continue
                try:
                    price = ctx.broker.latest_price(symbol)
                except Exception:
                    continue
                if price < order.limit_price:
                    warned[order.id] = now.isoformat()
                    result.alerts.append(
                        f"{symbol} is at {price:,.2f}, below its stop's {order.limit_price:,.2f} limit, so the stop "
                        f"can't sell {fmt_qty(order.qty)}. Decide whether to sell from your Alpaca account."
                    )
        ledger.set_state(session, ALERTS_KEY, warned)
        ledger.set_state(
            session,
            "last_protect_run",
            {
                "at": now.isoformat(),
                "placed": len(result.placed),
                "canceled": result.canceled_orders,
                "alerts": len(result.alerts),
            },
        )

    lines = [f"Stop placed under {s}." for s in result.placed if s not in result.replaced]
    lines += [f"Stop on {s} replaced to cover the whole position." for s in result.replaced]
    lines += [f"{s} was already below its stop, so it was sold." for s in result.sold]
    if result.canceled_orders:
        lines.append(
            f"Canceled {result.canceled_orders} order(s) that didn't fill within {settings.entry_ttl_minutes} min."
        )
    lines += result.alerts + [f"Couldn't protect {e}" for e in result.errors]
    if lines:
        ctx.notify(f"{tag} " + "\n".join(lines))
    return result

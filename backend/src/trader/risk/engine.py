"""The risk engine: every order passes these checks in code before it can reach the broker.

The checks are independent of the planner that sized the order, so a sizing bug still gets
caught here. Each rule has a test in tests/test_risk.py that tries to break it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trader import money
from trader.assets import fmt_qty
from trader.models import AccountState, IntentKind, OrderIntent, RiskDecision, Side, Violation
from trader.risk.limits import RiskLimits
from trader.utils import NY

EPS = 1e-6


@dataclass
class RiskContext:
    now: datetime
    universe: set[str]
    kill_switch_engaged: bool = False
    orders_submitted_today: int = 0
    used_client_order_ids: set[str] = field(default_factory=set)
    enforce_time_window: bool = False
    session_open: datetime | None = None
    session_close: datetime | None = None
    pending_new_positions: int = 0  # entries already accepted in this batch
    pending_exit_positions: int = 0  # exits planned ahead of these entries
    extra_buying_power: float = 0.0  # cash the planned exits will free
    whole_units: bool = True  # stocks: whole shares; forex: whole currency units; crypto: slices of a coin
    cash_symbols: frozenset[str] = field(default_factory=frozenset)  # idle-cash funds: not a position
    position_cap: float | None = None  # share of equity; overrides max_position_pct when set
    require_stops: bool = True


def check_order(
    intent: OrderIntent, account: AccountState, limits: RiskLimits, ctx: RiskContext
) -> RiskDecision:
    violations: list[Violation] = []

    def add(code: str, message: str) -> None:
        violations.append(Violation(code=code, message=message))

    if intent.source == "ai":
        add("ai_cannot_trade", "AI may rank or veto rules signals, but never creates, sizes or sends orders.")
    if intent.qty <= 0:
        add("invalid_qty", f"Quantity must be more than zero (got {fmt_qty(intent.qty)}).")
    elif ctx.whole_units and not float(intent.qty).is_integer():
        add("whole_shares", f"Orders here are in whole shares or units (got {fmt_qty(intent.qty)}).")
    if intent.limit_price <= 0:
        add("invalid_price", f"Limit price must be positive (got {intent.limit_price}).")
    if ctx.kill_switch_engaged:
        add("kill_switch", "The kill switch is engaged: no new orders until you release it.")
    if intent.client_order_id in ctx.used_client_order_ids:
        add("duplicate_order", f"Client order ID {intent.client_order_id} was already sent.")
    if ctx.orders_submitted_today >= limits.max_orders_per_day:
        add(
            "order_cap",
            f"{ctx.orders_submitted_today} orders already went out today; the cap is {limits.max_orders_per_day}.",
        )
    if ctx.enforce_time_window:
        _check_time_window(limits, ctx, add)

    if intent.kind == IntentKind.ENTRY:
        _check_entry(intent, account, limits, ctx, add)
    else:
        _check_exit(intent, account, add)

    return RiskDecision(approved=not violations, violations=violations)


def _check_exit(intent: OrderIntent, account: AccountState, add) -> None:  # noqa: ANN001
    """An exit may only close what is held: it can never open a position on the other side."""
    held = account.positions.get(intent.symbol)
    held_qty = held.qty if held else 0.0
    if intent.side == Side.SELL:
        long_qty = max(held_qty, 0.0)
        if intent.qty > long_qty + EPS:
            add(
                "no_shorting",
                f"Selling {fmt_qty(intent.qty)} {intent.symbol} exceeds the {fmt_qty(long_qty)} held; "
                "an exit can't open a short.",
            )
    else:
        short_qty = max(-held_qty, 0.0)
        if intent.qty > short_qty + EPS:
            add(
                "exit_too_large",
                f"Buying back {fmt_qty(intent.qty)} {intent.symbol} exceeds the {fmt_qty(short_qty)} sold "
                "short; an exit can't open a new position.",
            )


def _check_time_window(limits: RiskLimits, ctx: RiskContext, add) -> None:  # noqa: ANN001
    if ctx.session_open is None or ctx.session_close is None:
        add("market_closed", "There is no regular trading session today.")
        return
    earliest = ctx.session_open + timedelta(minutes=limits.no_trade_after_open_min)
    latest = ctx.session_close - timedelta(minutes=limits.no_trade_before_close_min)
    if not (earliest <= ctx.now <= latest):
        add(
            "outside_trading_window",
            f"Orders only go out between {earliest.astimezone(NY):%H:%M} and "
            f"{latest.astimezone(NY):%H:%M} New York time.",
        )


def _check_entry(
    intent: OrderIntent, account: AccountState, limits: RiskLimits, ctx: RiskContext, add
) -> None:  # noqa: ANN001
    symbol = intent.symbol
    parking = symbol in ctx.cash_symbols  # BIL counts as cash: no stop, no size cap, no position slot
    if symbol not in ctx.universe and not parking:
        add("not_in_universe", f"{symbol} is not on the approved ticker list.")
    if account.drawdown_pct >= limits.max_drawdown_pct:
        add(
            "max_drawdown",
            f"The account is {account.drawdown_pct:.1f}% below its peak; new entries stop at "
            f"{limits.max_drawdown_pct:g}%.",
        )
    if account.day_pnl_pct <= -limits.daily_loss_limit_pct:
        add(
            "daily_loss_limit",
            f"Down {abs(account.day_pnl_pct):.2f}% today; new entries stop at -{limits.daily_loss_limit_pct:g}%.",
        )

    short = intent.side == Side.SELL
    if short and not limits.allow_shorts:
        add(
            "no_shorting",
            f"Short selling is off: this entry would sell {intent.symbol} without owning it.",
        )

    equity = account.equity
    if equity <= 0:
        add("no_equity", "Account equity is zero or negative.")
        return

    existing = account.positions.get(symbol)
    if existing is not None and existing.qty != 0 and (existing.qty < 0) != short:
        held_side, new_side = ("short", "long") if existing.qty < 0 else ("long", "short")
        add(
            "opposite_position",
            f"{symbol} is held {held_side}; close that position before opening a {new_side} one.",
        )
    same_side = existing is not None and existing.qty != 0 and (existing.qty < 0) == short
    existing_value = existing.exposure if existing is not None and same_side else 0.0
    position_pct = (existing_value + intent.notional) / equity * 100
    cap_pct = limits.max_position_pct if ctx.position_cap is None else ctx.position_cap * 100
    if not parking and position_pct > cap_pct + EPS:
        add(
            "position_size",
            f"{symbol} would be {position_pct:.1f}% of equity; the limit is {cap_pct:g}%.",
        )

    if not parking and intent.stop_price is None and ctx.require_stops:
        add("missing_stop", "Every entry needs a protective stop.")
    elif (
        not parking
        and intent.stop_price is not None
        and not short
        and intent.stop_price >= intent.limit_price
    ):
        add("invalid_stop", f"Stop {intent.stop_price} must sit below the limit price {intent.limit_price}.")
    elif not parking and intent.stop_price is not None and short and intent.stop_price <= intent.limit_price:
        add(
            "invalid_stop",
            f"A short's stop {intent.stop_price} must sit above the limit price {intent.limit_price}.",
        )
    elif not parking and intent.stop_price is not None:
        # A crypto stop-limit can sell as low as its limit, past the stop itself.
        worst = limits.worst_exit_price(intent.stop_price, short)
        loss = money.loss_at(symbol, intent.signed_qty, intent.limit_price, worst)
        risk_pct = loss / equity * 100
        if risk_pct > limits.risk_per_trade_pct + 0.01:
            add(
                "risk_per_trade",
                f"Loss at the stop would be {risk_pct:.2f}% of equity; the limit is {limits.risk_per_trade_pct:g}%.",
            )

    if not parking and not same_side:
        held = {s for s in account.held_symbols() if s not in ctx.cash_symbols}
        open_after = len(held) - ctx.pending_exit_positions + ctx.pending_new_positions + 1
        if open_after > limits.max_open_positions:
            add(
                "max_positions",
                f"This would be position {open_after}; the limit is {limits.max_open_positions}.",
            )

    if intent.notional > account.buying_power + ctx.extra_buying_power + EPS:
        add(
            "buying_power",
            f"Order needs ${intent.notional:,.2f}; ${account.buying_power + ctx.extra_buying_power:,.2f} is available.",
        )

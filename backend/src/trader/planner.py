"""Turn target weights into order intents.

The live pipeline and the backtester both call plan_intents, so a backtest trades exactly the
way the live system would. Every live order is a full entry or a full exit: positions that are
held and still targeted on the same side are left alone (no trims or top-ups). Stocks trade in
whole shares; crypto in slices of a coin, rounded to each pair's steps (see trader.assets).

A target below zero asks for a short (forex, when short selling is on): a sell to open it and
a buy to close it, sized and stopped like a long, with the stop above the entry. A position
whose target turns to the other side is closed first; the new side opens on a later day.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from trader import money
from trader.assets import AssetRules, code_symbol
from trader.models import AccountState, IntentKind, OrderIntent, Side
from trader.risk.limits import RiskLimits
from trader.utils import is_number


def client_order_id(prefix: str, as_of: date, symbol: str, action: str) -> str:
    """tpA-20261112-SPY-buy. action is buy or sell, or for forex shorts short or cover."""
    return f"{prefix}-{as_of:%Y%m%d}-{code_symbol(symbol)}-{action}"


def freed_cash(exits: Iterable[OrderIntent], account: AccountState) -> float:
    """The cash the planned exits hand back at their limit prices."""
    total = 0.0
    for intent in exits:
        position = account.positions.get(intent.symbol)
        entry = position.avg_entry_price if position else intent.limit_price
        total += money.value(intent.symbol, intent.signed_qty, entry, intent.limit_price)
    return total


def entry_prices(
    rules: AssetRules, limits: RiskLimits, symbol: str, price: float, short: bool = False
) -> tuple[float, float | None]:
    """The limit and stop of an entry at this price: a buy pays a little more and stops below,
    a short sells a little lower and stops above. Both round toward less risk."""
    buffer = limits.entry_limit_buffer_pct / 100
    distance = limits.stop_loss_pct / 100
    if short:
        limit = rules.price_down(symbol, price * (1 - buffer))
        return limit, rules.price_down(symbol, limit * (1 + distance)) if distance > 0 else None
    limit = rules.price_up(symbol, price * (1 + buffer))
    return limit, rules.price_up(symbol, limit * (1 - distance)) if distance > 0 else None


def cap_by_risk(
    rules: AssetRules,
    limits: RiskLimits,
    symbol: str,
    qty: float,
    limit: float,
    stop: float | None,
    equity: float,
    short: bool = False,
) -> float:
    """qty, or less if the loss at the stop would pass the per-trade limit. Sizing by
    max_entry_fraction already keeps it inside for most assets; a pair with the dollar first
    (USD/JPY) counts its loss at the stop's price, which can come to a little more."""
    if stop is None or qty <= 0:
        return qty
    worst = limits.worst_exit_price(stop, short)
    per_unit = money.loss_at(symbol, -1.0 if short else 1.0, limit, worst)
    budget = limits.risk_per_trade_pct / 100 * equity
    if per_unit > 0 and qty * per_unit > budget * (1 + 1e-9):
        return rules.floor_qty(symbol, budget / per_unit)
    return qty


def _too_small(rules: AssetRules, symbol: str, limit: float, cash: float, sized: float) -> str:
    if rules.kind == "stocks":
        return (
            f"Not enough cash left: one share costs ${limit:,.2f}."
            if cash < sized
            else f"One share costs ${limit:,.2f}, more than the ${sized:,.0f} this position may use."
        )
    smallest = rules.lot(symbol).min_qty * money.unit_cost(symbol, limit)
    return (
        f"Not enough cash left: the smallest order costs ${smallest:,.2f}."
        if cash < sized
        else f"The smallest order costs ${smallest:,.2f}, more than the ${sized:,.0f} this position may use."
    )


def plan_intents(
    targets: Mapping[str, float],
    prices: Mapping[str, float],
    account: AccountState,
    limits: RiskLimits,
    universe: Sequence[str],
    as_of: date,
    cid_prefix: str,
    exclude: set[str] | frozenset[str] = frozenset(),
    skipped: dict[str, str] | None = None,
    rules: AssetRules | None = None,
) -> list[OrderIntent]:
    """Plan exits and entries for one rebalance.

    Exits: a held universe symbol whose target is zero (or on the other side) is closed in full.
    Positions outside the universe are never touched (they are yours, not the strategy's).
    Entries: an unheld symbol with a target above zero is bought, and with a target below zero
    sold short (only when limits.allow_shorts), at min(|target|, limits.max_entry_fraction())
    of equity, capped by the cash left after exits, by the loss allowed at the stop and by
    max_open_positions. Symbols are visited in universe order, so ties resolve the same way in
    the backtest and live.

    Pass a dict as `skipped` to learn why a symbol with a target got no entry.
    `rules` sets the order sizes and price steps (default: whole shares, or crypto steps when
    the universe holds crypto pairs).
    """
    rules = rules or AssetRules.for_symbols(universe)
    buffer = limits.entry_limit_buffer_pct / 100
    intents: list[OrderIntent] = []

    exiting: set[str] = set()
    for symbol in universe:
        position = account.positions.get(symbol)
        if position is None or rules.is_dust(symbol, abs(position.qty)) or symbol in exclude:
            continue
        weight = targets.get(symbol, 0.0)
        weight = float(weight) if is_number(weight) else 0.0
        long = position.qty > 0
        if (weight > 0 and long) or (weight < 0 and not long):
            continue  # still wanted on the same side
        price = prices.get(symbol, position.current_price)
        if not is_number(price) or price <= 0:
            price = position.current_price
        qty = rules.floor_qty(symbol, abs(position.qty))
        if qty <= 0:
            continue
        if long:
            side, action = Side.SELL, "sell"
            limit = rules.price_down(symbol, price * (1 - buffer))
            reason = f"{symbol} target dropped to 0%"
        else:
            side, action = Side.BUY, "cover"
            limit = rules.price_up(symbol, price * (1 + buffer))
            reason = f"{symbol} short target dropped to 0%: buy it back"
        intents.append(
            OrderIntent(
                symbol=symbol,
                side=side,
                kind=IntentKind.EXIT,
                qty=qty,
                limit_price=limit,
                reason=reason,
                client_order_id=client_order_id(cid_prefix, as_of, symbol, action),
            )
        )
        exiting.add(symbol)

    cash = account.cash + freed_cash(intents, account)
    held = {s for s, p in account.positions.items() if not rules.is_dust(s, abs(p.qty))} - exiting
    open_count = len(held)
    max_fraction = limits.max_entry_fraction()

    for symbol in universe:
        weight = targets.get(symbol, 0.0)
        if not is_number(weight) or weight == 0:
            continue
        short = weight < 0
        if symbol in held or symbol in exiting or symbol in exclude:
            continue
        if short and not limits.allow_shorts:
            if skipped is not None:
                skipped[symbol] = "Short selling is off."
            continue
        if open_count >= limits.max_open_positions:
            if skipped is not None:
                slots = limits.max_open_positions
                skipped[symbol] = (
                    f"All {slots} position slots are full."
                    if slots != 1
                    else "The one position slot is full."
                )
            continue
        price = prices.get(symbol)
        if not is_number(price) or price <= 0:
            if skipped is not None:
                skipped[symbol] = "No price for it today."
            continue
        limit, stop = entry_prices(rules, limits, symbol, price, short)
        sized = min(abs(weight), max_fraction) * account.equity
        dollars = min(sized, cash)
        qty = rules.floor_qty(symbol, dollars / money.unit_cost(symbol, limit))
        qty = cap_by_risk(rules, limits, symbol, qty, limit, stop, account.equity, short)
        if qty <= 0:
            if skipped is not None:
                skipped[symbol] = _too_small(rules, symbol, limit, cash, sized)
            continue
        intents.append(
            OrderIntent(
                symbol=symbol,
                side=Side.SELL if short else Side.BUY,
                kind=IntentKind.ENTRY,
                qty=qty,
                limit_price=limit,
                stop_price=stop,
                reason=(
                    f"{symbol} short target {abs(weight):.1%} of equity"
                    if short
                    else f"{symbol} target {weight:.1%} of equity"
                ),
                client_order_id=client_order_id(cid_prefix, as_of, symbol, "short" if short else "buy"),
            )
        )
        cash -= money.notional(symbol, qty, limit)
        open_count += 1

    return intents

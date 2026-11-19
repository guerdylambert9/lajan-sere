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

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from trader import money
from trader.assets import AssetRules, code_symbol
from trader.models import AccountState, IntentKind, OrderIntent, Side
from trader.risk.limits import RiskLimits
from trader.strategies.base import CashPark
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


def drifts_off_target(current: float, target: float, equity: float, band: float) -> bool:
    """True when `current` is off `target` by more than `band` of the account.

    A drift of exactly `band` is still inside the resize band and does not trade.
    """
    if equity <= 0:
        return False
    return abs(target - current) / equity > band


def _park_holding(
    cash_park: CashPark | None,
    prices: Mapping[str, float],
    account: AccountState,
    rules: AssetRules,
    blocked: bool,
) -> tuple[float, float]:
    """Shares of the cash fund already held, and the price to value them at. (0, 0) when it can't trade."""
    if cash_park is None or blocked:
        return 0.0, 0.0
    position = account.positions.get(cash_park.symbol)
    quoted = prices.get(cash_park.symbol)
    if not is_number(quoted) or quoted <= 0:
        quoted = position.current_price if position is not None else 0.0
    if not is_number(quoted) or quoted <= 0:
        return 0.0, 0.0
    qty = 0.0
    if position is not None and position.qty > 0:
        qty = rules.floor_qty(cash_park.symbol, position.qty)
    return qty, float(quoted)


def _shares_for_shortfall(
    rules: AssetRules, symbol: str, shortfall: float, sell_limit: float, held: float
) -> float:
    """Whole shares to sell so the proceeds cover `shortfall`, and no more than `held`."""
    per_share = money.notional(symbol, 1.0, sell_limit)
    if shortfall <= 1e-9 or per_share <= 0 or held <= 0:
        return 0.0
    need = math.ceil(shortfall / per_share - 1e-9)
    if need >= held:
        return held
    qty = rules.floor_qty(symbol, float(need))
    if money.notional(symbol, qty, sell_limit) + 1e-9 < shortfall:
        qty = min(held, rules.floor_qty(symbol, qty + rules.lot(symbol).qty_step))
    return qty


def _invested_value(
    account: AccountState,
    rules: AssetRules,
    exiting: set[str],
    park_symbol: str,
    entries: Sequence[OrderIntent],
) -> float:
    """What the non-cash positions are worth after today's trend exits and entries."""
    total = 0.0
    for symbol, position in account.positions.items():
        if symbol == park_symbol or symbol in exiting or position.qty <= 0:
            continue
        if rules.is_dust(symbol, position.qty):
            continue
        total += position.market_value
    return total + sum(intent.notional for intent in entries)


def _cash_fund_order(
    cash_park: CashPark | None,
    rules: AssetRules,
    account: AccountState,
    entries: Sequence[OrderIntent],
    exiting: set[str],
    limit_buffer: float,
    park_qty: float,
    park_left: float,
    park_price: float,
    sell_limit: float,
    cash: float,
    as_of: date,
    cid_prefix: str,
    blocked: bool,
) -> OrderIntent | None:
    """The one BIL order for today: a funding sale, a resize, or a buy of cash beyond the buffer.

    `park_left` is what remains after selling shares to fund entries. That sale stands even inside
    the resize band. A resize (buy or a further sale) happens only outside the band, and a buy
    never spends the cash buffer.
    """
    if cash_park is None or blocked or park_price <= 0:
        return None
    symbol = cash_park.symbol
    equity = account.equity
    if equity <= 0:
        return None
    trend_value = _invested_value(account, rules, exiting, symbol, entries)
    target_value = max(0.0, equity - trend_value - cash_park.buffer * equity)
    current_value = park_left * park_price
    final_qty = park_left
    resized = False
    if drifts_off_target(current_value, target_value, equity, cash_park.band):
        target_qty = rules.floor_qty(symbol, target_value / park_price)
        if target_qty > park_left and park_left == park_qty:
            buy_limit = rules.price_up(symbol, park_price * (1 + limit_buffer))
            room = max(0.0, cash - cash_park.buffer * equity)
            extra = (
                rules.floor_qty(symbol, room / money.unit_cost(symbol, buy_limit)) if buy_limit > 0 else 0.0
            )
            target_qty = min(target_qty, park_left + extra)
        if target_qty < park_left or (target_qty > park_qty and park_left == park_qty):
            final_qty = target_qty
            resized = True
    delta = final_qty - park_qty
    if abs(delta) < rules.lot(symbol).min_qty - 1e-12:
        return None
    if delta > 0:
        limit = rules.price_up(symbol, park_price * (1 + limit_buffer))
        reason = f"Cash beyond a {cash_park.buffer:.0%} buffer goes into {symbol}"
        side, action, kind = Side.BUY, "buy", IntentKind.ENTRY
        stop = None
    else:
        limit = sell_limit
        if resized:
            reason = f"{symbol} is {cash_park.band:.0%} of the account off its target"
        else:
            reason = f"Sell {symbol} to fund an entry"
        side, action, kind = Side.SELL, "sell", IntentKind.EXIT
        stop = None
        delta = -delta
    if limit <= 0 or delta <= 0:
        return None
    return OrderIntent(
        symbol=symbol,
        side=side,
        kind=kind,
        qty=delta,
        limit_price=limit,
        stop_price=stop,
        reason=reason,
        client_order_id=client_order_id(cid_prefix, as_of, symbol, action),
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
    cash_park: CashPark | None = None,
    position_cap: float | None = None,
    use_stops: bool = True,
) -> list[OrderIntent]:
    """Plan exits and entries for one rebalance.

    Exits: a held universe symbol whose target is zero (or on the other side) is closed in full.
    Positions outside the universe are never touched (they are yours, not the strategy's).
    Entries: an unheld symbol with a target above zero is bought, and with a target below zero
    sold short (only when limits.allow_shorts), at min(|target|, the position cap) of equity,
    capped by the cash left after exits, by the loss allowed at the stop and by
    max_open_positions. Symbols are visited in universe order, so ties resolve the same way in
    the backtest and live.

    `cash_park` opts one symbol in as idle cash (Candidate 3). After the trend orders, cash
    beyond its buffer is the target for that symbol. It is sold first when an entry needs the
    money, and resized when it drifts off target by more than the band. It takes no stop, ignores
    the position-size cap and does not use an open-position slot. With `cash_park` left unset,
    nothing here changes.

    `position_cap` replaces the account's position-size cap, as a share of equity, when a
    strategy sets one. `use_stops=False` sends the entry without a stop and does not shrink it
    to the per-trade risk limit. Left at their defaults, both keep the account's usual rules.

    Pass a dict as `skipped` to learn why a symbol with a target got no entry.
    `rules` sets the order sizes and price steps (default: whole shares, or crypto steps when
    the universe holds crypto pairs).
    """
    rules = rules or AssetRules.for_symbols(universe)
    buffer = limits.entry_limit_buffer_pct / 100
    intents: list[OrderIntent] = []
    park_symbol = cash_park.symbol if cash_park is not None else None
    # An order already working for the cash fund: don't spend it or resize it again today.
    park_blocked = park_symbol is not None and park_symbol in exclude

    exiting: set[str] = set()
    for symbol in universe:
        if symbol == park_symbol:
            continue
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
    if park_symbol is not None:
        held.discard(park_symbol)  # the cash fund is not one of the open positions
    open_count = len(held)
    max_fraction = limits.max_entry_fraction() if position_cap is None else position_cap
    park_qty, park_price = _park_holding(cash_park, prices, account, rules, park_blocked)
    park_left = park_qty
    sell_limit = (
        rules.price_down(park_symbol, park_price * (1 - buffer)) if park_symbol and park_price > 0 else 0.0
    )
    n_exits = len(intents)

    for symbol in universe:
        if symbol == park_symbol:
            continue
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
        if not use_stops:
            stop = None
        sized = min(abs(weight), max_fraction) * account.equity
        available = cash
        if park_left > 0 and sell_limit > 0 and park_symbol is not None:
            available += money.notional(park_symbol, park_left, sell_limit)
        dollars = min(sized, available)
        qty = rules.floor_qty(symbol, dollars / money.unit_cost(symbol, limit))
        if use_stops:
            qty = cap_by_risk(rules, limits, symbol, qty, limit, stop, account.equity, short)
        if qty <= 0:
            if skipped is not None:
                skipped[symbol] = _too_small(rules, symbol, limit, available, sized)
            continue
        cost = money.notional(symbol, qty, limit)
        sold = 0.0
        if cost > cash + 1e-9 and park_symbol is not None:
            sold = _shares_for_shortfall(rules, park_symbol, cost - cash, sell_limit, park_left)
        funded = cash + (money.notional(park_symbol, sold, sell_limit) if park_symbol is not None else 0.0)
        if cost > funded + 0.01:
            if skipped is not None:
                skipped[symbol] = _too_small(rules, symbol, limit, funded, sized)
            continue
        park_left -= sold
        cash = funded - cost
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
        open_count += 1

    park_order = _cash_fund_order(
        cash_park,
        rules,
        account,
        intents[n_exits:],
        exiting,
        buffer,
        park_qty,
        park_left,
        park_price,
        sell_limit,
        cash,
        as_of,
        cid_prefix,
        park_blocked,
    )
    if park_order is not None and park_order.kind == IntentKind.EXIT:
        intents.insert(n_exits, park_order)  # sold first, so the entry it funds can fill
    elif park_order is not None:
        intents.append(park_order)
    return intents

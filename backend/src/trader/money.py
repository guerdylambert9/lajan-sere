"""What a position or an order is worth in dollars.

Every book counts in US dollars. A share, a coin, or a currency pair quoted in dollars
(EUR/USD) is worth qty x price. A pair with the dollar first (USD/MXN) is quoted in pesos per
dollar: its size is already in dollars, and its profit, which comes in pesos, is turned back
into dollars at the current price.

Positions are fully paid for, short ones too. Opening a position sets aside its dollar size at
the entry price, and the position is then worth that plus its profit or loss. For a long
position in something quoted in dollars that comes to plain qty x price. A short (qty below
zero, forex only) gains when the price falls and loses when it rises.

Pairs without the dollar (EUR/GBP) aren't traded here; they are counted as if their second
currency were the dollar.
"""

from __future__ import annotations

from trader.assets import is_forex_symbol, split_pair


def dollar_first(symbol: str) -> bool:
    """True for a currency pair with the dollar first, like USD/MXN or USD/JPY."""
    pair = split_pair(symbol)
    return pair is not None and pair[0] == "USD" and pair[1] != "USD" and is_forex_symbol(symbol)


def dollars_per_quote_unit(symbol: str, price: float) -> float:
    """What one unit of the price's currency is worth in dollars: 1/price for USD/MXN, else 1."""
    return 1.0 / price if dollar_first(symbol) and price > 0 else 1.0


def unit_cost(symbol: str, price: float) -> float:
    """Dollars one unit costs at this price: $1 for USD/MXN (a unit is one dollar), else price."""
    return 1.0 if dollar_first(symbol) else price


def notional(symbol: str, qty: float, price: float) -> float:
    """Dollar size of qty units at price, long or short (never below zero)."""
    return abs(qty) * unit_cost(symbol, price)


def pnl(symbol: str, qty: float, entry: float, price: float) -> float:
    """Profit in dollars (a loss below zero) on qty units from entry to price; qty < 0 is a short."""
    return qty * (price - entry) * dollars_per_quote_unit(symbol, price)


def value(symbol: str, qty: float, entry: float, price: float) -> float:
    """What the position is worth: the dollars set aside when it opened, plus its profit or loss."""
    if qty >= 0 and not dollar_first(symbol):
        return qty * price  # shares, coins and EUR/USD-style longs, exactly as before
    entry = entry if entry > 0 else price
    return notional(symbol, qty, entry) + pnl(symbol, qty, entry, price)


def loss_at(symbol: str, qty: float, entry: float, price: float) -> float:
    """Dollars lost if the position closes at price (below zero when that would be a gain)."""
    return -pnl(symbol, qty, entry, price)


def return_pct(symbol: str, qty: float, entry: float, exit_price: float) -> float:
    """Profit as a share of the dollars set aside, in percent."""
    size = notional(symbol, qty, entry)
    return pnl(symbol, qty, entry, exit_price) / size * 100 if size > 0 else 0.0

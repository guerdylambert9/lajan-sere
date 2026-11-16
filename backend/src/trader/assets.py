"""What one unit of an asset is, and how order quantities and prices round for it.

Stocks trade here in whole shares, priced in cents. Crypto pairs such as BTC/USD trade in
fractions of a coin; the smallest order and the price step differ by pair, so the live app
reads them from Alpaca and falls back to the defaults below. Currency pairs such as EUR/USD
trade in whole units of the first currency, priced to a tenth of a pip (0.00001).

A symbol with a slash is a pair. When both sides are currencies (EUR/USD) it is forex;
otherwise (BTC/USD, ETH/USDT) it is crypto. That is how backtests tell the three apart.

A pair priced in a currency with many units to the dollar is quoted with fewer decimals: the
yen, the forint and the baht to 0.001, the koruna to 0.0001, the rest to 0.00001.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# Quote currencies of Alpaca's crypto pairs, longest first so USDT wins over USD.
QUOTES = ("USDT", "USDC", "USD", "BTC")
# ISO codes of the currencies retail forex desks quote. A pair of two of them is forex.
FIAT_CODES = "USD EUR GBP JPY CHF CAD AUD NZD SEK NOK DKK SGD HKD MXN ZAR PLN HUF CZK TRY CNH THB"
FIAT = frozenset(FIAT_CODES.split())


def split_pair(symbol: str) -> tuple[str, str] | None:
    parts = symbol.upper().split("/")
    return (parts[0], parts[1]) if len(parts) == 2 and all(parts) else None


def is_forex_symbol(symbol: str) -> bool:
    pair = split_pair(symbol)
    return pair is not None and pair[0] in FIAT and pair[1] in FIAT


def is_crypto_symbol(symbol: str) -> bool:
    return "/" in symbol and not is_forex_symbol(symbol)


# Decimals of a currency pair's price, by the currency it is priced in (OANDA's own figures).
QUOTE_DECIMALS = {"JPY": 3, "HUF": 3, "THB": 3, "CZK": 4}


def price_decimals(symbol: str) -> int:
    """Decimals a price is shown with: 5 for most currency pairs (3 for USD/JPY), else cents."""
    if is_forex_symbol(symbol):
        pair = split_pair(symbol)
        return QUOTE_DECIMALS.get(pair[1], 5) if pair else 5
    return 2


def fmt_price(value: float, symbol: str = "") -> str:
    """1,234.56 for a share or a coin, 1.08423 for a currency pair."""
    return f"{value:,.{price_decimals(symbol)}f}"


def fmt_quote(value: float, symbol: str = "") -> str:
    """A price as people say it: $1,234.56 for a share or a coin, plain 1.08423 for a pair."""
    return fmt_price(value, symbol) if is_forex_symbol(symbol) else f"${value:,.2f}"


def pair_symbol(symbol: str) -> str:
    """BTCUSD -> BTC/USD. Alpaca lists crypto positions without the slash, orders with it."""
    if "/" in symbol:
        return symbol
    for quote in QUOTES:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return f"{symbol[: -len(quote)]}/{quote}"
    return symbol


def code_symbol(symbol: str) -> str:
    """The symbol as it appears inside a client order ID: BTC/USD -> BTCUSD."""
    return symbol.replace("/", "")


def _decimals(step: float) -> int:
    text = f"{step:.12f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def _units(value: float, step: float) -> float:
    inverse = 1 / step
    if abs(inverse - round(inverse)) < 1e-9:  # 0.01 -> x * 100, exactly like rounding to cents
        return round(value * round(inverse), 6)
    return round(value / step, 6)


def floor_to(value: float, step: float) -> float:
    """Round down to a multiple of step (order sizes: never more than the cash allows)."""
    return round(math.floor(value / step + 1e-9) * step, _decimals(step))


def price_up(value: float, step: float) -> float:
    """Round up to the price step (buy limits and stops: never riskier than intended)."""
    return round(math.ceil(_units(value, step)) * step, _decimals(step))


def price_down(value: float, step: float) -> float:
    """Round down to the price step (sell limits: stay marketable)."""
    return round(math.floor(_units(value, step)) * step, _decimals(step))


def fmt_qty(qty: float) -> str:
    """10 shares print as 10, a slice of a coin as 0.0123."""
    return f"{qty:.8f}".rstrip("0").rstrip(".") or "0"


@dataclass(frozen=True)
class Lot:
    qty_step: float  # every order is a whole multiple of this
    min_qty: float  # the smallest order
    price_tick: float  # every price is a whole multiple of this


STOCK_LOT = Lot(qty_step=1.0, min_qty=1.0, price_tick=0.01)
# Used for backtests and the demo, and whenever Alpaca's own figures for a pair can't be read.
CRYPTO_LOT = Lot(qty_step=0.0001, min_qty=0.0001, price_tick=0.01)
# Currency pairs: whole units of the first currency, prices to 0.00001 (fewer decimals for the
# yen and the other currencies in QUOTE_DECIMALS). The live app reads each pair's steps from OANDA.
FOREX_LOT = Lot(qty_step=1.0, min_qty=1.0, price_tick=0.00001)


def forex_lot(symbol: str) -> Lot:
    digits = price_decimals(symbol)
    return Lot(qty_step=1.0, min_qty=1.0, price_tick=round(10.0**-digits, digits))


@dataclass(frozen=True)
class AssetRules:
    crypto: bool = False
    lots: Mapping[str, Lot] = field(default_factory=dict)
    forex: bool = False

    @classmethod
    def for_symbols(cls, symbols: Iterable[str]) -> AssetRules:
        symbols = list(symbols)
        return cls(
            crypto=any(is_crypto_symbol(symbol) for symbol in symbols),
            forex=any(is_forex_symbol(symbol) for symbol in symbols),
        )

    @property
    def kind(self) -> str:
        return "crypto" if self.crypto else "forex" if self.forex else "stocks"

    @property
    def unit(self) -> str:
        return "coin" if self.crypto else "unit" if self.forex else "share"

    def lot(self, symbol: str) -> Lot:
        if symbol in self.lots:
            return self.lots[symbol]
        if self.forex and not self.crypto:
            return forex_lot(symbol)
        return CRYPTO_LOT if self.crypto else STOCK_LOT

    def fmt_price(self, symbol: str, value: float) -> str:
        decimals = max(price_decimals(symbol), _decimals(self.lot(symbol).price_tick))
        return f"{value:,.{decimals}f}"

    def floor_qty(self, symbol: str, qty: float) -> float:
        """The largest valid order size at or below qty, or 0 when even the smallest order is too big."""
        lot = self.lot(symbol)
        rounded = floor_to(max(qty, 0.0), lot.qty_step)
        return rounded if rounded >= lot.min_qty - 1e-12 else 0.0

    def is_dust(self, symbol: str, qty: float) -> bool:
        """Too small to sell: the leftover a crypto fee or rounding can leave behind."""
        return qty < self.lot(symbol).min_qty - 1e-12

    def price_up(self, symbol: str, value: float) -> float:
        return price_up(value, self.lot(symbol).price_tick)

    def price_down(self, symbol: str, value: float) -> float:
        return price_down(value, self.lot(symbol).price_tick)

    def whole_units(self) -> bool:
        return not self.crypto

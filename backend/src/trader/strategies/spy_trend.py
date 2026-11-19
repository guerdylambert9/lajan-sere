"""Hold SPY above its moving average, and BIL otherwise.

One position for the whole account. There is no 10% position cap and no equal-weight basket.
BIL, the cash ETF trend-bil already uses, is the defensive holding: the account owns it as
a position. The moving-average window is the only parameter Gate 1 moves.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from trader.assets import fmt_quote
from trader.strategies.base import Strategy
from trader.strategies.trend_bil import BIL
from trader.utils import is_number

SPY = "SPY"


class SpyTrend(Strategy):
    """Long SPY while its close is above its moving average, and long BIL otherwise.

    The account holds one of those two names, at a target weight of 1, once the window is full.
    A close that equals the average is not above it, so the account holds BIL. Names in the
    configured universe other than SPY stay at 0.
    """

    name = "spy-trend"
    lesson = "trend-following"

    def __init__(self, window: int = 200) -> None:
        if window < 2:
            raise ValueError("window must be at least 2")
        self.window = int(window)

    @property
    def lookback_days(self) -> int:
        return self.window

    def extra_symbols(self) -> tuple[str, ...]:
        return (SPY, BIL)

    def position_cap(self) -> float | None:
        return 1.0

    def uses_stops(self) -> bool:
        return False

    def _ready(self, closes: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        spy = closes[SPY]
        average = spy.rolling(self.window, min_periods=self.window).mean()
        ready = average.notna() & spy.notna()
        above = ready & (spy > average)
        return average, ready, above

    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        columns = list(dict.fromkeys([*closes.columns, SPY, BIL]))
        weights = pd.DataFrame(0.0, index=closes.index, columns=columns)
        if SPY not in closes.columns or closes.empty:
            return weights
        _average, ready, above = self._ready(closes)
        weights.loc[above, SPY] = 1.0
        weights.loc[ready & ~above, BIL] = 1.0
        return weights

    def rule_text(self) -> str:
        return (
            f"Hold {SPY} while it closes above its {self.window}-day average, and hold {BIL} otherwise. "
            "One position, the whole account."
        )

    def explain(self, closes: pd.DataFrame) -> dict[str, str]:
        if closes.empty:
            return {}
        symbols = list(dict.fromkeys([*closes.columns, SPY, BIL]))
        if SPY not in closes.columns:
            return {symbol: f"This rule needs {SPY} prices." for symbol in symbols}
        average, _ready, above = self._ready(closes)
        price, mean = closes[SPY].iloc[-1], average.iloc[-1]
        ready = is_number(price) and is_number(mean) and pd.notna(price) and pd.notna(mean) and mean > 0
        if not ready:
            waiting = f"Not enough history yet: the rule needs {self.window} days of {SPY} closes."
            return {symbol: waiting for symbol in symbols}
        gap = float(price) / float(mean) - 1
        side = "above" if bool(above.iloc[-1]) else "below"
        comparison = (
            f"{SPY} closed at {fmt_quote(price, SPY)}, {abs(gap):.1%} {side} its {self.window}-day average "
            f"of {fmt_quote(mean, SPY)}."
        )
        held = SPY if bool(above.iloc[-1]) else BIL
        reasons: dict[str, str] = {}
        for symbol in symbols:
            if symbol == held:
                reasons[symbol] = f"{comparison} The account holds {held}."
            elif symbol in (SPY, BIL):
                reasons[symbol] = f"{comparison} The account holds {held}, so this is flat."
            else:
                reasons[symbol] = f"This rule holds only {SPY} or {BIL}."
        return reasons

    def params(self) -> dict[str, Any]:
        return {"window": self.window}

    def variants(self) -> list[Strategy]:
        return [SpyTrend(round(self.window * 0.8)), SpyTrend(round(self.window * 1.2))]

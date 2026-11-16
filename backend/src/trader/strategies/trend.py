"""Trend following: hold each asset while its close is above its N-day moving average."""

from __future__ import annotations

from typing import Any

import pandas as pd

from trader.assets import fmt_quote
from trader.strategies.base import Strategy
from trader.utils import is_number


class TrendFollowing(Strategy):
    """Equal weight (1/N of the universe) in every asset that closes above its moving average.

    A classic time-series trend rule: in cash for assets in a downtrend. With a 10-asset
    universe each holding targets 10% of equity. With shorts=True (forex only) an asset that
    closes below its average is sold short instead, at the same 1/N weight.
    """

    name = "trend"
    lesson = "trend-following"

    def __init__(self, window: int = 200, shorts: bool = False) -> None:
        if window < 2:
            raise ValueError("window must be at least 2")
        self.window = int(window)
        self.shorts = bool(shorts)

    @property
    def lookback_days(self) -> int:
        return self.window

    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        average = closes.rolling(self.window, min_periods=self.window).mean()
        in_trend = (closes > average) & average.notna()
        count = max(len(closes.columns), 1)
        weights = in_trend.astype(float) / count
        if self.shorts:
            below = (closes < average) & average.notna()
            weights = weights - below.astype(float) / count
        return weights

    def rule_text(self) -> str:
        if self.shorts:
            return (
                f"Own each pair while it closes above its {self.window}-day average and sell it short "
                "while it closes below, in equal shares."
            )
        return f"Own each symbol while it closes above its {self.window}-day average, in equal shares."

    def explain(self, closes: pd.DataFrame) -> dict[str, str]:
        if closes.empty:
            return {}
        average = closes.rolling(self.window, min_periods=self.window).mean().iloc[-1]
        last = closes.iloc[-1]
        reasons: dict[str, str] = {}
        for symbol in closes.columns:
            price, mean = last[symbol], average[symbol]
            if not (is_number(price) and is_number(mean)) or pd.isna(price) or pd.isna(mean) or mean <= 0:
                reasons[symbol] = f"Not enough history yet: the rule needs {self.window} days of closes."
                continue
            gap = float(price / mean - 1)
            side = "above" if gap > 0 else "below"
            reasons[symbol] = (
                f"Closed at {fmt_quote(price, symbol)}, {abs(gap):.1%} {side} its {self.window}-day average "
                f"of {fmt_quote(mean, symbol)}."
            )
        return reasons

    def params(self) -> dict[str, Any]:
        return {"window": self.window, "shorts": True} if self.shorts else {"window": self.window}

    def variants(self) -> list[Strategy]:
        return [
            TrendFollowing(round(self.window * 0.8), self.shorts),
            TrendFollowing(round(self.window * 1.2), self.shorts),
        ]

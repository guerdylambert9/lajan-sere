"""Relative momentum: each month, hold the top N assets by their 12-1 month return."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from trader.strategies.base import Strategy
from trader.utils import signed_pct


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class Momentum(Strategy):
    """Rank assets by return from `lookback` to `skip` days ago; hold the top N with a positive return.

    Rebalances on the first trading day of each month, a date known without looking ahead.
    Each holding targets 1/top_n of equity, then the risk limits cap it.
    """

    name = "momentum"
    lesson = "momentum"

    def __init__(self, lookback: int = 252, skip: int = 21, top_n: int = 3) -> None:
        if not 0 <= skip < lookback:
            raise ValueError("need 0 <= skip < lookback")
        if top_n < 1:
            raise ValueError("top_n must be at least 1")
        self.lookback = int(lookback)
        self.skip = int(skip)
        self.top_n = int(top_n)

    @property
    def lookback_days(self) -> int:
        return self.lookback + 1

    def history_days(self) -> int:
        # Extra room so at least one month start falls inside the fetched window.
        return super().history_days() + 45

    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        momentum = closes.shift(self.skip) / closes.shift(self.lookback) - 1
        rank = momentum.rank(axis=1, ascending=False, method="first")
        chosen = (rank <= self.top_n) & (momentum > 0)
        weights = chosen.astype(float) / self.top_n

        months = np.asarray(closes.index.year * 12 + closes.index.month)
        month_start = np.r_[True, months[1:] != months[:-1]] if len(months) else np.array([], dtype=bool)
        weights.loc[~month_start, :] = np.nan
        return weights.ffill().fillna(0.0)

    def _measure(self) -> str:
        if (self.lookback, self.skip) == (252, 21):
            return "return over the 12 months before the latest month"
        return f"return from {self.lookback} to {self.skip} trading days ago"

    def rule_text(self) -> str:
        return (
            f"On the first trading day of each month, own the {self.top_n} with the best {self._measure()}, "
            "if that return is positive."
        )

    def explain(self, closes: pd.DataFrame) -> dict[str, str]:
        if closes.empty:
            return {}
        momentum = closes.shift(self.skip) / closes.shift(self.lookback) - 1
        months = np.asarray(closes.index.year * 12 + closes.index.month)
        starts = np.flatnonzero(np.r_[True, months[1:] != months[:-1]])
        rebalance = closes.index[starts[-1]]
        at_rebalance = momentum.loc[rebalance].dropna().sort_values(ascending=False)
        today = momentum.iloc[-1].dropna().sort_values(ascending=False)
        then_rank = {symbol: i + 1 for i, symbol in enumerate(at_rebalance.index)}
        now_rank = {symbol: i + 1 for i, symbol in enumerate(today.index)}
        last = closes.index[-1]
        next_month = (last.month % 12) + 1
        next_name = pd.Timestamp(year=last.year + (last.month == 12), month=next_month, day=1).strftime("%B")
        reasons: dict[str, str] = {}
        for symbol in closes.columns:
            if symbol not in then_rank:
                reasons[symbol] = "Not enough history yet: the rule needs a year of closes."
                continue
            value = float(at_rebalance[symbol])
            text = (
                f"Its {self._measure()} was {signed_pct(value)} at the {rebalance:%b} {rebalance.day} "
                f"rebalance, {ordinal(then_rank[symbol])} of {len(at_rebalance)}"
            )
            if symbol in now_rank and now_rank[symbol] != then_rank[symbol]:
                text += f" ({ordinal(now_rank[symbol])} today)"
            reasons[symbol] = f"{text}. Next rebalance: the first trading day of {next_name}."
        return reasons

    def params(self) -> dict[str, Any]:
        return {"lookback": self.lookback, "skip": self.skip, "top_n": self.top_n}

    def variants(self) -> list[Strategy]:
        return [
            Momentum(round(self.lookback * 0.8), self.skip, self.top_n),
            Momentum(round(self.lookback * 1.2), self.skip, self.top_n),
        ]

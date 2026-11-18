"""Trend following with idle cash in BIL.

Candidate 3 keeps the trend signal. Cash beyond a 2% buffer goes into BIL, which is resized
when it drifts 5% of the account off target and is exempt from the stop, the 10% cap and the
position count. The 2% buffer and the 5% band stay fixed; Gate 1 moves only the trend window.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from trader.strategies.base import CashPark, Strategy
from trader.strategies.trend import TrendFollowing

BIL = "BIL"
CASH_BUFFER = 0.02
RESIZE_BAND = 0.05


class TrendWithBills(TrendFollowing):
    """The 200-day trend rule, with spare cash parked in the 1–3 month T-bill ETF.

    The signal is the existing trend rule on the stock ETF universe: each ETF above its moving
    average is a 1/N target, and BIL is not one of those signals. BIL is cash. Cash beyond a 2%
    buffer goes into BIL, which is resized when it drifts 5% of the account off target and is
    exempt from the stop, the 10% cap and the position count.
    """

    name = "trend-bil"
    lesson = "trend-following"

    def __init__(self, window: int = 200, buffer: float = CASH_BUFFER, band: float = RESIZE_BAND) -> None:
        super().__init__(window=window, shorts=False)
        if not 0 <= buffer < 1:
            raise ValueError("buffer must be a share of the account, from 0 up to but not including 1")
        if not 0 <= band < 1:
            raise ValueError("band must be a share of the account, from 0 up to but not including 1")
        self.buffer = float(buffer)
        self.band = float(band)

    def cash_park(self) -> CashPark:
        return CashPark(symbol=BIL, buffer=self.buffer, band=self.band)

    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        # BIL is the cash fund, not part of the trend signal. Drop it if a price frame includes it.
        universe = closes.drop(columns=[BIL], errors="ignore")
        return super().target_weights(universe)

    def rule_text(self) -> str:
        return (
            f"Own each ETF while it closes above its {self.window}-day average, in equal shares. "
            f"Cash beyond a {self.buffer:.0%} buffer goes into {BIL}, resized when it drifts "
            f"{self.band:.0%} of the account off target."
        )

    def params(self) -> dict[str, Any]:
        return {"window": self.window, "buffer": self.buffer, "band": self.band}

    def variants(self) -> list[Strategy]:
        # The buffer and the band were fixed before the test and do not move with the window.
        return [
            TrendWithBills(round(self.window * 0.8), self.buffer, self.band),
            TrendWithBills(round(self.window * 1.2), self.buffer, self.band),
        ]

"""Deterministic made-up prices for the demo and the tests. Not market data."""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

# Roughly how many units of each currency a dollar buys, so USD/XXX starts at a familiar level.
DOLLAR_LEVELS = {
    "JPY": 150.0,
    "CHF": 0.88,
    "CAD": 1.37,
    "MXN": 18.5,
    "ZAR": 18.0,
    "PLN": 3.9,
    "HUF": 360.0,
    "CZK": 22.5,
    "SGD": 1.33,
    "SEK": 10.5,
    "NOK": 10.8,
    "DKK": 6.9,
    "HKD": 7.8,
    "CNH": 7.2,
    "THB": 35.0,
    "TRY": 40.0,
}
EMERGING = frozenset({"MXN", "ZAR", "PLN", "HUF", "CZK", "TRY", "THB", "CNH"})


class SyntheticBarSource:
    """Random-walk prices with trending regimes, the same on every run for the same seed.

    The full series is generated once from a fixed start date, so the price on any given day
    never depends on which window you ask for. With crypto=True the series has a bar for every
    calendar day, swings about three times as hard and starts at coin-like prices. With
    forex=True it trades on weekdays, swings about half as hard as stocks, has no built-in
    upward drift (a currency pair has no equity premium) and starts near 1, like EUR/USD; a
    pair with the dollar first starts near that currency's usual level (USD/JPY in the
    hundreds), and an emerging-market currency swings about twice as hard as a major.
    """

    EPOCH = pd.Timestamp("2010-01-04")
    HORIZON = pd.Timestamp("2035-12-31")

    def __init__(self, seed: int | None = None, crypto: bool = False, forex: bool = False) -> None:
        self.seed = seed if seed is not None else (312 if crypto else 1102 if forex else 7)
        self.crypto = crypto
        self.forex = forex and not crypto
        self._scale = 3.0 if crypto else 0.45 if self.forex else 1.0
        self._bias = 0.0 if self.forex else 0.1
        self._dates = (
            pd.date_range(self.EPOCH, self.HORIZON, freq="D")
            if crypto
            else pd.bdate_range(self.EPOCH, self.HORIZON)
        )
        self._market = self._market_returns()
        self._cache: dict[str, pd.Series] = {}

    def _regime_drift(self, rng: np.random.Generator, size: int, scale: float) -> np.ndarray:
        drift = np.empty(size)
        position = 0
        while position < size:
            length = int(rng.integers(120, 320))
            drift[position : position + length] = rng.uniform(-scale, scale) + scale * self._bias
            position += length
        return drift

    def _market_returns(self) -> np.ndarray:
        rng = np.random.default_rng(self.seed)
        size = len(self._dates)
        return self._regime_drift(rng, size, 0.0009 * self._scale) + rng.normal(
            0.0, 0.009 * self._scale, size
        )

    def _series(self, symbol: str) -> pd.Series:
        if symbol not in self._cache:
            rng = np.random.default_rng([self.seed, zlib.crc32(symbol.encode())])
            size = len(self._dates)
            beta = rng.uniform(0.2, 1.3)
            drift = self._regime_drift(rng, size, 0.0006 * self._scale)  # draw order keeps old series
            own = drift + rng.normal(0.0, rng.uniform(0.004, 0.012) * self._scale, size)
            returns = beta * self._market + own
            if self.crypto:
                start_price = rng.uniform(500, 5_000)
            elif self.forex:
                start_price = rng.uniform(0.6, 1.6)
                base, _, quote = symbol.upper().partition("/")
                if base == "USD" and quote in DOLLAR_LEVELS:  # 0.8 to 1.25 times the usual level
                    start_price = DOLLAR_LEVELS[quote] * (0.8 + (start_price - 0.6) * 0.45)
                if quote in EMERGING or base in EMERGING:
                    returns = returns * 2
            else:
                start_price = rng.uniform(40, 400)
            self._cache[symbol] = pd.Series(
                start_price * np.exp(np.cumsum(returns)), index=self._dates, name=symbol
            )
        return self._cache[symbol]

    def get_closes(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frame = pd.DataFrame({symbol: self._series(symbol) for symbol in symbols})
        return frame.loc[pd.Timestamp(start) : pd.Timestamp(end)]

"""Daily crypto bars from Alpaca's market data API (no keys needed, though they're used if set).

Alpaca's crypto day runs from midnight to midnight US Central time, every day of the week.
Only finished days are returned: the bar for the day still in progress is dropped, so a signal
never rests on a close that hasn't happened yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from trader.data.base import clean_closes
from trader.utils import CT


def finished_bars(closes: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Drop daily bars whose day hasn't ended yet (bar timestamps mark the start of the day)."""
    if closes.empty:
        return closes
    index = pd.DatetimeIndex(closes.index)
    starts = index.tz_localize(UTC) if index.tz is None else index.tz_convert(UTC)
    done = starts + pd.Timedelta(days=1) <= pd.Timestamp(now).tz_convert(UTC)
    return closes[done]


class AlpacaCryptoBarSource:
    def __init__(self, api_key: str = "", secret_key: str = "") -> None:
        self.client = CryptoHistoricalDataClient(api_key or None, secret_key or None)

    def get_closes(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        now = datetime.now(UTC)
        request = CryptoBarsRequest(
            symbol_or_symbols=list(symbols),
            timeframe=TimeFrame.Day,
            start=datetime.combine(start, time(0, 0), tzinfo=CT),
            end=min(
                datetime.combine(end + timedelta(days=1), time(0, 0), tzinfo=CT) - timedelta(seconds=1), now
            ),
        )
        bars = self.client.get_crypto_bars(request).df
        if bars.empty:
            return pd.DataFrame(columns=list(symbols), dtype=float)
        closes = finished_bars(bars["close"].unstack(level=0), now)
        return clean_closes(closes, symbols)

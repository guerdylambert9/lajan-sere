"""Daily forex closes from OANDA's candles endpoint (needs an OANDA access token, practice is fine).

OANDA's daily candles end at 5 pm New York, the forex day's close, and each one is labeled here
by the date it closes on: the candle that opens Sunday evening is Monday's. Only finished
candles are kept, so a signal never rests on a close that hasn't happened yet. The closes are
mid prices, halfway between what buyers bid and sellers ask.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from trader import forex as fx
from trader.broker.oanda_broker import OandaClient
from trader.data.base import clean_closes
from trader.utils import NY

PAGE = 5000  # OANDA's largest page of candles


def _iso(moment: datetime) -> str:
    return f"{moment.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"


class OandaBarSource:
    def __init__(self, token: str = "", live: bool = False, client: OandaClient | None = None) -> None:
        self.client = client or OandaClient(token, live=live)

    def _closes(self, symbol: str, start: date, end: date) -> pd.Series:
        # The candle that closes on `start` opened at 5 pm the evening before.
        cursor = datetime.combine(start - timedelta(days=1), fx.DAY_ENDS, tzinfo=NY)
        last_close = datetime.combine(end, fx.DAY_ENDS, tzinfo=NY)
        closes: dict[pd.Timestamp, float] = {}
        while cursor < last_close:
            candles = self.client.get(
                f"/v3/instruments/{fx.instrument(symbol)}/candles",
                price="M",
                granularity="D",
                dailyAlignment=17,
                alignmentTimezone="America/New_York",
                count=PAGE,
                **{"from": _iso(cursor)},
            ).get("candles", [])
            for candle in candles:
                opened = pd.Timestamp(candle["time"]).tz_convert(NY)
                closes_on = opened.date() + timedelta(days=1)
                if candle.get("complete") and start <= closes_on <= end:
                    closes[pd.Timestamp(closes_on)] = float(candle["mid"]["c"])
            if len(candles) < PAGE:
                break
            cursor = pd.Timestamp(candles[-1]["time"]).to_pydatetime() + timedelta(seconds=1)
        return pd.Series(closes, dtype=float, name=symbol).sort_index()

    def get_closes(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frame = pd.DataFrame({symbol: self._closes(symbol, start, end) for symbol in symbols})
        if frame.empty:
            return pd.DataFrame(columns=list(symbols), dtype=float)
        return clean_closes(frame, symbols)

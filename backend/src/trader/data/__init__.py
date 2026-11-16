from __future__ import annotations

from typing import TYPE_CHECKING

from trader.data.base import BarSource, FrameBarSource, clean_closes
from trader.data.csv_source import CsvBarSource, save_closes
from trader.data.synthetic import SyntheticBarSource

if TYPE_CHECKING:
    from trader.config import Settings


def get_bar_source(settings: Settings) -> BarSource:
    from trader.config import DataSourceKind

    if settings.data_source == DataSourceKind.ALPACA:
        if settings.is_crypto:
            from trader.data.alpaca_crypto_source import AlpacaCryptoBarSource

            return AlpacaCryptoBarSource(settings.alpaca_api_key, settings.alpaca_secret_key)
        from trader.data.alpaca_source import AlpacaBarSource

        return AlpacaBarSource(settings.alpaca_api_key, settings.alpaca_secret_key, settings.alpaca_data_feed)
    if settings.data_source == DataSourceKind.OANDA:
        from trader.data.oanda_source import OandaBarSource

        return OandaBarSource(settings.oanda_api_token, live=settings.is_live)
    if settings.data_source == DataSourceKind.CSV:
        return CsvBarSource(settings.csv_path)
    return SyntheticBarSource(crypto=settings.is_crypto, forex=settings.is_forex)


__all__ = [
    "BarSource",
    "CsvBarSource",
    "FrameBarSource",
    "SyntheticBarSource",
    "clean_closes",
    "get_bar_source",
    "save_closes",
]

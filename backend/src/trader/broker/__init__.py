from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from trader.broker.base import Broker
from trader.broker.fake import FakeBroker

if TYPE_CHECKING:
    from trader.config import Settings

# Alpaca's lowest-volume crypto tier charges 0.25% to orders that take liquidity; the demo uses it.
CRYPTO_TAKER_FEE_BPS = 25.0


def get_broker(settings: Settings, price_source: Callable[[str], float | None] | None = None) -> Broker:
    from trader.config import BrokerKind

    if settings.broker == BrokerKind.ALPACA:
        from trader.broker.alpaca_broker import AlpacaBroker

        return AlpacaBroker(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=not settings.is_live,
            latest_feed=settings.alpaca_latest_feed,
            crypto=settings.is_crypto,
        )
    if settings.broker == BrokerKind.OANDA:
        from trader.broker.oanda_broker import OandaBroker

        return OandaBroker(settings.oanda_api_token, settings.oanda_account_id, live=settings.is_live)
    return FakeBroker(
        state_path=settings.fake_broker_state or None,
        always_open=True,
        price_source=price_source,
        crypto=settings.is_crypto,
        fee_bps=CRYPTO_TAKER_FEE_BPS if settings.is_crypto else 0.0,
        forex=settings.is_forex,
        financing_bps=settings.financing_bps_per_year if settings.is_forex else 0.0,
    )


__all__ = ["Broker", "FakeBroker", "get_broker"]

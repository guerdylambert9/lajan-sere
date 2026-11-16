"""Alpaca Trading API adapter (paper or live, set by TRADING_MODE).

Stock entries go out as OTO orders: a limit buy that, once filled, leaves a stop-loss sell
resting at Alpaca. They use GTC so the stop outlives the first day; the after-close
reconciliation cancels any entry that did not fill, so entries still behave like day orders.

A crypto book (crypto=True) trades pairs such as BTC/USD around the clock. Alpaca's crypto desk
takes market, limit and stop-limit orders with GTC or IOC, and no OTO, so entries are plain GTC
limits and the app adds a GTC stop-limit sell once one fills. Each book sees only its own asset
class, so a stock book never counts or cancels crypto orders, and the other way round.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from alpaca.common.exceptions import APIError
from alpaca.data.enums import DataFeed
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import CryptoLatestTradeRequest, StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetCalendarRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    StopLimitOrderRequest,
    StopLossRequest,
)

from trader.assets import CRYPTO_LOT, Lot, pair_symbol
from trader.models import AccountInfo, BrokerOrder, MarketClock, OrderIntent, Position, Side
from trader.utils import NY


def _num(value: Any, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _as_ny(moment: datetime) -> datetime:
    return moment.replace(tzinfo=NY) if moment.tzinfo is None else moment.astimezone(NY)


class AlpacaBroker:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        paper: bool = True,
        latest_feed: str = "iex",
        crypto: bool = False,
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY to use BROKER=alpaca.")
        self.paper = paper
        self.crypto = crypto
        self.asset_class = AssetClass.CRYPTO if crypto else AssetClass.US_EQUITY
        self.trading = TradingClient(api_key, secret_key, paper=paper)
        self.data = StockHistoricalDataClient(api_key, secret_key)
        self.crypto_data = CryptoHistoricalDataClient(api_key, secret_key) if crypto else None
        self.latest_feed = DataFeed(latest_feed)

    def _mine(self, item: Any) -> bool:
        """True when a position or order belongs to this book's asset class."""
        value = _text(getattr(item, "asset_class", None))
        if not value:
            return not self.crypto
        return value == self.asset_class.value

    def _symbol(self, symbol: str | None) -> str:
        # Alpaca lists crypto positions as BTCUSD; orders and data use BTC/USD.
        return pair_symbol(symbol or "") if self.crypto else (symbol or "")

    def lots(self, symbols: Iterable[str]) -> dict[str, Lot]:
        """Each crypto pair's smallest order, quantity step and price step, as Alpaca lists them."""
        if not self.crypto:
            return {}
        lots: dict[str, Lot] = {}
        for symbol in symbols:
            asset = self.trading.get_asset(symbol)
            lots[symbol] = Lot(
                qty_step=_num(getattr(asset, "min_trade_increment", None), None) or CRYPTO_LOT.qty_step,
                min_qty=_num(getattr(asset, "min_order_size", None), None) or CRYPTO_LOT.min_qty,
                price_tick=_num(getattr(asset, "price_increment", None), None) or CRYPTO_LOT.price_tick,
            )
        return lots

    def get_account(self) -> AccountInfo:
        account = self.trading.get_account()
        equity = _num(account.equity) or 0.0
        return AccountInfo(
            equity=equity,
            cash=_num(account.cash) or 0.0,
            buying_power=_num(account.buying_power) or 0.0,
            last_equity=_num(account.last_equity, equity) or equity,
        )

    def get_positions(self) -> list[Position]:
        return [
            Position(
                symbol=self._symbol(p.symbol),
                qty=_num(p.qty) or 0.0,
                avg_entry_price=_num(p.avg_entry_price) or 0.0,
                current_price=_num(p.current_price) or 0.0,
            )
            for p in self.trading.get_all_positions()
            if self._mine(p)
        ]

    def get_open_orders(self, symbol: str | None = None) -> list[BrokerOrder]:
        # Crypto symbols are filtered here rather than by Alpaca, which spells them two ways.
        wanted = [symbol] if symbol and not self.crypto else None
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=wanted, nested=False, limit=500)
        orders = [self._order(o) for o in self.trading.get_orders(filter=request) if self._mine(o)]
        return [o for o in orders if symbol is None or o.symbol == symbol]

    def get_orders_since(self, since: datetime) -> list[BrokerOrder]:
        request = GetOrdersRequest(status=QueryOrderStatus.ALL, after=since, nested=False, limit=500)
        return [self._order(o) for o in self.trading.get_orders(filter=request) if self._mine(o)]

    def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        try:
            return self._order(self.trading.get_order_by_client_id(client_order_id))
        except APIError as exc:
            if exc.status_code == 404 or "not found" in str(exc).lower():
                return None
            raise

    def submit_limit_order(self, intent: OrderIntent) -> BrokerOrder:
        side = OrderSide.BUY if intent.side == Side.BUY else OrderSide.SELL
        if self.crypto:  # no OTO and no DAY orders for crypto; the stop follows the fill
            request = LimitOrderRequest(
                symbol=intent.symbol,
                qty=intent.qty,
                side=side,
                time_in_force=TimeInForce.GTC,
                limit_price=intent.limit_price,
                client_order_id=intent.client_order_id,
            )
            return self._order(self.trading.submit_order(order_data=request))
        qty = int(intent.qty) if float(intent.qty).is_integer() else intent.qty
        if intent.stop_price is not None:
            request = LimitOrderRequest(
                symbol=intent.symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.GTC,
                limit_price=intent.limit_price,
                client_order_id=intent.client_order_id,
                order_class=OrderClass.OTO,
                stop_loss=StopLossRequest(stop_price=intent.stop_price),
            )
        else:
            request = LimitOrderRequest(
                symbol=intent.symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.DAY,
                limit_price=intent.limit_price,
                client_order_id=intent.client_order_id,
            )
        return self._order(self.trading.submit_order(order_data=request))

    def submit_protective_stop(
        self, symbol: str, qty: float, stop_price: float, limit_price: float, client_order_id: str
    ) -> BrokerOrder:
        request = StopLimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            stop_price=stop_price,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )
        return self._order(self.trading.submit_order(order_data=request))

    def cancel_order(self, order_id: str) -> None:
        self.trading.cancel_order_by_id(order_id)

    def latest_price(self, symbol: str) -> float:
        if self.crypto_data is not None:
            latest = self.crypto_data.get_crypto_latest_trade(
                CryptoLatestTradeRequest(symbol_or_symbols=symbol)
            )
            return float(latest[symbol].price)
        request = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=self.latest_feed)
        trades = self.data.get_stock_latest_trade(request)
        return float(trades[symbol].price)

    def clock(self) -> MarketClock:
        if self.crypto:  # crypto trades around the clock, every day
            now = datetime.now(UTC)
            return MarketClock(timestamp=now, is_open=True, next_open=now, next_close=now + timedelta(days=1))
        clock = self.trading.get_clock()
        today: date = clock.timestamp.astimezone(NY).date()
        session_open = session_close = None
        days = self.trading.get_calendar(GetCalendarRequest(start=today, end=today))
        if days and days[0].date == today:
            session_open = _as_ny(days[0].open)
            session_close = _as_ny(days[0].close)
        return MarketClock(
            timestamp=clock.timestamp,
            is_open=clock.is_open,
            next_open=clock.next_open,
            next_close=clock.next_close,
            session_open=session_open,
            session_close=session_close,
        )

    def _order(self, order: Any) -> BrokerOrder:
        return BrokerOrder(
            id=str(order.id),
            client_order_id=order.client_order_id,
            symbol=self._symbol(order.symbol),
            side=Side.BUY if _text(order.side) == "buy" else Side.SELL,
            qty=_num(order.qty) or 0.0,
            status=_text(order.status),
            filled_qty=_num(order.filled_qty) or 0.0,
            filled_avg_price=_num(order.filled_avg_price, None),
            limit_price=_num(order.limit_price, None),
            stop_price=_num(order.stop_price, None),
            order_type=_text(order.order_type or order.type) or "limit",
            order_class=_text(order.order_class) or "simple",
            submitted_at=order.submitted_at,
        )

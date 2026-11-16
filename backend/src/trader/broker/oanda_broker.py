"""OANDA v20 REST adapter for the forex book (practice or live, set by TRADING_MODE).

Alpaca doesn't trade currencies, so the forex book uses OANDA through its REST API: plain HTTPS
calls with a personal access token, no extra package.

- Entries are GTC limit orders with a stop-loss on fill: a buy, or with short selling on a sell
  (a negative number of units). When one fills, OANDA hangs a stop-loss order off the new trade,
  below a long and above a short, the way a stock entry carries its stop in an OTO order.
- Exits are REDUCE_ONLY limit orders on the other side: they can only shrink a position, never
  open one, and closing the trade cancels its stop-loss, so the stop stays in place until the
  exit fills.
- Entries are OPEN_ONLY. US accounts may not hedge (hold a long and a short in one pair) and
  close trades oldest first; this book holds one trade per pair, so neither rule bites.
- Positions are sized as if fully paid for, shorts too. OANDA would lend up to 50 times the
  deposit on the major pairs; here buying power is equity minus what is already held or on
  order, so the book never borrows. A pair with the dollar first (USD/MXN) is sized in dollars,
  which is what its units are.

OANDA reports prices as strings and stop-loss orders without a pair or a size (they belong to
a trade), so this adapter joins them with the open trades before handing them to the app.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import httpx

from trader import forex as fx
from trader import money
from trader.assets import Lot, fmt_qty, price_decimals
from trader.models import AccountInfo, BrokerOrder, IntentKind, MarketClock, OrderIntent, Position, Side
from trader.utils import as_utc

log = logging.getLogger(__name__)

PRACTICE_URL = "https://api-fxpractice.oanda.com"
LIVE_URL = "https://api-fxtrade.oanda.com"
TAG = "lajan-sere"
STATUS = {"PENDING": "new", "FILLED": "filled", "TRIGGERED": "filled", "CANCELLED": "canceled"}
ORDER_TYPES = {
    "LIMIT": "limit",
    "MARKET": "market",
    "STOP": "stop",
    "STOP_LOSS": "stop",
    "GUARANTEED_STOP_LOSS": "stop",
    "TRAILING_STOP_LOSS": "trailing_stop",
    "TAKE_PROFIT": "limit",
}
PROBE = "EUR/USD"  # asked whether prices are tradeable when the clock says the market is open


class OandaError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _num(value: Any, default: float | None = 0.0) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if "." in text:  # OANDA sends nanoseconds; Python reads microseconds
            head, tail = text.split(".", 1)
            text = f"{head}.{tail.rstrip('Z')[:6]}+00:00"
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _price_text(value: float, symbol: str) -> str:
    """OANDA rejects prices with more decimals than the pair is quoted in."""
    return f"{value:.{price_decimals(symbol)}f}".rstrip("0").rstrip(".")


class OandaClient:
    """A thin JSON client: one bearer token, errors raised as OandaError."""

    def __init__(
        self,
        token: str,
        live: bool = False,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not token:
            raise ValueError("Set OANDA_API_TOKEN (a personal access token from your OANDA account).")
        self.http = httpx.Client(
            base_url=LIVE_URL if live else PRACTICE_URL,
            headers={"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "RFC3339"},
            timeout=timeout,
            transport=transport,
        )

    def request(
        self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self.http.request(method, path, params=params, json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            reject = payload.get("orderRejectTransaction") or {}
            reason = payload.get("errorMessage") or reject.get("rejectReason") or response.text[:200]
            raise OandaError(f"OANDA {response.status_code}: {reason}", response.status_code)
        return payload

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self.request("GET", path, params=params or None)


class OandaBroker:
    def __init__(
        self, token: str, account_id: str, live: bool = False, client: OandaClient | None = None
    ) -> None:
        if not account_id:
            raise ValueError("Set OANDA_ACCOUNT_ID (it looks like 101-001-1234567-001) to use BROKER=oanda.")
        self.client = client or OandaClient(token, live=live)
        self.live = live
        self.base = f"/v3/accounts/{account_id}"
        self._fills: dict[str, dict[str, Any]] = {}  # fill transactions never change, so keep them
        self._closed_trades: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------ reads

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        return self.client.get(self.base + path, **params)

    def _open_trades(self) -> dict[str, dict[str, Any]]:
        return {str(t["id"]): t for t in self._get("/openTrades").get("trades", [])}

    def _pending(self) -> list[dict[str, Any]]:
        return list(self._get("/pendingOrders").get("orders", []))

    def _prices(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        names = ",".join(fx.instrument(s) for s in dict.fromkeys(symbols))
        if not names:
            return {}
        prices = self._get("/pricing", instruments=names).get("prices", [])
        return {fx.symbol_of(p["instrument"]): p for p in prices}

    @staticmethod
    def _side_price(price: dict[str, Any], side: str) -> float | None:
        quotes = price.get(f"{side}s") or []
        best = _num(quotes[0].get("price"), None) if quotes else None
        return best if best is not None else _num(price.get(f"closeout{side.capitalize()}"), None)

    def _mid(self, price: dict[str, Any]) -> float:
        bid, ask = self._side_price(price, "bid"), self._side_price(price, "ask")
        if bid is None or ask is None:
            raise OandaError(f"OANDA sent no quote for {price.get('instrument')}.")
        return (bid + ask) / 2

    def _trade(self, trade_id: str, open_trades: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if trade_id in open_trades:
            return open_trades[trade_id]
        if trade_id not in self._closed_trades:
            self._closed_trades[trade_id] = self._get(f"/trades/{trade_id}").get("trade", {})
        return self._closed_trades[trade_id]

    def _fill(self, transaction_id: str) -> dict[str, Any]:
        if transaction_id not in self._fills:
            self._fills[transaction_id] = self._get(f"/transactions/{transaction_id}").get("transaction", {})
        return self._fills[transaction_id]

    def _order(self, raw: dict[str, Any], open_trades: dict[str, dict[str, Any]]) -> BrokerOrder:
        kind = str(raw.get("type", ""))
        status = STATUS.get(str(raw.get("state", "")), str(raw.get("state", "")).lower())
        trade_id = raw.get("tradeID")
        if trade_id:  # a stop-loss hanging off a trade has no pair or size of its own
            trade = self._trade(str(trade_id), open_trades)
            symbol = fx.symbol_of(str(trade.get("instrument", "")))
            # The stop closes the trade, so it sits on the other side: a sell under a long.
            units = -(_num(trade.get("currentUnits")) or _num(trade.get("initialUnits")) or 0.0)
        else:
            symbol = fx.symbol_of(str(raw.get("instrument", "")))
            units = _num(raw.get("units")) or 0.0
        filled_qty, filled_price = 0.0, None
        if status == "filled" and raw.get("fillingTransactionID"):
            fill = self._fill(str(raw["fillingTransactionID"]))
            filled_qty = abs(_num(fill.get("units")) or 0.0)
            filled_price = _num(fill.get("fullVWAP") or fill.get("price"), None)
        is_stop = kind in ("STOP", "STOP_LOSS", "GUARANTEED_STOP_LOSS", "TRAILING_STOP_LOSS")
        stop_value = raw.get("trailingStopValue") if kind == "TRAILING_STOP_LOSS" else raw.get("price")
        client = raw.get("clientExtensions") or {}
        return BrokerOrder(
            id=str(raw["id"]),
            client_order_id=str(client.get("id") or f"oanda-{raw['id']}"),
            symbol=symbol,
            side=Side.BUY if units > 0 else Side.SELL,
            qty=abs(units),
            status=status,
            filled_qty=filled_qty,
            filled_avg_price=filled_price,
            limit_price=None if is_stop else _num(raw.get("price"), None),
            stop_price=_num(stop_value, None) if is_stop else None,
            order_type=ORDER_TYPES.get(kind, kind.lower()),
            order_class="oto" if trade_id else "simple",
            submitted_at=_time(raw.get("createTime")),
            parent_id=f"trade-{trade_id}" if trade_id else None,
        )

    def lots(self, symbols: Iterable[str]) -> dict[str, Lot]:
        """Each pair's smallest order, unit step and price step, as OANDA lists them."""
        names = ",".join(fx.instrument(s) for s in dict.fromkeys(symbols))
        lots: dict[str, Lot] = {}
        for item in self._get("/instruments", instruments=names).get("instruments", []):
            units, digits = int(item.get("tradeUnitsPrecision", 0)), int(item.get("displayPrecision", 5))
            lots[fx.symbol_of(item["name"])] = Lot(
                qty_step=round(10.0**-units, units),
                min_qty=_num(item.get("minimumTradeSize"), 1.0) or 1.0,
                price_tick=round(10.0**-digits, digits),
            )
        return lots

    def get_account(self) -> AccountInfo:
        account = self._get("/summary").get("account", {})
        equity = _num(account.get("NAV")) or 0.0
        held = _num(account.get("positionValue")) or 0.0
        on_order = sum(  # entries waiting to fill, long or short (exits only hand money back)
            money.notional(
                fx.symbol_of(str(o.get("instrument", ""))),
                _num(o.get("units")) or 0.0,
                _num(o.get("price")) or 0.0,
            )
            for o in self._pending()
            if o.get("type") == "LIMIT" and o.get("positionFill") != "REDUCE_ONLY"
        )
        free = equity - held - on_order  # no leverage: only what isn't already used
        # OANDA doesn't report yesterday's equity; the app falls back to its own last record.
        return AccountInfo(equity=equity, cash=free, buying_power=free, last_equity=0.0)

    def get_positions(self) -> list[Position]:
        held: dict[str, list[float]] = {}  # pair -> [units, cost]
        for trade in self._open_trades().values():
            units = _num(trade.get("currentUnits")) or 0.0
            symbol = fx.symbol_of(str(trade.get("instrument", "")))
            entry = held.setdefault(symbol, [0.0, 0.0])
            entry[0] += units
            entry[1] += units * (_num(trade.get("price")) or 0.0)
        held = {symbol: values for symbol, values in held.items() if values[0] != 0}
        prices = self._prices(held)
        positions = []
        for symbol, (units, cost) in sorted(held.items()):
            average = cost / units
            quote = prices.get(symbol)
            mark = self._side_price(quote, "bid" if units > 0 else "ask") if quote else None
            positions.append(
                Position(symbol=symbol, qty=units, avg_entry_price=average, current_price=mark or average)
            )
        return positions

    def get_open_orders(self, symbol: str | None = None) -> list[BrokerOrder]:
        trades = self._open_trades()
        orders = [self._order(raw, trades) for raw in self._pending()]
        return [o for o in orders if symbol is None or o.symbol == symbol]

    def get_orders_since(self, since: datetime) -> list[BrokerOrder]:
        start = as_utc(since)
        trades = self._open_trades()
        orders = []
        for raw in self._get("/orders", state="ALL", count=500).get("orders", []):
            created = _time(raw.get("createTime"))
            if start is not None and created is not None and created < start:
                continue
            orders.append(self._order(raw, trades))
        return orders

    def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        try:
            raw = self._get(f"/orders/@{client_order_id}").get("order")
        except OandaError as exc:
            if exc.status_code == 404:
                return None
            raise
        if not raw:
            return None
        return self._order(raw, self._open_trades() if raw.get("tradeID") else {})

    # ------------------------------------------------------------ orders

    def submit_limit_order(self, intent: OrderIntent) -> BrokerOrder:
        buy = intent.side == Side.BUY
        entry = intent.kind == IntentKind.ENTRY
        order: dict[str, Any] = {
            "type": "LIMIT",
            "instrument": fx.instrument(intent.symbol),
            "units": fmt_qty(intent.qty) if buy else f"-{fmt_qty(intent.qty)}",
            "price": _price_text(intent.limit_price, intent.symbol),
            "timeInForce": "GTC",
            "positionFill": "OPEN_ONLY" if entry else "REDUCE_ONLY",
            "clientExtensions": {"id": intent.client_order_id, "tag": TAG},
        }
        if entry and intent.stop_price is not None:
            order["stopLossOnFill"] = {
                "price": _price_text(intent.stop_price, intent.symbol),
                "timeInForce": "GTC",
                "clientExtensions": {"id": f"{intent.client_order_id}-stop", "tag": TAG},
            }
        reply = self.client.request("POST", self.base + "/orders", body={"order": order})
        canceled = reply.get("orderCancelTransaction")
        if canceled and not reply.get("orderFillTransaction"):
            reason = canceled.get("reason", "no reason given")
            raise OandaError(f"OANDA canceled the {intent.symbol} order as soon as it arrived: {reason}.")
        created = reply.get("orderCreateTransaction") or {}
        raw = self._get(f"/orders/{created['id']}").get("order") if created.get("id") else None
        if raw is None:
            raise OandaError(f"OANDA accepted the {intent.symbol} order but didn't say which order it made.")
        return self._order(raw, {})

    def submit_protective_stop(
        self, symbol: str, qty: float, stop_price: float, limit_price: float, client_order_id: str
    ) -> BrokerOrder:
        raise NotImplementedError(
            "Forex entries carry their stop-loss: OANDA attaches it when the entry fills."
        )

    def cancel_order(self, order_id: str) -> None:
        self.client.request("PUT", f"{self.base}/orders/{order_id}/cancel")

    def latest_price(self, symbol: str) -> float:
        quote = self._prices([symbol]).get(symbol)
        if quote is None:
            raise KeyError(f"OANDA has no price for {symbol}.")
        return self._mid(quote)

    def clock(self) -> MarketClock:
        clock = fx.clock(datetime.now(UTC))
        if clock.is_open:  # holidays and the daily break: ask whether prices are tradeable
            try:
                probe = self._prices([PROBE]).get(PROBE)
                if probe is not None and probe.get("tradeable") is False:
                    clock = clock.model_copy(update={"is_open": False})
            except Exception:
                log.warning("Couldn't ask OANDA whether the market is open; going by the weekly hours.")
        return clock

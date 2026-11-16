"""In-memory broker for the demo, replays and tests. It is not connected to any market.

Marketable limit orders fill immediately at the current price. An entry with a stop creates
a separate open stop-sell order, the way Alpaca's OTO orders do once the entry fills.

With crypto=True it behaves like Alpaca's crypto desk instead: entries carry no stop leg (the
app places a stop-limit sell after the fill), and with fee_bps set each fill pays a fee in the
asset received, so a buy credits slightly fewer coins than were ordered.

With forex=True it behaves like OANDA: the market runs from Sunday to Friday 5 pm New York, an
entry's stop-loss rides along with it, an exit can close the position while that stop rests
(closing the trade cancels its stop), and with financing_bps set each held position pays that
yearly rate for every night it's held. A sell entry opens a short (its stop is a buy above the
price) and a buy exit closes it. Every position is fully paid for and valued in dollars, the
way trader.money counts it, so USD/MXN works like EUR/USD.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from trader import forex as fx
from trader import money
from trader.models import AccountInfo, BrokerOrder, IntentKind, MarketClock, OrderIntent, Position, Side
from trader.utils import NY, as_utc, is_number


def _system_now() -> datetime:
    return datetime.now(UTC)


class FakeBroker:
    def __init__(
        self,
        cash: float = 100_000.0,
        prices: Mapping[str, float] | None = None,
        state_path: str | Path | None = None,
        now_fn: Callable[[], datetime] | None = None,
        always_open: bool = False,
        price_source: Callable[[str], float | None] | None = None,
        crypto: bool = False,
        fee_bps: float = 0.0,
        forex: bool = False,
        financing_bps: float = 0.0,
    ) -> None:
        self.crypto = crypto
        self.fee = fee_bps / 10_000
        self.forex = forex
        self.financing = financing_bps / 10_000  # a year's interest on what's held
        self.financed_on: date | None = None
        self.financing_paid = 0.0
        self.cash = float(cash)
        self.last_equity = float(cash)
        self.prices: dict[str, float] = {k: float(v) for k, v in (prices or {}).items()}
        self.positions: dict[str, dict[str, float]] = {}
        self.orders: dict[str, BrokerOrder] = {}
        self._seq = 0
        self.now_fn: Callable[[], datetime] = now_fn or _system_now
        self.always_open = always_open
        self.price_source = price_source
        self.state_path = Path(state_path) if state_path else None
        if self.state_path and self.state_path.exists():
            self._load()

    # ------------------------------------------------------------ persistence

    def _load(self) -> None:
        assert self.state_path is not None
        data = json.loads(self.state_path.read_text())
        self.cash = float(data["cash"])
        self.last_equity = float(data["last_equity"])
        self.prices.update({k: float(v) for k, v in data.get("prices", {}).items()})
        self.positions = {
            k: {"qty": float(v["qty"]), "avg_price": float(v["avg_price"])}
            for k, v in data.get("positions", {}).items()
        }
        self.orders = {k: BrokerOrder.model_validate(v) for k, v in data.get("orders", {}).items()}
        self._seq = int(data.get("seq", 0))
        financed_on = data.get("financed_on")
        self.financed_on = date.fromisoformat(financed_on) if financed_on else None
        self.financing_paid = float(data.get("financing_paid", 0.0))

    def _save(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cash": self.cash,
            "last_equity": self.last_equity,
            "prices": self.prices,
            "positions": self.positions,
            "orders": {k: v.model_dump(mode="json") for k, v in self.orders.items()},
            "seq": self._seq,
            "financed_on": self.financed_on.isoformat() if self.financed_on else None,
            "financing_paid": self.financing_paid,
        }
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=1))
        temp.replace(self.state_path)

    # ------------------------------------------------------------ simulation controls

    def set_prices(self, prices: Mapping[str, float]) -> None:
        self.prices.update({k: float(v) for k, v in prices.items() if is_number(v) and float(v) > 0})
        self._save()

    def end_of_day(self) -> None:
        """Mark the close: the next day's P&L is measured from here. A forex book first pays
        financing on what it held for each night since the last close (three over a weekend)."""
        if self.financing:
            today = as_utc(self.now_fn()).astimezone(NY).date()  # type: ignore[union-attr]
            nights = (today - self.financed_on).days if self.financed_on else 0
            held = sum(
                money.notional(symbol, p["qty"], self._mark(symbol, p))
                for symbol, p in self.positions.items()
            )
            if nights > 0 and held > 0:
                charge = held * self.financing * nights / 365
                self.cash -= charge
                self.financing_paid += charge
            self.financed_on = today
        self.last_equity = self.get_account().equity
        self._save()

    def trigger_stops(self) -> list[BrokerOrder]:
        """Fill open stop orders whose stop price has been reached at the current prices.

        A sell stop fires at or below its price, a buy stop (over a forex short) at or above it.
        A stop-limit fills only at its limit or better; past it, it stays open, unfilled.
        """
        filled = []
        for order in self.get_open_orders():
            if order.stop_price is None:
                continue
            price = self._price(order.symbol)
            selling = order.side == Side.SELL
            if (price > order.stop_price) if selling else (price < order.stop_price):
                continue
            limit = order.limit_price if order.order_type == "stop_limit" else None
            if limit is not None and ((price < limit) if selling else (price > limit)):
                continue
            held = self.positions.get(order.symbol, {}).get("qty", 0.0)
            qty = min(order.qty, held if selling else -held)
            if qty <= 0:
                order.status = "canceled"
                continue
            if selling:
                self._fill_sell(order, price, qty)
            else:
                self._fill_cover(order, price, qty)
            filled.append(order)
        self._save()
        return filled

    # ------------------------------------------------------------ helpers

    def _price(self, symbol: str) -> float:
        price = self.prices.get(symbol)
        if price is None and self.price_source is not None:
            fetched = self.price_source(symbol)
            if is_number(fetched) and float(fetched) > 0:  # type: ignore[arg-type]
                price = float(fetched)  # type: ignore[arg-type]
                self.prices[symbol] = price
        if price is None:
            raise KeyError(f"The fake broker has no price for {symbol}.")
        return price

    def _mark(self, symbol: str, position: dict[str, float]) -> float:
        try:
            return self._price(symbol)
        except KeyError:
            return position["avg_price"]

    def _next_id(self) -> str:
        self._seq += 1
        return f"fake-{self._seq:06d}"

    def _fill_buy(self, order: BrokerOrder, price: float) -> None:
        position = self.positions.setdefault(order.symbol, {"qty": 0.0, "avg_price": 0.0})
        received = order.qty * (1 - self.fee)  # crypto fees come out of the coins received
        new_qty = position["qty"] + received
        position["avg_price"] = (position["qty"] * position["avg_price"] + order.qty * price) / new_qty
        position["qty"] = new_qty
        self.cash -= money.notional(order.symbol, order.qty, price)
        order.status = "filled"
        order.filled_qty = order.qty
        order.filled_avg_price = price

    def _fill_short(self, order: BrokerOrder, price: float) -> None:
        """Open a forex short: the dollars it's worth are set aside, as for a long."""
        self.positions[order.symbol] = {"qty": -order.qty, "avg_price": price}
        self.cash -= money.notional(order.symbol, order.qty, price)
        order.status = "filled"
        order.filled_qty = order.qty
        order.filled_avg_price = price

    def _closed(self, order: BrokerOrder) -> None:
        del self.positions[order.symbol]
        if self.forex:  # closing a trade cancels the stop-loss that hangs off it
            for other in self.get_open_orders(order.symbol):
                if other is not order and other.is_protective_stop:
                    other.status = "canceled"

    def _fill_sell(self, order: BrokerOrder, price: float, qty: float | None = None) -> None:
        qty = order.qty if qty is None else qty
        position = self.positions[order.symbol]
        proceeds = money.value(order.symbol, qty, position["avg_price"], price)
        position["qty"] -= qty
        if position["qty"] <= 1e-9:
            self._closed(order)
        self.cash += proceeds * (1 - self.fee)
        order.status = "filled"
        order.filled_qty = qty
        order.filled_avg_price = price

    def _fill_cover(self, order: BrokerOrder, price: float, qty: float | None = None) -> None:
        """Buy back (part of) a forex short: what it's worth comes back to cash."""
        qty = order.qty if qty is None else qty
        position = self.positions[order.symbol]
        self.cash += money.value(order.symbol, -qty, position["avg_price"], price)
        position["qty"] += qty
        if position["qty"] >= -1e-9:
            self._closed(order)
        order.status = "filled"
        order.filled_qty = qty
        order.filled_avg_price = price

    # ------------------------------------------------------------ Broker protocol

    def get_account(self) -> AccountInfo:
        holdings = sum(
            money.value(symbol, p["qty"], p["avg_price"], self._mark(symbol, p))
            for symbol, p in self.positions.items()
        )
        equity = self.cash + holdings
        return AccountInfo(
            equity=equity, cash=self.cash, buying_power=self.cash, last_equity=self.last_equity
        )

    def get_positions(self) -> list[Position]:
        return [
            Position(
                symbol=symbol,
                qty=p["qty"],
                avg_entry_price=p["avg_price"],
                current_price=self._mark(symbol, p),
            )
            for symbol, p in sorted(self.positions.items())
            if p["qty"] != 0
        ]

    def get_open_orders(self, symbol: str | None = None) -> list[BrokerOrder]:
        return [o for o in self.orders.values() if o.is_open and (symbol is None or o.symbol == symbol)]

    def get_orders_since(self, since: datetime) -> list[BrokerOrder]:
        start = as_utc(since)
        assert start is not None
        return [o for o in self.orders.values() if o.submitted_at is None or as_utc(o.submitted_at) >= start]  # type: ignore[operator]

    def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        return next((o for o in self.orders.values() if o.client_order_id == client_order_id), None)

    def submit_limit_order(self, intent: OrderIntent) -> BrokerOrder:
        if self.get_order_by_client_id(intent.client_order_id) is not None:
            raise ValueError("client_order_id must be unique")
        now = self.now_fn()
        price = self._price(intent.symbol)
        order = BrokerOrder(
            id=self._next_id(),
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            qty=intent.qty,
            status="new",
            limit_price=intent.limit_price,
            order_type="limit",
            order_class="oto" if intent.stop_price is not None and not self.crypto else "simple",
            submitted_at=now,
        )
        opening_short = self.forex and intent.side == Side.SELL and intent.kind == IntentKind.ENTRY
        covering = self.forex and intent.side == Side.BUY and intent.kind == IntentKind.EXIT
        held = self.positions.get(intent.symbol, {}).get("qty", 0.0)
        if self.forex and intent.kind == IntentKind.ENTRY and held and (held < 0) != opening_short:
            # OANDA's OPEN_ONLY: an entry may not shrink a position on the other side.
            order.status = "canceled"
        elif covering:
            self._check_available(intent.symbol, intent.qty, Side.BUY)
            if price <= intent.limit_price:
                self._fill_cover(order, price)
        elif intent.side == Side.BUY or opening_short:
            fills = price <= intent.limit_price if intent.side == Side.BUY else price >= intent.limit_price
            if fills:
                if money.notional(intent.symbol, intent.qty, price) > self.cash + 1e-9:
                    order.status = "rejected"
                else:
                    if opening_short:
                        self._fill_short(order, price)
                    else:
                        self._fill_buy(order, price)
                    if intent.stop_price is not None and not self.crypto:
                        leg = BrokerOrder(
                            id=self._next_id(),
                            client_order_id=f"{intent.client_order_id}-stop",
                            symbol=intent.symbol,
                            side=Side.BUY if opening_short else Side.SELL,
                            qty=intent.qty,
                            status="new",
                            order_type="stop",
                            order_class="oto",
                            stop_price=intent.stop_price,
                            submitted_at=now,
                            parent_id=order.id,
                        )
                        self.orders[leg.id] = leg
        else:
            self._check_available(intent.symbol, intent.qty, Side.SELL)
            if price >= intent.limit_price:
                self._fill_sell(order, price)
        self.orders[order.id] = order
        self._save()
        return order

    def _check_available(self, symbol: str, qty: float, side: Side = Side.SELL) -> None:
        """A sell may close at most the long held, a buy-back at most the short."""
        held = self.positions.get(symbol, {}).get("qty", 0.0)
        held = held if side == Side.SELL else -held
        reserved = sum(
            o.qty - o.filled_qty
            for o in self.get_open_orders(symbol)
            if o.side == side and not (self.forex and o.is_protective_stop)  # forex stops hold nothing back
        )
        if qty > held - reserved + 1e-9:
            raise ValueError(
                f"insufficient qty available for order (requested {qty}, available {held - reserved:g})"
            )

    def submit_protective_stop(
        self, symbol: str, qty: float, stop_price: float, limit_price: float, client_order_id: str
    ) -> BrokerOrder:
        if self.get_order_by_client_id(client_order_id) is not None:
            raise ValueError("client_order_id must be unique")
        self._check_available(symbol, qty)
        order = BrokerOrder(
            id=self._next_id(),
            client_order_id=client_order_id,
            symbol=symbol,
            side=Side.SELL,
            qty=qty,
            status="new",
            order_type="stop_limit",
            stop_price=stop_price,
            limit_price=limit_price,
            submitted_at=self.now_fn(),
        )
        self.orders[order.id] = order
        self._save()
        return order

    def cancel_order(self, order_id: str) -> None:
        order = self.orders.get(order_id)
        if order is not None and order.is_open:
            order.status = "canceled"
            self._save()

    def latest_price(self, symbol: str) -> float:
        return self._price(symbol)

    def clock(self) -> MarketClock:
        now = as_utc(self.now_fn())
        assert now is not None
        if self.always_open:
            return MarketClock(
                timestamp=now,
                is_open=True,
                next_open=now + timedelta(days=1),
                next_close=now + timedelta(hours=2),
                session_open=now - timedelta(hours=2),
                session_close=now + timedelta(hours=2),
            )
        if self.forex:
            return fx.clock(now)
        local = now.astimezone(NY)
        trading_day = local.weekday() < 5
        session_open = datetime.combine(local.date(), time(9, 30), tzinfo=NY)
        session_close = datetime.combine(local.date(), time(16, 0), tzinfo=NY)
        is_open = trading_day and session_open <= local < session_close

        def next_weekday_at(hour: int, minute: int, strictly_after: datetime) -> datetime:
            day = strictly_after.date()
            candidate = datetime.combine(day, time(hour, minute), tzinfo=NY)
            while candidate <= strictly_after or candidate.weekday() >= 5:
                day += timedelta(days=1)
                candidate = datetime.combine(day, time(hour, minute), tzinfo=NY)
            return candidate

        return MarketClock(
            timestamp=now,
            is_open=is_open,
            next_open=next_weekday_at(9, 30, local),
            next_close=next_weekday_at(16, 0, local),
            session_open=session_open if trading_day else None,
            session_close=session_close if trading_day else None,
        )

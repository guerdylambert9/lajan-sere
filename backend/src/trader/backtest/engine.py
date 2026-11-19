"""Daily backtester that trades through the same planner the live system uses.

Each day: mark positions to the close, fire stops whose level the close has reached, then ask
plan_intents for exits and entries and fill them at that close plus costs. With lag=1 a signal
trades at the close it was computed on (slightly optimistic); lag=2 trades one day later
(pessimistic). Live fills, at the next morning's price, land in between, so a strategy worth
trading should survive both.

Stops fill at the close that reached them. For crypto that is generous in one way: a real
stop-limit can stay unfilled when the price falls straight through its limit.

Forex positions pay financing for every night they're held (financing_bps_per_year, charged on
what's held, long or short, three nights over a weekend). The real charge is the gap between
the two currencies' interest rates plus the broker's markup, and it can be a credit; a flat
charge is the cautious stand-in.

Shorts (forex, with short selling on) are fully paid for like longs: opening one sets aside its
dollar size, and its stop sits above the entry. Every value is in dollars (trader.money), so a
pair with the dollar first, like USD/MXN, counts the same way as EUR/USD.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from trader import money
from trader.assets import AssetRules
from trader.models import AccountState, IntentKind, Position, Side
from trader.planner import plan_intents
from trader.risk.limits import RiskLimits
from trader.strategies.base import Strategy

TRADE_COLUMNS = [
    "symbol",
    "entry_date",
    "entry_price",
    "qty",  # below zero for a short
    "exit_date",
    "exit_price",
    "return_pct",
    "exit_reason",
]
FILL_COLUMNS = ["date", "symbol", "side", "qty", "price", "notional"]


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100_000.0
    cost_bps: float = 5.0  # per side: spread and slippage (stocks), plus the trading fee (crypto)
    lag: int = 1
    use_stops: bool = True
    financing_bps_per_year: float = 0.0  # forex: a year's interest on what's held, charged nightly

    def __post_init__(self) -> None:
        if self.lag < 1:
            raise ValueError("lag must be at least 1")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.cost_bps < 0:
            raise ValueError("cost_bps cannot be negative")
        if self.financing_bps_per_year < 0:
            raise ValueError("financing_bps_per_year cannot be negative")


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: pd.DataFrame
    fills: pd.DataFrame
    open_positions: pd.Series
    exposure: pd.Series
    config: BacktestConfig
    strategy: dict[str, Any]
    financing: pd.Series | None = None  # forex: financing paid each day


def run_backtest(
    closes: pd.DataFrame,
    strategy: Strategy,
    limits: RiskLimits,
    config: BacktestConfig | None = None,
    universe: Sequence[str] | None = None,
    rules: AssetRules | None = None,
) -> BacktestResult:
    config = config or BacktestConfig()
    park = strategy.cash_park()
    park_symbol = park.symbol if park is not None else None
    base = list(closes.columns) if universe is None else list(universe)
    listed = [s for s in strategy.traded_universe(base) if s in closes.columns]
    if park_symbol is not None and park_symbol not in closes.columns:
        raise ValueError(
            f"No {park_symbol} prices. {strategy.name} puts cash beyond a {park.buffer:.0%} buffer into it."
        )
    absent = [s for s in strategy.extra_symbols() if s != park_symbol and s not in closes.columns]
    if absent:
        needed = ", ".join(absent)
        raise ValueError(f"No {needed} prices. {strategy.name} holds them.")
    symbols = [s for s in listed if s != park_symbol]
    price_symbols = [*symbols, *([park_symbol] if park_symbol and park_symbol not in symbols else [])]
    rules = rules or AssetRules.for_symbols(price_symbols)
    if not symbols:
        raise ValueError("None of the universe symbols are in the price data.")
    if len(closes) < 2:
        raise ValueError("Need at least two days of prices.")

    prices = closes[price_symbols].astype(float)
    weights = strategy.target_weights(closes[symbols]).reindex(columns=symbols).fillna(0.0)
    targets = weights.shift(config.lag - 1).fillna(0.0)
    cost = config.cost_bps / 10_000
    financing_rate = config.financing_bps_per_year / 10_000

    cash = config.initial_capital
    shares: dict[str, float] = {}  # below zero: a short
    stops: dict[str, float | None] = {}
    entries: dict[str, tuple[pd.Timestamp, float]] = {}
    last_price: dict[str, float] = {}
    trades: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    equity_values: list[float] = []
    open_counts: list[int] = []
    exposure_values: list[float] = []
    financing_values: list[float] = []
    peak = previous_equity = config.initial_capital
    previous_day: pd.Timestamp | None = None

    price_matrix = prices.to_numpy()
    target_matrix = targets.to_numpy()

    def worth(symbol: str, qty: float) -> float:
        return money.value(symbol, qty, entries[symbol][1], last_price[symbol])

    def size(symbol: str, qty: float) -> float:
        return money.notional(symbol, qty, last_price[symbol])

    def close_position(symbol: str, when: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        qty = shares.pop(symbol)
        net_price = price * (1 - cost) if qty > 0 else price * (1 + cost)  # a short buys back
        entry_date, entry_price = entries.pop(symbol)
        cash += money.value(symbol, qty, entry_price, net_price)
        stops.pop(symbol, None)
        if qty > 0 and not money.dollar_first(symbol):
            returned = (net_price / entry_price - 1) * 100
        else:
            returned = money.return_pct(symbol, qty, entry_price, net_price)
        trades.append(
            {
                "symbol": symbol,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "qty": qty,
                "exit_date": when,
                "exit_price": net_price,
                "return_pct": returned,
                "exit_reason": reason,
            }
        )
        fills.append(
            {
                "date": when,
                "symbol": symbol,
                "side": "sell" if qty > 0 else "buy",
                "qty": abs(qty),
                "price": price,
                "notional": money.notional(symbol, qty, price),
            }
        )

    def reduce_position(symbol: str, qty: float, when: pd.Timestamp, price: float, reason: str) -> None:
        """Sell part of a long cash-fund holding. Other exits still close the whole position."""
        nonlocal cash
        held = shares[symbol]
        qty = min(qty, held)
        net_price = price * (1 - cost)
        entry_date, entry_price = entries[symbol]
        cash += money.value(symbol, qty, entry_price, net_price)
        left = held - qty
        if left <= 1e-9:
            shares.pop(symbol)
            entries.pop(symbol)
            stops.pop(symbol, None)
        else:
            shares[symbol] = left
        trades.append(
            {
                "symbol": symbol,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "qty": qty,
                "exit_date": when,
                "exit_price": net_price,
                "return_pct": (net_price / entry_price - 1) * 100 if entry_price else 0.0,
                "exit_reason": reason,
            }
        )
        fills.append(
            {
                "date": when,
                "symbol": symbol,
                "side": "sell",
                "qty": qty,
                "price": price,
                "notional": money.notional(symbol, qty, price),
            }
        )

    for i, when in enumerate(prices.index):
        charged = 0.0
        if financing_rate and shares and previous_day is not None:
            nights = max((when - previous_day).days, 0)
            held = sum(size(s, qty) for s, qty in shares.items())
            charged = held * financing_rate * nights / 365
            cash -= charged
        financing_values.append(charged)
        previous_day = when
        today: dict[str, float] = {}
        for j, symbol in enumerate(price_symbols):
            value = price_matrix[i, j]
            if np.isfinite(value) and value > 0:
                today[symbol] = float(value)
                last_price[symbol] = float(value)

        stopped: set[str] = set()
        if config.use_stops:
            for symbol in list(shares):
                stop = stops.get(symbol)
                price = today.get(symbol)
                if stop is None or price is None:
                    continue
                if (price <= stop) if shares[symbol] > 0 else (price >= stop):
                    close_position(symbol, when, price, "stop")
                    stopped.add(symbol)

        holdings = sum(worth(s, qty) for s, qty in shares.items())
        equity = cash + holdings
        account = AccountState(
            equity=equity,
            cash=cash,
            buying_power=cash,
            day_start_equity=previous_equity,
            peak_equity=max(peak, equity),
            positions={
                s: Position(symbol=s, qty=q, avg_entry_price=entries[s][1], current_price=last_price[s])
                for s, q in shares.items()
            },
        )
        day_targets = {symbol: float(target_matrix[i, j]) for j, symbol in enumerate(symbols)}
        missing = {s for s in symbols if s not in today}
        intents = plan_intents(
            day_targets,
            today,
            account,
            limits,
            symbols,
            when.date(),
            "bt",
            exclude=stopped | missing,
            rules=rules,
            cash_park=park,
            position_cap=strategy.position_cap(),
            use_stops=strategy.uses_stops(),
        )
        for intent in intents:
            price = today[intent.symbol]
            if intent.kind == IntentKind.EXIT:
                held_qty = shares.get(intent.symbol, 0.0)
                partial = (
                    park_symbol is not None
                    and intent.symbol == park_symbol
                    and 0 < intent.qty < abs(held_qty) - 1e-9
                )
                if partial:
                    reduce_position(intent.symbol, intent.qty, when, price, "signal")
                else:
                    close_position(intent.symbol, when, price, "signal")
                continue
            short = intent.side == Side.SELL
            fill_price = price * (1 - cost) if short else price * (1 + cost)
            affordable = cash / money.unit_cost(intent.symbol, fill_price)
            qty = min(intent.qty, rules.floor_qty(intent.symbol, affordable))
            if qty <= 0:
                continue
            cash -= money.notional(intent.symbol, qty, fill_price)
            topping_up = park_symbol is not None and intent.symbol == park_symbol and intent.symbol in shares
            if topping_up and not short:
                old_qty = shares[intent.symbol]
                old_entry = entries[intent.symbol][1]
                new_qty = old_qty + qty
                entries[intent.symbol] = (
                    entries[intent.symbol][0],
                    (old_qty * old_entry + qty * fill_price) / new_qty,
                )
                shares[intent.symbol] = new_qty
                stops[intent.symbol] = intent.stop_price
            else:
                shares[intent.symbol] = -qty if short else qty
                stops[intent.symbol] = intent.stop_price
                entries[intent.symbol] = (when, fill_price)
            fills.append(
                {
                    "date": when,
                    "symbol": intent.symbol,
                    "side": "sell" if short else "buy",
                    "qty": qty,
                    "price": price,
                    "notional": money.notional(intent.symbol, qty, price),
                }
            )

        holdings = sum(worth(s, qty) for s, qty in shares.items())
        gross = sum(size(s, qty) for s, qty in shares.items())
        equity = cash + holdings
        peak = max(peak, equity)
        previous_equity = equity
        equity_values.append(equity)
        open_counts.append(sum(1 for symbol in shares if symbol != park_symbol))
        exposure_values.append(gross / equity if equity > 0 else 0.0)

    for symbol, qty in shares.items():
        entry_date, entry_price = entries[symbol]
        price = last_price[symbol]
        if qty > 0 and not money.dollar_first(symbol):
            returned = (price / entry_price - 1) * 100
        else:
            returned = money.return_pct(symbol, qty, entry_price, price)
        trades.append(
            {
                "symbol": symbol,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "qty": qty,
                "exit_date": pd.NaT,
                "exit_price": price,
                "return_pct": returned,
                "exit_reason": "open",
            }
        )

    index = prices.index
    return BacktestResult(
        equity=pd.Series(equity_values, index=index, name="equity"),
        trades=pd.DataFrame(trades, columns=TRADE_COLUMNS),
        fills=pd.DataFrame(fills, columns=FILL_COLUMNS),
        open_positions=pd.Series(open_counts, index=index, name="open_positions"),
        exposure=pd.Series(exposure_values, index=index, name="exposure"),
        config=config,
        strategy=strategy.describe(),
        financing=pd.Series(financing_values, index=index, name="financing"),
    )

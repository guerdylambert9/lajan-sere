"""Candidate 3: the trend signal, with cash beyond a 2% buffer parked in BIL.

Prices here are fixtures. Nothing in this file looks at the 2023–now holdout.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from tests.helpers import TODAY, UNIVERSE, make_ctx
from trader.assets import price_up
from trader.backtest import BacktestConfig, run_backtest
from trader.models import AccountState, IntentKind, Position, Side
from trader.planner import drifts_off_target, plan_intents
from trader.risk import RiskContext, RiskLimits, check_order
from trader.strategies import TrendFollowing, TrendWithBills, get_strategy
from trader.strategies.base import CashPark
from trader.strategies.trend_bil import BIL, CASH_BUFFER, RESIZE_BAND

LIMITS = RiskLimits()
PARK = CashPark(BIL, CASH_BUFFER, RESIZE_BAND)
EQUITY = 100_000.0


def account(
    cash: float, positions: dict[str, Position] | None = None, equity: float | None = None
) -> AccountState:
    positions = positions or {}
    if equity is None:
        equity = cash + sum(p.market_value for p in positions.values())
    return AccountState(
        equity=equity,
        cash=cash,
        buying_power=cash,
        day_start_equity=equity,
        peak_equity=equity,
        positions=positions,
    )


def position(symbol: str, qty: float, price: float) -> Position:
    return Position(symbol=symbol, qty=qty, avg_entry_price=price, current_price=price)


def park(targets, acct, limits=LIMITS, universe=UNIVERSE, prices=None):
    prices = prices or {symbol: 100.0 for symbol in [*universe, BIL]}
    return plan_intents(targets, prices, acct, limits, universe, TODAY, "tpA", cash_park=PARK)


def bil_orders(intents):
    return [intent for intent in intents if intent.symbol == BIL]


def test_cash_beyond_the_2_percent_buffer_goes_into_bil():
    (order,) = bil_orders(park({}, account(EQUITY)))
    assert order.side == Side.BUY and order.kind == IntentKind.ENTRY
    assert order.stop_price is None
    # The buy is the idle cash, so it is most of the account and it leaves the buffer.
    assert order.notional > EQUITY * LIMITS.max_position_pct / 100
    assert order.notional <= EQUITY * (1 - CASH_BUFFER) + 0.01
    assert EQUITY - order.notional >= EQUITY * CASH_BUFFER - 0.01


def test_resize_band_holds_when_the_drift_is_5_percent_or_less():
    """A drift of 4% and a drift of exactly 5% of the account stay inside the band."""
    spy = position("SPY", 80, 500.0)  # 40_000, still targeted, so the trend book is left alone
    held = {"SPY": spy}
    inside = park(
        {"SPY": 0.1},
        account(6_000.0, {**held, BIL: position(BIL, 540, 100.0)}),
        prices={"SPY": 500.0, BIL: 100.0},
    )
    exact = park(
        {"SPY": 0.1},
        account(7_000.0, {**held, BIL: position(BIL, 530, 100.0)}),
        prices={"SPY": 500.0, BIL: 100.0},
    )
    assert bil_orders(inside) == []
    assert bil_orders(exact) == []
    assert not drifts_off_target(54_000, 58_000, EQUITY, RESIZE_BAND)
    assert not drifts_off_target(53_000, 58_000, EQUITY, RESIZE_BAND)


def test_resize_buys_bil_when_it_drifts_more_than_5_percent_below_target():
    spy = position("SPY", 80, 500.0)
    intents = park(
        {"SPY": 0.1},
        account(8_000.0, {"SPY": spy, BIL: position(BIL, 520, 100.0)}),
        prices={"SPY": 500.0, BIL: 100.0},
    )
    (order,) = bil_orders(intents)
    assert [intent.symbol for intent in intents] == [BIL]
    assert order.side == Side.BUY and order.stop_price is None
    room = 8_000.0 - EQUITY * CASH_BUFFER  # cash above the buffer is what may be invested
    limit = price_up(100.0 * 1.002, 0.01)
    assert order.qty == math.floor(room / limit)
    assert order.notional <= room + 0.01
    assert drifts_off_target(52_000, 58_000, EQUITY, RESIZE_BAND)


def test_resize_sells_bil_when_it_is_more_than_5_percent_of_the_account_above_target():
    # The band is measured against account equity. Here BIL is marked at 90,000 while the
    # target for this equity, after the trend holding and the 2% buffer, is 78,000.
    acct = account(
        2_000.0,
        {"SPY": position("SPY", 40, 500.0), BIL: position(BIL, 900, 100.0)},
        equity=EQUITY,
    )
    (order,) = park({"SPY": 0.1}, acct, prices={"SPY": 500.0, BIL: 100.0})
    assert order.symbol == BIL and order.side == Side.SELL and order.kind == IntentKind.EXIT
    assert order.stop_price is None
    assert order.qty == 120  # 900 shares down to the 780-share target
    assert drifts_off_target(90_000, 78_000, EQUITY, RESIZE_BAND)


def test_bil_is_sold_first_when_an_entry_needs_the_cash():
    acct = account(
        2_000.0,
        {"SPY": position("SPY", 80, 500.0), BIL: position(BIL, 580, 100.0)},
    )
    intents = park(
        {"SPY": 0.1, "QQQ": 0.1},
        acct,
        prices={"SPY": 500.0, "QQQ": 400.0, BIL: 100.0},
    )
    assert [intent.symbol for intent in intents] == [BIL, "QQQ"]
    sale, buy = intents
    assert sale.side == Side.SELL and sale.stop_price is None
    assert buy.side == Side.BUY and buy.stop_price is not None and buy.stop_price < buy.limit_price
    assert buy.notional > 2_000.0  # the 2% buffer alone cannot pay for the ETF
    assert sale.qty * sale.limit_price + 2_000.0 >= buy.notional - 0.01


def test_bil_ignores_the_position_cap_and_the_open_position_count():
    limits = RiskLimits(max_open_positions=len(UNIVERSE))
    held = {symbol: position(symbol, 1, 10.0) for symbol in UNIVERSE}
    intents = park(dict.fromkeys(UNIVERSE, 0.1), account(EQUITY - 60.0, held), limits)
    (order,) = intents
    assert order.symbol == BIL and order.stop_price is None
    assert order.notional > EQUITY * limits.max_position_pct / 100
    assert len(held) == limits.max_open_positions


def test_sending_bil_does_not_put_the_cap_or_the_stop_back():
    """The morning re-price keeps a BIL buy over 10% and without a stop, and a sale partial."""
    from trader.db import ProposalRow
    from trader.services.execution import refresh_intent

    ctx = make_ctx(strategy=TrendWithBills())
    ctx.broker.set_prices({BIL: 100.0})
    acct = account(EQUITY)
    buy = ProposalRow(
        as_of=TODAY,
        symbol=BIL,
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        qty=500,
        est_price=100.0,
        limit_price=100.2,
        stop_price=None,
        client_order_id="tpA-20261112-BIL-buy",
        status="approved",
        source="rules",
        reason="park",
    )
    intent, problem = refresh_intent(ctx, buy, acct)
    assert problem is None and intent is not None
    assert intent.stop_price is None and intent.qty == 500

    held = account(2_000.0, {BIL: position(BIL, 900, 100.0)})
    sale = ProposalRow(
        as_of=TODAY,
        symbol=BIL,
        side=Side.SELL,
        kind=IntentKind.EXIT,
        qty=120,
        est_price=100.0,
        limit_price=99.8,
        client_order_id="tpA-20261112-BIL-sell",
        status="approved",
        source="rules",
        reason="resize",
    )
    intent, problem = refresh_intent(ctx, sale, held)
    assert problem is None and intent is not None
    assert intent.qty == 120  # not the whole 900-share holding

    plain = make_ctx()
    plain.broker.set_prices({"SPY": 100.0})
    spy = ProposalRow(
        as_of=TODAY,
        symbol="SPY",
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        qty=500,
        est_price=100.0,
        limit_price=100.2,
        stop_price=92.0,
        client_order_id="tpA-20261112-SPY-buy",
        status="approved",
        source="rules",
        reason="trend",
    )
    capped, problem = refresh_intent(plain, spy, account(EQUITY))
    assert problem is None and capped is not None
    assert capped.stop_price is not None and capped.qty < 500


def test_choosing_trend_or_momentum_does_not_park_cash_in_bil():
    assert get_strategy("trend").cash_park() is None
    assert get_strategy("momentum").cash_park() is None
    held = account(EQUITY, {BIL: position(BIL, 100, 100.0)})
    plain = plan_intents({"SPY": 0.1}, {"SPY": 500.0, BIL: 100.0}, held, LIMITS, UNIVERSE, TODAY, "tpA")
    assert [intent.symbol for intent in plain] == ["SPY"]
    with pytest.raises(ValueError, match="only buys"):
        get_strategy("trend-bil", shorts=True)


def test_risk_engine_exempts_bil_from_the_stop_the_cap_and_the_position_count():
    from datetime import datetime

    from trader.models import OrderIntent
    from trader.utils import NY

    now = datetime(2026, 11, 12, 10, 30, tzinfo=NY)
    full = {
        f"S{i}": Position(symbol=f"S{i}", qty=10, avg_entry_price=100, current_price=100)
        for i in range(LIMITS.max_open_positions)
    }
    acct = account(EQUITY, full, equity=EQUITY)
    order = OrderIntent(
        symbol=BIL,
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        qty=500,  # half the account: over the 10% cap, and a 9th position, with no stop
        limit_price=100.0,
        stop_price=None,
        client_order_id="tpA-20261112-BIL-buy",
    )
    parked = RiskContext(now=now, universe={"SPY"}, cash_symbols=frozenset({BIL}))
    assert check_order(order, acct, LIMITS, parked).approved

    blocked = check_order(order, acct, LIMITS, RiskContext(now=now, universe={"SPY"}))
    assert {item.code for item in blocked.violations} >= {"missing_stop", "position_size", "max_positions"}

    killed = RiskContext(now=now, universe={"SPY"}, cash_symbols=frozenset({BIL}), kill_switch_engaged=True)
    assert "kill_switch" in {item.code for item in check_order(order, acct, LIMITS, killed).violations}

    # The exemptions are BIL's. A stock entry is unchanged.
    spy = OrderIntent(
        symbol="SPY",
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        qty=50,
        limit_price=100.0,
        stop_price=None,
        client_order_id="tpA-20261112-SPY-buy",
    )
    assert "missing_stop" in {
        item.code for item in check_order(spy, account(EQUITY), LIMITS, parked).violations
    }


def _fixture_prices() -> pd.DataFrame:
    """SPY falls through its 2-day average, then jumps above it. BIL stays at 100."""
    index = pd.bdate_range("2020-01-01", periods=12)
    return pd.DataFrame(
        {"SPY": [100, 99, 98, 97, 96, 95, 110, 112, 114, 116, 118, 120], "BIL": 100.0},
        index=index,
    )


def test_backtest_parks_cash_and_sells_bil_to_fund_the_trend_entry():
    closes = _fixture_prices()
    limits = RiskLimits()
    config = BacktestConfig(cost_bps=0, initial_capital=EQUITY)
    result = run_backtest(closes, TrendWithBills(window=2), limits, config, ["SPY"])
    trend = run_backtest(closes, TrendFollowing(window=2), limits, config, ["SPY"])

    bil_fills = result.fills[result.fills.symbol == BIL]
    assert (bil_fills.side == "buy").any()
    assert trend.fills[trend.fills.symbol == BIL].empty

    spy_day = result.fills.loc[result.fills.symbol == "SPY", "date"].iloc[0]
    same_day = bil_fills[bil_fills.date == spy_day]
    assert (same_day.side == "sell").any()  # sold first so the ETF entry has the cash
    # No resize in the quiet days after the first park and before the ETF entry.
    first_buy = bil_fills[bil_fills.side == "buy"].date.min()
    quiet = bil_fills[(bil_fills.date > first_buy) & (bil_fills.date < spy_day)]
    assert quiet.empty

    stopped = result.trades[(result.trades.symbol == BIL) & (result.trades.exit_reason == "stop")]
    assert stopped.empty
    # BIL is held alongside SPY and does not count as an open position.
    assert result.open_positions.max() == 1
    open_bil = result.trades[(result.trades.symbol == BIL) & (result.trades.exit_reason == "open")]
    assert len(open_bil) == 1 and open_bil.iloc[0].qty > 0

    trend_qty = trend.fills.loc[trend.fills.symbol == "SPY", "qty"].iloc[0]
    bil_qty = result.fills.loc[result.fills.symbol == "SPY", "qty"].iloc[0]
    assert bil_qty == trend_qty

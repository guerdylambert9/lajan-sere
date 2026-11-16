"""The watchlist scanner: ranked ideas from a list you choose. Ideas only, never orders.

It ranks the watchlist the way the momentum strategy would on a rebalance day: by return over
the 12 months before the latest month, with the top N that are positive as buy ideas. Trend
and distance from the 52-week high are shown for context. Entry, stop and size follow the
same risk rules as real orders, so an idea reads like the order it would become.

Ideas stay untested until a strategy covering the watchlist passes Gate 1: set UNIVERSE to
the watchlist and STRATEGY=momentum, then run `trader gate1`.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd

from trader import ledger
from trader.strategies.momentum import ordinal
from trader.utils import signed_pct

if TYPE_CHECKING:
    from trader.services.context import AppContext

log = logging.getLogger(__name__)

SCAN_KEY = "scan"
LOOKBACK = 252  # trading days: about 12 months
SKIP = 21  # trading days: the latest month, left out
TREND = 200  # trading days for the trend average

RULE = (
    "Ranks the watchlist by return over the 12 months before the latest month, the way the "
    "momentum strategy does; the top {top_n} with a positive return are buy ideas."
)
HOW_TO_TEST = (
    "Untested: no strategy covering this watchlist has passed Gate 1. To test it, set UNIVERSE to "
    "the watchlist and STRATEGY=momentum, then run trader gate1. A pass turns these ideas into real "
    "recommendations."
)


def _empty(as_of: date | None, watchlist: list[str], top_n: int) -> dict[str, Any]:
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "watchlist": watchlist,
        "top_n": top_n,
        "rule": RULE.format(top_n=top_n),
        "tested": False,
        "how_to_test": HOW_TO_TEST,
        "rows": [],
    }


def scan_closes(closes: pd.DataFrame, top_n: int) -> list[dict[str, Any]]:
    """Rank the last row of `closes`; pure, so tests can check it without a broker."""
    momentum = (closes.shift(SKIP) / closes.shift(LOOKBACK) - 1).iloc[-1]
    average = closes.rolling(TREND, min_periods=TREND).mean().iloc[-1]
    high = closes.rolling(LOOKBACK, min_periods=TREND).max().iloc[-1]
    last = closes.iloc[-1]
    ranked = momentum.dropna().sort_values(ascending=False)
    ranks = {symbol: i + 1 for i, symbol in enumerate(ranked.index)}

    rows: list[dict[str, Any]] = []
    for symbol in closes.columns:
        price, value, mean, top = last[symbol], momentum[symbol], average[symbol], high[symbol]
        if any(pd.isna(x) for x in (price, value, mean, top)):
            rows.append(
                {
                    "symbol": symbol,
                    "rank": None,
                    "label": "no_data",
                    "close": None if pd.isna(price) else float(price),
                    "reason": "Not enough history yet: the scan needs about a year of closes.",
                }
            )
            continue
        rank = ranks[symbol]
        if value > 0 and rank <= top_n:
            label = "buy_idea"
        elif value > 0:
            label = "watch"
        else:
            label = "skip"
        trend_gap = float(price / mean - 1)
        from_high = float(price / top - 1)
        high_text = (
            "at its 52-week high" if from_high >= -0.0005 else f"{abs(from_high):.1%} below its 52-week high"
        )
        rows.append(
            {
                "symbol": symbol,
                "rank": rank,
                "label": label,
                "close": float(price),
                "momentum": float(value),
                "trend_gap": trend_gap,
                "from_high": from_high,
                "reason": (
                    f"Return over the 12 months before the latest month: {signed_pct(float(value))}, "
                    f"{ordinal(rank)} of {len(ranked)}. Closed {abs(trend_gap):.1%} "
                    f"{'above' if trend_gap > 0 else 'below'} its 200-day average and {high_text}."
                ),
            }
        )
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))
    return rows


def run_scan(ctx: AppContext, end: date | None = None) -> dict[str, Any]:
    settings = ctx.settings
    watchlist = settings.watchlist_list
    top_n = settings.scan_top_n
    end = end or ctx.today()
    if not watchlist:
        result = _empty(None, [], top_n)
    else:
        start = end - timedelta(days=int((LOOKBACK + 1) * 1.5) + 45)
        closes = ctx.bars.get_closes(watchlist, start, end)
        closes = closes[[s for s in watchlist if s in closes.columns]]
        if closes.empty:
            result = _empty(None, watchlist, top_n)
        else:
            result = _empty(closes.index[-1].date(), watchlist, top_n)
            rows = scan_closes(closes, top_n)
            limits = ctx.limits
            equity = ctx.broker.get_account().equity
            rules = ctx.rules
            held = {p.symbol for p in ctx.broker.get_positions() if not rules.is_dust(p.symbol, p.qty)}
            size = limits.max_entry_fraction() * equity
            for row in rows:
                row["held"] = row["symbol"] in held
                if row["close"] is None or row["label"] == "no_data":
                    continue
                symbol = row["symbol"]
                entry = rules.price_up(symbol, row["close"] * (1 + limits.entry_limit_buffer_pct / 100))
                stop = (
                    rules.price_up(symbol, entry * (1 - limits.stop_loss_pct / 100))
                    if limits.stop_loss_pct > 0
                    else None
                )
                qty = rules.floor_qty(symbol, size / entry) if entry > 0 else 0
                row |= {
                    "entry": entry,
                    "stop": stop,
                    "qty": qty,
                    "risk_dollars": qty * (entry - stop) if stop is not None else None,
                }
            result["rows"] = rows
    with ctx.session() as session:
        ledger.set_state(session, SCAN_KEY, result)
        ledger.set_state(session, "last_scan_run", {"at": ctx.now().isoformat(), "as_of": result["as_of"]})
    return result


def latest_scan(ctx: AppContext) -> dict[str, Any]:
    with ctx.session() as session:
        saved = ledger.get_state(session, SCAN_KEY)
    return saved or _empty(None, ctx.settings.watchlist_list, ctx.settings.scan_top_n)

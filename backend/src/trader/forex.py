"""Forex market hours and OANDA's instrument names.

Retail forex runs from Sunday 5 pm to Friday 5 pm New York time, around the clock in between.
Each trading day ends at 5 pm New York: OANDA's daily candles close then, overnight financing is
booked then, and spreads widen for a few minutes around it. So the forex book labels a day by
the date of its 5 pm close: the candle that opens Sunday evening is Monday's.

Holidays such as Christmas and New Year's Day are not in this schedule; the OANDA adapter also
asks OANDA whether prices are tradeable before it calls the market open.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from trader.models import MarketClock
from trader.utils import NY, as_utc

DAY_ENDS = time(17, 0)  # New York
SUNDAY, FRIDAY, SATURDAY = 6, 4, 5
# Orders wait while spreads are wide around the daily close.
ROLLOVER_START, ROLLOVER_END = time(16, 45), time(17, 15)


def instrument(symbol: str) -> str:
    """EUR/USD -> EUR_USD, the way OANDA names it."""
    return symbol.upper().replace("/", "_")


def symbol_of(name: str) -> str:
    """EUR_USD -> EUR/USD."""
    return name.upper().replace("_", "/")


def _local(moment: datetime) -> datetime:
    utc = as_utc(moment)
    assert utc is not None
    return utc.astimezone(NY)


def is_open(moment: datetime) -> bool:
    local = _local(moment)
    weekday, clock = local.weekday(), local.time()
    if weekday == SATURDAY:
        return False
    if weekday == SUNDAY:
        return clock >= DAY_ENDS
    if weekday == FRIDAY:
        return clock < DAY_ENDS
    return True


def _next(local: datetime, weekday: int) -> datetime:
    """The next 5 pm New York on a given weekday, strictly after `local`."""
    day = local.date() + timedelta(days=(weekday - local.weekday()) % 7)
    candidate = datetime.combine(day, DAY_ENDS, tzinfo=NY)
    if candidate <= local:
        candidate = datetime.combine(day + timedelta(days=7), DAY_ENDS, tzinfo=NY)
    return candidate


def clock(moment: datetime) -> MarketClock:
    local = _local(moment)
    return MarketClock(
        timestamp=as_utc(moment),  # type: ignore[arg-type]
        is_open=is_open(moment),
        next_open=_next(local, SUNDAY),
        next_close=_next(local, FRIDAY),
    )


def bar_date(moment: datetime) -> date:
    """The day of the newest finished daily bar: today after 5 pm New York, else the day before,
    never a weekend (the session that opens Sunday evening belongs to Monday)."""
    local = _local(moment)
    day = local.date() if local.time() >= DAY_ENDS else local.date() - timedelta(days=1)
    while day.weekday() >= SATURDAY:
        day -= timedelta(days=1)
    return day


def in_rollover(moment: datetime) -> bool:
    clock_time = _local(moment).time()
    return ROLLOVER_START <= clock_time < ROLLOVER_END

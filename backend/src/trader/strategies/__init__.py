from trader.strategies.base import Strategy
from trader.strategies.momentum import Momentum
from trader.strategies.spy_trend import SpyTrend
from trader.strategies.trend import TrendFollowing
from trader.strategies.trend_bil import TrendWithBills

STRATEGIES: dict[str, type[Strategy]] = {
    TrendFollowing.name: TrendFollowing,
    Momentum.name: Momentum,
    TrendWithBills.name: TrendWithBills,
    SpyTrend.name: SpyTrend,
}


def get_strategy(name: str, shorts: bool = False) -> Strategy:
    """The named strategy. shorts=True (forex short selling) works with the trend rule only."""
    try:
        kind = STRATEGIES[name]
    except KeyError:
        known = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"Unknown strategy {name!r}. Choose one of: {known}.") from None
    if not shorts:
        return kind()
    if kind is not TrendFollowing:
        raise ValueError(f"The {name} strategy only buys; short selling works with STRATEGY=trend.")
    return TrendFollowing(shorts=True)


__all__ = [
    "STRATEGIES",
    "Momentum",
    "SpyTrend",
    "Strategy",
    "TrendFollowing",
    "TrendWithBills",
    "get_strategy",
]

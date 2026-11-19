"""Strategy interface. A strategy is a pure function of past closes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class CashPark:
    """Idle cash parked in one fund. Only a strategy that opts in uses this.

    Cash beyond `buffer` (a share of the account) is the target. The holding is resized when it
    drifts `band` (a share of the account) off that target. A drift of exactly `band` stays put.
    """

    symbol: str
    buffer: float = 0.02
    band: float = 0.05


class Strategy(ABC):
    name: str = "base"
    lesson: str = "reading-a-recommendation"  # the Learn lesson that explains this strategy

    @property
    @abstractmethod
    def lookback_days(self) -> int:
        """Trading days of history needed before the first valid signal."""

    @abstractmethod
    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        """Target portfolio weights, one row per day and one column per symbol.

        Row t may only use closes up to and including t (decided after that close).
        Weights are in [-1, 1], below zero for a short (forex only, when short selling is on),
        and each row's absolute weights sum to at most 1; the rest is cash.
        """

    @abstractmethod
    def params(self) -> dict[str, Any]:
        """The parameters that define this instance."""

    @abstractmethod
    def variants(self) -> list[Strategy]:
        """The same strategy with its parameters moved about 20% each way (Gate 1 robustness)."""

    def rule_text(self) -> str:
        """One sentence, in plain words, on what the strategy holds."""
        return f"{type(self).__name__} with {self.params()}."

    def explain(self, closes: pd.DataFrame) -> dict[str, str]:
        """Why each symbol is in or out as of the last row of `closes`, in plain words."""
        weights = self.target_weights(closes)
        if weights.empty:
            return {}
        last = weights.iloc[-1]
        return {
            symbol: f"Target {float(last[symbol]):.0%} of equity." if last[symbol] != 0 else "Target 0%."
            for symbol in closes.columns
        }

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, **self.params()}

    def cash_park(self) -> CashPark | None:
        """The idle-cash fund, or None when this strategy leaves spare cash as cash."""
        return None

    def extra_symbols(self) -> tuple[str, ...]:
        """Symbols to price besides the traded universe, such as the cash fund."""
        park = self.cash_park()
        return (park.symbol,) if park is not None else ()

    def traded_universe(self, universe: Sequence[str]) -> list[str]:
        """`universe`, plus symbols this strategy holds that the list leaves out.

        A cash-park symbol is not added. It is cash, not one of the signals.
        """
        park = self.cash_park()
        skip = park.symbol if park is not None else None
        extra = [symbol for symbol in self.extra_symbols() if symbol != skip]
        return list(dict.fromkeys([*universe, *extra]))

    def position_cap(self) -> float | None:
        """Largest share of equity one new position may take, or None for the account's cap.

        None keeps the 10% position cap and the per-trade risk limit. A strategy that puts the
        whole account in one name returns 1.0.
        """
        return None

    def uses_stops(self) -> bool:
        """False when this strategy's own rule is the only exit, so entries carry no stop."""
        return True

    def history_days(self) -> int:
        """Calendar days of history the live pipeline fetches so its signals match the backtest."""
        return int(self.lookback_days * 1.5) + 45

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={v}" for k, v in self.params().items())
        return f"{type(self).__name__}({args})"

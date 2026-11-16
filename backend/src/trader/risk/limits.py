"""Risk limits shared by the planner, the risk engine and the backtester."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trader.config import Settings


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade_pct: float = 1.0
    stop_loss_pct: float = 8.0
    max_position_pct: float = 10.0
    max_open_positions: int = 8
    daily_loss_limit_pct: float = 2.0
    max_drawdown_pct: float = 10.0
    max_orders_per_day: int = 10
    no_trade_after_open_min: int = 15
    no_trade_before_close_min: int = 15
    entry_limit_buffer_pct: float = 0.2
    stop_limit_band_pct: float = 0.0  # crypto: the stop-limit's limit sits this far below the stop
    allow_shorts: bool = False  # forex only, and only once you switch it on

    @classmethod
    def from_settings(cls, settings: Settings) -> RiskLimits:
        return cls(
            risk_per_trade_pct=settings.risk_per_trade_pct,
            stop_loss_pct=settings.stop_loss_pct,
            max_position_pct=settings.max_position_pct,
            max_open_positions=settings.max_open_positions,
            daily_loss_limit_pct=settings.daily_loss_limit_pct,
            max_drawdown_pct=settings.max_drawdown_pct,
            max_orders_per_day=settings.max_orders_per_day,
            no_trade_after_open_min=settings.no_trade_after_open_min,
            no_trade_before_close_min=settings.no_trade_before_close_min,
            entry_limit_buffer_pct=settings.entry_limit_buffer_pct,
            stop_limit_band_pct=settings.stop_limit_band_pct,
            allow_shorts=settings.allow_shorts,
        )

    def worst_exit_loss(self) -> float:
        """Share of the entry price lost if the stop fills at its worst allowed price.

        Stocks use stop orders, so that is the stop distance itself. Crypto uses stop-limit
        orders, which fill no lower than their limit, so the band adds to it.
        """
        stop = self.stop_loss_pct / 100
        band = self.stop_limit_band_pct / 100
        if band <= 0:
            return stop
        return 1 - (1 - stop) * (1 - band)

    def stop_limit_price(self, stop_price: float) -> float:
        """The lowest price a crypto stop-limit may sell at (before rounding to the price step)."""
        return stop_price * (1 - self.stop_limit_band_pct / 100)

    def worst_exit_price(self, stop_price: float, short: bool = False) -> float:
        """The worst price the stop may close the position at: the stop itself, or for a
        stop-limit its limit (below the stop for a long, above it for a short)."""
        band = self.stop_limit_band_pct / 100
        if band <= 0:
            return stop_price
        return stop_price * (1 + band) if short else stop_price * (1 - band)

    def max_entry_fraction(self) -> float:
        """Largest share of equity a single new position may take.

        Two caps apply: the position-size limit, and the size at which hitting the stop
        (at its worst allowed price) would lose exactly risk_per_trade_pct of equity.
        """
        cap = self.max_position_pct / 100
        if self.stop_limit_band_pct <= 0:
            if self.stop_loss_pct > 0:
                cap = min(cap, self.risk_per_trade_pct / self.stop_loss_pct)
            return cap
        loss = self.worst_exit_loss()
        if loss > 0:
            cap = min(cap, self.risk_per_trade_pct / 100 / loss)
        return cap

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"max_entry_fraction": self.max_entry_fraction()}

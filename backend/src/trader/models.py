"""Domain objects shared by the strategy, risk, broker and service layers."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from trader import money


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class IntentKind(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


def action_of(side: str, kind: str) -> str:
    """What an order does, in one word: buy, sell, or for a forex short, short and cover."""
    if kind == IntentKind.ENTRY:
        return "short" if side == Side.SELL else "buy"
    return "cover" if side == Side.BUY else "sell"


class ProposalStatus(StrEnum):
    PENDING = "pending"  # waiting for your approval
    APPROVED = "approved"  # approved, waiting for the morning submission
    REJECTED = "rejected"  # you said no
    BLOCKED = "blocked"  # failed a risk check or an AI veto
    SUBMITTED = "submitted"  # sent to the broker
    FILLED = "filled"
    CANCELED = "canceled"  # canceled, expired or rejected at the broker
    EXPIRED = "expired"  # never submitted in time
    DRY_RUN = "dry_run"  # passed every check, but DRY_RUN=true kept it from the broker
    ERROR = "error"


OPEN_PROPOSAL_STATUSES = {ProposalStatus.PENDING, ProposalStatus.APPROVED}

OPEN_ORDER_STATUSES = {
    "new",
    "accepted",
    "pending_new",
    "partially_filled",
    "held",
    "accepted_for_bidding",
    "pending_replace",
}


class Position(BaseModel):
    symbol: str
    qty: float  # below zero: a short (forex only)
    avg_entry_price: float
    current_price: float

    @property
    def is_short(self) -> bool:
        return self.qty < 0

    @property
    def market_value(self) -> float:
        """What the position is worth in dollars (see trader.money): qty x price for a long."""
        return money.value(self.symbol, self.qty, self.avg_entry_price, self.current_price)

    @property
    def cost_basis(self) -> float:
        """The dollars set aside when it opened."""
        return money.notional(self.symbol, self.qty, self.avg_entry_price)

    @property
    def exposure(self) -> float:
        """Its dollar size at today's price, long or short."""
        return money.notional(self.symbol, self.qty, self.current_price)

    @property
    def unrealized_pl(self) -> float:
        return money.pnl(self.symbol, self.qty, self.avg_entry_price, self.current_price)


class AccountInfo(BaseModel):
    equity: float
    cash: float
    buying_power: float
    last_equity: float  # equity at the previous close


class AccountState(BaseModel):
    equity: float
    cash: float
    buying_power: float
    day_start_equity: float
    peak_equity: float
    positions: dict[str, Position] = Field(default_factory=dict)

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity * 100)

    @property
    def day_pnl_pct(self) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        return (self.equity - self.day_start_equity) / self.day_start_equity * 100

    def held_symbols(self) -> set[str]:
        return {symbol for symbol, position in self.positions.items() if position.qty != 0}


class OrderIntent(BaseModel):
    symbol: str
    side: Side
    kind: IntentKind
    qty: float  # whole shares for stocks, a slice of a coin for crypto, currency units for forex
    limit_price: float
    stop_price: float | None = None  # entries: below the limit for a buy, above it for a short
    source: str = "rules"  # rules | manual | ai (the risk engine always refuses ai)
    reason: str = ""
    client_order_id: str

    @property
    def notional(self) -> float:
        """The order's size in dollars at its limit price."""
        return money.notional(self.symbol, self.qty, self.limit_price)

    @property
    def is_short(self) -> bool:
        """True when the order opens a short (a sell entry) or closes one (a buy exit)."""
        return (self.side == Side.SELL) == (self.kind == IntentKind.ENTRY)

    @property
    def signed_qty(self) -> float:
        """The position this order opens or closes: below zero for a short."""
        return -self.qty if self.is_short else self.qty

    @property
    def action(self) -> str:
        """buy, sell, short or cover: what the order does, in one word."""
        return action_of(self.side, self.kind)


class BrokerOrder(BaseModel):
    id: str
    client_order_id: str
    symbol: str
    side: Side
    qty: float
    status: str
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    order_type: str = "limit"
    order_class: str = "simple"
    submitted_at: datetime | None = None
    parent_id: str | None = None

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_ORDER_STATUSES

    @property
    def is_protective_stop(self) -> bool:
        """A stop that closes a position: a sell stop under a long, a buy stop over a short."""
        return self.stop_price is not None

    def protects(self, position_qty: float) -> bool:
        if not self.is_protective_stop:
            return False
        return self.side == (Side.SELL if position_qty > 0 else Side.BUY)


class MarketClock(BaseModel):
    timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime
    session_open: datetime | None = None  # today's regular session, when today is a trading day
    session_close: datetime | None = None


class Violation(BaseModel):
    code: str
    message: str


class RiskDecision(BaseModel):
    approved: bool
    violations: list[Violation] = Field(default_factory=list)


AI_RATINGS = ("buy", "overweight", "hold", "underweight", "sell")


class AIDecision(BaseModel):
    symbol: str
    as_of: date
    rating: str = "no_opinion"  # one of AI_RATINGS, or no_opinion
    summary: str = ""
    model: str = ""
    cost_usd: float | None = None

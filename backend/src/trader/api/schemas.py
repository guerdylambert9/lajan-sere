"""Response and request models for the dashboard API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from trader.utils import as_utc


def _utc(value: Any) -> Any:
    return as_utc(value) if isinstance(value, datetime) else value


UTCDateTime = Annotated[datetime, BeforeValidator(_utc)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProposalOut(ORMModel):
    id: int
    created_at: UTCDateTime
    as_of: date
    symbol: str
    side: str
    kind: str
    qty: float
    est_price: float
    limit_price: float
    stop_price: float | None
    reason: str
    source: str
    status: str
    violations: list[dict[str, Any]]
    ai_rating: str | None
    ai_summary: str | None
    client_order_id: str
    decided_at: UTCDateTime | None
    decided_by: str | None
    submitted_at: UTCDateTime | None
    broker_order_id: str | None
    error: str | None


class OrderOut(ORMModel):
    id: int
    client_order_id: str
    broker_order_id: str | None
    proposal_id: int | None
    symbol: str
    side: str
    action: str | None = None  # buy, sell, short, cover, or stop_sell / stop_buy for a protective stop
    qty: float
    filled_qty: float
    filled_avg_price: float | None
    status: str
    order_class: str
    limit_price: float | None
    stop_price: float | None
    submitted_at: UTCDateTime | None
    updated_at: UTCDateTime


class SignalOut(ORMModel):
    id: int
    as_of: date
    strategy: str
    symbol: str
    target_weight: float
    price: float | None


class AIDecisionOut(ORMModel):
    id: int
    created_at: UTCDateTime
    as_of: date
    symbol: str
    rating: str
    summary: str
    model: str
    cost_usd: float | None


class ReconciliationOut(ORMModel):
    id: int
    ts: UTCDateTime
    ok: bool
    mismatches: list[dict[str, Any]]


class PositionOut(BaseModel):
    symbol: str
    side: str = "long"  # or short (forex, with short selling on): qty is then below zero
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_pl_pct: float
    weight_pct: float
    stop_price: float | None
    stop_limit_price: float | None = None  # crypto: the lowest price its stop-limit may sell at
    protected: bool


class EquityPoint(BaseModel):
    as_of: date
    equity: float
    benchmark: float | None


class PreferencesIn(BaseModel):
    """Only the fields you send change; null goes back to the settings file or the recommendation."""

    stop_loss_pct: float | None = None
    pair_set: str | None = None  # forex: standard or exotic
    allow_shorts: bool | None = None  # forex
    confirm: bool = False  # set after reading the warnings a riskier choice returns

    def changes(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.model_fields_set if name != "confirm"}


class KillSwitchIn(BaseModel):
    engage: bool
    reason: str = "Engaged from the dashboard"
    confirm: str | None = None


class LessonProgressIn(BaseModel):
    done: bool = True


class QuizResultIn(BaseModel):
    score: int = Field(ge=0)
    total: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def _score_fits(self) -> QuizResultIn:
        if self.score > self.total:
            raise ValueError("score can't be more than total")
        return self

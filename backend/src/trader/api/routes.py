"""Dashboard API. Everything except /health needs the bearer token when API_TOKEN is set."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from trader import __version__, ledger, preferences
from trader.api.schemas import (
    AIDecisionOut,
    EquityPoint,
    KillSwitchIn,
    LessonProgressIn,
    OrderOut,
    PositionOut,
    PreferencesIn,
    ProposalOut,
    QuizResultIn,
    ReconciliationOut,
    SignalOut,
)
from trader.db import ProposalRow
from trader.models import action_of
from trader.services import killswitch, learn
from trader.services.account import load_account_state
from trader.services.approvals import InvalidTransitionError, ProposalNotFoundError, decide_proposal
from trader.services.execution import submit_approved
from trader.services.pipeline import run_nightly
from trader.services.protect import protect
from trader.services.recommendations import build_recommendations
from trader.services.reconcile import reconcile
from trader.services.scanner import latest_scan, run_scan

if TYPE_CHECKING:
    from trader.services.context import AppContext

JOB_NAMES = ("nightly", "submit", "reconcile", "scan", "protect")


def book_id(ctx: AppContext) -> str:
    return str(ctx.settings.asset_class)


def describe_book(ctx: AppContext, path: str) -> dict[str, Any]:
    with ctx.session() as session:
        pending = len(ledger.list_proposals(session, ctx.label, status="pending", limit=500))
    return {
        "id": book_id(ctx),
        "label": book_id(ctx).capitalize(),
        "path": path,
        "account_label": ctx.label,
        "mode": ctx.settings.mode_label,
        "pending_proposals": pending,
    }


def build_router(
    ctx: AppContext,
    auth: AppContext | None = None,
    books: Callable[[], list[dict[str, Any]]] | None = None,
) -> APIRouter:
    """The dashboard API for one book. `auth` lends another book's token (a second book is
    never left open), and `books` lists every book this server runs."""

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = (auth or ctx).settings.api_token
        if not expected:
            return
        supplied = (authorization or "").encode()
        if not hmac.compare_digest(supplied, f"Bearer {expected}".encode()):
            raise HTTPException(status_code=401, detail="Missing or wrong API token.")

    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    api = APIRouter(dependencies=[Depends(require_token)])

    @api.get("/status")
    def status() -> dict[str, Any]:
        settings = ctx.settings
        account: dict[str, Any] | None = None
        clock: dict[str, Any] | None = None
        broker_error = None
        with ctx.session() as session:
            kill = killswitch.state(session)
            last_runs = {name: ledger.get_state(session, f"last_{name}_run") for name in JOB_NAMES}
            recent = ledger.recent_reconciliations(session, ctx.label, limit=1)
            pending = len(ledger.list_proposals(session, ctx.label, status="pending", limit=500))
            try:
                state = load_account_state(ctx, session)
                account = {
                    "equity": state.equity,
                    "cash": state.cash,
                    "buying_power": state.buying_power,
                    "day_pnl_pct": state.day_pnl_pct,
                    "drawdown_pct": state.drawdown_pct,
                    "peak_equity": state.peak_equity,
                    "open_positions": len(state.held_symbols()),
                }
                market = ctx.broker.clock()
                clock = {
                    "is_open": market.is_open,
                    "next_open": market.next_open,
                    "next_close": market.next_close,
                }
            except Exception as exc:  # show the dashboard even if the broker is unreachable
                broker_error = str(exc)
        return jsonable_encoder(
            {
                "mode": settings.mode_label,
                "book": book_id(ctx),
                "asset_class": str(settings.asset_class),
                "broker": str(settings.broker),
                "trading_mode": str(settings.trading_mode),
                "dry_run": settings.dry_run,
                "account_label": ctx.label,
                "strategy": ctx.strategy.describe(),
                "universe": settings.universe_list,
                "benchmark": settings.benchmark_symbol,
                "ai_mode": str(settings.ai_mode),
                "auto_approve": settings.auto_approve,
                "kill_switch": kill,
                "account": account,
                "clock": clock,
                "broker_error": broker_error,
                "pending_proposals": pending,
                "scheduler_running": ctx.scheduler_running,
                "last_runs": last_runs,
                "last_reconciliation": ReconciliationOut.model_validate(recent[0]).model_dump(mode="json")
                if recent
                else None,
            }
        )

    @api.get("/proposals", response_model=list[ProposalOut])
    def proposals(
        status: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 100
    ) -> list[ProposalOut]:
        with ctx.session() as session:
            return [
                ProposalOut.model_validate(row)
                for row in ledger.list_proposals(session, ctx.label, status, limit)
            ]

    def decide(proposal_id: int, approve: bool) -> ProposalOut:
        with ctx.session() as session:
            try:
                row = decide_proposal(
                    session, proposal_id, approve, by="dashboard", label=ctx.label, at=ctx.now()
                )
            except ProposalNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except InvalidTransitionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return ProposalOut.model_validate(row)

    @api.post("/proposals/{proposal_id}/approve", response_model=ProposalOut)
    def approve(proposal_id: int) -> ProposalOut:
        return decide(proposal_id, True)

    @api.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
    def reject(proposal_id: int) -> ProposalOut:
        return decide(proposal_id, False)

    @api.get("/positions", response_model=list[PositionOut])
    def positions() -> list[PositionOut]:
        held = ctx.broker.get_positions()
        if ctx.is_crypto:
            held = [p for p in held if not ctx.rules.is_dust(p.symbol, p.qty)]
        open_orders = ctx.broker.get_open_orders()
        equity = ctx.broker.get_account().equity
        out = []
        for position in held:
            # A long's stop is a sell below it; a forex short's is a buy above it.
            stop = next(
                (o for o in open_orders if o.symbol == position.symbol and o.protects(position.qty)), None
            )
            cost = position.cost_basis
            out.append(
                PositionOut(
                    symbol=position.symbol,
                    side="short" if position.is_short else "long",
                    qty=position.qty,
                    avg_entry_price=position.avg_entry_price,
                    current_price=position.current_price,
                    market_value=position.market_value,
                    unrealized_pl=position.unrealized_pl,
                    unrealized_pl_pct=position.unrealized_pl / cost * 100 if cost else 0.0,
                    weight_pct=position.exposure / equity * 100 if equity else 0.0,
                    stop_price=stop.stop_price if stop else None,
                    stop_limit_price=stop.limit_price if stop and stop.order_type == "stop_limit" else None,
                    protected=stop is not None,
                )
            )
        return out

    @api.get("/orders", response_model=list[OrderOut])
    def orders(limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[OrderOut]:
        with ctx.session() as session:
            rows = ledger.recent_orders(session, ctx.label, limit)
            ids = [row.proposal_id for row in rows if row.proposal_id is not None]
            found = session.execute(select(ProposalRow.id, ProposalRow.kind).where(ProposalRow.id.in_(ids)))
            kinds = {proposal_id: kind for proposal_id, kind in found.all()}
            out = []
            for row in rows:
                kind = kinds.get(row.proposal_id) if row.proposal_id is not None else None
                if kind is not None:  # an entry or an exit the app planned
                    action = action_of(row.side, kind)
                else:  # a stop working under (or over) a position
                    action = f"stop_{row.side}" if row.stop_price is not None else row.side
                out.append(OrderOut.model_validate(row).model_copy(update={"action": action}))
            return out

    @api.get("/signals", response_model=list[SignalOut])
    def signals() -> list[SignalOut]:
        with ctx.session() as session:
            return [SignalOut.model_validate(row) for row in ledger.latest_signals(session, ctx.label)]

    @api.get("/equity", response_model=list[EquityPoint])
    def equity() -> list[EquityPoint]:
        with ctx.session() as session:
            rows = ledger.equity_history(session, ctx.label)
        base = next((row for row in rows if row.benchmark_price), None)
        scale = base.equity / base.benchmark_price if base and base.benchmark_price else None
        return [
            EquityPoint(
                as_of=row.as_of,
                equity=row.equity,
                benchmark=row.benchmark_price * scale if scale and row.benchmark_price else None,
            )
            for row in rows
        ]

    @api.get("/risk")
    def risk() -> dict[str, Any]:
        settings = ctx.settings
        usage: dict[str, Any] = {}
        with ctx.session() as session:
            usage["orders_today"] = ledger.orders_submitted_on(session, ctx.today(), ctx.tz, ctx.label)
            try:
                state = load_account_state(ctx, session)
                usage |= {
                    "open_positions": len(state.held_symbols()),
                    "drawdown_pct": state.drawdown_pct,
                    "day_pnl_pct": state.day_pnl_pct,
                }
            except Exception:
                usage |= {"open_positions": None, "drawdown_pct": None, "day_pnl_pct": None}
        return {
            "limits": ctx.limits.as_dict(),
            "usage": usage,
            "max_gap_pct": settings.max_gap_pct,
            "auto_approve": settings.auto_approve,
        }

    @api.get("/ai-decisions", response_model=list[AIDecisionOut])
    def ai_decisions(limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[AIDecisionOut]:
        with ctx.session() as session:
            return [
                AIDecisionOut.model_validate(row)
                for row in ledger.recent_ai_decisions(session, ctx.label, limit)
            ]

    @api.get("/reconciliations", response_model=list[ReconciliationOut])
    def reconciliations(limit: Annotated[int, Query(ge=1, le=100)] = 10) -> list[ReconciliationOut]:
        with ctx.session() as session:
            return [
                ReconciliationOut.model_validate(row)
                for row in ledger.recent_reconciliations(session, ctx.label, limit)
            ]

    @api.post("/kill-switch")
    def kill_switch(body: KillSwitchIn) -> dict[str, Any]:
        with ctx.session() as session:
            if body.engage:
                killswitch.engage(ctx, session, body.reason or "Engaged from the dashboard", by="dashboard")
            else:
                if (body.confirm or "").strip().upper() != "RELEASE":
                    raise HTTPException(status_code=400, detail="Type RELEASE to confirm.")
                killswitch.release(ctx, session, by="dashboard")
            return killswitch.state(session)

    @api.get("/preferences")
    def get_preferences() -> dict[str, Any]:
        return jsonable_encoder(preferences.view(ctx))

    @api.put("/preferences")
    def put_preferences(body: PreferencesIn) -> dict[str, Any]:
        """Change the stop-loss (and for forex the pair set and short selling). A riskier choice
        answers 409 with its warnings until it comes back with confirm=true."""
        result = preferences.update(ctx, body.changes(), confirm=body.confirm)
        payload = jsonable_encoder(asdict(result))
        if result.status == "invalid":
            raise HTTPException(status_code=400, detail=result.message)
        if result.status in ("needs_confirm", "blocked"):
            raise HTTPException(status_code=409, detail=payload)
        return payload | {"preferences": jsonable_encoder(preferences.view(ctx))}

    @api.get("/recommendations")
    def recommendations() -> dict[str, Any]:
        with ctx.session() as session:
            return jsonable_encoder(build_recommendations(ctx, session))

    @api.get("/scan")
    def scan() -> dict[str, Any]:
        return jsonable_encoder(latest_scan(ctx))

    @api.get("/learn/progress")
    def learn_progress() -> dict[str, Any]:
        with ctx.session() as session:
            return learn.get_progress(session)

    @api.post("/learn/lessons/{lesson_id}")
    def lesson_done(lesson_id: str, body: LessonProgressIn) -> dict[str, Any]:
        if not learn.valid_id(lesson_id):
            raise HTTPException(status_code=400, detail="Unknown lesson id.")
        with ctx.session() as session:
            return learn.mark_lesson(session, lesson_id, body.done, ctx.now())

    @api.post("/learn/quizzes/{module_id}")
    def quiz_result(module_id: str, body: QuizResultIn) -> dict[str, Any]:
        if not learn.valid_id(module_id):
            raise HTTPException(status_code=400, detail="Unknown module id.")
        with ctx.session() as session:
            return learn.record_quiz(session, module_id, body.score, body.total, ctx.now())

    @api.post("/jobs/{name}")
    def run_job(name: str, force: bool = False) -> dict[str, Any]:
        if name == "nightly":
            result: Any = run_nightly(ctx, force=force)
        elif name == "submit":
            result = submit_approved(ctx)
        elif name == "reconcile":
            result = reconcile(ctx)
        elif name == "protect":
            result = protect(ctx)
        elif name == "scan":
            return {"job": name, "result": jsonable_encoder(run_scan(ctx))}
        else:
            raise HTTPException(
                status_code=404, detail="Unknown job. Use nightly, submit, reconcile, protect or scan."
            )
        return {"job": name, "result": jsonable_encoder(asdict(result))}

    @api.get("/books")
    def list_books() -> list[dict[str, Any]]:
        return books() if books else [describe_book(ctx, "/api")]

    router.include_router(api)
    return router

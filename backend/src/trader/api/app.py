"""FastAPI app: the dashboard API, plus the built dashboard itself when frontend/dist exists."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from trader import __version__
from trader.api.routes import build_router, describe_book
from trader.config import AssetClass
from trader.notify.telegram import TelegramNotifier, TelegramPoller
from trader.services.context import AppContext, build_context, extra_book_settings

log = logging.getLogger(__name__)


def create_app(
    ctx: AppContext | None = None,
    start_background: bool | None = None,
    crypto_ctx: AppContext | None = None,
    forex_ctx: AppContext | None = None,
) -> FastAPI:
    """The API for one book, plus a crypto book under /api/crypto and a forex book under
    /api/forex when given them.

    Each book keeps its own settings, broker, ledger and schedule; they share the API token
    and, when they use the same bot, one Telegram listener.
    """
    if ctx is None:
        ctx = build_context()
        extra = extra_book_settings(ctx.settings)
        if crypto_ctx is None and AssetClass.CRYPTO in extra:
            crypto_ctx = build_context(extra[AssetClass.CRYPTO])
        if forex_ctx is None and AssetClass.FOREX in extra:
            forex_ctx = build_context(extra[AssetClass.FOREX])
    mounted = [
        (book, f"/api/{book.settings.asset_class}") for book in (crypto_ctx, forex_ctx) if book is not None
    ]
    books = [ctx] + [book for book, _ in mounted]
    background = ctx.settings.enable_scheduler if start_background is None else start_background

    def list_books() -> list[dict[str, Any]]:
        return [describe_book(ctx, "/api")] + [describe_book(book, path) for book, path in mounted]

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        schedulers = []
        pollers: dict[str, TelegramPoller] = {}
        if background:
            from trader.scheduler import start_scheduler

            for book in books:
                schedulers.append(start_scheduler(book))
                book.scheduler_running = True
                if isinstance(book.notifier, TelegramNotifier):
                    poller = pollers.get(book.notifier.token)
                    if poller is None:
                        pollers[book.notifier.token] = TelegramPoller(book, book.notifier)
                    else:
                        poller.add_book(book)
            for poller in pollers.values():
                poller.start()
        yield
        for scheduler in schedulers:
            scheduler.shutdown(wait=False)
        for book in books:
            book.scheduler_running = False
        for poller in pollers.values():
            poller.stop()

    app = FastAPI(title="Lajan Sere API", version=__version__, lifespan=lifespan)
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ctx.settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_router(ctx, books=list_books), prefix="/api")
    for book, path in mounted:
        app.include_router(build_router(book, auth=ctx, books=list_books), prefix=path)

    dist = Path(ctx.settings.frontend_dist)
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    else:
        log.info("No built dashboard at %s; run `npm run build` in frontend/ to serve it here.", dist)
    return app

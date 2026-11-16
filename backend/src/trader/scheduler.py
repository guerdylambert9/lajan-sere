"""Background schedule.

Stocks (New York time, weekdays):
09:50  submit approved orders (after the first 15 minutes)
16:30  reconcile with the broker, record equity, cancel unfilled entries
17:15  nightly pipeline: signals, risk checks, proposals for your approval

Crypto (every day; Alpaca's crypto day ends at midnight Chicago time, 1:00 am in New York):
00:05 Chicago     reconcile and record the finished day's equity
00:15 Chicago     daily pipeline on the day that just ended
every 5 minutes   submit approved orders
every 5 minutes   protect: a stop-limit under each new position, stale orders canceled

Forex (New York time, weekdays; the forex day ends at 5 pm New York):
09:50  submit approved orders, while the London and New York sessions overlap
17:05  reconcile, record the day's equity, cancel entries and exits that didn't fill
17:15  nightly pipeline on the day that just closed
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from trader import ledger
from trader.utils import CT, NY

if TYPE_CHECKING:
    from trader.services.context import AppContext

log = logging.getLogger(__name__)

SCHEDULE = {
    "submit": (9, 50),
    "reconcile": (16, 30),
    "nightly": (17, 15),
}
CRYPTO_DAILY = {"reconcile": (0, 5), "nightly": (0, 15)}  # Chicago time
CRYPTO_EVERY_MINUTES = {"submit": 5, "protect": 5}
FOREX_SCHEDULE = {"submit": (9, 50), "reconcile": (17, 5), "nightly": (17, 15)}  # New York time


def guarded(ctx: AppContext, name: str, job: Callable[[], Any]) -> Callable[[], None]:
    def run() -> None:
        try:
            result = job()
            log.info("Job %s finished: %s", name, result)
        except Exception as exc:
            log.exception("Job %s failed", name)
            try:
                with ctx.session() as session:
                    ledger.audit(session, "job_failed", job=name, error=str(exc))
            finally:
                ctx.notify(f"[{ctx.settings.mode_label} {ctx.label}] Job '{name}' failed: {exc}")

    return run


def start_scheduler(ctx: AppContext) -> BackgroundScheduler:
    from trader.services.execution import submit_approved
    from trader.services.pipeline import run_nightly
    from trader.services.protect import protect
    from trader.services.reconcile import reconcile

    jobs: dict[str, Callable[[], Any]] = {
        "submit": lambda: submit_approved(ctx),
        "reconcile": lambda: reconcile(ctx),
        "nightly": lambda: run_nightly(ctx),
        "protect": lambda: protect(ctx),
    }
    scheduler = BackgroundScheduler(timezone=ctx.tz)
    options: dict[str, Any] = {"replace_existing": True, "coalesce": True, "misfire_grace_time": 1800}
    if ctx.is_crypto:
        for name, (hour, minute) in CRYPTO_DAILY.items():
            trigger = CronTrigger(hour=hour, minute=minute, timezone=CT)
            scheduler.add_job(guarded(ctx, name, jobs[name]), trigger, id=name, **options)
        for name, minutes in CRYPTO_EVERY_MINUTES.items():
            trigger = IntervalTrigger(minutes=minutes, timezone=ctx.tz)
            scheduler.add_job(
                guarded(ctx, name, jobs[name]), trigger, id=name, **options | {"misfire_grace_time": 120}
            )
        described = [f"{n} {h:02d}:{m:02d} Chicago" for n, (h, m) in CRYPTO_DAILY.items()]
        described += [f"{n} every {m} min" for n, m in CRYPTO_EVERY_MINUTES.items()]
    else:
        times, zone = (FOREX_SCHEDULE, NY) if ctx.is_forex else (SCHEDULE, ctx.tz)
        for name, (hour, minute) in times.items():
            trigger = CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=zone)
            scheduler.add_job(guarded(ctx, name, jobs[name]), trigger, id=name, **options)
        described = [f"{n} {h:02d}:{m:02d}" for n, (h, m) in times.items()]
    scheduler.start()
    log.info("Scheduler started for account %s: %s", ctx.label, ", ".join(described))
    return scheduler

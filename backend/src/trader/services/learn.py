"""Progress through the Learn section, kept in the ledger so it follows you across devices."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from trader import ledger

PROGRESS_KEY = "learn_progress"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def valid_id(value: str) -> bool:
    return bool(ID_PATTERN.match(value))


def get_progress(session: Session) -> dict[str, Any]:
    saved = ledger.get_state(session, PROGRESS_KEY) or {}
    return {"lessons": dict(saved.get("lessons", {})), "quizzes": dict(saved.get("quizzes", {}))}


def mark_lesson(session: Session, lesson_id: str, done: bool, at: datetime) -> dict[str, Any]:
    progress = get_progress(session)
    if done:
        progress["lessons"][lesson_id] = at.isoformat()
    else:
        progress["lessons"].pop(lesson_id, None)
    ledger.set_state(session, PROGRESS_KEY, progress)
    return progress


def record_quiz(session: Session, module_id: str, score: int, total: int, at: datetime) -> dict[str, Any]:
    progress = get_progress(session)
    best = progress["quizzes"].get(module_id, {}).get("best", 0)
    progress["quizzes"][module_id] = {
        "score": score,
        "total": total,
        "best": max(best, score),
        "at": at.isoformat(),
    }
    ledger.set_state(session, PROGRESS_KEY, progress)
    return progress

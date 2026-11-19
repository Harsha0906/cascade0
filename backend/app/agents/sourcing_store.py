"""
Durable Sourcing sessions (table `sourcing_sessions`) with optimistic concurrency.

Each row carries a `version`. A save only succeeds if the stored version still equals the
version the session was loaded at (compare-and-set); otherwise ConcurrentUpdateError, and the
caller reloads and re-applies. This keeps sessions correct across restarts and workers.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from app import db

if TYPE_CHECKING:  # sourcing imports this module; resolved lazily at call time
    from app.agents.sourcing import SourcingSession

_TABLE = "sourcing_sessions"
_lock = threading.Lock()


class ConcurrentUpdateError(RuntimeError):
    """The stored session changed since it was loaded."""


def _from_row(row: dict) -> "SourcingSession":
    from app.agents.sourcing import SourcingSession

    session = SourcingSession.from_dict(row["payload"])
    session.version = int(row["version"])
    return session


def load(run_id: str) -> Optional["SourcingSession"]:
    row = db.fetch_by_id(_TABLE, "run_id", run_id)
    return _from_row(row) if row else None


def save(session: "SourcingSession") -> None:
    next_version = session.version + 1
    payload = session.to_dict()
    payload["version"] = next_version
    payload = json.loads(json.dumps(payload))
    row = {
        "run_id": session.run_id,
        "status": session.status,
        "version": next_version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    with _lock:
        if session.version == 0:
            if db.fetch_by_id(_TABLE, "run_id", session.run_id) is not None:
                raise ConcurrentUpdateError(session.run_id)
            db.insert_row(_TABLE, row)
        else:
            updates = {k: v for k, v in row.items() if k != "run_id"}
            updated = db.update_rows_where(
                _TABLE, {"run_id": session.run_id, "version": session.version}, updates)
            if not updated:
                raise ConcurrentUpdateError(session.run_id)
    session.version = next_version


def active() -> List["SourcingSession"]:
    """ACTIVE sessions, most recently updated first."""
    rows = [r for r in db.fetch_all(_TABLE) if r.get("status") == "ACTIVE"]
    rows.reverse()  # ties: later-inserted first
    rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return [_from_row(r) for r in rows]

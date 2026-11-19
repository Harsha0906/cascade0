"""
Durable store of pipeline runs (table `analysis_runs`).

Execution must use the plan the server computed, never numbers echoed back by a client,
so /execute-plan looks the playbook up here by run_id. Runs live in the database (offline
mode: the in-memory mirror), so they survive restarts and multiple workers. Execution receipts: db.get_receipt.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app import db
from app.factory_model import FactoryModel

_TABLE = "analysis_runs"


def save_run(result: Dict[str, Any]) -> None:
    payload = dict(result)
    model = payload.get("factory_model")
    if isinstance(model, FactoryModel):
        payload["factory_model"] = model.to_dict()
    try:
        payload = json.loads(json.dumps(payload))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"run payload is not JSON-serialisable: {exc}") from exc
    db.upsert_row(_TABLE, {
        "run_id": result["run_id"],
        "parent_run_id": result.get("parent_run_id"),
        "factory_id": result.get("factory_id") or (model.factory_id if isinstance(model, FactoryModel) else None),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    })


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    row = db.fetch_by_id(_TABLE, "run_id", run_id)
    if row is None:
        return None
    payload = copy.deepcopy(row["payload"])
    if isinstance(payload.get("factory_model"), dict):
        payload["factory_model"] = FactoryModel.from_dict(payload["factory_model"])
    return payload


def latest_run_id() -> Optional[str]:
    rows = db.fetch_ordered(_TABLE, "created_at", desc=True, limit=1)
    return rows[0]["run_id"] if rows else None

"""
In-process store of recent pipeline runs.

Execution must use the plan the server computed, never numbers echoed back by a client,
so /execute-plan looks the playbook up here by run_id. Each run can be executed at most
once (idempotency): a repeat request returns the original receipt.

Limitation: this lives in memory, so runs are lost on restart and it does not work across
multiple worker processes. Persist runs in the database before scaling out.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

_MAX_RUNS = 100
_lock = threading.Lock()
_runs: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_receipts: Dict[str, Dict[str, Any]] = {}
_latest_run_id: Optional[str] = None


def save_run(result: Dict[str, Any]) -> None:
    global _latest_run_id
    run_id = result["run_id"]
    with _lock:
        _runs[run_id] = result
        _runs.move_to_end(run_id)
        while len(_runs) > _MAX_RUNS:
            old, _ = _runs.popitem(last=False)
            _receipts.pop(old, None)
        _latest_run_id = run_id


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return _runs.get(run_id)


def latest_run_id() -> Optional[str]:
    with _lock:
        return _latest_run_id


def get_receipt(run_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return _receipts.get(run_id)


def claim_execution(run_id: str) -> bool:
    """Atomically mark a run as being executed. Returns False if already claimed."""
    with _lock:
        if run_id in _receipts:
            return False
        _receipts[run_id] = {"pending": True}
        return True


def store_receipt(run_id: str, receipt: Dict[str, Any]) -> None:
    with _lock:
        _receipts[run_id] = receipt


def release_claim(run_id: str) -> None:
    with _lock:
        if _receipts.get(run_id, {}).get("pending"):
            _receipts.pop(run_id, None)


def clear() -> None:
    global _latest_run_id
    with _lock:
        _runs.clear()
        _receipts.clear()
        _latest_run_id = None

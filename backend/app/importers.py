"""
Pure CSV parsers for Tally / Excel exports (no database access).

Each parser returns an ImportResult: the valid rows plus row-level errors
({"line": n, "error": "..."}; line 1 is the header). Callers pass in the ids already
known to the system so unknown items, suppliers and orders are reported per row.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Collection

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_ETA_TIME = time(17, 0)  # a date alone means 17:00 IST

_ALIASES = {
    "item_code": ("item_code", "item code", "stock item code"),
    "item_name": ("item_name", "item name", "name of item"),
    "qty": ("on_hand_qty", "closing quantity", "quantity", "pending quantity", "qty"),
    "shipment_id": ("shipment_id", "po number", "voucher no"),
    "supplier_id": ("supplier_id", "supplier code", "party code"),
    "eta": ("eta", "due date", "due on"),
    "order_id": ("order_id", "order no", "sales order no"),
}


@dataclass
class ImportResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)  # new stock items (stock summary only)


def _norm(header: str) -> str:
    return re.sub(r"[\s_]+", " ", (header or "").strip().lower())


def _read(csv_text: str, wanted: dict[str, bool]):
    """Return ([(line, {field: value})], header errors). `wanted` maps field -> required."""
    reader = csv.reader(io.StringIO((csv_text or "").lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration:
        return [], [{"line": 1, "error": "empty file"}]
    index: dict[str, int] = {}
    for fld in wanted:
        names = [_norm(a) for a in _ALIASES[fld]]
        found = [(names.index(_norm(h)), i) for i, h in enumerate(header) if _norm(h) in names]
        if found:
            index[fld] = min(found)[1]  # the highest-priority alias present
    missing = [f for f, required in wanted.items() if required and f not in index]
    if missing:
        return [], [{"line": 1, "error": "missing column: " + "; ".join(
            f"{m} (one of: {', '.join(_ALIASES[m])})" for m in missing)}]
    rows = []
    for line_no, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        rows.append((line_no, {f: (cells[i].strip() if i < len(cells) else "") for f, i in index.items()}))
    return rows, []


_QTY_RE = re.compile(r"^(\d+|\d{1,3}(?:,\d{2,3})*,\d{3})(?:\s+[A-Za-z]+\.?)?$")


def parse_qty(raw: str, allow_zero: bool = False) -> int:
    text = (raw or "").strip()
    if not text:
        raise ValueError("quantity is empty")
    match = _QTY_RE.match(text)
    if not match:
        raise ValueError(f"invalid quantity {text!r}")
    qty = int(match.group(1).replace(",", ""))
    if qty == 0 and not allow_zero:
        raise ValueError("quantity must be greater than zero")
    return qty


_DATE_RE = re.compile(r"^(\S+)(?:\s+(\d{1,2}):(\d{2}))?$")
_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y")


def parse_eta(raw: str) -> datetime:
    """Parse a file date (IST) into an aware UTC datetime. A date alone means 17:00 IST."""
    text = (raw or "").strip()
    match = _DATE_RE.match(text)
    if not match:
        raise ValueError(f"invalid date {text!r}")
    day = None
    for fmt in _DATE_FORMATS:
        try:
            day = datetime.strptime(match.group(1), fmt).date()
            break
        except ValueError:
            continue
    if day is None:
        raise ValueError(f"invalid date {text!r}")
    if match.group(2) is None:
        clock = DEFAULT_ETA_TIME
    else:
        hour, minute = int(match.group(2)), int(match.group(3))
        if hour > 23 or minute > 59:
            raise ValueError(f"invalid time in date {text!r}")
        clock = time(hour, minute)
    return datetime.combine(day, clock, tzinfo=IST).astimezone(timezone.utc)


def _today_ist(today: date | datetime) -> date:
    if isinstance(today, datetime):
        return (today if today.tzinfo else today.replace(tzinfo=timezone.utc)).astimezone(IST).date()
    return today


def parse_stock_summary(csv_text: str, factory_id: str, known_items: Collection[str]) -> ImportResult:
    result = ImportResult()
    rows, header_errors = _read(csv_text, {"item_code": True, "qty": True, "item_name": False})
    result.errors.extend(header_errors)
    known, seen = set(known_items), set()
    for line, r in rows:
        code = r["item_code"]
        try:
            if not code:
                raise ValueError("missing item code")
            if code in seen:
                raise ValueError(f"duplicate item code {code}")
            qty = parse_qty(r["qty"], allow_zero=True)
            name = r.get("item_name", "")
            if code not in known and not name:
                raise ValueError(f"unknown item {code} (no item name given to create it)")
        except ValueError as exc:
            result.errors.append({"line": line, "error": str(exc)})
            continue
        seen.add(code)
        if code not in known:
            result.items.append({"factory_id": factory_id, "item_code": code, "name": name, "unit": "pcs"})
        result.rows.append({"factory_id": factory_id, "item_code": code, "on_hand_qty": qty})
    return result


def parse_open_purchase_orders(
    csv_text: str,
    factory_id: str,
    known_items: Collection[str],
    known_suppliers: Collection[str],
    today: date | datetime,
) -> ImportResult:
    result = ImportResult()
    rows, header_errors = _read(csv_text, {
        "shipment_id": True, "item_code": True, "supplier_id": True, "qty": True, "eta": True,
    })
    result.errors.extend(header_errors)
    items, suppliers, seen = set(known_items), set(known_suppliers), set()
    today_ist = _today_ist(today)
    for line, r in rows:
        try:
            sid, code, sup = r["shipment_id"], r["item_code"], r["supplier_id"]
            if not sid:
                raise ValueError("missing PO number")
            if sid in seen:
                raise ValueError(f"duplicate PO number {sid}")
            if code not in items:
                raise ValueError(f"unknown item {code or '(blank)'}")
            if sup not in suppliers:
                raise ValueError(f"unknown supplier {sup or '(blank)'}")
            qty = parse_qty(r["qty"])
            eta = parse_eta(r["eta"])
            if eta.astimezone(IST).date() < today_ist:
                raise ValueError(f"due date {r['eta']} is in the past")
        except ValueError as exc:
            result.errors.append({"line": line, "error": str(exc)})
            continue
        seen.add(sid)
        result.rows.append({
            "shipment_id": sid, "factory_id": factory_id, "item_code": code, "supplier_id": sup,
            "qty": qty, "eta": eta.isoformat(), "status": "OPEN",
        })
    return result


def parse_sales_order_lines(
    csv_text: str,
    known_orders: Collection[str],
    known_items: Collection[str],
) -> ImportResult:
    result = ImportResult()
    rows, header_errors = _read(csv_text, {"order_id": True, "item_code": True, "qty": True})
    result.errors.extend(header_errors)
    orders, items, seen = set(known_orders), set(known_items), set()
    for line, r in rows:
        try:
            oid, code = r["order_id"], r["item_code"]
            if oid not in orders:
                raise ValueError(f"unknown order {oid or '(blank)'}")
            if code not in items:
                raise ValueError(f"unknown item {code or '(blank)'}")
            if (oid, code) in seen:
                raise ValueError(f"duplicate line for order {oid} item {code}")
            qty = parse_qty(r["qty"])
        except ValueError as exc:
            result.errors.append({"line": line, "error": str(exc)})
            continue
        seen.add((oid, code))
        result.rows.append({"order_id": oid, "item_code": code, "qty": qty})
    return result

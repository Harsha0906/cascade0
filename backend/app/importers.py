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
from typing import Any, Collection, Mapping

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_ETA_TIME = time(17, 0)  # a date alone means 17:00 IST

_ALIASES = {
    "item_code": ("item_code", "item code", "stock item code"),
    "item_name": ("item_name", "item name", "name of item"),
    "unit": ("unit", "uom"),
    "shipment_id": ("shipment_id", "po number", "voucher no"),
    "supplier_id": ("supplier_id", "supplier code", "party code"),
    "eta": ("eta", "due date", "due on"),
    "order_id": ("order_id", "order no", "sales order no"),
}

# The quantity column depends on the file, in priority order: when a file has more than one,
# the first listed wins. A pending-PO export carries both the ordered Quantity and the Pending
# Quantity; only the pending part is still inbound. A stock summary's Closing Quantity is on hand.
_QTY_ALIASES = {
    "stock": ("on_hand_qty", "closing quantity", "quantity", "qty"),
    "po": ("pending quantity", "pending qty", "quantity", "qty"),
    "lines": ("qty", "quantity"),
}
DEFAULT_UNIT = "pcs"  # unit of an item created by a stock summary that has no Unit/UOM column


@dataclass
class ImportResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)  # new stock items (stock summary only)
    warnings: list[dict[str, Any]] = field(default_factory=list)  # {"line", "warning"}; rows still imported/skipped
    # Snapshot support: every key named by a data row (valid or not; total rows excluded), and
    # whether the header was readable. Callers remove/close only what the file does not mention,
    # and nothing at all when the header failed.
    mentioned: set = field(default_factory=set)
    header_ok: bool = True


def _norm(header: str) -> str:
    return re.sub(r"[\s_]+", " ", (header or "").strip().lower())


def normalize_header(header: str) -> str:
    """Lower-case, trimmed header with spaces turned into underscores ('Order No' -> 'order_no')."""
    return _norm(header).replace(" ", "_")


def _read(csv_text: str, wanted: dict[str, bool], qty_aliases: tuple = (),
          extra_aliases: Mapping[str, tuple] | None = None):
    """Return ([(line, {field: value})], header errors). `wanted` maps field -> required;
    `qty_aliases` are the accepted quantity headers for this file, in priority order."""
    aliases = {**_ALIASES, "qty": qty_aliases, **(extra_aliases or {})}
    reader = csv.reader(io.StringIO((csv_text or "").lstrip("\ufeff")))
    try:
        header = next(reader)
    except StopIteration:
        return [], [{"line": 1, "error": "empty file"}]
    index: dict[str, int] = {}
    for fld in wanted:
        names = [_norm(a) for a in aliases[fld]]
        found = [(names.index(_norm(h)), i) for i, h in enumerate(header) if _norm(h) in names]
        if found:
            index[fld] = min(found)[1]  # the highest-priority alias present
    missing = [f for f, required in wanted.items() if required and f not in index]
    if missing:
        return [], [{"line": 1, "error": "missing column: " + "; ".join(
            f"{m} (one of: {', '.join(aliases[m])})" for m in missing)}]
    rows = []
    for line_no, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        rows.append((line_no, {f: (cells[i].strip() if i < len(cells) else "") for f, i in index.items()}))
    return rows, []


_QTY_RE = re.compile(r"^(\d+|\d{1,3}(?:,\d{2,3})*,\d{3})(?:\.0+)?(?:\s+[A-Za-z]+\.?)?$")


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


_TOTAL_RE = re.compile(r"^(grand\s+)?total$", re.IGNORECASE)
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
    rows, header_errors = _read(csv_text, {"item_code": True, "qty": True, "item_name": False, "unit": False},
                                _QTY_ALIASES["stock"])
    result.errors.extend(header_errors)
    result.header_ok = not header_errors
    known, seen = set(known_items), set()
    for line, r in rows:
        code = r["item_code"]
        name_cell = r.get("item_name", "")
        if _TOTAL_RE.match(code) or _TOTAL_RE.match(name_cell):
            result.warnings.append({"line": line, "warning": "total row skipped (not imported)"})
            continue
        if code:
            result.mentioned.add(code)
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
            result.items.append({"factory_id": factory_id, "item_code": code, "name": name,
                                 "unit": r.get("unit") or DEFAULT_UNIT})
        result.rows.append({"factory_id": factory_id, "item_code": code, "on_hand_qty": qty})
    return result


def parse_open_purchase_orders(
    csv_text: str,
    factory_id: str,
    known_items: Collection[str],
    known_suppliers: Collection[str],
    today: date | datetime,
    existing_shipments: Mapping[str, Mapping[str, Any]] | None = None,
) -> ImportResult:
    result = ImportResult()
    rows, header_errors = _read(csv_text, {
        "shipment_id": True, "item_code": True, "supplier_id": True, "qty": True, "eta": True,
    }, _QTY_ALIASES["po"])
    result.errors.extend(header_errors)
    result.header_ok = not header_errors
    items, suppliers, seen = set(known_items), set(known_suppliers), set()
    today_ist = _today_ist(today)
    existing = existing_shipments or {}
    for line, r in rows:
        warnings: list[str] = []
        status = "OPEN"
        if r["shipment_id"]:
            result.mentioned.add(r["shipment_id"])
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
            due = eta.astimezone(IST).date()
            if due < today_ist:
                warnings.append(f"PO {sid} overdue since {due.isoformat()}")
            prior = existing.get(sid)
            if prior is not None:
                if prior.get("factory_id") != factory_id:
                    raise ValueError(f"PO number {sid} belongs to another factory")
                if prior.get("status", "OPEN") != "OPEN":
                    status = prior["status"]
                    warnings.append(f"PO {sid} is already {status}; status kept (not reopened)")
        except ValueError as exc:
            result.errors.append({"line": line, "error": str(exc)})
            continue
        seen.add(sid)
        result.warnings.extend({"line": line, "warning": w} for w in warnings)
        result.rows.append({
            "shipment_id": sid, "factory_id": factory_id, "item_code": code, "supplier_id": sup,
            "qty": qty, "eta": eta.isoformat(), "status": status,
        })
    return result


def parse_sales_order_lines(
    csv_text: str,
    known_orders: Collection[str],
    known_items: Collection[str],
) -> ImportResult:
    result = ImportResult()
    rows, header_errors = _read(csv_text, {"order_id": True, "item_code": True, "qty": True},
                                _QTY_ALIASES["lines"])
    result.errors.extend(header_errors)
    result.header_ok = not header_errors
    orders, items, seen = set(known_orders), set(known_items), set()
    for line, r in rows:
        if r["order_id"] in orders:
            result.mentioned.add((r["order_id"], r["item_code"]))
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


# ─── Setup data (Round S): suppliers and production lines ─────────────────────
# These parsers only read and type the cells; the API validates bounds and writes. A row's
# `_line` is its CSV line number (for the API's row-level errors).

_SUPPLIER_FIELDS = {
    "name": ("name", "supplier", "supplier name"),
    "sourcing_role": ("sourcing_role", "role", "sourcing role"),
    "unit_cost": ("unit_cost", "unit cost", "extra cost per unit"),
    "flat_cost": ("flat_cost", "flat cost", "flat charter cost"),
    "max_units": ("max_units", "max units", "max qty", "max available qty"),
    "lead_hours": ("lead_hours", "lead hours", "lead time hours"),
    "min_lead_hours": ("min_lead_hours", "min lead hours", "minimum lead hours"),
    "route": ("route",),
    "risk_profile": ("risk_profile", "risk profile", "risk"),
    "past_orders": ("past_orders", "past orders"),
    "on_time": ("on_time", "on time", "on time deliveries"),
    "telegram_chat_id": ("telegram_chat_id", "telegram chat id", "telegram"),
}
_SUPPLIER_REQUIRED = {"name", "sourcing_role", "max_units", "lead_hours", "route", "risk_profile"}
_SUPPLIER_NUMBERS = {"unit_cost", "flat_cost", "max_units", "lead_hours", "min_lead_hours", "past_orders", "on_time"}

_LINE_FIELDS = {
    "name": ("name", "line", "line name"),
    "rated_units_per_hour": ("rated_units_per_hour", "rated units per hour", "rated rate"),
    "ot_units_per_hour": ("ot_units_per_hour", "ot units per hour", "extra units per ot hour"),
    "ot_cost_per_hour": ("ot_cost_per_hour", "ot cost per hour", "overtime cost per hour"),
    "max_ot_hours": ("max_ot_hours", "max ot hours"),
}
_LINE_REQUIRED = {"name", "rated_units_per_hour"}
_LINE_NUMBERS = {"rated_units_per_hour", "ot_units_per_hour", "ot_cost_per_hour", "max_ot_hours"}


def _cell_number(raw: str, name: str) -> float:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be a finite number")
    return value


def _parse_table(csv_text: str, fields: dict, required: set, numbers: set) -> ImportResult:
    result = ImportResult()
    wanted = {f: f in required for f in fields}
    rows, header_errors = _read(csv_text, wanted, (), fields)
    result.errors.extend(header_errors)
    result.header_ok = not header_errors
    for line, r in rows:
        try:
            row: dict[str, Any] = {"_line": line}
            for name, raw in r.items():
                if raw == "":
                    if name in required:
                        raise ValueError(f"missing {name}")
                    continue
                row[name] = _cell_number(raw, name) if name in numbers else raw
        except ValueError as exc:
            result.errors.append({"line": line, "error": str(exc)})
            continue
        result.rows.append(row)
    return result


def parse_suppliers_csv(csv_text: str) -> ImportResult:
    """Supplier rows (required columns: name, sourcing_role, max_units, lead_hours, route,
    risk_profile). Numbers are read as numbers, text is kept as written."""
    return _parse_table(csv_text, _SUPPLIER_FIELDS, _SUPPLIER_REQUIRED, _SUPPLIER_NUMBERS)


def parse_lines_csv(csv_text: str) -> ImportResult:
    """Production line rows (required columns: name, rated_units_per_hour)."""
    return _parse_table(csv_text, _LINE_FIELDS, _LINE_REQUIRED, _LINE_NUMBERS)

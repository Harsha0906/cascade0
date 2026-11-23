"""
CascadeZero — Autonomous Agent Tools
Defines tools bound to the 4 LangGraph agents:
  1. extract_disruption_entities (Gemini structured extraction + regex fallback; reports which ran)
  2. query_blast_radius_sql (Supabase blast-radius calculation & state updates)
  3. run_pulp_milp_and_monte_carlo (Arbitrator PuLP MILP solver & Monte Carlo engine)
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence

from app.config import settings
from app.db import (
    fetch_all,
    get_all_orders,
    get_all_production_lines,
    get_all_suppliers,
    get_order,
    update_rows,
    upsert_row,
)
from app.schemas import DisruptionExtraction, LineImpactExtraction
from app.disruption import DisruptionResolutionError, ResolvedDisruption, resolve_reference
from app.factory_model import FactoryModel
from app.inventory import deadline_hours
from app.solver import generate_playbooks

logger = logging.getLogger("cascadezero.tools")


# ─── 1. Disruption Entity Extraction (Gemini Structured Outputs) ─────────────

def _single_char_tail(chunks: list[str]) -> str:
    """Join chunks; a final single LETTER must match as an uppercase letter (not 'la la', 'line a bit')."""
    esc = [re.escape(c) for c in chunks]
    if len(chunks[-1]) == 1 and chunks[-1].isalpha():
        esc[-1] = rf"(?-i:{re.escape(chunks[-1].upper())})"
    return esc


def _mention_pattern(ident: str) -> str:
    """Regex for an id like 'LINE-2' with flexible separators ('line 2', 'Line-2', 'line2')."""
    chunks = re.findall(r"[A-Za-z0-9]+", ident)
    body = r"[\s\-_]?".join(_single_char_tail(chunks))
    return rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"


def _name_pattern(name: str) -> str:
    words = [re.sub(r"[^A-Za-z0-9]", "", w) or w for w in name.split()]
    body = r"\s+".join(_single_char_tail(words))
    return rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"


_TEMP_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:°\s*c\b|deg(?:rees)?\b|celsius\b|c\b)", re.I)
_SPEED_CUE_RE = re.compile(
    r"\b(?:at|to)\s*(\d{1,3})\s*%(?!\s*of\b)|(\d{1,3})\s*%\s*(?:speed|capacity)\b", re.I)
# A whole number, with optional thousands separators: 1,200 and Indian 1,20,000 grouping.
_NUM = r"(\d{1,3}(?:,\d{2,3})+(?![\d,])|\d+)"
_HOURS = r"(?:h|hr|hrs|hours?)\b"
_DAYS = r"days?\b"


def _delay_cues(unit: str) -> tuple:
    return (
        re.compile(rf"{_NUM}\s*{unit}\s*(?:of\s+)?delay", re.I),
        re.compile(rf"(?:delay(?:ed)?|late)\s*(?:by|of|:)?\s*{_NUM}\s*{unit}", re.I),
        re.compile(rf"\+\s*{_NUM}\s*{unit}", re.I),
    )


_DELAY_CUE_RES = _delay_cues(_HOURS)
_DELAY_DAY_CUE_RES = _delay_cues(_DAYS)
_SHORT_CUE_RES = (
    re.compile(rf"\b(?:shortfall|deficit|missing)\s*(?:is|of|:)?\s*{_NUM}", re.I),
    re.compile(rf"\b{_NUM}\s*(?:[A-Za-z]+\s+){{0,3}}?(?:short|missing)\b", re.I),
    re.compile(rf"\bshort(?!fall)\s*(?:by|of)?\s*{_NUM}", re.I),
)
_SUPPLIER_DELAY_CUE_RE = re.compile(r"\b(?:delay(?:ed)?|late|blocked|stuck|held)\b", re.I)
# The alert says something is delayed, even when it gives no duration.
_DELAY_MENTION_RE = re.compile(r"\b(?:delay(?:s|ed)?|late|blocked|stuck|held\s+up)\b", re.I)
# "stuck at 50%" / "held at 50%" describe a line's speed, not a shipment delay.
_SPEED_AFTER_CUE_RE = re.compile(r"\s*(?:(?:at|to)\s*)?\d{1,3}\s*%", re.I)
# "no delays", "not delayed", "without delay", "never late": negated, not a delay.
_NEGATED_BEFORE_RE = re.compile(r"\b(?:no|not|without|never|zero)\s+(?:[A-Za-z]+\s+)?$", re.I)


def _mentions_delay(text: str) -> bool:
    for m in _DELAY_MENTION_RE.finditer(text):
        if _SPEED_AFTER_CUE_RE.match(text, m.end()):
            continue
        if _NEGATED_BEFORE_RE.search(text[max(0, m.start() - 30):m.start()]):
            continue
        return True
    return False


# A speed cue right after a line mention ("line a at 40%", "line a running at 40%").
_IMMEDIATE_SPEED_CUE_RE = re.compile(
    r"\s*(?:(?:is|was|now|running|down|dropped|slowed)\s+){0,2}(?:at|to)\s*\d{1,3}\s*%", re.I)
_LINE_MENTION_RE = re.compile(r"\bline[\s\-_]*([A-Za-z0-9]{1,6})\b", re.I)
_ORDER_MENTION_RE = re.compile(r"(?:\border\b\s*#?|#)\s*([A-Za-z]{1,6}-?\d{1,6})\b", re.I)
_ORDER_ON_RE = re.compile(r"\b(?:on|for)\s+([A-Za-z]{1,6}-\d{1,6})\b", re.I)
_SUPPLIER_MENTION_RE = re.compile(
    r"(?i:supplier|vendor)\s+([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*){0,3})")
_WINDOW_CHARS = 80
_SUPPLIER_CUE_CHARS = 60


_WEATHER_RE = re.compile(
    r"\b(?:flood(?:s|ed|ing)?|cyclone|heavy\s+rain(?:s|fall)?|storm|landslides?|waterlogg(?:ed|ing))\b", re.I)
# "flood of orders", "storm of complaints", "storm in a teacup": figurative, not weather.
_FIGURATIVE_AFTER_RE = re.compile(r"\s+(?:of|in\s+a)\b", re.I)


def _has_weather(text: str) -> bool:
    """A weather cue that is neither negated ("no flooding", "without storms") nor figurative."""
    for m in _WEATHER_RE.finditer(text or ""):
        if _FIGURATIVE_AFTER_RE.match(text, m.end()):
            continue
        if _NEGATED_BEFORE_RE.search(text[max(0, m.start() - 30):m.start()]):
            continue
        return True
    return False


# A route counts as blocked only with a block cue in its clause; "clear"/"open" cues say it is not.
_BLOCK_CUE_RE = re.compile(
    r"\b(?:block(?:ed|age)?|clos(?:ed|ure)|shut(?:\s+down)?|jam(?:med)?|flood(?:ed|ing)|submerged|"
    r"washed\s+out|landslide|accident|divert(?:ed|ion)|stuck)\b", re.I)
_CLEAR_CUE_RE = re.compile(r"\b(?:clear(?:ed)?|open(?:ed)?|reopen(?:ed)?|normal|moving|restored)\b", re.I)
_CLAUSE_BREAK_RE = re.compile(r"[;.!?\n]")


def _is_blocked_mention(text: str, start: int, end: int) -> bool:
    """The nearest cue (block or clear) in the mention's clause decides, preferring one that
    follows the mention; a negated block cue ("not blocked") does not block."""
    lo = max([m.end() for m in _CLAUSE_BREAK_RE.finditer(text, 0, start)] or [0])
    nxt = _CLAUSE_BREAK_RE.search(text, end)
    hi = nxt.start() if nxt else len(text)
    after = before = None   # nearest cue after / before the mention: (distance, kind)
    for kind, rx in (("block", _BLOCK_CUE_RE), ("clear", _CLEAR_CUE_RE)):
        for m in rx.finditer(text, lo, hi):
            k = kind
            if k == "block" and _NEGATED_BEFORE_RE.search(text[max(lo, m.start() - 30):m.start()]):
                k = "clear"
            if m.start() >= end:
                if after is None or m.start() - end < after[0]:
                    after = (m.start() - end, k)
            elif m.end() <= start:
                if before is None or start - m.end() < before[0]:
                    before = (start - m.end(), k)
    # A cue that follows the mention describes it ("NH48 is clear but Hosur corridor blocked");
    # one before it ("flooding on NH48") counts only when nothing follows.
    best = after or before
    return best is not None and best[1] == "block"


_ROUTE_NOUNS = r"corridor|highway|road|route|area|industrial|bypass|expressway|flyover|belt|zone|junction"
_UNKNOWN_NOUNS = "corridor|highway|road|route|bypass|expressway|flyover"
_ROUTE_STOP = {"area", "industrial", "corridor", "highway", "cargo", "road", "route", "air"}
# A road named in the alert that is not a known route ("Mysore Road", "NH44"): kept as written so the
# resolver can say it matched nothing. Generic openers ("The highway", "National Highway") are not names.
_UNKNOWN_ROUTE_RE = re.compile(
    rf"\b([A-Z][A-Za-z-]+(?:\s+[A-Z][A-Za-z-]+)?\s+(?i:{_UNKNOWN_NOUNS}))\b"
    r"|(?-i:\b((?:NH|SH|MDR|ORR)[\s-]?\d{1,3})\b)")
_GENERIC_ROUTE_WORDS = {"the", "a", "an", "this", "that", "our", "main", "key", "national", "state", "local"}


def _supplier_spans(text: str, model: FactoryModel) -> list:
    """Every span of the text that names a supplier (id or leading words of the name)."""
    spans = []
    for sid, name in list(model.primary_suppliers) + [(v.supplier_id, v.name) for v in model.vendors]:
        pats = [_mention_pattern(sid)]
        words = name.split(" (")[0].split()
        pats += [_name_pattern(" ".join(words[:n])) for n in range(len(words), 1, -1)]
        spans += [(m.start(), m.end()) for pat in pats for m in re.finditer(pat, text, re.I)]
    return spans


def _blocked_routes(text: str, model: FactoryModel) -> list:
    """Routes the alert names as blocked, as written, in order of mention: a known route's
    identifying word (NH48, Hosur corridor) first, else (only when no known route is named) a
    road-shaped name that matches no route, so resolution can note it. A word that is part of a
    supplier's name ("Hosur Precision Castings") is not a route, and neither is a route whose
    clause says it is clear or open."""
    spans = _supplier_spans(text, model)
    routes = {v.route for v in model.vendors} | {r for _, r in model.primary_routes}
    found = []
    for route in routes:
        for tok in re.findall(r"[A-Za-z0-9]+", route.split(" (")[0]):
            if len(tok) < 3 or tok.lower() in _ROUTE_STOP:
                continue
            tail = "" if any(c.isdigit() for c in tok) else rf"(?=\s+(?:{_ROUTE_NOUNS})\b)"
            for m in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(tok)}(?![A-Za-z0-9]){tail}", text, re.I):
                if not any(a <= m.start() and m.end() <= b for a, b in spans):
                    found.append((m.start(), m.end(), m.group(0)))
    if not found:
        for m in _UNKNOWN_ROUTE_RE.finditer(text):
            name = m.group(1) or m.group(2)
            if name.split()[0].lower() not in _GENERIC_ROUTE_WORDS:
                found.append((m.start(), m.end(), name))
    out: list = []
    for st, en, written in sorted(found):
        if _is_blocked_mention(text, st, en) and _norm_text(written) not in {_norm_text(x) for x in out}:
            out.append(written)
    return out


def _to_int(s: str) -> int:
    return int(s.replace(",", ""))


def _cue_values(regexes, text: str, scale: int = 1) -> set:
    return {_to_int(g) * scale for rx in regexes for m in rx.finditer(text) for g in m.groups() if g}


def _regex_extract(raw_text: str, model: FactoryModel, order_ids: Sequence[str]) -> DisruptionExtraction:
    text = raw_text

    # Delay: a number of hours/days bound to a delay cue; else the only hours/days number;
    # else unknown. A delay that is mentioned without a duration is reported as such.
    vals = _cue_values(_DELAY_CUE_RES, text) | _cue_values(_DELAY_DAY_CUE_RES, text, 24)
    if not vals:
        vals = ({_to_int(x) for x in re.findall(rf"{_NUM}\s*{_HOURS}", text, re.I)}
                | {_to_int(x) * 24 for x in re.findall(rf"{_NUM}\s*{_DAYS}", text, re.I)})
    delay_hours = next(iter(vals)) if len(vals) == 1 else None
    delay_mentioned = _mentions_delay(text)

    # Shortfall: a number bound to a shortfall cue; else the only units-count number; else unknown.
    vals = _cue_values(_SHORT_CUE_RES, text)
    if not vals:
        item_words = re.findall(r"[A-Za-z]+", model.stock_item_name or "")
        units = [r"battery\s+casings", r"casings", r"units", r"pcs", r"u\b"]
        if item_words:
            units.append(rf"{re.escape(item_words[-1])}s?\b")
        vals = {_to_int(x) for x in re.findall(rf"\b{_NUM}\s*(?:" + "|".join(units) + r")", text, re.I)}
    shortfall = next(iter(vals)) if len(vals) == 1 else None

    # Line mentions (id or full name), overlapping spans collapsed to the earliest/longest.
    spans = []
    for line in model.lines:
        for pat in (_mention_pattern(line.line_id), _name_pattern(line.name)):
            for mm in re.finditer(pat, text, re.I):
                spans.append((mm.start(), mm.end(), line.line_id))
            # A lowercase single-letter tail ("line a") counts only when a speed cue follows.
            loose = pat.replace("(?-i:", "(?:")
            if loose != pat:
                for mm in re.finditer(loose, text, re.I):
                    if _IMMEDIATE_SPEED_CUE_RE.match(text, mm.end()):
                        spans.append((mm.start(), mm.end(), line.line_id))
    spans.sort(key=lambda s: (s[0], -s[1]))
    kept = []
    for s in spans:
        if kept and s[0] < kept[-1][1]:
            continue
        kept.append(s)

    speeds: dict[str, set] = {}
    temps: dict[str, Optional[float]] = {}
    for i, (_, end, lid) in enumerate(kept):
        stop = min(end + _WINDOW_CHARS, kept[i + 1][0] if i + 1 < len(kept) else len(text))
        window = text[end:stop]
        speeds.setdefault(lid, set())
        temps.setdefault(lid, None)
        sp = _SPEED_CUE_RE.search(window)
        if sp:
            speeds[lid].add(int(sp.group(1) or sp.group(2)))
        tm = _TEMP_RE.search(window)
        if tm and temps[lid] is None and 0 < float(tm.group(1)) < 200:
            temps[lid] = float(tm.group(1))
    # Line-shaped mentions that match no model line are emitted as-is so resolution fails loudly.
    # A token must look like an identifier (has a digit, a single capital, or is all capitals) so
    # that prose such as "line is down" or "line a bit slow" is not mistaken for a line.
    mentions = [m for m in _LINE_MENTION_RE.finditer(text)]
    for i, m in enumerate(mentions):
        tok = m.group(1)
        if any(m.start() < e and s0 < m.end() for s0, e, _ in kept):
            continue
        if not (any(c.isdigit() for c in tok) or (tok.isupper() and tok.isalpha())):
            continue
        stop = min(m.end() + _WINDOW_CHARS, mentions[i + 1].start() if i + 1 < len(mentions) else len(text))
        sp = _SPEED_CUE_RE.search(text[m.end():stop])
        speeds.setdefault(m.group(0).strip(), set())
        temps.setdefault(m.group(0).strip(), None)
        if sp:
            speeds[m.group(0).strip()].add(int(sp.group(1) or sp.group(2)))
    impacts = [
        LineImpactExtraction(
            line=lid,
            speed_pct=next(iter(sv)) if len(sv) == 1 else None,
            temp_celsius=temps[lid],
        )
        for lid, sv in speeds.items()
    ]

    # Supplier: a single mentioned supplier wins; with several, the one clearly nearest a delay cue.
    mentioned: dict[str, tuple[int, int]] = {}
    candidates = list(model.primary_suppliers) + [(v.supplier_id, v.name) for v in model.vendors]
    for sid, name in candidates:
        pats = [_mention_pattern(sid)]
        words = name.split(" (")[0].split()
        for n in range(len(words), 1, -1):
            pats.append(_name_pattern(" ".join(words[:n])))
        found = [m for pat in pats for m in re.finditer(pat, text, re.I)]
        if found:
            m0 = min(found, key=lambda m: m.start())
            mentioned[sid] = (m0.start(), max(m.end() for m in found if m.start() == m0.start()))
    supplier = None
    if len(mentioned) == 1:
        supplier = next(iter(mentioned))
    elif len(mentioned) > 1:
        cues = [(c.start(), c.end()) for c in _SUPPLIER_DELAY_CUE_RE.finditer(text)]
        dist = {}
        for sid, (st, en) in mentioned.items():
            ds = [max(cs - en, st - ce, 0) for cs, ce in cues]
            if ds and min(ds) <= _SUPPLIER_CUE_CHARS:
                dist[sid] = min(ds)
        ranked = sorted(dist.items(), key=lambda kv: kv[1])
        if ranked and (len(ranked) == 1 or ranked[0][1] < ranked[1][1]):
            supplier = ranked[0][0]

    order = None
    best = None
    for oid in order_ids:
        mm = re.search(_mention_pattern(oid), text, re.I)
        if mm and (best is None or mm.start() < best):
            best, order = mm.start(), oid

    # Order- or supplier-shaped mentions that match nothing known are emitted (fail loud).
    known_orders = {re.sub(r"[^a-z0-9]", "", o.lower()) for o in order_ids}
    other_ids = {re.sub(r"[^a-z0-9]", "", i.lower())
                 for i in [l.line_id for l in model.lines] + [sid for sid, _ in candidates]}
    for mm in [*_ORDER_MENTION_RE.finditer(text), *_ORDER_ON_RE.finditer(text)]:
        norm = re.sub(r"[^a-z0-9]", "", mm.group(1).lower())
        if norm not in known_orders and norm not in other_ids:
            order = mm.group(1)
            break

    names = {sid: nm for sid, nm in candidates}
    for mm in _SUPPLIER_MENTION_RE.finditer(text):
        words = mm.group(1).split()
        resolved = False
        for n in range(len(words), 0, -1):
            try:
                resolve_reference(" ".join(words[:n]), names, "supplier")
                resolved = True
                break
            except DisruptionResolutionError:
                continue
        if not resolved:
            supplier = mm.group(1)
            break

    return DisruptionExtraction(
        delay_hours=delay_hours,
        affected_lines=impacts,
        affected_supplier=supplier,
        affected_order=order,
        shortfall_units=shortfall,
        affected_route=(_blocked_routes(text, model) or [None])[0],
        affected_routes=_blocked_routes(text, model),
        weather_alert=_has_weather(text),
        delay_mentioned=delay_mentioned,
        raw_summary=raw_text[:200],
    )


def _gemini_prompt(raw_text: str, model: FactoryModel, order_ids: Sequence[str]) -> str:
    lines = "\n".join(f"- {l.line_id} — {l.name}" for l in model.lines)
    suppliers = "\n".join(
        [f"- {sid} — {name}" for sid, name in model.primary_suppliers]
        + [f"- {v.supplier_id} — {v.name}" for v in model.vendors]
    )
    orders = ", ".join(order_ids)
    return (
        f"You are the Crisis Detection Engine for {model.name}. "
        f"Extract the disruption parameters stated in this alert:\n\n"
        f'"{raw_text}"\n\n'
        f"Production lines:\n{lines}\n\nSuppliers:\n{suppliers}\n\nOpen orders: {orders}\n\n"
        f"Refer to every line, supplier and order using exactly one of the ids listed above. "
        f"Leave a field null (or the list empty) when the alert does not state it; "
        f"never invent numbers. Report each affected line with its speed_pct and temp_celsius "
        f"only if stated, delay_hours, and shortfall_units of {model.stock_item_name}. "
        f"Set affected_route to the road or route named as blocked or delayed, as written "
        f"(e.g. 'NH48', 'Hosur corridor'), and weather_alert to true only if the alert reports "
        f"a flood, cyclone, heavy rain, storm, landslide or waterlogging."
    )


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _ground_numbers(extraction: DisruptionExtraction, raw_text: str,
                    model: Optional[FactoryModel] = None) -> DisruptionExtraction:
    """Null every LLM number that does not appear in the alert text (no invented numbers).
    Thousands separators are ignored; a delay may also be a stated number of days x 24."""
    text = re.sub(r"(?<=\d),(?=\d)", "", raw_text or "")
    stated = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)}

    def grounded(value, days_ok: bool = False):
        if value is None:
            return None
        if float(value) in stated or (days_ok and value % 24 == 0 and value / 24 in stated):
            return value
        logger.warning("Gemini returned %r, which the alert does not state; ignored", value)
        return None

    # A Gemini route is kept only when the deterministic rules also find it blocked outside any
    # supplier-name mention ("Hosur Precision Castings delayed" is a supplier, not a route).
    blocked = _blocked_routes(raw_text or "", model) if model is not None else []
    route = extraction.affected_route
    if route and not any(_norm_text(route) and _norm_text(route) in _norm_text(b) for b in blocked):
        logger.warning("Gemini returned route %r, which the alert does not name as blocked; ignored", route)
        route = None
    return extraction.model_copy(update={
        "affected_route": route,
        "affected_routes": blocked,
        # the weather flag is deterministic: the LLM cannot raise it without a cue in the text
        "weather_alert": _has_weather(raw_text or ""),
        "delay_hours": grounded(extraction.delay_hours, days_ok=True),
        "shortfall_units": grounded(extraction.shortfall_units),
        "affected_lines": [
            li.model_copy(update={"speed_pct": grounded(li.speed_pct),
                                  "temp_celsius": grounded(li.temp_celsius)})
            for li in extraction.affected_lines
        ],
    })


_call_stats = threading.local()   # latency/tokens of this thread's latest Gemini extraction call


def usage_tokens(resp: Any) -> dict:
    """input_tokens/output_tokens from a Gemini response's usage_metadata, when it reports them."""
    um = getattr(resp, "usage_metadata", None)
    out = {}
    for key, attr in (("input_tokens", "prompt_token_count"), ("output_tokens", "candidates_token_count")):
        v = getattr(um, attr, None) if um is not None else None
        if isinstance(v, int) and not isinstance(v, bool):
            out[key] = v
    return out


def last_extraction_stats() -> dict:
    """Latency (ms) and token counts of this thread's latest Gemini extraction call ({} when the
    regex path ran, or Gemini failed before answering)."""
    return dict(getattr(_call_stats, "last", None) or {})


def extract_disruption_entities(
    raw_text: str, model: FactoryModel, order_ids: Sequence[str]
) -> tuple[DisruptionExtraction, str]:
    """
    Extract structured disruption metrics from raw text (English/Hinglish/alerts), aware of the
    factory model so any line, supplier or order can be named. Gemini structured output first;
    deterministic regex fallback otherwise.

    Returns (extraction, source) where source is "gemini:<model>", "regex-fallback", or
    "structured-overrides" for an empty message (a slider/override-only run: nothing to extract).
    """
    if not (raw_text or "").strip():
        return DisruptionExtraction(), "structured-overrides"

    _call_stats.last = {}
    if settings.has_gemini:
        started = time.perf_counter()
        try:
            from google import genai

            client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options={"timeout": 10000},
            )
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=_gemini_prompt(raw_text, model, order_ids),
                config={
                    "response_mime_type": "application/json",
                    "response_schema": DisruptionExtraction,
                },
            )
            _call_stats.last = {"latency_ms": round((time.perf_counter() - started) * 1000, 1),
                                **usage_tokens(response)}
            logger.info("Gemini extraction: %s", _call_stats.last)
            if response.text:
                data = json.loads(response.text)
                extraction = _ground_numbers(DisruptionExtraction(**data), raw_text, model)
                return extraction, f"gemini:{settings.GEMINI_MODEL}"
        except Exception as exc:
            logger.warning("⚠ Gemini structured extraction failed (%s) — using deterministic fail-safe", exc)

    return _regex_extract(raw_text, model, order_ids), "regex-fallback"


# ─── 2. Blast-Radius SQL Query & Realtime State Updater ──────────────────────

def query_blast_radius_sql(
    model: FactoryModel, disruption: ResolvedDisruption, now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Computes the blast radius of a resolved disruption and writes it to the database: the delayed
    supplier, every impacted line and the order at risk. Realtime subscribers see the change.
    Everything returned about the order comes from the order row; nothing is defaulted.
    `hours_remaining` is the time left until the order's due_at at `now` (the MILP deadline).
    """
    order = get_order(disruption.order_id)
    if order is None:
        raise DisruptionResolutionError(f"Unknown order '{disruption.order_id}'")
    hours_remaining = round(deadline_hours(order, now or datetime.now(timezone.utc)), 2)
    delay = disruption.delay_hours

    if disruption.supplier_id and delay > 0:
        update_rows("suppliers", "id", disruption.supplier_id, {
            "status": "DELAYED",
            "delay_hours": delay,
        })

    for li in disruption.line_impacts:
        updates: Dict[str, Any] = {
            "status": "THROTTLED" if li.speed_pct < 100 else "NORMAL",
            "speed_pct": li.speed_pct,
        }
        if li.temp_celsius is not None:
            updates["temp_celsius"] = li.temp_celsius
        update_rows("production_lines", "line_id", li.line_id, updates)

    update_rows("orders", "order_id", disruption.order_id, {
        "status": "BREACH_RISK",
        "shortfall_units": disruption.shortfall_units,
    })

    has_supply = bool(disruption.supplier_id) and delay > 0
    has_line = bool(disruption.line_impacts)
    if has_supply and has_line:
        severity = "COMPOUND"
    elif has_supply:
        severity = "SUPPLY"
    elif has_line:
        severity = "CAPACITY"
    else:
        severity = "LOW"

    return {
        "order_id": disruption.order_id,
        "client": order["client"],
        "shortfall_units": disruption.shortfall_units,
        "sla_penalty_inr": order["sla_penalty_inr"],
        "partial_delay_penalty_inr": order["partial_delay_penalty_inr"],
        "hours_remaining": hours_remaining,
        "inbound_delay_hours": delay,
        "affected_supplier_id": disruption.supplier_id,
        "line_impacts": [
            {"line_id": li.line_id, "speed_pct": li.speed_pct, "temp_celsius": li.temp_celsius}
            for li in disruption.line_impacts
        ],
        "blast_radius_severity": severity,
    }


# ─── 3. Arbitrator: PuLP MILP Solver & Monte Carlo Engine ────────────────────

def run_pulp_milp_and_monte_carlo(
    model: FactoryModel,
    shortfall_units: int,
    delay_hours: int,
    line_speeds: Mapping[str, int],
    **solver_kwargs: Any,
) -> Dict[str, Any]:
    """
    Invokes the PuLP mixed-integer program and Monte Carlo simulation and
    returns the playbooks ranked by risk-adjusted expected cost.
    Keyword arguments (order_id, sla_penalty_inr, partial_penalty_inr, deadline_hours,
    client, cfo_min_vendor_reliability_pct, ...) are passed through to generate_playbooks.
    FactoryDataError propagates to the caller.
    """
    result = generate_playbooks(
        model=model,
        shortfall_units=shortfall_units,
        delay_hours=delay_hours,
        line_speeds=line_speeds,
        **solver_kwargs,
    )
    return result.model_dump()

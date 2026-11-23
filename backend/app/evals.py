"""
Extraction evals: how well do the regex fallback and Gemini read free-text alerts and vendor replies?

    python -m app.evals [--path regex|gemini|both] [--live] [--verbose]

Disruptions are scored on what the pipeline would act on: the alert is extracted, then resolved
against the demo factory (offline mirror, orders EV-402 and EV-405) exactly as a run would, and the
resolved delay, line speeds, supplier id, order id and shortfall (or the error category) are
compared with the labelled ground truth in `backend/evals/disruptions.jsonl`. Vendor replies use
`backend/evals/vendor_replies.jsonl`. For each field the report counts

    correct   expected and got the same value
    wrong     expected a value, got a different one
    missed    expected a value, got nothing
    spurious  expected nothing, got a value

with precision = correct / (correct + wrong + spurious) and recall = correct / (correct + wrong + missed).

Safety: the run is OFFLINE (no Supabase, no WhatsApp, no Gemini) unless `--live` is given, and `--live`
is required for the gemini path because it calls the live Gemini API. Supabase stays offline even then.
"""

from __future__ import annotations

import os
import sys

# Offline before any app module is imported (python-dotenv never overrides variables already set).
_ALWAYS_OFFLINE = {
    "SUPABASE_URL": "", "SUPABASE_ANON_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": "",
    "META_WA_ACCESS_TOKEN": "", "META_WA_PHONE_NUMBER_ID": "",
    "TWILIO_ACCOUNT_SID": "", "TWILIO_AUTH_TOKEN": "", "OPENWEATHER_API_KEY": "",
    "SOURCING_MODE": "simulated", "SOURCING_RFQ_TEMPLATE": "",
}
os.environ.update(_ALWAYS_OFFLINE)
if "--live" not in sys.argv:
    os.environ["GEMINI_API_KEY"] = ""

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent.parent / "evals"
DISRUPTIONS_PATH = EVALS_DIR / "disruptions.jsonl"
VENDOR_PATH = EVALS_DIR / "vendor_replies.jsonl"
ORDER_IDS = ["EV-402", "EV-405"]
DISRUPTION_FIELDS = ("delay_hours", "lines", "supplier_id", "order_id", "shortfall_units", "error")
VENDOR_FIELDS = ("accepted", "units", "unit_price_inr", "eta_hours")

# Recorded regex recall per field on the committed dataset; a drop is a regression (test_evals).
BASELINE_RECALL: Dict[str, float] = {
    "delay_hours": 0.82,
    "lines": 0.80,
    "supplier_id": 0.82,
    "order_id": 0.81,
    "shortfall_units": 0.81,
    "error": 0.84,
}


class LiveRequiredError(RuntimeError):
    """The gemini path calls the live Gemini API and must be requested with --live."""


def load_jsonl(path: Path) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ─── Scoring ─────────────────────────────────────────────────────────────────

def _new_counts() -> Dict[str, Any]:
    return {"correct": 0, "wrong": 0, "missed": 0, "spurious": 0}


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) < 0.01
    return a == b


def _tally(counts: Dict[str, int], expected: Any, got: Any) -> str:
    """Score one value (None = absent). Returns the outcome, "" when both are absent."""
    if expected is None and got is None:
        return ""
    if expected is None:
        outcome = "spurious"
    elif got is None:
        outcome = "missed"
    else:
        outcome = "correct" if _same(expected, got) else "wrong"
    counts[outcome] += 1
    return outcome


def _finish(counts: Dict[str, Any]) -> Dict[str, Any]:
    c, w, m, s = counts["correct"], counts["wrong"], counts["missed"], counts["spurious"]
    counts["precision"] = round(c / (c + w + s), 3) if (c + w + s) else None
    counts["recall"] = round(c / (c + w + m), 3) if (c + w + m) else None
    return counts


def error_category(exc: Exception) -> str:
    msg = str(exc)
    table = (
        ("Unknown line", "unknown_line"), ("Unknown supplier", "unknown_supplier"),
        ("Unknown order", "unknown_order"), ("Ambiguous", "ambiguous"),
        ("delay_hours not stated", "delay_not_stated"), ("speed for line", "speed_not_stated"),
        ("order not stated", "order_not_stated"), ("shortfall_units not stated", "shortfall_not_stated"),
        ("name the delayed supplier", "supplier_not_named"),
    )
    for needle, cat in table:
        if needle in msg:
            return cat
    return "other"


def _factory():
    from app.factory_model import load_factory_model
    return load_factory_model()


def _extract(text: str, model, path: str):
    """(extraction, source, latency_ms, tokens) for one alert on the given path."""
    from app.agents import tools
    if path == "regex":
        t0 = time.perf_counter()
        ex = tools._regex_extract(text, model, ORDER_IDS)
        return ex, "regex-fallback", (time.perf_counter() - t0) * 1000, {}
    t0 = time.perf_counter()
    ex, source = tools.extract_disruption_entities(text, model, ORDER_IDS)
    return ex, source, (time.perf_counter() - t0) * 1000, tools.last_extraction_stats()


def _resolved_view(text: str, model, path: str) -> tuple:
    """(got dict in the dataset's shape, source, latency_ms, tokens)."""
    from app.disruption import resolve_disruption
    got = {"delay_hours": None, "lines": {}, "supplier_id": None, "order_id": None,
           "shortfall_units": None, "error": None}
    try:
        ex, source, latency, tokens = _extract(text, model, path)
    except Exception as exc:  # extraction itself failed (e.g. invalid structured output)
        got["error"] = "other"
        return got, "extraction-failed", 0.0, {}
    try:
        r = resolve_disruption(ex, model, ORDER_IDS)
        got.update({
            "delay_hours": r.delay_hours or None,
            "lines": {li.line_id: li.speed_pct for li in r.line_impacts},
            "supplier_id": r.supplier_id, "order_id": r.order_id,
            "shortfall_units": r.shortfall_units,
        })
    except Exception as exc:
        got["error"] = error_category(exc)
    return got, source, latency, tokens


def _score_disruptions(rows: List[dict], path: str) -> Dict[str, Any]:
    model = _factory()
    counts = {f: _new_counts() for f in DISRUPTION_FIELDS}
    failures: List[dict] = []
    latencies: List[float] = []
    tokens = {"input_tokens": 0, "output_tokens": 0}
    fallbacks = 0
    exact = 0
    for row in rows:
        exp = row["expected"]
        got, source, latency, usage = _resolved_view(row["text"], model, path)
        if path != "regex":
            latencies.append(latency)
            fallbacks += source == "regex-fallback"
            for k in tokens:
                tokens[k] += usage.get(k, 0)
        bad = []
        for field in DISRUPTION_FIELDS:
            if field == "lines":
                e, g = exp["lines"] or {}, got["lines"] or {}
                for lid in sorted(set(e) | set(g)):
                    if _tally(counts["lines"], e.get(lid), g.get(lid)) in ("wrong", "missed", "spurious"):
                        bad.append(f"lines[{lid}]")
            elif _tally(counts[field], exp[field], got[field]) in ("wrong", "missed", "spurious"):
                bad.append(field)
        if bad:
            failures.append({"text": row["text"], "wrong_fields": bad, "expected": exp, "got": got})
        else:
            exact += 1
    out: Dict[str, Any] = {
        "rows": len(rows), "rows_fully_correct": exact,
        "fields": {f: _finish(c) for f, c in counts.items()}, "failures": failures,
    }
    if path != "regex":
        out["latency_ms_mean"] = round(sum(latencies) / len(latencies), 1) if latencies else None
        out["gemini_fallbacks_to_regex"] = fallbacks
        out.update(tokens)
    return out


def _score_vendor_replies(rows: List[dict], path: str) -> Dict[str, Any]:
    from app.agents.sourcing import RFQ, _regex_parse, parse_vendor_reply
    counts = {f: _new_counts() for f in VENDOR_FIELDS}
    failures: List[dict] = []
    latencies: List[float] = []
    exact = 0
    for row in rows:
        rfq = RFQ(id="R", run_id="EVAL", round=1, supplier_id="SUP-PNY-02", supplier_name="Peenya",
                  units_requested=row["rfq_units"], expected_unit_price_inr=600, needed_within_hours=34,
                  channel="simulated")
        t0 = time.perf_counter()
        if path == "regex":
            offer = _regex_parse(row["text"], rfq)
        else:
            offer, _ = parse_vendor_reply(row["text"], rfq)
            latencies.append((time.perf_counter() - t0) * 1000)
        accepted = not offer.declined
        got = {"accepted": accepted,
               "units": offer.available_units if accepted else None,
               "unit_price_inr": offer.unit_price_inr if accepted else None,
               "eta_hours": offer.eta_hours if accepted else None}
        exp = row["expected"]
        bad = []
        for field in VENDOR_FIELDS:
            if _tally(counts[field], exp[field], got[field]) in ("wrong", "missed", "spurious"):
                bad.append(field)
        if bad:
            failures.append({"text": row["text"], "wrong_fields": bad, "expected": exp, "got": got})
        else:
            exact += 1
    out: Dict[str, Any] = {"rows": len(rows), "rows_fully_correct": exact,
                           "fields": {f: _finish(c) for f, c in counts.items()}, "failures": failures}
    if path != "regex":
        out["latency_ms_mean"] = round(sum(latencies) / len(latencies), 1) if latencies else None
    return out


def _run_path(path: str) -> Dict[str, Any]:
    return {
        "path": path,
        "disruptions": _score_disruptions(load_jsonl(DISRUPTIONS_PATH), path),
        "vendor_replies": _score_vendor_replies(load_jsonl(VENDOR_PATH), path),
    }


def run_evals(path: str = "regex", live: bool = False) -> Dict[str, Any]:
    """Score the datasets. "regex" is offline and deterministic. "gemini" (and "both") call the live
    Gemini API and need live=True (CLI: --live) plus a GEMINI_API_KEY; "both" returns
    {"regex": ..., "gemini": ...}."""
    if path not in ("regex", "gemini", "both"):
        raise ValueError(f"unknown path {path!r}; use regex, gemini or both")
    if path in ("gemini", "both"):
        if not live:
            raise LiveRequiredError(
                "the gemini path calls the live Gemini API: pass --live (CLI) or live=True")
        from app.config import settings
        if not settings.has_gemini:
            raise LiveRequiredError("--live needs GEMINI_API_KEY to be configured")
    if path == "both":
        return {"regex": _run_path("regex"), "gemini": _run_path("gemini")}
    return _run_path(path)


# ─── Report ──────────────────────────────────────────────────────────────────

def _fmt(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.2f}"


def _table(title: str, block: Dict[str, Any]) -> List[str]:
    lines = [f"{title}  ({block['rows']} rows, {block['rows_fully_correct']} fully correct)",
             f"  {'field':<17}{'correct':>8}{'wrong':>7}{'missed':>8}{'spurious':>9}{'precision':>10}{'recall':>8}"]
    for field, m in block["fields"].items():
        lines.append(f"  {field:<17}{m['correct']:>8}{m['wrong']:>7}{m['missed']:>8}{m['spurious']:>9}"
                     f"{_fmt(m['precision']):>10}{_fmt(m['recall']):>8}")
    if "latency_ms_mean" in block:
        extra = f"  mean latency {block['latency_ms_mean']} ms"
        if "input_tokens" in block:
            extra += f", tokens in/out {block['input_tokens']}/{block['output_tokens']}"
            extra += f", {block['gemini_fallbacks_to_regex']} fell back to regex"
        lines.append(extra)
    return lines


def format_report(result: Dict[str, Any], verbose: bool = False) -> str:
    runs = [result] if "disruptions" in result else [result["regex"], result["gemini"]]
    out: List[str] = []
    for run in runs:
        mode = "offline, regex fallback" if run["path"] == "regex" else "LIVE Gemini"
        out.append(f"=== path: {run['path']} ({mode}) ===")
        out += _table("Disruption extraction (resolved against the demo factory)", run["disruptions"])
        out.append("")
        out += _table("Vendor reply parsing", run["vendor_replies"])
        out.append("")
        if verbose:
            for name in ("disruptions", "vendor_replies"):
                for f in run[name]["failures"]:
                    out.append(f"  [{name}] {f['wrong_fields']} :: {f['text']!r}")
                    out.append(f"      expected {json.dumps(f['expected'], ensure_ascii=False)}")
                    out.append(f"      got      {json.dumps(f['got'], ensure_ascii=False)}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.evals", description=__doc__.split("\n\n")[0])
    ap.add_argument("--path", choices=("regex", "gemini", "both"), default="regex")
    ap.add_argument("--live", action="store_true",
                    help="allow the live Gemini API (required for --path gemini/both); Supabase stays offline")
    ap.add_argument("--verbose", action="store_true", help="list every row that was not fully correct")
    args = ap.parse_args(argv)
    if args.path in ("gemini", "both"):
        if not args.live:
            print("error: --path " + args.path + " calls the live Gemini API; re-run with --live "
                  "(the default run is offline and regex only)", file=sys.stderr)
            return 2
        print("WARNING: --live calls the live Gemini API (quota and cost apply).", file=sys.stderr)
    try:
        result = run_evals(args.path, live=args.live)
    except LiveRequiredError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(format_report(result, verbose=args.verbose))
    return 0


if __name__ == "__main__":
    sys.exit(main())

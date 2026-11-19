"""
CascadeZero — Legacy ERP / Tally Folder Watcher & Supabase Sync Agent
Continuously monitors `watched_erp_folder/` for exported CSV files from
legacy manufacturing software (Tally ERP 9, SAP Business One, Marg ERP, Excel).

When an SME supervisor or accountant drops an updated order sheet,
CascadeZero immediately parses the contract terms, penalties, and required
casing volumes, synchronizing them into Supabase via FastAPI `/api/v1/ingest/erp-csv`.
"""

import argparse
import csv
import io
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# Ensure clean UTF-8 stdout on Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API_DEFAULT_BASE = "http://localhost:8000"
WATCHED_DIR = Path(__file__).resolve().parent / "watched_erp_folder"


def sync_file_to_api(file_path: Path, api_base: str) -> bool:
    """Reads a CSV file and posts it to the FastAPI ERP ingestion endpoint."""
    if not file_path.exists() or not file_path.suffix.lower() == ".csv":
        return False

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"❌ Could not read {file_path.name}: {exc}")
        return False

    # Preview rows
    try:
        reader = list(csv.DictReader(io.StringIO(content)))
        print(f"\n📂 Parsing '{file_path.name}' ({len(reader)} orders found):")
        for row in reader:
            oid = row.get("order_id", "N/A")
            client = row.get("client", "N/A")
            qty = row.get("required_qty", "0")
            penalty = int(row.get("sla_penalty_inr", 0) or 0)
            print(f"   • Order #{oid}: {client} | Qty: {qty} units | SLA Penalty: ₹{penalty:,}")
    except Exception as exc:
        print(f"⚠️ Warning parsing preview: {exc}")

    url = f"{api_base}/api/v1/ingest/erp-csv"
    payload = {
        "filename": file_path.name,
        "csv_content": content,
    }

    try:
        headers = {"X-API-Key": os.environ["CASCADE_API_KEY"]} if os.environ.get("CASCADE_API_KEY") else {}
        with httpx.Client(timeout=5.0) as client:
            res = client.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                data = res.json()
                print(
                    f"✅ [HTTP 200] Successfully synced {data.get('imported_count', 0)} "
                    f"orders into Supabase from {file_path.name}!"
                )
                return True
            else:
                print(f"❌ [HTTP {res.status_code}] Sync failed: {res.text}")
                return False
    except Exception as exc:
        print(f"❌ Connection error syncing to {url}: {exc}")
        return False


def run_watch_loop(api_base: str, poll_interval_sec: float = 2.0):
    """Monitors watched_erp_folder continuously for modified or added files."""
    WATCHED_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print(" 📑 CASCADEZERO LEGACY ERP / TALLY CSV FOLDER WATCHER")
    print(f" Watching Directory: {WATCHED_DIR}")
    print(f" Target API: {api_base}/api/v1/ingest/erp-csv")
    print(f" Polling Interval: {poll_interval_sec}s | Press Ctrl+C to stop")
    print("=" * 72)

    # Track file modification timestamps
    last_mtimes = {}

    # Perform initial sync of all existing CSV files
    initial_files = list(WATCHED_DIR.glob("*.csv"))
    if initial_files:
        print(f"🔍 Found {len(initial_files)} existing CSV files. Performing baseline sync:")
        for f in initial_files:
            sync_file_to_api(f, api_base)
            last_mtimes[f.name] = f.stat().st_mtime

    print(f"\n👀 Standing by... Drop any .csv order export into: {WATCHED_DIR}\n")

    try:
        while True:
            current_files = list(WATCHED_DIR.glob("*.csv"))
            for f in current_files:
                mtime = f.stat().st_mtime
                if f.name not in last_mtimes or mtime > last_mtimes[f.name]:
                    now_str = datetime.now().strftime("%H:%M:%S")
                    print(f"[{now_str}] ⚡ File change detected in '{f.name}'! Synchronizing...")
                    success = sync_file_to_api(f, api_base)
                    if success:
                        last_mtimes[f.name] = mtime

            time.sleep(poll_interval_sec)

    except KeyboardInterrupt:
        print("\n🛑 ERP sync folder watcher stopped by user.")


def main():
    parser = argparse.ArgumentParser(
        description="CascadeZero Legacy ERP / Tally CSV File Watcher & Sync Agent"
    )
    parser.add_argument(
        "--api",
        type=str,
        default=API_DEFAULT_BASE,
        help="FastAPI base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Perform a single one-shot sync of all CSVs in watched_erp_folder and exit",
    )

    args = parser.parse_args()

    if args.sync:
        WATCHED_DIR.mkdir(parents=True, exist_ok=True)
        csv_files = list(WATCHED_DIR.glob("*.csv"))
        if not csv_files:
            print(f"⚠️ No CSV files found in {WATCHED_DIR}")
            return
        for f in csv_files:
            sync_file_to_api(f, args.api)
    else:
        run_watch_loop(args.api)


if __name__ == "__main__":
    main()

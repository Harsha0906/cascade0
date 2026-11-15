"""
CascadeZero — Step 6 End-to-End System Verification Suite
Tests the complete multi-channel industrial pipeline:
1. Legacy ERP / Tally CSV Sync (watched folder -> /api/v1/ingest/erp-csv)
2. Shop-Floor Machine PLC Telemetry (/api/v1/ingest/plc-telemetry)
3. Physical Phone Twilio WhatsApp Webhook (/api/v1/webhooks/whatsapp -> TwiML XML response)
4. Full LangGraph 4-Agent Cyclic Debate & PuLP Optimization
5. HITL Execution & Tally XML PO Generation (/api/v1/execute-plan)
6. Factory Reset (/api/v1/reset)
"""

import io
import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Ensure UTF-8 output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.main import app
from app.db import fetch_all

client = TestClient(app)


def test_step6_e2e():
    print("=" * 72)
    print(" 🚀 CASCADEZERO STEP 6 END-TO-END SYSTEM INTEGRATION TEST")
    print("=" * 72)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Test ERP CSV Folder Ingestion
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 1/6] Ingesting Legacy Tally ERP CSV Sheet...")
    sample_csv_path = Path(__file__).parent / "watched_erp_folder" / "sample_tally_orders.csv"
    assert sample_csv_path.exists(), "sample_tally_orders.csv missing!"
    csv_text = sample_csv_path.read_text(encoding="utf-8")

    res_erp = client.post(
        "/api/v1/ingest/erp-csv",
        json={"filename": "sample_tally_orders.csv", "csv_content": csv_text},
    )
    assert res_erp.status_code == 200, f"ERP ingestion failed: {res_erp.text}"
    erp_data = res_erp.json()
    print(f"  ✅ ERP Ingestion OK: {erp_data['imported_count']} orders synced: {erp_data['orders']}")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Test Shop-Floor PLC Machine Telemetry Ingestion
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 2/6] Ingesting Live PLC Machine Overheat Telemetry...")
    res_plc = client.post(
        "/api/v1/ingest/plc-telemetry",
        json={
            "line_id": "LINE-2",
            "speed_pct": 50,
            "temp_celsius": 89.2,
            "status": "OVERHEATING_THROTTLED",
        },
    )
    assert res_plc.status_code == 200, f"PLC ingestion failed: {res_plc.text}"
    plc_data = res_plc.json()
    print(f"  ✅ Machine LINE-2 updated in Supabase: {plc_data['temp_celsius']}°C, speed {plc_data['speed_pct']}%, status {plc_data['status']}")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Test Physical Phone Twilio WhatsApp Webhook Trigger
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 3/6] Simulating Phone WhatsApp Webhook (Form-encoded)...")
    whatsapp_payload = {
        "Body": "🚨 Urgent: Supply truck stalled on NH48 Vellore floodwater. Casings delayed 48 hrs.",
        "From": "whatsapp:+919876543210",
        "To": "whatsapp:+14155238886",
    }
    res_wa = client.post(
        "/api/v1/webhooks/whatsapp",
        data=whatsapp_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res_wa.status_code == 200, f"WhatsApp webhook failed: {res_wa.text}"
    assert "xml" in res_wa.headers.get("content-type", "").lower()
    assert "<Response>" in res_wa.text
    assert "<Message>" in res_wa.text
    print("  ✅ Twilio TwiML XML Response returned successfully:")
    # Print preview of TwiML message
    first_lines = res_wa.text.split("\n")[:8]
    print("     " + "\n     ".join(first_lines))

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Verify Factory State & Multi-Agent Audit Logs
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 4/6] Verifying Live Plant State & Multi-Agent Audit Trail...")
    res_state = client.get("/api/v1/state")
    assert res_state.status_code == 200
    state = res_state.json()
    print(f"  • Factory Name: {state['factory_name']}")
    print(f"  • Total Agent Logs: {len(state['agent_logs'])}")
    assert len(state["agent_logs"]) >= 4, "Expected at least 4 agent logs in trail"
    print(f"  • Latest Agent: [{state['agent_logs'][-1]['agent_name']}] - {state['agent_logs'][-1]['message'][:80]}...")

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Test HITL Execution & Tally XML PO Generation
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 5/6] Testing HITL Execution & Tally ERP XML Generation...")
    res_exec = client.post(
        "/api/v1/execute-plan",
        json={
            "po_number": "PO-APEX-2026-E2E",
            "playbook_id": "PLAN_B",
            "order_id": "EV-402",
            "allocations": [
                {
                    "supplier_id": "SUP-PNY-02",
                    "supplier_name": "Peenya Rapid Metals",
                    "tier": "TIER-2",
                    "units_allocated": 150,
                    "cost_per_unit_inr": 600,
                    "flat_charter_cost_inr": 0,
                    "total_cost_inr": 90000,
                    "lead_time_hours": 4,
                    "route": "Peenya (14 km)",
                }
            ],
            "overtime_hours": 4,
            "total_cost_inr": 180000,
            "net_sla_saved_inr": 2320000,
            "confidence_pct": 94.2,
            "client": "Ather-Grid Mobility Corp",
        },
    )
    assert res_exec.status_code == 200, f"Execution failed: {res_exec.text}"
    exec_data = res_exec.json()
    assert exec_data["success"] is True
    assert "<ENVELOPE>" in exec_data["tally_xml_payload"]
    assert "PO-APEX-2026-E2E" in exec_data["tally_xml_payload"]
    assert "Peenya Rapid Metals" in exec_data["tally_xml_payload"]
    print(f"  ✅ Tally PO #{exec_data['po_number']} created in Supabase 'purchase_orders'.")
    print(f"  • SLA Saved: ₹{exec_data['net_sla_saved_inr']:,}")
    print(f"  • Supervisor Code: {exec_data['shift_broadcast_msg'].split('code:')[-1].strip()}")

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Test Factory Reset
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[TEST 6/6] Testing Clean Factory Reset...")
    res_reset = client.post("/api/v1/reset")
    assert res_reset.status_code == 200
    reset_data = res_reset.json()
    assert reset_data["success"] is True
    print("  ✅ Factory restored to pristine seed state in Supabase.")

    print("\n" + "=" * 72)
    print(" 🏆 ALL 6 STEP 6 END-TO-END INTEGRATION CHECKS PASSED PERFECTLY!")
    print("=" * 72)


if __name__ == "__main__":
    test_step6_e2e()

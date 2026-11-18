"""
CascadeZero — Simulated PLC Telemetry (HTTP JSON)
Generates synthetic machine ticks and POSTs them as JSON to the backend.
It does NOT speak Modbus, OPC-UA or MQTT; a real deployment needs an edge collector
(e.g. pymodbus / asyncua) that reads the PLC and posts the same payload.
Lines simulated:
- Line 2: Robotic Welding Line 2 (LINE-2)
- Line 1: Automated Stamping Press 1 (LINE-1)
- Line 3: Ultrasonic Cell Pack Assembler (LINE-3)

Can run in continuous streaming mode, one-shot crisis trigger, or gradual thermal ramp.
"""

import argparse
import io
import json
import random
import sys
import time
from datetime import datetime, timezone

import os

import httpx

# Ensure clean UTF-8 stdout on Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API_DEFAULT_BASE = "http://localhost:8000"


def send_telemetry(api_base: str, line_id: str, speed_pct: int, temp_c: float, status: str) -> bool:
    """Sends a single PLC machine tick to the CascadeZero FastAPI backend."""
    url = f"{api_base}/api/v1/ingest/plc-telemetry"
    payload = {
        "line_id": line_id,
        "speed_pct": int(speed_pct),
        "temp_celsius": round(float(temp_c), 1),
        "status": status,
    }

    try:
        headers = {"X-API-Key": os.environ["CASCADE_API_KEY"]} if os.environ.get("CASCADE_API_KEY") else {}
        with httpx.Client(timeout=4.0) as client:
            res = client.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                return True
            else:
                print(f"⚠️ [HTTP {res.status_code}] Failed to update {line_id}: {res.text}")
                return False
    except Exception as exc:
        print(f"❌ Connection error sending to {url}: {exc}")
        return False


def run_continuous_stream(api_base: str, interval_sec: float = 2.0):
    """
    Simulates continuous real-time telemetry broadcast from shop-floor PLC.
    Starts normal, then after 5 ticks begins an thermal anomaly ramp.
    """
    print("=" * 72)
    print(" 🏭 CASCADEZERO SIMULATED PLC TELEMETRY (synthetic data over HTTP)")
    print(f" Target Endpoint: {api_base}/api/v1/ingest/plc-telemetry")
    print(f" Telemetry Interval: {interval_sec}s | Press Ctrl+C to stop")
    print("=" * 72)

    tick = 0
    temp_l2 = 62.0
    speed_l2 = 100
    status_l2 = "NORMAL"

    try:
        while True:
            tick += 1
            now_str = datetime.now().strftime("%H:%M:%S")

            # Ambient thermal noise
            jitter = random.uniform(-0.4, 0.4)

            # Auto-ramp trigger on tick 8 if left unattended
            if tick > 8 and temp_l2 < 89.0:
                temp_l2 += 4.5
                speed_l2 = max(50, speed_l2 - 8)
                if temp_l2 >= 85.0:
                    status_l2 = "OVERHEATING_THROTTLED"
                else:
                    status_l2 = "WARNING_HIGH_TEMP"
            elif tick <= 8:
                temp_l2 = 62.0 + jitter
                speed_l2 = 100
                status_l2 = "NORMAL"

            ok = send_telemetry(api_base, "LINE-2", speed_l2, temp_l2, status_l2)
            icon = "🔥" if temp_l2 >= 85.0 else "⚠️" if temp_l2 >= 75.0 else "🟢"
            flag = "CRISIS THRESHOLD BREACHED" if temp_l2 >= 85.0 else "NOMINAL"

            print(
                f"[{now_str}] Tick #{tick:03d} | {icon} LINE-2: {temp_l2:.1f}°C | "
                f"Speed: {speed_l2}% | Status: {status_l2} ({flag}) {'[SYNCED]' if ok else '[FAILED]'}"
            )

            # Also occasionally send Line 1 nominal tick
            if tick % 3 == 0:
                temp_l1 = 58.5 + random.uniform(-0.5, 0.5)
                send_telemetry(api_base, "LINE-1", 100, temp_l1, "NORMAL")

            time.sleep(interval_sec)

    except KeyboardInterrupt:
        print("\n🛑 Telemetry streaming halted by user.")


def run_instant_crisis(api_base: str):
    """Instantly injects an emergency thermal trip and speed throttling into LINE-2."""
    print("🚨 INJECTING INSTANT SHOP-FLOOR CRISIS: LINE-2 THERMAL OVERHEAT")
    ok = send_telemetry(
        api_base=api_base,
        line_id="LINE-2",
        speed_pct=50,
        temp_c=89.2,
        status="OVERHEATING_THROTTLED",
    )
    if ok:
        print("✅ SUCCESS: Robotic Welding Line 2 throttled to 50% at 89.2°C in Supabase.")
        print("   -> Frontend 2.5D Digital Twin Canvas turns crimson in real time.")
    else:
        print("❌ FAILED: Could not deliver crisis telemetry.")


def run_restore_normal(api_base: str):
    """Restores LINE-2 to optimal operating condition."""
    print("🟢 RESTORING SHOP-FLOOR TELEMETRY: LINE-2 NORMALIZED")
    ok = send_telemetry(
        api_base=api_base,
        line_id="LINE-2",
        speed_pct=100,
        temp_c=62.0,
        status="NORMAL",
    )
    if ok:
        print("✅ SUCCESS: Line 2 restored to 100% speed at 62.0°C.")
    else:
        print("❌ FAILED to restore line.")


def run_gradual_ramp(api_base: str):
    """Executes an authentic 5-step industrial thermal runaway simulation."""
    print("📈 EXECUTING 5-STEP THERMAL RUNAWAY RAMP ON LINE-2")
    steps = [
        (62.0, 100, "NORMAL"),
        (69.5, 95, "NOMINAL_HIGH"),
        (76.2, 85, "WARNING_ELEVATED_HEAT"),
        (83.0, 70, "THERMAL_THROTTLE_INITIATED"),
        (89.4, 50, "OVERHEATING_THROTTLED"),
    ]

    for i, (temp, speed, status) in enumerate(steps, 1):
        print(f" Step {i}/5: Injecting {temp}°C, {speed}% speed -> {status}...")
        send_telemetry(api_base, "LINE-2", speed, temp, status)
        time.sleep(1.5)

    print("🔥 THERMAL RUNAWAY COMPLETE: Machine running in emergency throttled state.")


def main():
    parser = argparse.ArgumentParser(
        description="CascadeZero Shop-Floor Machine PLC Telemetry Emulator"
    )
    parser.add_argument(
        "--api",
        type=str,
        default=API_DEFAULT_BASE,
        help="FastAPI base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Run continuous live telemetry stream with auto-escalation",
    )
    parser.add_argument(
        "--crisis",
        action="store_true",
        help="Instantly inject critical Line-2 overheat (89.2°C, 50% speed)",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore Line-2 to normal operating parameters (62.0°C, 100% speed)",
    )
    parser.add_argument(
        "--ramp",
        action="store_true",
        help="Perform a live 5-step temperature ramp from 62°C to 89.4°C",
    )

    args = parser.parse_args()

    if args.crisis:
        run_instant_crisis(args.api)
    elif args.restore:
        run_restore_normal(args.api)
    elif args.ramp:
        run_gradual_ramp(args.api)
    elif args.stream:
        run_continuous_stream(args.api)
    else:
        # Default interactive menu if no flags provided
        print("\n🏭 CASCADEZERO PLC TELEMETRY SIMULATOR")
        print("1. Inject Instant Crisis (LINE-2 @ 89.2°C, 50% Speed)")
        print("2. 5-Step Live Thermal Ramp (Watch Canvas Live)")
        print("3. Restore Normal Operations (62.0°C, 100% Speed)")
        print("4. Continuous Realtime Ticks (Ctrl+C to stop)")
        choice = input("Select mode [1/2/3/4] (default: 1): ").strip()

        if choice == "2":
            run_gradual_ramp(args.api)
        elif choice == "3":
            run_restore_normal(args.api)
        elif choice == "4":
            run_continuous_stream(args.api)
        else:
            run_instant_crisis(args.api)


if __name__ == "__main__":
    main()

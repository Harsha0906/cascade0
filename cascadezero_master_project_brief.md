# CASCADEZERO — COMPLETE AGENT ENGINEERING & MASTER PRODUCT BRIEF

> ⚠️ **SUPERSEDED BUILD SPEC — not a description of current behaviour.** This was the original prompt used to generate the first version. Fixed figures (e.g. Plan B, 13.9x ROI, 94.2%), "dispatch" and "zero-hallucination" language below do not reflect the current code. See README.md ("What Is Real vs Simulated").


> **INSTRUCTIONS FOR THE AI CODING AGENT IN GOOGLE ANTIGRAVITY:**
> This document is the single source of truth for building **CascadeZero**. Nothing has been implemented yet; you are starting from a clean slate. Read every section carefully and adhere strictly to the architecture, database schema, 4-Agent LangGraph design, PuLP + Monte Carlo math solver, hex color tokens, and the **Step-by-Step Build Order** in Section 8. **Never skip ahead to Step N+1 until the user has run, tested, and verified Step N.** Always provide complete, top-to-bottom file contents (never partial diffs or `// ... existing code ...` placeholders).

---

## 1. PROJECT OVERVIEW

* **Project Name:** CascadeZero
* **Tagline:** Neuro-Symbolic Multi-Agent Copilot & 2.5D Digital Twin for Compound-Risk Orchestration in Manufacturing.
* **Hackathon Track:** Manufacturing (Supply Chain & Shop-Floor Operations) + AI Engineering.
* **Purpose & Core Problem:**
  Small and mid-sized manufacturing enterprises (SMEs)—such as EV battery pack manufacturers and precision engineering units in industrial hubs like Peenya or Hosur—operate on razor-thin margins with critical operational data trapped in isolated silos:
  1. **Inbound Logistics:** Third-party highway trucks, weather/traffic blockades, and driver WhatsApp messages.
  2. **Inventory & Multi-Tier Vendors:** Warehouse Bill of Materials (BOM) buffers, regional vendor pricing, lead times, capacity caps, and historical reliability records.
  3. **Shop-Floor Machines:** PLC/SCADA machine speeds, thermal throttling logs, and parallel line shift overtime rates.
  4. **Client SLA Contracts:** Delivery deadlines and severe financial penalty clauses sitting in legacy accounting/ERP software (Tally Prime, Zoho Inventory, SAP Business One, Excel).

  When a single delay happens, managers adjust manually. However, when a **compound disruption** strikes—for example, *NH48 Chennai–Bengaluru highway flooding delays a Tier-1 shipment of 500 aluminum battery casings by 48 hours* **at the exact same time** *Robotic Welding Line 2 overheats (89°C) and throttles down to 50% speed*—legacy ERPs only flash isolated warnings. They cannot compute the cascading domino effect across active customer orders (such as Order `#EV-402` for Ather-Grid Mobility Corp requiring 500 battery packs by Friday 17:00 IST with a `₹25,00,000` SLA penalty). Factory managers, finance heads, and floor supervisors are forced into a 5-hour war-room panic with spreadsheets and calculators, either wasting lakhs on panic air-freight charters or breaching the SLA.

* **The Solution:**
  CascadeZero is an "AI Crisis Control Tower" and zero-hardware decision-and-execution layer that connects a factory's existing tools (Tally/Excel, PLC logs, Weather/Traffic APIs, and WhatsApp) onto one live **2.5D Interactive Node Flow Canvas**. When a compound disruption hits, CascadeZero resolves the 5-hour panic in under 10 seconds:
  1. **Multi-Channel Chaos Ingestion:** Ingests live unstructured alerts from a **real physical phone via Twilio WhatsApp Webhook**, live PLC machine telemetry streams, legacy Tally/CSV folder syncs, and external highway weather/traffic APIs.
  2. **Causal Blast-Radius Mapping on a 2.5D Digital Twin:** Dynamically maps how the upstream supply delay + shop-floor thermal slowdown collide to create an exact unit shortfall and rupee SLA penalty exposure on the 2.5D React Flow graph.
  3. **God-Level 4-Agent Adversarial Boardroom (LangGraph) + Neuro-Symbolic Math Solver (PuLP + Monte Carlo):** Four autonomous, tool-calling AI agents (`Blast-Radius Detective`, `Operations Hawk`, `CFO Watchdog`, and `Neuro-Symbolic Arbitrator`) debate across a cyclic LangGraph workflow, querying live Supabase tables, checking historical vendor reliability memory, running a **Mixed-Integer Linear Programming (`PuLP`) cost optimizer**, and running a **1,000-iteration Monte Carlo risk simulation** so the AI never hallucinates financial arithmetic.
  4. **One-Click Human-in-the-Loop (HITL) ERP Execution:** Presents the manager with 3 mathematically verified recovery playbooks (`Plan A`, `Plan B`, `Plan C`). With one click on **`[APPROVE & EXECUTE]`**, CascadeZero commits the transaction to Supabase, generates a downloadable **Tally Prime XML & JSON Purchase Order**, dispatches a **WhatsApp Business shift overtime broadcast** to floor supervisors, and issues a **Client SLA Compliance Notice**.

* **Target Audience:**
  Indian and global SME and mid-market manufacturers who cannot afford $2M SAP/IoT hardware overhauls and need a production-grade, cloud-native AI operational copilot that deploys in under 48 hours with zero hardware capex.

* **Overall Vision & Feel (In the User's Own Words):**
  * *"I need it to be industry level with a high-end tech stack; when I'm building it, it should be production-ready."*
  * *"Scrap 3D, let's only do 2.5D—the nodes thing."*
  * *"Can we make the AI agents god-level... and trigger the webhook from my phone during the live pitch so the judges see my phone trigger the dashboard live?"*

---

## 2. TECH STACK & CONSTRAINTS

### Approved Production Tech Stack
* **Database & Realtime Event Bus (Single Source of Truth):**
  * **Supabase** (Cloud PostgreSQL relational database + **Supabase Realtime `postgres_changes`** WebSocket stream).
  * Backend client: `supabase` (`supabase-py`) and/or `httpx` REST/Postgres client.
  * Frontend client: `@supabase/supabase-js` subscribed directly to database table changes for 0ms polling updates.
* **Backend Engine (`backend/`):**
  * **Runtime & API Framework:** Python 3.11+ / 3.14 with **FastAPI** (`fastapi`, `uvicorn[standard]`, `pydantic`, `python-dotenv`, `python-multipart`).
  * **Multi-Agent Orchestration:** **LangGraph** (`langgraph`, `langchain-core`) implementing a cyclic, stateful `StateGraph` with autonomous tool-calling (`bind_tools` / structured tool nodes) and adversarial rebuttal loops.
  * **LLM & Structured Extraction:** **Google Gemini SDK (`google-genai`)** using model **`gemini-2.5-flash`** with strict **Pydantic Structured Outputs (`response_schema`)** for zero-regex unstructured entity parsing and multi-agent debate generation.
  * **Mathematical Optimization & Risk Simulation:**
    * **PuLP (`pulp`)** Mixed-Integer Linear Programming (MILP) solver for exact multi-vendor unit allocation and shift overtime optimization across capacity caps and lead times.
    * **Monte Carlo Simulation Engine** (built with Python `random` / `numpy` inside `solver.py`) executing 1,000 stochastic timeline runs per playbook to compute exact **SLA Survival Probability %** (`Confidence %`).
  * **Physical Phone & Field Webhooks:**
    * **Twilio WhatsApp Sandbox Webhook** (`twilio`) exposed via `ngrok` or `cloudflared` tunnel (`POST /api/v1/webhooks/whatsapp`).
* **Frontend Command Center (`frontend/`):**
  * **Framework:** **Next.js (App Router, TypeScript)** (or Vite + React + TypeScript if preferred, with Next.js App Router as default).
  * **2.5D Interactive Node Flow Canvas:** **`@xyflow/react` (React Flow v12)** for custom industrial telemetry nodes, animated SVG flow pipes, pan/zoom controls, and interactive node inspection.
  * **Styling & UI Primitives:** **Tailwind CSS**, **Shadcn UI** patterns (modals, slide-over drawers, badges), and **Lucide React (`lucide-react`)** icons.
  * **State Management:** **Zustand (`zustand`)** wired to both FastAPI REST responses and **Supabase Realtime (`postgres_changes`)** subscriptions.

### Explicitly Rejected Technologies (DO NOT USE)
* **NO 3D Isometric / Three.js / WebGL models:** Strictly forbidden. Only build the **2.5D Interactive Node Flow Canvas (`@xyflow/react`)**.
* **NO Toy Single-File HTML/JSON Prototypes:** Do not build a static `index.html` with `factory_db.json`. Build the modular `backend/`, `frontend/`, and `supabase/` production architecture.
* **NO Pure Regex (`re.search`) as the Primary AI Parser:** Always use Gemini 2.5 Flash Structured Outputs (`response_schema`) with Pydantic models as the primary parser, keeping deterministic parsing strictly as an automatic offline fail-safe if API/Wi-Fi drops.
* **NO Physical Microcontrollers (Arduino/ESP32):** Connect to hardware the way real enterprise software does—via webhook ingestion endpoints (`/api/v1/ingest/plc-telemetry`, `/api/v1/webhooks/whatsapp`, and `cascade_sync.py` ERP folder watcher).

### Complete Monorepo Folder Structure
```text
cascadezero/
├── supabase/
│   └── schema.sql                   # Complete PostgreSQL DDL, Realtime publication setup, & Sandbox Seed Data
├── backend/
│   ├── .env.example                 # Template for SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY, TWILIO_*, OPENWEATHER_API_KEY
│   ├── requirements.txt             # Python dependencies
│   ├── simulator_plc.py             # Standalone PLC Hardware Telemetry Producer pushing live machine temp/speed ticks
│   ├── cascade_sync.py              # Standalone SME Desktop Folder-Watcher syncing Tally XML / Excel CSV files
│   ├── watched_erp_folder/          # Drop folder watched by cascade_sync.py for live ERP file ingestion
│   │   └── sample_tally_orders.csv
│   └── app/
│       ├── __init__.py
│       ├── config.py                # Environment configuration loader
│       ├── db.py                    # Supabase client initialization & CRUD helpers (with in-memory fail-safe mirror)
│       ├── schemas.py               # Strict Pydantic schemas for Gemini Structured Outputs, API requests, & DB states
│       ├── solver.py                # PuLP MILP Multi-Vendor Cost Optimizer + 1,000-Run Monte Carlo Confidence Simulator
│       ├── main.py                  # FastAPI server, CORS, Webhooks (WhatsApp, PLC, ERP CSV, Highway Weather), & Execution
│       └── agents/
│           ├── __init__.py
│           ├── tools.py             # Autonomous tools bound to the 4 agents (SQL queries, memory lookup, solver trigger)
│           └── graph.py             # God-Level 4-Agent LangGraph Cyclic StateGraph (Detective, Ops Hawk, CFO, Arbitrator)
├── frontend/
│   ├── .env.local.example           # Template for NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, NEXT_PUBLIC_API_URL
│   ├── package.json
│   └── src/
│       ├── app/
│       │   ├── layout.tsx           # Dark mode root layout with Inter & JetBrains Mono fonts
│       │   ├── globals.css          # Tailwind + custom React Flow engineering grid & glowing SVG pipe keyframes
│       │   ├── page.tsx             # Main 2.5D Command Center War-Room Page
│       │   └── mobile/
│       │       └── page.tsx         # Option 2 Backup: Pinned Mobile Web Controller Page for instant phone trigger
│       ├── components/
│       │   ├── TopKpiBar.tsx        # Executive status bar, Active Orders, Contract Risk, CSV upload, & Crisis Trigger
│       │   ├── WebhookBar.tsx       # SME Multi-Channel Ingestion Bar (3 Scenario Pills + Live Editable Webhook Input + Highway Poll)
│       │   ├── AgentPipelineStrip.tsx # Visual 4-Agent status strip showing active agent node & tool calls in real time
│       │   ├── FlowCanvas.tsx       # @xyflow/react 2.5D Interactive Node Flow Canvas with 5 nodes & 4 animated SVG edges
│       │   ├── CustomNodes.tsx      # High-density custom telemetry node cards + click-to-inspect SQL drawer
│       │   ├── AgentStream.tsx      # Bottom Live Agent Debate Terminal streaming thoughts & tool calls via Supabase Realtime
│       │   ├── PlaybookSidebar.tsx  # Right sidebar rendering 3 PuLP-verified Playbook cards + HITL Approve button
│       │   └── ExecutionModal.tsx   # HITL Execution Receipt Modal (Tally XML/JSON PO download, WhatsApp Shift Broadcast, SLA Notice)
│       ├── lib/
│       │   └── supabase.ts          # Frontend Supabase client & Realtime subscription helper
│       └── store/
│           └── useFactoryStore.ts   # Zustand store synchronizing React Flow nodes, edges, logs, and playbooks
└── pitch-deck/
    └── cascadezero_ppt_deck.html    # Self-contained 5-slide dark-mode pitch deck with .PPTX and .PDF export buttons
```

---

## 3. DESIGN DIRECTION

* **Visual Aesthetic & Enterprise Inspiration:**
  * Model the interface after **$2M industrial and AI engineering platforms**: **Palantir Foundry**, **LangGraph Studio**, **n8n**, **Linear**, and **Stripe Dashboard**.
  * Ultra-sharp, high-contrast dark mode engineered so hackathon judges can read every rupee figure, temperature, and delay metric from 6 feet away on a projector.
* **Exact Color Tokens (Hex & RGBA):**
  * **App Shell Background:** `#070b14`
  * **2.5D Canvas Background (Engineering Dot Grid):** `#090e1a` with radial dot matrix `rgba(148, 163, 184, 0.16)` (`1.5px` dots spaced `24px × 24px`).
  * **Header & Right Sidebar Surface:** `#0b1120` with border `1px solid rgba(30, 41, 59, 0.9)`.
  * **SME Webhook Ingestion Bar & Agent Pipeline Strip Surface:** `#0d1526`.
  * **Bottom Live Agent Terminal Surface:** `#080d19`.
  * **Semantic Operational State Colors:**
    * **Nominal / On-Track / SLA Protected (Emerald Neon):** Primary `#10b981`, Text/Accent `#34d399`, Node Card Surface `rgba(15, 23, 42, 0.88)` (Normal) or `rgba(10, 30, 24, 0.94)` (Active Recovery), Border `1.5px solid rgba(16, 185, 129, 0.5)` to `2px solid rgba(16, 185, 129, 0.95)`, Box Shadow `0 0 32px rgba(16, 185, 129, 0.4)`.
    * **Compound Crisis / Blocked / Thermal Throttle / Breach Risk (Crimson Rose):** Primary `#f43f5e`, Text/Accent `#fb7185`, Node Card Surface `rgba(28, 12, 20, 0.94)`, Border `1.5px solid rgba(244, 63, 94, 0.9)`, Box Shadow `0 0 32px rgba(244, 63, 94, 0.35)`.
    * **Standby Backup Vendor / Warning (Amber Gold):** Primary `#f59e0b`, Text/Accent `#fbbf24`, Node Card Surface `rgba(24, 22, 16, 0.88)`, Border `1.5px solid rgba(245, 158, 11, 0.55)`.
    * **Parallel Buffer / Overtime Active (Electric Sky/Cyan):** Primary `#38bdf8` / `#22d3ee`, Node Card Surface `rgba(12, 24, 42, 0.92)`, Border `1.5px solid rgba(56, 189, 248, 0.85)`, Box Shadow `0 0 26px rgba(56, 189, 248, 0.28)`.
* **Typography:**
  * **UI & Headers:** `'Inter', sans-serif` (weights 400, 500, 600, 700, 800).
  * **Telemetry, Math, Currency & Agent Terminal Logs:** `'JetBrains Mono', monospace` (weights 400, 500, 600, 700). All rupee figures (`₹25,00,000`, `₹1.8L`, `₹23.2L`), delay hours (`+48h`), machine speeds (`50%`), temperatures (`89°C`), confidence scores (`94.2%`), and tool calls must use `JetBrains Mono`.

---

## 4. FEATURES & BEHAVIOR (COMPLETE SPECIFICATION)

### A. Supabase PostgreSQL Schema & Seed Data (7 Relational Tables)
`supabase/schema.sql` must create and seed the following tables for **Apex Volt EV Battery Plant (Bengaluru Unit-2)** and add them to the `supabase_realtime` publication (`ALTER PUBLICATION supabase_realtime ADD TABLE ...`):

1. **`suppliers` Table:**
   * Columns: `id` (PK text), `name` (text), `tier` (text), `route` (text), `part_name` (text), `inbound_qty` (int), `max_available_qty` (int), `extra_cost_per_unit_inr` (int), `flat_charter_cost_inr` (int), `lead_time_hours` (int), `traffic_risk_pct` (float), `weather_risk_pct` (float), `status` (text), `delay_hours` (int), `updated_at` (timestamptz).
   * Seed Rows:
     * `SUP-CHN-01`: **Chennai Precision Casings Ltd** | `TIER-1` | Route: `NH48 Chennai-Bengaluru Highway` | Inbound: `500` | Max Cap: `500` | Extra Cost: `₹0` | Lead Time: `12h` | Traffic Risk: `5.0%` | Status: `ON_TIME`, `delay_hours: 0`.
     * `SUP-PNY-02`: **Peenya Rapid Metals (Local SME Vendor)** | `TIER-2` | Route: `Peenya Industrial Area (14 km)` | Inbound: `0` | Max Cap: `200` | Extra Cost: `₹600/unit` | Lead Time: `4h` | Traffic Risk: `6.0%` | Status: `STANDBY`, `delay_hours: 0`.
     * `SUP-HSR-03`: **Hosur Precision Castings** | `TIER-3` | Route: `Hosur Industrial Corridor (42 km)` | Inbound: `0` | Max Cap: `180` | Extra Cost: `₹850/unit` | Lead Time: `8h` | Traffic Risk: `8.0%` | Status: `STANDBY`, `delay_hours: 0`.
     * `SUP-AIR-04`: **BlueDart Aviation Charter** | `EMERGENCY-AIR` | Route: `HAL/KEMPEGOWDA Air Cargo Corridor` | Inbound: `0` | Max Cap: `500` | Flat Cost: `₹6,00,000` | Lead Time: `6h` | Weather Risk: `2.0%` | Status: `STANDBY`, `delay_hours: 0`.

2. **`vendor_history` Table (Episodic Memory for Agents):**
   * Columns: `id` (serial PK), `supplier_id` (FK), `past_orders_count` (int), `on_time_deliveries` (int), `reliability_score_pct` (float), `quality_rejection_rate_pct` (float), `last_incident_note` (text).
   * Seed Rows:
     * `SUP-CHN-01`: `48/50` on-time (`96.0%`), `0.5%` rejection, `"Vulnerable to NE Monsoon flooding near Vellore/Ambur."`
     * `SUP-PNY-02`: `14/15` emergency POs fulfilled on time (`93.3%`), `0.8%` rejection, `"Consistent 4h delivery via Tumkur Road; max batch 200 units."`
     * `SUP-HSR-03`: `9/11` on-time (`81.8%`), `2.1%` rejection, `"Border toll bottleneck at Attibele during peak hours."`
     * `SUP-AIR-04`: `5/5` on-time (`98.5%`), `0.0%` rejection, `"Guaranteed priority airfreight slot; high flat charter fee."`

3. **`production_lines` Table:**
   * Columns: `line_id` (PK text), `name` (text), `status` (text), `speed_pct` (int), `temp_celsius` (float), `daily_capacity_units` (int), `overtime_cost_per_hour_inr` (int), `extra_units_per_ot_hour` (int), `max_ot_hours` (int), `updated_at` (timestamptz).
   * Seed Rows:
     * `LINE-1`: **Robotic Welding Line 1** | `NORMAL` | `100%` | `61.0°C` | Cap: `200` | Combined Parallel OT Rate (Lines 1 & 3): `₹22,500/hr` yielding `38 extra units/hr` (up to `8h` max OT).
     * `LINE-2`: **Robotic Welding Line 2** | `NORMAL` | `100%` | `62.0°C` | Cap: `200` (throttles to `50%` speed / `89.0°C` during crisis).
     * `LINE-3`: **Robotic Welding Line 3** | `NORMAL` | `100%` | `60.0°C` | Cap: `150`.

4. **`orders` Table:**
   * Columns: `order_id` (PK text), `client` (text), `required_qty` (int), `deadline_label` (text), `hours_remaining` (int), `sla_penalty_inr` (int), `partial_delay_penalty_inr` (int), `status` (text), `shortfall_units` (int), `updated_at` (timestamptz).
   * Seed Rows:
     * `EV-402`: **Ather-Grid Mobility Corp** | `500 units` | `Friday 17:00 IST (38 Hours Remaining)` | Full SLA Penalty: `₹25,00,000` (`₹25.0L`) | Partial Delay Penalty: `₹5,00,000` (`₹5.0L`) | Status: `ON_TRACK` | Shortfall: `0`.
     * `EV-405`: **Deccan E-Fleet Logistics** | `300 units` | `Monday 12:00 IST (110 Hours Remaining)` | Full SLA Penalty: `₹10,00,000` | Partial Penalty: `₹2,00,000` | Status: `ON_TRACK` | Shortfall: `0`.

5. **`disruption_events` Table:**
   * Stores raw and structured crisis payloads (`id`, `source_channel`, `raw_message`, `delay_hours`, `line2_speed_pct`, `shortfall_units`, `created_at`).

6. **`agent_logs` Table (Realtime Streamed to Terminal):**
   * Columns: `id` (serial PK), `run_id` (text), `step_order` (int), `agent_name` (text), `agent_role` (text), `badge_color` (text), `tool_called` (text), `tool_output_summary` (text), `message` (text), `created_at` (timestamptz).

7. **`purchase_orders` Table (HITL Execution Ledger):**
   * Columns: `po_number` (PK text), `playbook_id` (text), `order_id` (text), `vendor_allocations_json` (jsonb), `overtime_hours` (int), `total_cost_inr` (int), `net_sla_saved_inr` (int), `confidence_pct` (float), `tally_xml_payload` (text), `shift_broadcast_msg` (text), `client_sla_notice` (text), `status` (text), `created_at` (timestamptz).

---

### B. God-Level 4-Agent Adversarial LangGraph Architecture (`backend/app/agents/`)
The core AI engine is a **4-Node Cyclic LangGraph `StateGraph`** (`CascadeGraphState`) with autonomous tool-calling, episodic memory lookup, and an adversarial rebuttal loop:

1. **Agent 1: `🕵️‍♂️ Blast-Radius Detective` (`detective_node` — Amber Badge)**
   * **Tools Bound:**
     * `extract_disruption_entities(raw_text)` — Calls `gemini-2.5-flash` with strict Pydantic `response_schema=DisruptionExtraction` to parse `delay_hours`, `line2_speed_pct`, `line2_temp_celsius`, `shortfall_units`, and `affected_order_id` from messy English/Hinglish text.
     * `query_blast_radius_sql()` — Joins `suppliers`, `production_lines`, and `orders` in Supabase to calculate exact inventory starvation and SLA exposure (`₹25,00,000` on Order `#EV-402`).
   * **Action:** Updates Supabase `suppliers`, `production_lines`, and `orders` to their `CRITICAL` / `BREACH_RISK` states (which immediately turns the 2.5D React Flow nodes crimson red via Supabase Realtime) and logs its causal trace to `agent_logs`.

2. **Agent 2: `⚙️ Operations Hawk` (`ops_hawk_node` — Rose Badge)**
   * **Objective Function:** 100% On-Time SLA Delivery & Zero Line Starvation, regardless of cost.
   * **Tools Bound:**
     * `check_air_charter_and_max_overtime()` — Queries `SUP-AIR-04` (`BlueDart Aviation Charter @ ₹6,00,000`) and maximum shift overtime capacity on Lines 1 & 3.
   * **Action (Round 1 Proposal):** Demands **Plan A (Emergency Air Cargo + Full Overtime)** to eliminate the `₹25.0L` penalty risk.

3. **Agent 3: `💰 CFO Watchdog` (`cfo_watchdog_node` — Cyan Badge)**
   * **Objective Function:** Margin Protection & Working-Capital Optimization without breaching the SLA.
   * **Tools Bound:**
     * `query_regional_vendors_and_memory(shortfall_units)` — Queries `suppliers` (`SUP-PNY-02` Peenya @ `₹600/unit`, cap `200`; `SUP-HSR-03` Hosur @ `₹850/unit`, cap `180`) AND queries `vendor_history` (Episodic Memory: verifying Peenya's `93.3%` historical emergency reliability).
   * **Action (Round 2 Counter-Attack & Conditional Rebuttal Loop):**
     * Directly critiques `Ops Hawk`'s `₹6.0L` air charter spend.
     * **Conditional Edge (`should_rebuttal_continue`):** If `shortfall_units > 200` (exceeding Peenya's 200-unit stock cap, e.g., Scenario 3 with `350 units`), LangGraph routes back for a **Stress-Test Rebuttal Turn** where `Ops Hawk` flags the capacity overflow (`"Peenya caps at 200 units! Where do the remaining 150 casings come from?"`) and `CFO Watchdog` dynamically pulls in Tier-3 `Hosur Precision Castings` (`150 units @ ₹850`) or concedes to Air Charter!

4. **Agent 4: `⚖️ Neuro-Symbolic Arbitrator` (`arbitrator_node` — Emerald Badge)**
   * **Objective Function:** Zero-Hallucination Mathematical Verification & Risk-Adjusted ROI Ranking.
   * **Tools Bound:**
     * `run_pulp_milp_and_monte_carlo(shortfall_units, delay_hours, line2_speed_pct)` — Calls `solver.py` to solve the Mixed-Integer Linear Program (`PuLP`) and run the **1,000-iteration Monte Carlo simulation**.
   * **Action:** Logs the exact LP solver proof (`variables`, `objective_value`, `monte_carlo_confidence_pct`), outputs the 3 ranked Playbooks (`Plan A`, `Plan B`, `Plan C`), and prepares the Tally XML/JSON and WhatsApp execution payloads.

---

### C. Mathematical Optimization (`PuLP`) & 1,000-Run Monte Carlo Solver (`backend/app/solver.py`)
The Python solver must never fake or hardcode recommendations—it must dynamically react to whatever numbers are in the alert text:
* **PuLP Linear Programming Formulation:**
  * **Decision Variables:**
    * $x_{\text{peenya}} \in [0, 200]$ (Integer units from Peenya Tier-2 @ `₹600/unit`)
    * $x_{\text{hosur}} \in [0, 180]$ (Integer units from Hosur Tier-3 @ `₹850/unit`)
    * $x_{\text{air}} \in \{0, 1\}$ (Binary air charter trigger @ `₹6,00,000`)
    * $h_{\text{ot}} \in [2, 8]$ (Integer overtime hours on Lines 1 & 3 @ `₹22,500/hr`, producing `38 units/hr`)
  * **Objective Function:**
    $$\min Z = 600 x_{\text{peenya}} + 850 x_{\text{hosur}} + 600000 x_{\text{air}} + 22500 h_{\text{ot}}$$
  * **Constraints:**
    * Supply constraint: $x_{\text{peenya}} + x_{\text{hosur}} + 500 x_{\text{air}} \ge \text{shortfall\_units}$ (when `delay_hours > 12`)
    * Shop-floor capacity constraint: $38 \times h_{\text{ot}} \ge \text{shortfall\_units}$
* **1,000-Iteration Monte Carlo Risk Simulation:**
  * Simulates 1,000 stochastic realizations of route traffic delay ($\mathcal{N}(\mu_{\text{lead}}, \sigma_{\text{traffic}}^2)$), weather delay risk, and Line 2 thermal variance against the `38-hour` SLA deadline window to compute the exact `confidence_pct` (`SLA Survival Probability %`, e.g., `94.2%` for Plan B, `98.4%` for Plan A, `97.1%` for Plan C minor overtime).
* **Dynamic Winner Across All 3 Benchmark Scenarios (Skeptic Judge Test):**
  1. **Scenario 1 (Standard Compound Crisis: `48h delay`, `50% Line 2 speed`, `150 units shortfall`):**
     * **Plan B Wins (`RECOMMENDED OPTIMAL ROI`):** `150 units` from Peenya (`₹90,000`) + `4h` Overtime on Lines 1 & 3 (`₹90,000`) = **₹1.8L** (`₹1,80,000`) cost | Saves **₹23.2L** (`13.9x ROI`) | Confidence: **~94.2%**.
     * **Plan A (`OPS HAWK CHOICE`):** BlueDart Air Charter + Overtime = **₹6.0L** (`₹6,00,000`) cost | Saves **₹19.0L** (`4.2x ROI`) | Confidence: **~98.4%**.
     * **Plan C (`PASSIVE FALLBACK`):** Partial SLA Delay Renegotiation (pay 20% extension penalty) = **₹5.0L** (`₹5,00,000`) cost | Saves **₹20.0L** (`5.0x ROI`) | Confidence: **~78.0%**.
  2. **Scenario 2 (Minor Disruption: `6h delay`, `85% Line 2 speed`, `25 units shortfall`):**
     * **Plan C Wins (`OPTIMAL FOR MINOR DELAY`):** **Targeted 2h Shift Overtime Only** (`₹0` extra supplier spend + `2h × ₹22,500` = **₹0.45L** / `₹45,000` cost) | Saves **₹24.55L** (`55.6x ROI`) | Confidence: **~97.1%**.
  3. **Scenario 3 (Severe Supplier Collapse: `72h delay`, `25% Line 2 speed`, `350 units shortfall`):**
     * Peenya hits its `200-unit` maximum cap! The PuLP solver automatically allocates **200 units from Peenya + 150 units from Hosur Precision + 8h Overtime** (`200×600 + 150×850 + 8×22500 = ₹4.28L`) OR recommends **Plan A (Air Charter)** if Hosur lead time + thermal risk drops Plan B's Monte Carlo confidence below threshold!

---

### D. The 4 Real-World SME Data Bridges & Phone Triggers
1. **Bridge 1: Live Physical Phone WhatsApp Webhook (`POST /api/v1/webhooks/whatsapp`):**
   * Accepts Twilio WhatsApp Sandbox form data (`Body`, `From`) or JSON. Triggers the full LangGraph + PuLP pipeline and returns a TwiML XML reply to the user's phone with the recommended Playbook and ROI.
2. **Bridge 2: Mobile Web Controller Backup Page (`http://<laptop-ip>:3000/mobile`):**
   * A dedicated, sleek mobile control panel in Next.js with 3 tactile trigger buttons + custom input box so the presenter can trigger the live dashboard from their phone over local Wi-Fi even if cellular carrier SMS/ngrok is blocked in the auditorium.
3. **Bridge 3: Shop-Floor PLC Telemetry Producer (`backend/simulator_plc.py` -> `POST /api/v1/ingest/plc-telemetry`):**
   * Standalone terminal script that streams realistic machine telemetry ticks (`temp_celsius` rising `62°C -> 74°C -> 89°C`, `speed_pct` dropping `100% -> 50%`) into FastAPI.
4. **Bridge 4: Legacy Tally / Excel Folder-Watcher (`backend/cascade_sync.py` -> `POST /api/v1/ingest/erp-csv`) + Live Highway Weather Check (`POST /api/v1/ingest/live-highway-check`):**
   * `cascade_sync.py` watches `backend/watched_erp_folder/` for CSV/XML order updates and syncs them automatically.
   * `/api/v1/ingest/live-highway-check` polls live OpenWeatherMap / highway conditions along the NH48 corridor (with deterministic fallback if no weather key is set).

---

### E. 2.5D Interactive Node Flow Canvas & War-Room UI Layout (`frontend/`)
1. **Top Executive KPI Bar (`TopKpiBar.tsx`):**
   * Left: Glowing status indicator dot + `CASCADEZERO` brand + Dynamic Status Pill (`STATUS: NORMAL OPERATIONS` in emerald $\rightarrow$ `STATUS: CRISIS (COMPOUND DISRUPTION)` in crimson $\rightarrow$ `STATUS: SLA PROTECTED (PLAN X EXECUTED)` in emerald).
   * Right: `Active Orders: 5`, `Contract Risk: ₹0` (flips to `-₹25,00,000` in crimson, then `₹0 (Saved ₹23.2L)` in emerald), **`[🔴 Simulate Crisis]`** button, **`[📄 View Dispatched PO & Notices]`** button (appears after approval), **`[📤 Upload ERP CSV]`** button, `Reset` button, and live connection badge (`SUPABASE REALTIME + PULP LP LIVE`).
2. **SME Multi-Channel Webhook Bar (`WebhookBar.tsx`) & 4-Agent Pipeline Strip (`AgentPipelineStrip.tsx`):**
   * 3 one-click scenario pills (`1. Flood (48h / 150u)`, `2. Minor (6h / 25u)`, `3. Severe (72h / 350u)`), **`[🌦️ Poll NH48 Weather]`** button, and a **live editable text input box** so judges can type any custom delay hours or unit shortfall.
   * Directly below: The **4-Agent Pipeline Strip** showing `🕵️‍♂️ 1. Detective` $\rightarrow$ `⚙️ 2. Ops Hawk ⚡vs⚡ 💰 3. CFO Watchdog` $\rightarrow$ `⚖️ 4. Arbitrator + PuLP LP`, highlighting each agent and its active tool call as it executes.
3. **Center 2.5D React Flow Canvas (`FlowCanvas.tsx` & `CustomNodes.tsx`):**
   * 5 Custom Draggable/Inspectable Telemetry Nodes arranged Left-to-Right with 4 animated SVG connecting pipes:
     * **Node 1 (Top-Left):** `🚚 NH48 CHENNAI SUPPLY` (`SUP-CHN-01`) — Tier-1 badge, status headline, delay hours, inbound batch (`500 Casings`).
     * **Node 2 (Bottom-Left):** `⚡ PEENYA + HOSUR BACKUP` (`SUP-PNY-02` / `SUP-HSR-03`) — `14 KM` badge, standby pricing (`₹600/u`), available stock & PO dispatch status.
     * **Node 3 (Center-Top):** `🔥 WELDING LINE 2` (`LINE-2`) — `PLC-L2` badge, speed %, unit loss (`-150 Units`), live temperature (`62°C` $\rightarrow$ `89°C`).
     * **Node 4 (Center-Bottom):** `⚡ LINES 1 & 3 (PARALLEL)` (`LINE-1` & `LINE-3`) — `BUFFER` badge, shift capacity, overtime status (`+4h Overtime Standby @ ₹22.5k/h`).
     * **Node 5 (Right):** `🚨 ORDER #EV-402 SLA` (`EV-402`) — Client (`Ather-Grid`), deadline (`Friday 17:00`), unit shortfall, and SLA penalty exposure (`₹0` $\rightarrow$ `₹25,00,000` $\rightarrow$ `Saved ₹23.2L`).
   * **Click-to-Inspect Node Drawer:** Clicking any of the 5 nodes opens an inspection panel displaying its live Supabase SQL record and historical reliability metrics from `vendor_history`.
4. **Bottom Live Agent Debate Terminal (`AgentStream.tsx`):**
   * Streams each agent's reasoning and **exact tool call telemetry** (`⚡ Tool: query_regional_vendors_and_memory -> Peenya 93.3% reliability`) with a live solve timer (`Solved in X.XXs`).
5. **Right Sidebar: 3 Audited Playbook Cards (`PlaybookSidebar.tsx`):**
   * Displays `✓ Math Verified by Python LP Solver` badge.
   * Renders **Plan A**, **Plan B**, and **Plan C** with Mitigation Cost, Net SLA Saved, ROI Multiplier, and **Monte Carlo SLA Confidence %**.
   * Highlights the winning playbook in glowing emerald with the **`[APPROVE & EXECUTE]`** button.
6. **HITL Execution Complete Modal (`ExecutionModal.tsx`):**
   * Pops open upon clicking **`[APPROVE & EXECUTE]`** and displays:
     1. **Tally Prime XML / JSON Purchase Order (`PO-APEX-2026-889`)** with real working **`[⬇ Download Tally PO (.JSON)]`** and **`[⬇ Download Tally XML (.XML)]`** buttons.
     2. **WhatsApp Business Shift Supervisor Broadcast** (Lines 1 & 3 overtime dispatch confirmation).
     3. **Client SLA Compliance Notice** (sent to Ather-Grid Mobility Corp).

---

## 5. DECISIONS MADE

1. **Pure 2.5D Interactive Node Flow (`@xyflow/react`) Over 3D Isometric (`Three.js`):** Chosen for instant executive readability from 6 feet away, Palantir/Linear visual authority, and zero WebGL performance overhead.
2. **Production Multi-Tier Architecture Over Toy Single-File HTML:** Scrapped the early single-file prototype completely in favor of **Supabase PostgreSQL + Realtime + FastAPI + LangGraph + PuLP + Next.js/React Flow**.
3. **God-Level 4-Agent Cyclic LangGraph Over Single Prompt:** Implemented autonomous tool-calling, episodic vendor reliability memory (`vendor_history`), and a conditional rebuttal loop between `Ops Hawk` and `CFO Watchdog`.
4. **Neuro-Symbolic Math Guardrail (`PuLP` MILP + 1,000-Run Monte Carlo):** Guaranteed zero LLM arithmetic hallucination and dynamic multi-vendor allocation when a judge tests numbers exceeding a single vendor's capacity cap.
5. **Dual Live Phone Triggers (Option 1 Twilio WhatsApp Webhook + Option 2 `/mobile` Web Controller):** Gives the presenter the ultimate live WhatsApp flex on stage while providing a 100% auditorium-Wi-Fi-proof mobile web trigger backup.
6. **Zero-Crash Resilient Architecture:** Both `db.py` and the frontend store include an automatic in-memory/local mirror so even if venue internet or an external API key drops mid-pitch, the PuLP solver, agent debate, and 2.5D canvas never crash or hang.

---

## 6. OPEN QUESTIONS

* **No Architectural Questions Remain.**
* **API Keys Setup:** During the build steps, the user will add their `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `GEMINI_API_KEY` into `backend/.env` and `frontend/.env.local` (and `TWILIO_*` credentials in Step 6). Ensure the code starts cleanly and works immediately even before optional keys are pasted by using clean `.env` loading with automatic local mirror fallbacks.

---

## 7. ASSETS & EXTERNAL DEPENDENCIES

* **Backend (`backend/requirements.txt`):**
  ```text
  fastapi>=0.115.0
  uvicorn[standard]>=0.32.0
  pydantic>=2.9.0
  python-dotenv>=1.0.1
  python-multipart>=0.0.12
  supabase>=2.10.0
  google-genai>=1.0.0
  langgraph>=0.2.50
  langchain-core>=0.3.15
  pulp>=2.9.0
  twilio>=9.3.0
  httpx>=0.27.2
  ```
* **Frontend (`frontend/package.json` dependencies):**
  * `next`, `react`, `react-dom`, `typescript`
  * `@xyflow/react`
  * `@supabase/supabase-js`
  * `zustand`
  * `lucide-react`
  * `tailwindcss`, `postcss`, `autoprefixer`, `clsx`, `tailwind-merge`

---

## 8. PROPOSED BUILD ORDER (STRICT STEP-BY-STEP EXECUTION)

> **CRITICAL RULE FOR AGENT:** Execute **ONLY ONE STEP AT A TIME**. After providing the complete files and terminal verification commands for Step $N$, **STOP AND WAIT** for the user to confirm Step $N$ works before generating Step $N+1$.

### Step 1: Supabase PostgreSQL Schema, Realtime Setup & Backend DB Layer
* **Deliverables:**
  1. `supabase/schema.sql` (All 7 tables, Realtime publications, and Apex Volt EV Battery Plant seed data).
  2. `backend/requirements.txt` and `backend/.env.example`.
  3. `backend/app/config.py` and `backend/app/db.py` (Supabase client connection + automatic in-memory fallback mirror so tests always pass).
* **Verification:** User runs `schema.sql` in Supabase SQL Editor, installs `requirements.txt`, and runs `python -m app.db` to verify all seeded suppliers, lines, vendor history, and orders print cleanly in the terminal.

### Step 2: Pydantic Schemas, PuLP Linear Programming Optimizer & Monte Carlo Risk Engine
* **Deliverables:**
  1. `backend/app/schemas.py` (Strict Pydantic models for `DisruptionExtraction`, `VendorAllocation`, `PlaybookOption`, `AgentLogEntry`, and API requests).
  2. `backend/app/solver.py` (The `PuLP` MILP multi-vendor + overtime solver and the 1,000-iteration Monte Carlo confidence simulator).
* **Verification:** User runs `python -m app.solver` in the terminal to verify the exact mathematical output and confidence scores across all 3 scenarios (Scenario 1: 150u -> Plan B ₹1.8L wins; Scenario 2: 25u -> Plan C ₹0.45L OT-only wins; Scenario 3: 350u -> Multi-tier Peenya+Hosur / Plan A wins).

### Step 3: God-Level 4-Agent LangGraph Engine & FastAPI Webhook Server
* **Deliverables:**
  1. `backend/app/agents/tools.py` (Autonomous agent tools: SQL blast-radius query, vendor + episodic memory lookup, air charter lookup, and PuLP + Monte Carlo invocation).
  2. `backend/app/agents/graph.py` (The 4-Node cyclic LangGraph `StateGraph` with `Detective`, `Ops Hawk`, `CFO Watchdog`, conditional rebuttal edge, and `Arbitrator`, using `gemini-2.5-flash`).
  3. `backend/app/main.py` (FastAPI server exposing `/api/v1/state`, `/api/v1/simulate-crisis`, `/api/v1/webhooks/whatsapp`, `/api/v1/ingest/plc-telemetry`, `/api/v1/ingest/erp-csv`, `/api/v1/ingest/live-highway-check`, `/api/v1/execute-plan`, and `/api/v1/reset`).
* **Verification:** User runs `python -m app.main` (`http://localhost:8000/docs`), tests `/api/v1/simulate-crisis`, and sees the 4-agent tool calls, rebuttal loop, and playbooks execute and persist to Supabase.

### Step 4: Next.js + `@xyflow/react` 2.5D Interactive Node Flow Canvas & Zustand Realtime Store
* **Deliverables:**
  1. Scaffold `frontend/` (`package.json`, `globals.css`, `layout.tsx`, `src/lib/supabase.ts`, `src/store/useFactoryStore.ts` with Supabase Realtime `postgres_changes` listener).
  2. `src/components/TopKpiBar.tsx`, `src/components/WebhookBar.tsx`, and `src/components/AgentPipelineStrip.tsx`.
  3. `src/components/CustomNodes.tsx` and `src/components/FlowCanvas.tsx` (The 5 custom 2.5D telemetry nodes, animated SVG pipes, and click-to-inspect SQL drawer).
* **Verification:** User runs `npm run dev` (`http://localhost:3000`) and verifies the 2.5D React Flow canvas, draggable/zoomable nodes, and live inspection drawer.

### Step 5: Live Agent Debate Terminal, Audited Playbooks Sidebar & HITL Tally PO Modal
* **Deliverables:**
  1. `src/components/AgentStream.tsx` (Bottom live terminal showing agent tool calls, arguments, and solve timer).
  2. `src/components/PlaybookSidebar.tsx` (Right sidebar with the 3 PuLP + Monte Carlo verified playbook cards and `[APPROVE & EXECUTE]` button).
  3. `src/components/ExecutionModal.tsx` (HITL receipt modal with working `.JSON` and `.XML` Tally Purchase Order downloads, WhatsApp shift broadcast, and SLA compliance notice).
  4. Complete `src/app/page.tsx` assembling the full Command Center War-Room.
* **Verification:** User clicks `[Simulate Crisis]`, tests Scenarios 1, 2, and 3, watches the 4 agents debate and update the 2.5D canvas, clicks `[APPROVE & EXECUTE]`, and downloads the Tally Purchase Order.

### Step 6: Live Phone Trigger (`Twilio WhatsApp + /mobile`), PLC Emulator & ERP Folder Sync
* **Deliverables:**
  1. `frontend/src/app/mobile/page.tsx` (Mobile Web Controller for instant phone triggering over Wi-Fi/tunnel).
  2. `backend/simulator_plc.py` (Live shop-floor machine overheating & speed-drop streamer).
  3. `backend/cascade_sync.py` + `backend/watched_erp_folder/sample_tally_orders.csv` (Live Tally/CSV folder watcher).
  4. Step-by-step instructions to run `ngrok http 8000` and paste the webhook URL into the Twilio WhatsApp Sandbox so the user's physical phone triggers the dashboard live via WhatsApp.
* **Verification:** User triggers a crisis from their physical phone (via WhatsApp and `/mobile`) and watches the laptop dashboard react live in real time.

---

## 9. USER WORKING PREFERENCES

1. **Consult Before Major Decisions:** Always ask before changing any agreed architectural pattern.
2. **Strict One-Step-at-a-Time Pacing:** Deliver **only one step at a time** from Section 8. Explain what is being created, provide the exact terminal commands and complete code files, and **wait for user confirmation** before moving to the next step.
3. **Complete Files Only:** Always output complete, copy-paste-ready files from top to bottom. Never use placeholders or partial code snippets.
4. **Immediate Start Instruction:** When the user pastes this brief into Antigravity, acknowledge the architecture briefly and immediately begin **Step 1 (Supabase PostgreSQL Schema, Realtime Setup & Backend DB Layer)**.
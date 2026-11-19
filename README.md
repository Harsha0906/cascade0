# CascadeZero — Neuro-Symbolic AI Crisis Control Tower & 2.5D Digital Twin

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-black.svg?style=flat&logo=next.js)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![PuLP](https://img.shields.io/badge/PuLP-MILP%20Solver-blue.svg?style=flat)](https://coin-or.github.io/pulp/)
[![Supabase](https://img.shields.io/badge/Supabase-Realtime%20Postgres-3ECF8E.svg?style=flat&logo=supabase)](https://supabase.com)
[![TailwindCSS](https://img.shields.io/badge/Tailwind-Rinesk%20Glass-38B2AC.svg?style=flat&logo=tailwind-css)](https://tailwindcss.com)

> **Disruption-response copilot and digital twin for discrete manufacturing (demo plant).**  
> Pairs an **LLM for reading messy alerts and narrating decisions (Gemini, configurable)** with a **PuLP mixed-integer program and Monte Carlo simulation** that make every numeric decision, so the LLM never does the arithmetic. A human approves every plan.

---

## ⚡ The Core Problem: Why LLM-Only Agents Fail in Factories

When an Indian EV battery plant faces compound disruptions (e.g., an NH48 highway flood delaying battery casing trucks while Robotic Welding Line 2 throttles due to thermal overheating), standard generative AI agents fail catastrophically:

1. **Arithmetic Hallucinations:** Generative LLMs cannot reliably perform constrained optimization over 15+ variables (overtime rates, transit delays, tier-2 vendor pricing, SLA penalty tiers).
2. **Subjective Bias:** An operations prompt will charter expensive air freight (\$7,000 flat) to avoid SLA delays; a financial prompt will hoard capital and cause customer SLA breach.
3. **No Shop-Floor Verification:** Generative chat outputs cannot generate valid Tally Prime XML accounting vouchers or Modbus PLC machine speed commands.

### The CascadeZero Solution: Neuro-Symbolic Multi-Agent Architecture

```
                  ┌──────────────────────────────────────────────┐
                  │          UNSTRUCTURED DISRUPTION FEED        │
                  │  (Driver text / simulated PLC / ERP CSV)     │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │          BLAST-RADIUS DETECTIVE AGENT        │
                  │    • Gemini Entity Extractor (NLP)           │
                  │    • Causal Graph SQL Blast-Radius Mapper    │
                  └──────────────────────┬───────────────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   │                                           │
                   ▼                                           ▼
   ┌───────────────────────────────┐           ┌───────────────────────────────┐
   │     OPERATIONS HAWK AGENT     │           │       CFO WATCHDOG AGENT      │
   │  • Objective: Minimize Delay  │ ◄───────► │  • Objective: Maximize Margin │
   │  • Demands: BlueDart Air Cargo│  REBUTTAL │  • Vetoes Air Charter Waste   │
   │  • Authorizes 8h Max Overtime │   CYCLE   │  • Demands Peenya Regional SME│
   └───────────────┬───────────────┘           └───────────────┬───────────────┘
                   │                                           │
                   └─────────────────────┬─────────────────────┘
                                         │ Competing Proposals
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │       MATHEMATICAL ARBITRATOR AGENT          │
                  │    • Symbolic PuLP MILP Optimization Solver  │
                  │    • 1,000-run seeded Monte Carlo            │
                  │    • Ranks by risk-adjusted expected cost    │
                  └──────────────────────┬───────────────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   │                                           │
                   ▼                                           ▼
   ┌───────────────────────────────┐           ┌───────────────────────────────┐
   │   2.5D DIGITAL TWIN COCKPIT   │           │      HITL ONE-TAP EXECUTION   │
   │  • Organic Sage Glass (Rinesk)│           │  • Draft Tally Prime XML PO   │
   │  • Executive vs Studio Views  │           │  • Draft shift notice (text)  │
   │  • Custom Scenario Sandbox    │           │  • Draft client SLA notice    │
   └───────────────────────────────┘           └───────────────────────────────┘
```

---

## 🌟 Key Capabilities

### 1. 👔 Executive Story View vs 🏭 2.5D Twin Studio
- **Executive Mode:** Eliminates cognitive clutter. Shows the plain-English crisis narrative, the Ops vs. CFO debate summary, the PuLP mathematical proof, and a single thumb-friendly **`[⚡ APPROVE PLAN B & EXECUTE]`** action.
- **2.5D Twin Studio:** Interactive React Flow canvas depicting real-time causal blast radii from Chennai, Peenya, and Hosur to Welding Lines 1, 2, and 3.

### 2. 🎛️ Custom Crisis Scenario Studio
- **Preset Scenarios:** NH48 Highway Flood (150 casings), Severe Cyclone Collapse (350 casings with automatic multi-agent rebuttal loop), Attibele Border Toll Strike (180 casings).
- **Freeform Natural Language:** Type any custom message (*e.g., "Truck breakdown near Krishnagiri, 120 casings short on EV-402, Line 2 running at 50%"*).
- **Interactive Sliders:** Adjust shortfall units (25–450u), transit delay (6–96h), and machine thermal degradation on the fly.

### 3. 🏭 Real Shop-Floor SME Integration
- **`cascade_sync.py`:** Watches local on-premise folders for exported Tally ERP / Excel CSV sheets.
- **`simulator_plc.py`:** Generates *synthetic* thermal and speed ticks and POSTs them as JSON over HTTP. It does not speak Modbus/OPC-UA; a real plant needs an edge collector.
- **Draft Tally Prime XML PO:** One Purchase Order voucher per supplier, XML-escaped, with party and inventory entries. Not yet validated against a live Tally instance; ledgers/stock item must exist and GST ledgers are not included.

### 4. 📱 Mobile Field Controller (`/mobile`)
- Dedicated handheld web UI for shop-floor supervisors with one-tap scenario injection and instant recovery authorization.

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10+
- Node.js 18+
- Supabase Account (Free Tier)
- Gemini API Key

### 1. Clone & Set Up Backend

```bash
git clone https://github.com/Harsha0906/cascade0.git
cd cascade0/backend

# Install Python dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env: SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY, CASCADE_API_KEY

# Start FastAPI server
python -m app.main
```
Backend runs at: `http://localhost:8000`

### 2. Set Up Frontend

```bash
cd ../frontend

# Install Node dependencies
npm install

# Configure environment (set CASCADE_API_KEY to the same value as the backend; server-side only)
cp .env.local.example .env.local

# Start Next.js dev server
npm run dev
```
Frontend runs at: `http://localhost:3000`  
Mobile Field Controller: `http://localhost:3000/mobile`

### 3. Database

Run `supabase/schema.sql`, then `supabase/migrations/001_rls_and_audit.sql` in the Supabase SQL editor.
The migration enables Row-Level Security (browser = read-only) and adds approval audit columns.
After it, backend writes require `SUPABASE_SERVICE_ROLE_KEY`.

### 4. Run the Tests

```bash
cd ../backend
python -m unittest discover -s tests -t .
```
Offline suite (no Supabase, LLM or WhatsApp calls): solver correctness, infeasibility reporting,
ranking, Monte Carlo sensitivity, Tally XML well-formedness, API auth, webhook signatures,
WhatsApp approver allowlist, idempotent execution and CSV import.

`python test_step6.py` is a separate **live** smoke test that uses the keys in `.env`. It covers:
- Legacy Tally CSV Ingestion
- PLC Overheat Telemetry
- Phone WhatsApp Webhook Emulation
- Multi-Agent Audit Trail Verification
- HITL Tally XML Purchase Order Generation
- Factory Seed Reset

---

## ✅ What Is Real vs Simulated

| Component | Status |
|---|---|
| MILP allocation (vendors, overtime, deadline feasibility, Line 2 throughput gap) | Real (PuLP + HiGHS/CBC). Infeasible inputs are reported, not hidden |
| Plan ranking | Real: argmin of `cost + (1 − P_on_time) × SLA penalty` |
| Monte Carlo on-time probability | Real, seeded; distributions are **assumptions** for the demo plant |
| **Sourcing Agent** | Real agent loop: sends enquiries (not orders) to the vendors in a plan, reads replies (Gemini or regex, English/Hinglish), and re-plans with confirmed capacity/price/ETA, asking the next vendor when one declines, offers less, or times out (max 3 rounds). WhatsApp or simulated channel |
| Ops ⇄ CFO debate | Proposals are solver outputs; the rebuttal fires on computed risk (weak vendor, infeasibility, confidence gap) and the CFO re-solves |
| LLM | Extracts parameters from free text and narrates. The UI shows when it fell back to regex/templates |
| Vendor costs, capacities, lead times | Loaded per factory from the database (`suppliers`, `vendor_history`, `production_lines`, `factories`) |
| PLC telemetry | Simulated, HTTP JSON |
| Weather | OpenWeatherMap city weather if a key is set; otherwise shown as offline |
| WhatsApp | Meta Cloud API with HMAC verification; approvals only from allow-listed numbers |
| Execution | Generates **drafts** (Tally XML, notices). Nothing is sent to suppliers automatically |

## 🤝 Sourcing Agent

The planner's vendor numbers are assumptions; the Sourcing Agent replaces them with what vendors actually say.

1. After an analysis, click **Confirm with suppliers first** (dashboard) or `POST /api/v1/sourcing/start {run_id}`.
2. The agent sends an enquiry to each vendor in the chosen plan — explicitly *not* a purchase order.
3. Replies arrive over WhatsApp (`SOURCING_MODE=whatsapp`, vendor numbers in `suppliers.whatsapp_number`) or are typed on the dashboard (simulated mode, or a reply received by phone).
4. Each reply becomes a structured offer. Declines and timeouts remove that vendor; partial or re-priced offers update capacity, price and lead time for this run only.
5. When no enquiry is outstanding it re-solves. If the best plan needs an unconfirmed vendor, it asks that vendor (next round); otherwise it hands a **confirmed plan** back for human approval (`<run_id>-S<round>`).

Only one PO can ever be created per analysis — the original run and its sourced re-plan share an idempotency key.
Apply `supabase/migrations/002_sourcing_agent.sql` for vendor numbers and the enquiry audit table, then `supabase/migrations/003_factory_model.sql` (must be applied after 002) for the per-factory model the planner reads.

## 🔐 Security Setup

- `CASCADE_API_KEY` gates every mutating endpoint. The Next.js middleware injects it server-side; it never reaches the browser. This is an operator-level gate, not per-user auth.
- `META_APP_SECRET` verifies WhatsApp webhook signatures; `WA_APPROVER_NUMBERS` lists who may approve.
- `ALLOWED_ORIGINS` replaces the old `*` CORS policy.
- `CASCADE_ENV=production` refuses to start if any of the above is missing, and disables `/reset` and the Twilio sandbox.
- Execution uses the plan the server computed for a `run_id`, once per run. Costs are never accepted from the client.

## 🏗️ Repository Architecture

```
cascade0/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── graph.py          # LangGraph 4-Agent Cyclic StateGraph
│   │   │   └── tools.py          # SQL Blast-Radius, Vendor Memory & Gemini Extraction
│   │   ├── config.py             # Pydantic v2 Environment Settings
│   │   ├── db.py                 # Supabase Realtime Client & Seed Engine
│   │   ├── main.py               # FastAPI Endpoints & Webhook Gateways
│   │   ├── schemas.py            # Pydantic Request/Response Models
│   │   └── solver.py             # PuLP MILP Solver & Tally XML Generators
│   ├── cascade_sync.py           # On-Premise Tally Folder Watcher Daemon
│   ├── simulator_plc.py          # Shop-Floor Machine Telemetry Streamer
│   └── test_step6.py             # 6-Step End-to-End Verification Suite
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx          # Dual-Mode Command Center (Executive + Twin)
│   │   │   ├── mobile/page.tsx   # Handheld Mobile Field Controller
│   │   │   └── globals.css       # Anastasia Cherniak "Rinesk" Design System
│   │   ├── components/
│   │   │   ├── TopKpiBar.tsx     # View Mode Switcher & Financial Risk Header
│   │   │   ├── ExecutiveStoryView.tsx # Streamlined 3-Step Decision Flow
│   │   │   ├── CrisisSandboxModal.tsx # Freeform & Slider Crisis Injector
│   │   │   ├── FlowCanvas.tsx    # 2.5D React Flow Digital Twin Canvas
│   │   │   ├── CustomNodes.tsx   # Industrial Supply Chain & Machine Nodes
│   │   │   ├── AgentStream.tsx   # Live Autonomous Agent Audit Trail
│   │   │   ├── PlaybookSidebar.tsx # Multi-Plan Trade-Off Comparison
│   │   │   └── ExecutionModal.tsx# Draft Tally XML PO & notices
│   │   └── store/
│   │       └── useFactoryStore.ts# Zustand Global Factory State & Realtime Sync
│
├── supabase/
│   ├── schema.sql                # Tables & seed data
│   └── migrations/               # Row-Level Security & audit columns
├── PRODUCTION_ROADMAP.md         # Commercial B2B SaaS Architecture Blueprint
├── run.md                        # Master Startup & Daemon Command Guide
└── README.md
```

---

## 📄 License
MIT License. Built for industrial discrete manufacturing and resilient AI operations.

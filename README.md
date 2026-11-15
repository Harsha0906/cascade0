# CascadeZero — Neuro-Symbolic AI Crisis Control Tower & 2.5D Digital Twin

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-black.svg?style=flat&logo=next.js)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![PuLP](https://img.shields.io/badge/PuLP-MILP%20Solver-blue.svg?style=flat)](https://coin-or.github.io/pulp/)
[![Supabase](https://img.shields.io/badge/Supabase-Realtime%20Postgres-3ECF8E.svg?style=flat&logo=supabase)](https://supabase.com)
[![TailwindCSS](https://img.shields.io/badge/Tailwind-Rinesk%20Glass-38B2AC.svg?style=flat&logo=tailwind-css)](https://tailwindcss.com)

> **Autonomous Multi-Agent Disruption Arbitrator & Digital Twin for Discrete Manufacturing.**  
> Solves high-stakes industrial supply-chain failures by pairing **LLM cognitive perception (Gemini 3.8 Flash)** with **deterministic mathematical optimization (PuLP MILP)** to eliminate arithmetic hallucinations.

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
                  │  (Driver Text / IoT Sensor / Toll FASTag)    │
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
                  │    • 1,000 Monte Carlo Stochastic Simulations│
                  │    • Zero Arithmetic Hallucination Proof     │
                  └──────────────────────┬───────────────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   │                                           │
                   ▼                                           ▼
   ┌───────────────────────────────┐           ┌───────────────────────────────┐
   │   2.5D DIGITAL TWIN COCKPIT   │           │      HITL ONE-TAP EXECUTION   │
   │  • Organic Sage Glass (Rinesk)│           │  • Native Tally Prime XML PO  │
   │  • Executive vs Studio Views  │           │  • Shift Supervisor SMS Alerts│
   │  • Custom Scenario Sandbox    │           │  • Client SLA Protection Notice│
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
- **`simulator_plc.py`:** Generates live Modbus/OPC-UA thermal and speed ticks simulating overheating welding robots.
- **Automated Tally Prime XML PO:** Produces schema-compliant accounting vouchers directly importable into Tally ERP 9 / Tally Prime.

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
# Edit .env with your SUPABASE_URL, SUPABASE_SERVICE_KEY, and GEMINI_API_KEY

# Start FastAPI server
python -m app.main
```
Backend runs at: `http://localhost:8000`

### 2. Set Up Frontend

```bash
cd ../frontend

# Install Node dependencies
npm install

# Configure environment
cp .env.local.example .env.local

# Start Next.js dev server
npm run dev
```
Frontend runs at: `http://localhost:3000`  
Mobile Field Controller: `http://localhost:3000/mobile`

### 3. Run Automated System Test Suite

```bash
cd ../backend
python test_step6.py
```
Runs 6 end-to-end integration tests:
- Legacy Tally CSV Ingestion
- PLC Overheat Telemetry
- Phone WhatsApp Webhook Emulation
- Multi-Agent Audit Trail Verification
- HITL Tally XML Purchase Order Generation
- Factory Seed Reset

---

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
│   │   │   └── ExecutionModal.tsx# Tally XML PO Receipt & SMS Dispatcher
│   │   └── store/
│   │       └── useFactoryStore.ts# Zustand Global Factory State & Realtime Sync
│
├── supabase/
│   └── migrations/               # PostgreSQL Tables & Row-Level Security
├── PRODUCTION_ROADMAP.md         # Commercial B2B SaaS Architecture Blueprint
├── run.md                        # Master Startup & Daemon Command Guide
└── README.md
```

---

## 📄 License
MIT License. Built for industrial discrete manufacturing and resilient AI operations.

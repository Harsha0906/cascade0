# 🚀 CascadeZero — Quick Run & Execution Guide

CascadeZero is an Autonomous AI Crisis Control Tower & 2.5D Digital Twin for high-stakes manufacturing operations.

---

## ⚡ Quick Start (2-Terminal Startup)

### Terminal 1: FastAPI Backend
```powershell
cd "c:\Users\harsh\Desktop\cascade 0\cascadezero\backend"
python -m app.main
```
> **Backend runs on:** `http://localhost:8000` (or `http://0.0.0.0:8000`)  
> **Interactive Swagger API Docs:** `http://localhost:8000/docs`

---

### Terminal 2: Next.js Frontend (Anastasia Cherniak "Rinesk" UI)
```powershell
cd "c:\Users\harsh\Desktop\cascade 0\cascadezero\frontend"
npm run dev
```
> **Desktop Control Tower:** `http://localhost:3000`  
> **Mobile Field Controller:** `http://localhost:3000/mobile`  
> *(To open on your physical phone, connect phone to same Wi-Fi and open `http://<YOUR_PC_IP>:3000/mobile`, e.g. `http://192.168.1.5:3000/mobile`)*

---

## 🧪 Run Automated End-to-End Integration Tests
Validates all 6 steps: ERP ingestion, PLC telemetry, WhatsApp webhook parsing, LangGraph 4-agent debate, PuLP MILP solver, Tally XML generation, and Supabase clean reset:

```powershell
cd "c:\Users\harsh\Desktop\cascade 0\cascadezero\backend"
python test_step6.py
```

---

## 📱 Live WhatsApp Bot Integration (Meta Official Cloud API & Twilio)

CascadeZero supports both **Meta's Official WhatsApp Cloud API (Native Interactive Buttons)** and Twilio Sandbox.

### A. Meta WhatsApp Business Cloud API (Recommended — 1,000 Free Chats/Mo Forever)

1. **Start Zero-Install Public Tunnel:**
   ```powershell
   npx localtunnel --port 8000
   ```
   *(e.g. outputs: `https://swift-otter-42.loca.lt`)*

2. **Configure Webhook in [developers.facebook.com](https://developers.facebook.com/):**
   - In your WhatsApp App Dashboard $\rightarrow$ **Configuration** $\rightarrow$ **Webhook** $\rightarrow$ Click **Edit**.
   - **Callback URL:** `https://<YOUR_TUNNEL_URL>/api/v1/webhooks/whatsapp`
   - **Verify Token:** `cascadezero_verify_token_2026`
   - Click **Verify and Save**.
   - Under Webhook fields, click **Subscribe** to `messages`.

3. **Add Credentials to `backend/.env`:**
   - Copy **Temporary Access Token** to `META_WA_ACCESS_TOKEN`
   - Copy **Phone Number ID** to `META_WA_PHONE_NUMBER_ID`

4. **Send Message from Phone:**
   - Send any disruption report: *"Driver Ramesh reporting flood on NH48..."*
   - CascadeZero replies with native clickable buttons: `[⚡ Approve Plan B]` and `[📊 Plant Status]`! Tapping a button automatically executes the recovery and creates the Tally PO!

---

### B. Twilio Sandbox Fallback
1. Open [Twilio Console -> Messaging -> Try WhatsApp](https://console.twilio.com/).
2. In **Sandbox Settings**, paste into *"When a message comes in"*:
   ```
   https://<YOUR_TUNNEL_URL>/api/v1/webhooks/whatsapp
   ```
3. Set HTTP method to **`HTTP POST`** and click **Save**.
4. Send any disruption text or voice transcript from WhatsApp (e.g., *"Driver Ramesh reporting landslide near Krishnagiri on NH48. Truck stalled, 48 hours delay."*) — the 4 AI agents will immediately debate, optimize via PuLP, and reply with Plan B directly in WhatsApp!

---

## 🏭 Optional Industrial Floor Simulators

### 1. Live Shop-Floor PLC Telemetry Emulator
Continuously streams simulated temperature and speed ticks from robotic welding machines to Supabase:

```powershell
cd "c:\Users\harsh\Desktop\cascade 0\cascadezero\backend"

# Continuous streaming mode (normal operating temperature)
python simulator_plc.py --mode stream

# OR trigger an instant line-2 overheat crisis (89.2°C, 50% speed throttle):
python simulator_plc.py --mode crisis
```

### 2. Legacy ERP / Tally Folder Watcher
Automatically detects CSV order sheets dropped into `backend/watched_erp_folder/` and syncs them to Supabase:

```powershell
cd "c:\Users\harsh\Desktop\cascade 0\cascadezero\backend"
python cascade_sync.py
```

---

## 🔄 One-Click Factory Reset
If you want to clear simulated disruptions and reset the factory database to pristine seed status:

- **Via Web UI:** Click the **`↺ Reset`** pill button in the top navigation bar.
- **Via cURL / PowerShell:**
  ```powershell
  Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/reset"
  ```

---

## 🛠️ Key Environment Variables Reference

### Backend (`cascadezero/backend/.env`)
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_ANON_KEY`: Supabase anon public key
- `GEMINI_API_KEY`: Google Gemini API Key (powers LangGraph agents & natural-language parsing)
- `TWILIO_ACCOUNT_SID` & `TWILIO_AUTH_TOKEN`: For WhatsApp bot messaging
- `OPENWEATHER_API_KEY`: For real-time NH48 highway weather monitoring

### Frontend (`cascadezero/frontend/.env.local`)
- `NEXT_PUBLIC_SUPABASE_URL`: Supabase URL for client Realtime subscriptions
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`: Supabase Anon key
- `NEXT_PUBLIC_API_URL`: `http://localhost:8000`

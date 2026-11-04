# BI Escales — Pay Only If We Sail

PayPal AI Hackathon 2026 project by Association Berry-Mappemonde.

A supporter's PayPal pledge is **authorized** (Orders v2 `intent=AUTHORIZE`), and **captured** only once the AI Captain has reviewed the evidence for a voyage stop and a human treasurer has approved it; otherwise it is **voided**. The AI Captain proposes, it never executes.

- `bi-escales/` — FastAPI backend: pledges (authorize / capture / void), milestones and evidence, AI Captain, audit journal. Partner integrations (e.g. PayPal Agent Toolkit) are optional modules behind environment flags, off by default.
- `bi-escales/frontend/` — React UI (PayPal sandbox AUTHORIZE, treasurer queue, optional `ag-grid-community` gauges). That community grid is not AG Studio and is not a Studio Agent Framework entry; the flag stays off and the HTML table is the core build.
- `naviguide-escales/` — NAVIGUIDE voyage simulator (snapshot, no history).

Status: in development. PayPal **sandbox only**; no real money moves. Planned departure: 15 May 2027.

## Quick start (backend)
```bash
cd bi-escales/backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q
```
Copy `.env.example` to `.env` and fill in sandbox values locally; never commit it.

## Quick start (frontend)
```bash
cd bi-escales/frontend
cp .env.example .env.local   # VITE_PAYPAL_CLIENT_ID, VITE_ENABLE_AG_GRID=0
npm install
npm test
npm run dev                  # proxy /api -> http://127.0.0.1:8000
```

Démo backend + frontend :
```bash
cd bi-escales/frontend && npm run demo
```
(Active `ESCALES_ENABLED=1`, mémoire locale, clé trésorier de démo locale uniquement. Ce script refuse de démarrer sur Render et la clé ne doit pas y être recopiée.)

## License
Dual-licensed under MIT (`LICENSE-MIT`) or Apache-2.0 (`LICENSE-APACHE`), at your option.

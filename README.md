# BI Escales — Pay Only If We Sail

PayPal AI Hackathon 2026 project by Association Berry-Mappemonde.

A supporter's PayPal pledge is **authorized** (Orders v2 `intent=AUTHORIZE`), and **captured** only once the AI Captain has reviewed the evidence for a voyage stop and a human treasurer has approved it; otherwise it is **voided**. The AI Captain proposes, it never executes.

- `bi-escales/` — FastAPI backend: pledges (authorize / capture / void), milestones and evidence, AI Captain, audit journal. Partner integrations (e.g. PayPal Agent Toolkit) are optional modules behind environment flags, off by default.
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

## License
Dual-licensed under MIT (`LICENSE-MIT`) or Apache-2.0 (`LICENSE-APACHE`), at your option.

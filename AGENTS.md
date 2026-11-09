# AGENTS.md — BI Escales (OpenAI Codex)

Instructions for coding agents (Codex and similar) working in this repository.

## Project summary

**BI Escales — "Pay Only If We Sail"** is Association Berry-Mappemonde's entry for the **PayPal AI Hackathon 2026**.

- Devpost project id: **1517178**
- Public project page: https://devpost.com/software/bi-escales-pay-only-if-we-sail
- Hackathon deadline: **12 Nov 2026, 15:00 America/Toronto**
- Simulated expedition / voyage clock reference date: **12 Nov 2026** (do not invent or mention any other departure month)

**Stop** pledges are **authorized** (Orders v2 `intent=AUTHORIZE`) and **captured when the boat arrives** (or **voided** if the stop is cancelled). **Cabins** capture at leg **departure**. **Common fund** and **project donations** are **charged immediately** — not gated by Captain review or treasurer capture. For held stop/cabin pledges, the AI Captain reviews evidence and proposes; a human treasurer captures or voids. The Captain never executes money movement.

## Source of truth

The living plan and checklist is the Notion page:

https://app.notion.com/p/BI-Escales-PayPal-AI-Hackathon-plan-checklist-40eca9d24b43818aa64aee5bd2e92b81

Prefer that plan over ad-hoc scope guesses. Repository `README.md` describes architecture and local setup. Do not invent partner integrations that are not in the plan or code.

## Repository layout

| Path | Role |
|------|------|
| `bi-escales/` | Product app: FastAPI backend + Vite/React frontend, Render blueprint, Postman, docs, scripts |
| `bi-escales/backend/` | FastAPI app (`app.main:app`), pytest suite under `tests/` |
| `bi-escales/frontend/` | Vite + React + TypeScript UI (`npm` scripts) |
| `bi-escales/docs/` | Operator and partner docs (Render, PayPal sandbox helpers, …) |
| `bi-escales/postman/` | Sandbox Postman collection/environment (not loaded by the app) |
| `bi-escales/render.yaml` | Optional Render blueprint (`autoDeployTrigger: off`) |
| `bi-escales/.env.example` | Env var **names** only — copy locally; never commit real values |
| `naviguide-escales/` | NAVIGUIDE voyage simulator snapshot used by BI Escales (this repo only) |
| `README.md` | Project overview and quick start |

There is **no** root `package.json`. Backend deps live in `bi-escales/backend/requirements.txt`. Frontend deps live in `bi-escales/frontend/package.json`.

## Environments

| Env | URL | Notes |
|-----|-----|--------|
| test2 | https://bi-escales-api-test2.onrender.com | Preferred integration / demo target |
| prod | https://escales.naviguide.fr | Live BI Escales shell |
| Health | `GET /api/health` | On the API host (see `render.yaml` `healthCheckPath`) |

Do not redeploy Render from a PR. Pushes do not auto-deploy (`autoDeployTrigger: off`); deploys are manual by the owner.

## Install / run / test

Commands below are verified against the files in this tree. Run them from the paths shown.

### Backend

```bash
cd bi-escales/backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q
# optional local API
python -m uvicorn app.main:app --reload --port 8000
```

Copy `bi-escales/.env.example` to `bi-escales/backend/.env` (or the path your local setup uses) and fill **sandbox** values locally. Never commit `.env`.

### Frontend

```bash
cd bi-escales/frontend
npm ci
npm run dev      # Vite
npm run build    # tsc --noEmit && vite build
npm test         # vitest run (+ advisoryLabel node test)
```

### Same-origin smoke (optional)

```bash
python bi-escales/scripts/smoke_same_origin.py
```

(See `bi-escales/docs/` for return URLs and same-origin notes.)

## Git workflow (hard)

1. Create a **feature branch** from the current integration tip.
2. Open a **pull request into `test/integration-2` only**.
3. **Never** push, force-push, rebase onto, or open a PR targeting **`main`**.
4. Do not merge your own PR unless the owner explicitly asks.
5. Prefer small, reviewable PRs with English titles and descriptions.

Default branch on GitHub is `main`. Active integration branch is **`test/integration-2`**. All agent work targets that integration branch via PR.

## Hard rules (non-negotiable)

- **Never touch** the separate repository `Berry-Mappemonde/NAVIGUIDE`. Work only in `BI-Escales-PayPal` (including the in-repo `naviguide-escales/` snapshot when needed).
- **Never commit, paste, log, or request secrets**: API keys, tokens, Mongo/`MONGO_URL` / `BI_MARINAS_MONGODB_URI` values, PayPal client secrets, admin keys, webhook secrets, NVIDIA/OpenRouter keys, or `.env` contents. Use placeholders and `.env.example` names only.
- **PayPal stays sandbox** (`PAYPAL_ENV=sandbox`). No live/production PayPal money movement.
- **No spending**: do not purchase upgrades, paid quota, or paid APIs on the owner's behalf.
- **Never submit** or finalize the Devpost submission. Do not change the Devpost form unless the owner explicitly says to (e.g. only after an explicit “publish” / “update Devpost” instruction).
- **Never mention HelloAsso** in docs, UI copy, PRs, or commits.
- **Never mention a May departure date.** The expedition / voyage clock reference is **12 Nov 2026**. Do not invent other departure months.
- **Docs, code comments, commit messages, and PR text in English.** Chat with Clément may be French elsewhere; repository artifacts stay English.
- Do not capture or void real pledges, and do not perform Capture pledge / vault release demos that move or risk real funds, without an explicit per-action owner approval.
- Optional partner flags (AG Grid, Bryntum, Zapier, toolkit, webhooks, …) stay behind env flags; do not turn production-risk features on without being asked.

## PayPal server code

Any Python change that calls PayPal must follow this workflow (PayPal **sandbox** only; never live):

1. **Load the entry skill first:** read `bi-escales/backend/.cursor/skills/paypal-server-sdk/python-getting-started/SKILL.md` (and other `python-*` skills under that directory as needed). Do not use marketplace `python-integrate-paypal` skills — they target a different SDK.
2. **Dependency:** use `paypal-server-sdk==2.4.0` and import `paypalserversdk` (not legacy REST helpers unless the plan says otherwise).
3. **Plan before code:** write or refresh `bi-escales/backend/paypal-plan.md` with the PayPal operations you will call, method signatures, error types, and any duplicate-claim / idempotency rows **before** editing application code.
4. **PR hygiene:** name which vendored `python-*` skills you used in the pull request body.

## How to work with this codebase

- Prefer extending existing routes, components, and tests over new parallel stacks.
- Match existing patterns in `bi-escales/backend/app/` and `bi-escales/frontend/src/`.
- Keep the AI Captain advisory-only: it must not execute capture/void.
- When changing PayPal flows, keep Orders v2 authorize → human approve → capture/void semantics and sandbox-only assumptions.
- Update or add pytest / vitest coverage for behaviour you change.
- Do not add secrets to Codex environments, CI, or Render blueprints committed to git (names only, `sync: false` where applicable).

## Out of scope unless asked

- Editing Devpost, YouTube, or Synthesia publish steps
- Changing Render production env values in the dashboard
- Force-merging into `test/integration-2` or `main`
- Cross-repo changes outside `Berry-Mappemonde/BI-Escales-PayPal`

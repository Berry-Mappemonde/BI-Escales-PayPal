# AI audit (2026-11-04)

Scope: `app/core/llm.py`, `app/escales/captain.py`, `app/escales/app_i18n.py`, `app/routers/escales.py`, frontend Captain chat, `.env.example`, README AI section.

Money paths (capture, void, settle, Vault, 29-day rule, capture rule) are unchanged by this audit.

## Fix checklist

| Id | Item | Status | Notes |
|----|------|--------|-------|
| P0-1 | `fallback_reason` on `model_source`; NIM id logs | **Done** | `llm.py`, `captain._model_source`; `test_ai_audit` 1/15, `test_startup_log_names_model_ids_only` |
| P0-2 | Hop timeouts 20s/10s; Retry-After; 404/403 circuit breaker | **Done** | `NIM_TIMEOUT_S`, `HOP_BLOCK_S`; tests 14–15, `test_llm_cascade.py` |
| P0-3 | App language drives every AI prompt and reply | **Done** | Languages from frontend `i18n/locales/*.json`; `resolve_app_language` overrides message and Accept-Language; chat, milestone report, advisory JSON schema + system; `test_app_i18n`, `test_ai_language_harmony`, `test_router_uses_app_language_only` |
| P0-4 | Dates from code only; drop inverted ranges | **Done** | `_code_dates_sentence`, `_drop_inverted_ranges`; tests 3, 12, `test_inverted_date_sentence_is_dropped` |
| P1-5 | Drop model treasurer sentence when code adds rule | **Done** | `_drop_sentences` / `_TREASURER_ONLY`; test 1 |
| P1-6 | FR/EN lexicon (escale/stopover, étape/leg) | **Done** | `_french_labels`, `_english_labels`; tests 2, 4–6, 8 |
| P1-7 | NIM payload: no `reasoning_effort`, no `nvext`; `top_p` if temp>0 | **Done** | `test_llm_cascade.py`, test 14 |
| P1-8 | `ask_json` Lightning first; schema validation | **Done** | `JSON_HTTP_CASCADE`, localized `advisory_proposal_schema`; test 13 |
| P1-9 | OpenRouter free default; Referer/Title; 402/429 skip | **Done** | `OPENROUTER_DEFAULT_MODEL`; `test_openrouter_defaults_to_the_free_model_and_skips_402` |
| P2-10 | OmniRoute optional hop | **Cancelled** | Removed from cascade and docs; not deployed. |
| P2-11 | `.env.example` + README provider limits | **Done** | `bi-escales/.env.example`, README § AI |
| P2-12 | Treasurer `GET /admin/llm-cascade-probe` | **Done** | Provider, model, `fallback_reason` only; `test_admin_llm_cascade_probe_returns_metadata_only` |

## Findings addressed

- **F1–F2**: Super fallback surfaced via `fallback_reason`; chat language from app (not message or browser header).
- **F3–F4**: Lexicon + date guards.
- **F5**: Treasurer duplication stripped in `_compose_chat_reply`.
- **F6**: Miles without stop → “Which stopover?” / “Quelle escale ?” (`test_f6_sponsor_miles_without_a_stopover_asks_which_stopover`).
- **F7–F11**: Payload and cascade order as in fix list.

## Live testing (still to do)

Automated tests mock HTTP. No production call has been made to NVIDIA NIM, OpenRouter, or Anthropic from this audit branch. Run `GET /api/escales/admin/llm-cascade-probe` with the treasurer key on a staging service once keys are set, and spot-check Captain chat/review in EN and FR.

## Test matrix

Automated in `backend/tests/test_ai_audit.py` (cases 1–15 plus OpenRouter, router lang, startup log, inverted dates, F6), `test_ai_language_harmony.py`, and `test_app_i18n.py`.

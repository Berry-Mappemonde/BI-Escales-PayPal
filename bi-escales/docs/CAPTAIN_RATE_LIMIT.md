# Captain per-IP rate limit

Production (`ESCALES_ENV=production`) enables in-memory limits on `POST /api/escales/captain/chat` and `POST /api/escales/captain/review/{id}` unless overridden with `ESCALES_RATE_LIMIT_ENABLED`. Development leaves limits off by default.

| Variable | Default | Role |
|----------|---------|------|
| `ESCALES_CAPTAIN_RATE_PER_MINUTE` | `10` | Sliding one-minute window per client IP |
| `ESCALES_CAPTAIN_RATE_PER_DAY` | `100` | Calendar UTC day per client IP |
| `ESCALES_TRUSTED_PROXY_HOPS` | `1` | When non-zero, client IP is the first `X-Forwarded-For` entry; when `0`, use the socket host only |

Invalid or empty env values fall back to the defaults above. This cap is separate from the LLM daily budget (`ESCALES_LLM_DAILY_CAP` in `app/core/llm.py`).

When limited, the API responds with HTTP **429**, a French or English message (from request `lang`), and a **Retry-After** header (seconds).

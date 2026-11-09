# Captain per-IP rate limit

Production (`ESCALES_ENV=production`) enables in-memory limits on `POST /api/escales/captain/chat` and `POST /api/escales/captain/review/{id}` unless overridden with `ESCALES_RATE_LIMIT_ENABLED`. Development leaves limits off by default.

| Variable | Default | Role |
|----------|---------|------|
| `ESCALES_CAPTAIN_RATE_PER_MINUTE` | `10` | Sliding one-minute window per client IP |
| `ESCALES_CAPTAIN_RATE_PER_DAY` | `100` | Calendar UTC day per client IP |
| `ESCALES_TRUSTED_PROXY_HOPS` | `1` | Trust **N** hops from the **right** of `X-Forwarded-For` (`parts[-N]`); when `0`, use the socket host only |

Invalid or empty env values fall back to the defaults above. Per-IP caps are separate from the service-wide LLM daily budget in `app/core/llm.py` (`ESCALES_LLM_DAILY_CAP`, default `100` unless raised in production).

### Judging window (optional)

When both bounds are valid ISO 8601 instants with timezone offset and **START &lt; END**, the API uses elevated per-IP limits while **real wall-clock UTC now** is inside `[START, END)`. The voyage clock (`ESCALES_CLOCK_NOW` / simulated `now`) does **not** control this window. When `ESCALES_JUDGING_START` / `ESCALES_JUDGING_END` are unset, behaviour is unchanged from the standard table above.

| Variable | Default (window active) | Role |
|----------|-------------------------|------|
| `ESCALES_JUDGING_START` | *(unset)* | Window opens at this instant |
| `ESCALES_JUDGING_END` | *(unset)* | Window closes at this instant (exclusive) |
| `ESCALES_CAPTAIN_RATE_PER_MINUTE_JUDGING` | `36` | Per-minute cap while the judging window is active |
| `ESCALES_CAPTAIN_RATE_PER_DAY_JUDGING` | `9000` | Per-day cap while the judging window is active |
| `ESCALES_LLM_DAILY_CAP_JUDGING` | `9000` | Service-wide LLM call budget per UTC day while the judging window is active |

**Rationale:** NVIDIA NIM (Nemotron) allows **40 requests/minute** and **10,000 requests/day per API key**. Built-in judging defaults apply a **10% margin** → **36/min** and **9000/day** for both per-IP captain limits and the global `ESCALES_LLM_DAILY_CAP_JUDGING`. Env values override; invalid values log a warning and fall back to these judging defaults.

If either date is missing, unparsable, or `START >= END`, the judging window stays off (standard limits apply) and the backend logs **one** warning at startup/first use—no crash, and standard limits never drop below 10/min and 100/day.

`GET /api/escales/features` exposes the **effective** per-IP limits as `captain_rate`: `{ per_minute, per_day, judging_window_active }`.

Judges sharing one public IP are bounded by `min(per-IP judging limit, effective LLM daily cap)` on total LLM-backed captain traffic for the service.

> **Shared NVIDIA key:** Production (`escales.naviguide.fr`) and test2 (`bi-escales-api-test2.onrender.com`) currently use the **same** `NVIDIA_API_KEY`, so NIM usage during judging **adds up against one quota**. A separate key for test2 is the operator’s decision (not changed from this repo).

**Suggested production values for operator confirmation** (set on Render only after merge to `main`; do not enable from this repo):

- `ESCALES_JUDGING_START=2026-11-30T17:00:00-05:00`
- `ESCALES_JUDGING_END=2026-12-16T00:00:00-05:00`
- Judging rate knobs may be left unset to use **36 / 9000 / 9000** above, or set explicitly to the same values.

### Why rightmost, not leftmost?

The **leftmost** `X-Forwarded-For` entries are supplied by the caller and can be spoofed to rotate per-IP buckets. Render’s edge appends the real peer on the **right**, which clients cannot forge. With default `ESCALES_TRUSTED_PROXY_HOPS=1`, the rate-limit key is that rightmost entry (the edge-visible client). Increase the hop count if another trusted proxy is chained in front of the app.

When limited, the API responds with HTTP **429**, a French or English message (from request `lang`), and a **Retry-After** header (seconds).

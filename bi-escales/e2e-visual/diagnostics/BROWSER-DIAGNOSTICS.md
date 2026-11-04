# Browser diagnostics

Viewport: desktop 1440x900. Mobile viewports were not run.

Listeners: `console` (warning, error, assert), `pageerror`, `requestfailed`, and HTTP responses with status >= 400.
Each step lists every event observed since the previous screenshot. An empty table means none were observed.

## 01-user-journey

### 01-home-fr

Screenshot: `screenshots/01-user-journey/01-home-fr.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 02-language-en

Screenshot: `screenshots/01-user-journey/02-language-en.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 03-milestones

Screenshot: `screenshots/01-user-journey/03-milestones.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 04-evidence

Screenshot: `screenshots/01-user-journey/04-evidence.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 05-captain-chat

Screenshot: `screenshots/01-user-journey/05-captain-chat.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 06-queue-needs-key

Screenshot: `screenshots/01-user-journey/06-queue-needs-key.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 07-wrong-admin-key

Screenshot: `screenshots/01-user-journey/07-wrong-admin-key.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| http | warning | 403 GET http://127.0.0.1:5173/api/escales/pledges | http://127.0.0.1:5173/api/escales/pledges | Show the treasurer error inline (already on the queue). Do not retry a rejected key in a loop. A deliberate bad-key step will still record this 401. |
| console | error | Failed to load resource: the server responded with a status of 403 (Forbidden) | http://127.0.0.1:5173/api/escales/pledges:1:1 | Show the treasurer error inline (already on the queue). Do not retry a rejected key in a loop. A deliberate bad-key step will still record this 401. |

### 08-queue-loading

Screenshot: `screenshots/01-user-journey/08-queue-loading.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 09-queue-empty

Screenshot: `screenshots/01-user-journey/09-queue-empty.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 10-captain-review

Screenshot: `screenshots/01-user-journey/10-captain-review.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 11-pledge-rejected-unknown-milestone

Screenshot: `screenshots/01-user-journey/11-pledge-rejected-unknown-milestone.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| http | warning | 422 POST http://127.0.0.1:5173/api/escales/pledges | http://127.0.0.1:5173/api/escales/pledges | Seed a valid milestone arrival. Horizons of 29 days or more need ESCALES_VAULT_ENABLED; a missing date must stay a visible 422, not a silent AUTHORIZE. |
| console | error | Failed to load resource: the server responded with a status of 422 (Unprocessable Entity) | http://127.0.0.1:5173/api/escales/pledges:1:1 | Seed a valid milestone arrival. Horizons of 29 days or more need ESCALES_VAULT_ENABLED; a missing date must stay a visible 422, not a silent AUTHORIZE. |

### 12-pledge-authorized

Screenshot: `screenshots/01-user-journey/12-pledge-authorized.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 13-queue-with-pledge

Screenshot: `screenshots/01-user-journey/13-queue-with-pledge.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 14-after-capture

Screenshot: `screenshots/01-user-journey/14-after-capture.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 15-finance-ledger

Screenshot: `screenshots/01-user-journey/15-finance-ledger.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### Accessibility basics

No unlabeled controls, images missing alt, missing html lang, or skipped heading levels on the scanned screen.

## 02-paypal-journey

### 01-home-needs-key

Screenshot: `screenshots/02-paypal-journey/01-home-needs-key.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 02-empty-queue-and-ledger-ready

Screenshot: `screenshots/02-paypal-journey/02-empty-queue-and-ledger-ready.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 03-created-hidden-from-queue

Screenshot: `screenshots/02-paypal-journey/03-created-hidden-from-queue.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 04-authorized

Screenshot: `screenshots/02-paypal-journey/04-authorized.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 05-authorize-batch

Screenshot: `screenshots/02-paypal-journey/05-authorize-batch.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 06-vault-setup

Screenshot: `screenshots/02-paypal-journey/06-vault-setup.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 07-vaulted

Screenshot: `screenshots/02-paypal-journey/07-vaulted.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 08-captured

Screenshot: `screenshots/02-paypal-journey/08-captured.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 09-voided

Screenshot: `screenshots/02-paypal-journey/09-voided.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 10-vault-captured

Screenshot: `screenshots/02-paypal-journey/10-vault-captured.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 11-webhooks-pending-denied-settled

Screenshot: `screenshots/02-paypal-journey/11-webhooks-pending-denied-settled.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 12-pending-void-rejected

Screenshot: `screenshots/02-paypal-journey/12-pending-void-rejected.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| http | warning | 409 POST http://127.0.0.1:5173/api/escales/pledges/85218371e580411aa01d76039e358562/void | http://127.0.0.1:5173/api/escales/pledges/85218371e580411aa01d76039e358562/void | Hide Capture and Void unless the pledge is authorized or vaulted. Pending, failed, and settled rows cannot take those transitions. |
| console | error | Failed to load resource: the server responded with a status of 409 (Conflict) | http://127.0.0.1:5173/api/escales/pledges/85218371e580411aa01d76039e358562/void:1:1 | Hide Capture and Void unless the pledge is authorized or vaulted. Pending, failed, and settled rows cannot take those transitions. |

### 13-queue-survives-without-localstorage

Screenshot: `screenshots/02-paypal-journey/13-queue-survives-without-localstorage.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### 14-finance-ledger

Screenshot: `screenshots/02-paypal-journey/14-finance-ledger.png`

| Kind | Level | Message | Source file | Suggested fix |
| --- | --- | --- | --- | --- |
| — | — | No console error, warning, failed request, or uncaught exception on this step. | — | — |

### Accessibility basics

No unlabeled controls, images missing alt, missing html lang, or skipped heading levels on the scanned screen.

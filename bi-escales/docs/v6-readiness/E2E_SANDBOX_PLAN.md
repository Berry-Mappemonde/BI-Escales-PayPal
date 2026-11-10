# Sandbox E2E plan — staged, not executed on TEST2

Hamid exclusively owns test/integration-2, TEST2 and PROD until explicit release.
Do not merge, retarget, deploy, change merchant settings, run remote checkout,
or make sandbox payment writes from this task. Future integration is through
owner-approved test/integration-3; PR 182 is reviewed last.

## Secure prerequisites and evidence

Use an owner-approved isolated sandbox merchant/app and buyer only. Credentials
are supplied through existing secure bindings, never chat, test code, Git,
command arguments, screenshots, HARs or raw logs. The VITE public client ID must
belong to that sandbox app; a client secret must never enter a frontend bundle.
Record the exact Git SHA and deployed artifact identity before independent QA.
Allowlist observed destinations explicitly; do not broaden an unknown saved list.
Check every request origin: PayPal API must be api-m.sandbox.paypal.com, core
www.sandbox.paypal.com/web-sdk/v6/core. Native Google uses TEST mode. Stop on any
production PayPal API/core origin. Native provider CDNs are separate from PayPal.

Default Playwright tests are offline contract tests (frontend/playwright.config.ts:1)
with traces and screenshots off. Never turn them into real payments by replacing
mocks with credentials. For future sandbox evidence, record allowlisted fields
only: case ID, Git SHA, request method and host/path (no query), response status,
resource ID, state transition, attempt ID and redacted server receipt. Do not
capture request headers, payer/contact/card/payment-source payloads, browser
storage dumps, access tokens, full redirect URLs or complete response bodies.
Keep raw provider IDs out of public reports when unnecessary; use a stable alias.

## Independent QA cases after explicit release/operation approval

| Case | Action after approval | Required positive receipt | Required negative/recovery case |
|---|---|---|---|
| S01 wallet AUTHORIZE | One fixed-price sandbox pledge and buyer approval | matching original order/pledge; authorization only; one ledger entry | cancel, wrong order/return, duplicate callback |
| S02 deferred capture | Advance simulated voyage and approve a qualifying human review, then separately authorize capture action | exactly one server/provider capture at eligible time | WAIT/missing/stale/pre-arrival review never permits capture |
| S03 void/refund/reset | Each money-affecting operation requires its own owner approval | void/refund identity and matching original finance row | retry, shared token ownership, reset does not forge approval |
| S04 wallet Vault | Buyer consent to save, verify stored setup token | one approved setup/payment token linked to original pledge | denied consent/cancel/unapproved token cannot register |
| S05 later Vault payment | Separate explicit authorization for later sandbox charge | eligible voyage clock + human review + one payment receipt | not vaulted, wrong token, premature charge, uncertain retry |
| S06 card/issuer 3DS | Sandbox card fixture and authorized checkout | matching token, succeeded state, server authorization | declined, canceled, challenge timeout, failed liability/authentication and changed form |
| S07 subscription | Display server plan/price, create one pending subscription, buyer approval | same plan and monthly EUR price; backend remotely verified ACTIVE | stale/foreign/overridden plan, pending/canceled status, callback remount |
| S08 retry | Inject lost response after provider accepted request | same idempotency key, one provider resource and one local record | concurrent browser clicks, reload, two workers, known terminal new consent |
| S09 Pay Later | Server-validated order amount and SDK financing eligibility | correct country/product and amount/currency | below/above threshold, unsupported currency/country, unavailable method, edited amount |
| S10 Apple Pay | Verify exact HTTPS domain artifact against merchant console, native Safari sandbox tester | validateMerchant then matching PayPal confirm/authorization | unregistered domain, wrong artifact, unsupported device, native cancel |
| S11 Google Pay | Independently enable sandbox merchant product and TEST readiness | native-ready, matching confirm; close sheet before 3DS and server approval | Apple unavailable must not suppress Google; reject 3DS/cancel/mismatch |
| S12 redirect/mobile | Desktop redirect and supported mobile app-switch, then refresh | resume once using original correlation; server-verified receipt | forged URL, lost storage, cross-page/tab, ambiguous attempts, duplicate callback, cancel |
| S13 edited form | Change amount/target while an old popup is pending, approve original | original pledge identified explicitly, one original ledger entry | edited form never receives a false success/capture |

No real sandbox/provider E2E result is currently claimed. In particular, focused
resume tests do not prove mobile browser URL/storage behavior. Existing App URL
cleanup and SDK initialization timing must be observed on real devices.
LangSmith offline redaction tests are separate from actual remote ingestion.

## Future conflict resolution, without touching Hamid's baseline

After Hamid releases the baseline and the owner approves integration: fetch and
record immutable stable-baseline and test/integration-3 SHAs; do not assume today's
integration-2 tip is the final release. Compare the merge-base and both diffs read-only.
High-risk overlaps are PledgeButton, CrewSubscribeButton, return handling in App,
PayPal backend subscriptions/routes, lockfile/type configs and CI. Preserve Hamid's
ledger, refund, cancellation/reset and human-approval fixes as invariants. Resolve
contracts per operation, not whole-file ours/theirs. No force-push or automatic
rebase/cherry-pick/retarget is authorized now. Re-run baseline QA regressions,
F01–F06 tests, full suites and exact-head Actions on the approved integration
candidate before requesting independent TEST2 QA. Never deploy merely to resolve
a code conflict. The baseline release and v6 must remain separately identifiable.

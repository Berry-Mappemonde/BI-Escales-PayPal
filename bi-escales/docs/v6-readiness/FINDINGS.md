# Independent v6 findings — PR 182

Audited starting HEAD: `368db4ca80f3239cf183ec2afaa0fffa7c925110`.
Live root instructions were read; the owner overrides the integration-2 workflow:
feature branch only, no retarget/merge/deploy, TEST2 and PROD reserved to Hamid.
Collaboration inspection reported only the root agent active before edits.
The linked audit Doc was blocked by CONNECT 403; F01–F06 were supplied verbatim
by the owner. No finding was inferred from the inaccessible document.

## Reproduction and disposition

Before application repairs, one focused run produced **6 failing tests / 8 passing**
across the three audit test files. These reproduce source/contract omissions,
not a real lost charge. The sanitized original red log is retained at
`/workspace/.cloud-setup/audit-red.log`. No provider writes were performed.

| Rank | Finding | Observed proof and repair | Reviewer disposition |
|---|---|---|---|
| 1 / P1 | F02 late approval can outlive form revision | `frontend/src/components/PledgeButton.audit.test.tsx:13` failed because the old approval notified the new form. Immutable original pledge/amount/currency/target correlation and original-receipt UI now live at `frontend/src/components/PledgeButton.tsx:283`. Shared server reconciliation: `frontend/src/paypal/checkoutAttempts.ts:24`. | Source repair; original pledge verification is retained and the edited form is not credited. Real popup race and ledger receipt remain a sandbox QA gate. |
| 2 / P1 | F03 displayed subscription plan not checked end-to-end | `frontend/src/paypal/audit-findings.test.ts:22` failed on mismatched returned plan. Backend already returned plan_id: the initial finding did not imply that field was absent. Client now compares it; backend treats submitted selection only as a constraint, resolves the catalog, and validates ACTIVE/monthly/EUR 5.00 before creation (`backend/app/escales/paypal_subscriptions.py:380`). Wrong plan and wrong currency/price tests: `backend/tests/test_v6_subscription_audit.py:33`. | Source repair. Real sandbox plan/price and ACTIVE receipt still unverified. |
| 3 / P1 | F04 uncertain subscription retry changed request identity | `frontend/src/paypal/audit-findings.test.ts:27` observed distinct request IDs after injected transport failure. A non-secret logical key persists in session storage; shared concurrent requests reuse it (`frontend/src/paypal/paypalSdk.ts:136`). Verified terminal approval clears it; `audit-findings.test.ts:46` proves a new consent attempt is possible. Backend same-process creation/cache serialization: `backend/app/escales/paypal_subscriptions.py:349`. | Repaired locally. Cross-worker/provider exactly-once behavior depends on PayPal idempotency and needs an actual sandbox receipt; no exactly-once network guarantee claimed. |
| 4 / P1 risk | F01 return sessions lacked explicit resume | `frontend/src/paypal/audit-findings.test.ts:15` failed because hasReturned/resume were never used. Correlated, idempotent resume controller: `frontend/src/paypal/checkoutAttempts.ts:38`; SDK render: `frontend/src/paypal/paypalSdk.ts:256`. Existing App return handlers keep their callbacks and share reconciliation (`frontend/src/App.tsx:1`). Subscription resume uses persisted consent scope. Duplicate, ambiguous, forged and cross-page cases: `frontend/src/paypal/checkoutAttempts.test.ts:9`. | Contract mitigation, **not proof of a previously lost payment**. Mobile/direct-app-switch behavior, URL cleanup versus SDK initialization timing, refresh across browser processes and actual server/provider receipt remain blocking sandbox QA items. |
| 5 / P1–P2 | F06 approval promise settled before verified ACTIVE | `frontend/src/components/CrewSubscribeButton.test.tsx:181` failed because onApprove returned undefined. It now awaits a shared server verification promise and requires ACTIVE with the selected plan (`frontend/src/components/CrewSubscribeButton.tsx:150`). Non-ACTIVE failures at test line 197; admin audit remains separate/nonblocking. | Source repair. Remote ACTIVE status and trace ingestion not claimed. |
| 6 / P2 | F05 financing eligibility omitted transaction amount | `frontend/src/paypal/audit-findings.test.ts:35` observed no amount and cache reuse after amount change. Normalized amount is sent for one-time flows and included in their cache key (`frontend/src/paypal/paypalSdk.ts:366`). Invalid decimal inputs rejected; unrelated recurring/vault flows do not re-query for amount changes. | Source repair. This is the amount submitted for server validation, not proof that PayPal agreed to it before creation. Merchant/country/amount eligibility must be verified on sandbox. |

All repository paths in this table are relative to `bi-escales/`.
Do not downgrade the remaining provider/runtime gates merely because mocks pass.

## Corrected preliminary claims

Keep **paypal-pay-later-button** and **paypal-message**. The current public package
is `@paypal/paypal-js@11.3.0` (registry checked during this review).
Its `types/v6/components/web-components.d.ts:34`, `:87`, `:153`, `:157` explicitly
name those elements. The official examples checkout was verified at
`paypal-examples/v6-web-sdk-sample-integration@c4333b444368a67ad54fa4786fccb57021c5abdd`.
Both elements are correct; no rename repair was justified.

## Additional confirmed CI issue

`frontend/tsconfig.test.json:5` restricted ambient types and excluded installed
Google Pay/Apple Pay declarations. The original test typecheck failed with missing
Google/Apple names; adding those packages to the explicit types list passes.
Historical Actions run 42677401211 has matching frontend annotations but is for
**e319b23**, not the audited HEAD. It cannot establish final-head CI.
No baseline branch or remote environment was used to obtain this evidence.

## Mandatory residual gates

- F01 remains a runtime risk until a real sandbox redirect/app-switch and refresh
  confirms the SDK's return detection and the existing App URL cleanup ordering.
- The source-level F02 test proves original server reconciliation and no false
  new-form callback. It is not an observed production ledger/payment discrepancy.
- F03 validation applies to new v6 selection-constrained requests; legacy clients
  without that optional constraint retain their prior server catalog behavior.
- F04 serializes one event loop and retains provider idempotency identity. It
  does not implement a distributed transaction across workers and PayPal.
- No sandbox buyer approval, actual card/3DS or wallet device eligibility,
  merchant-console setup, or remote LangSmith ingestion was executed.
- GitHub Actions must be matched to the final feature SHA, not a PR merge ref.

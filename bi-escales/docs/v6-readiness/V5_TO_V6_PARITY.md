# Application v5 → v6 parity and executable evidence

Paths below are relative to `bi-escales/`. This matrix maps the application's
existing checkout journeys, not every product offered by the v5 SDK.
All listed executable tests use mocked providers; live merchant readiness is separate.

| Journey | Official v6 contract / app authority | Positive executable proof | Negative executable proof / runtime gap |
|---|---|---|---|
| PayPal wallet / AUTHORIZE | One-time session + Promise<{orderId}>; existing server authorization route | `frontend/src/paypal/paypalSdk.test.ts:92`; `frontend/e2e/checkout.spec.ts:4` authorize case | token failure/duplicate start: SDK test `:260`, `:280`; no actual sandbox sheet |
| Project capture | commit=true; existing server policy, no direct browser capture API | SDK test `:253`; browser project case | mismatched card order rejected at SDK test `:335`; real capture is not authorized by this review |
| Deferred human-approved capture | Backend evidence/arrival and latest qualifying human review | `backend/tests/test_review_approval_binding.py:89` | `:118`, `:176`, `:208`, `:225`: missing/stale/wait/rewound approvals fail closed; no provider capture performed |
| Void / cancel / reset / refund | Existing server routes and ledger semantics retained | `backend/tests/test_escales_vault.py:374`; existing backend suite | shared token protected `:295`, `:483`; provider effects require separately authorized sandbox actions |
| Baseline arrival/cancel/reset | Existing treasurer-only demo operations; preserve Hamid's baseline | `frontend/src/components/DemoStopMoment.test.tsx:36`; `backend/tests/test_judge_moment.py:226` | missing key `DemoStopMoment.test.tsx:63`; reset preserves captured pledge `test_judge_moment.py:240` |
| Refund and cancellation | Existing server-authoritative remaining balance and ledger | `frontend/src/components/TreasurerQueue.test.tsx:72`; `backend/tests/test_hamid_review.py:184` | cancel no request `TreasurerQueue.test.tsx:136`; busy/error/reconfirmation `:176`; over-refund `backend/tests/test_c3_refund_idempotency.py:246` |
| Wallet Vault consent / later payment | Save-payment session + Promise<{vaultSetupToken}>; stored token verified server-side | SDK test `:121`; browser vault case; `backend/tests/test_escales_vault.py:134` | not-approved token rejected `:209`; premature capture `:236`; missing admin `:270`; no later payment executed |
| Card Fields | Typed hosted components; submit(orderId), succeeded and matching ID | SDK test `:167`; browser card case | SDK test `:309`, `:335`: disposed/mismatched submission cannot approve |
| Card Vault / 3DS | save card session submit(setupToken); state gate | SDK test `:322` succeeded case | `:197`, `:322` failed/canceled cases; actual issuer 3DS challenge/abandonment unverified |
| Subscriptions | subscription session + server-owned selected plan, RECURRING_PAYMENT | SDK test `:137`; F03 tests; `backend/tests/test_paypal_lang_priority.py:305` | `frontend/src/paypal/audit-findings.test.ts:22`; backend audit `:33`, `:40`: stale/foreign plan and price rejected |
| Subscription ACTIVE callback | Await Promise<void> until verified server receipt | `frontend/src/components/CrewSubscribeButton.test.tsx:181` | `:197`: pending/canceled receipt never shows success; real ACTIVE receipt pending |
| Subscription retry/consent | Stable logical attempt identity, terminal reset | `frontend/src/paypal/audit-findings.test.ts:27`, `:46`; backend audit `:47` | uncertain provider response/cross-worker replay still requires sandbox proof |
| Pay Later | native paypal-pay-later-button; SDK country/product; amount-sensitive query | SDK test `:290`; audit test `:35` | SDK test `:229` UI threshold; audit `:70` malformed amount; unsupported merchant/country must fall back via SDK eligibility |
| Messages | createPayPalMessages + native paypal-message | SDK test `:237` | absent factory produces no message, no v5 renderer loaded; real offer copy unverified |
| Apple Pay | Independent native/device and merchant check; validateMerchant + confirmOrder | `frontend/src/paypal/paypalWallets.test.ts:90`; browser Apple case | unsupported device returns no wallet (`:32`); domain/Safari/sandbox tester required |
| Google Pay | Independent TEST client readiness; typed config + confirmOrder; 3DS after native sheet closes | wallet test `:32`, `:64`; browser approval/3DS cases | `:25`, `:41`, `:55`, `:74`, `:82`, `:118`: ineligible/cancel/failed 3DS/mismatched order cannot approve |
| Redirect/mobile return | hasReturned/resume with non-sensitive local correlation; existing server handlers retained | audit test `:15`, `:58`; `frontend/src/paypal/checkoutAttempts.test.ts:9` | controller test `:15`, `:22`: forged/cross-page/ambiguous/cancel not resumed; real mobile refresh is an unresolved gate |
| Form edit / stale approval | Immutable original attempt, shared receipt, explicit original-pledge notice | `frontend/src/components/PledgeButton.audit.test.tsx:13` | current edited form receives no onAuthorized callback; actual ledger/provider race unverified |
| Mixed SDK / script failure | One sandbox core; no v5 coexistence | SDK test `:22`, `:47` | SDK test `:66`, `:77`: legacy collision and missing public ID rejected |

Run frontend tests from `frontend` with `npm test`, test typecheck with
`npm run typecheck:test`, and browser mocks with `npm run test:e2e`.
Run server evidence from `backend` with `python -m pytest tests -m 'not live' -q`.
These commands contain no credential values and perform no live payment writes.

# SHA and CI evidence protocol

Starting/audited PR head: `368db4ca80f3239cf183ec2afaa0fffa7c925110`.
Both PR and branch Git refs were fetched and matched before edits. Only the
existing feature branch is authorized for commits/pushes. No retarget/merge.

The public commit Checks page reported no checks for that SHA. REST requests to
api.github.com fail at cloud-proxy CONNECT (403/Envoy), before authentication.
However GitHub's Actions web pages are readable. Historical run
https://github.com/Berry-Mappemonde/BI-Escales-PayPal/actions/runs/42677401211
is a failed frontend typecheck for **e319b23**, not the audited/final head. Its
annotations reproduce the missing wallet ambient types; it is not final evidence.

The feature-branch push trigger in `.github/workflows/ci.yml:7` requests Actions
for the exact repaired head. Frontend steps include npm ci, Vitest,
typecheck:test, build and mocked Playwright E2E. Backend CI runs the strict SDK
gateway typecheck and full pytest excluding live provider tests. Permissions are
contents:read; no deploy or secret injection was added. No integration-branch
push is needed to request these checks.

A SHA cannot be embedded in the same commit whose hash it identifies. The final
SHA, observed remote refs, run URL and per-job outcomes are therefore written
**after the feature push** into the external deliverable
`/workspace/.cloud-setup/pr182-audit/SHA_CI_REPORT.md`. That receipt must identify
the run's exact commit from GitHub's run title/commit link, not merely the branch,
PR number, latest run, merge SHA or green historical run. Pending/inaccessible
jobs remain unverified. Do not publish another documentation commit solely to
make the already verified SHA stale.

Local executions are reported separately from GitHub-hosted execution and
simulated Chromium from real sandbox payments. The six-test red reproduction
and subsequent command logs are retained under /workspace/.cloud-setup.

## Local results before feature push

- `npm ci --cache /workspace/.cloud-setup/npm-cache --no-audit --no-fund`: passed.
- `npm test`: 104 Vitest files, 572 tests passed; 3 Node tests passed.
- `npm run typecheck:test`: passed with explicit Google/Apple ambient types.
- `npm run build`: TypeScript and Vite passed; advisory chunk warnings only.
- `npm run test:e2e`: 7 simulated Chromium tests passed; no real provider request.
- `python -m pytest tests -m 'not live' -q -ra`: 928 passed, 2 external tests
  deselected; deprecation warnings only.
- `python -m mypy --strict app/escales/paypal_sdk_gateway.py`: passed using
  the same pinned mypy 2.4.1 as CI.
- Local runtime is Node 24 / Python 3.12; hosted CI explicitly selects Node 22 /
  Python 3.12. Local success is not substituted for hosted results.

All six audit reproductions were red before the repair and green afterward.
Additional negative tests cover ambiguous/cross-page returns, malformed amount,
non-ACTIVE subscription status, remount/retry, stale terminal callback ownership,
server plan mismatch, unsupported price/currency and unadvertised extra fees.

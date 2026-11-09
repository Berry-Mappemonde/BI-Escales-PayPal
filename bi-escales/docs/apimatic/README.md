# APIMatic Context Plugin for the PayPal Server SDK

BI Escales uses the APIMatic Context Plugin for the PayPal Server SDK as agent guidance. The copy in this repository is [paypaldev/server-sdk-context-plugin-preview](https://github.com/paypaldev/server-sdk-context-plugin-preview) at commit [`6aa057126f0d4709a42e15002aab832a94935d92`](https://github.com/paypaldev/server-sdk-context-plugin-preview/commit/6aa057126f0d4709a42e15002aab832a94935d92).

The plugin's Python skills describe the generated package `paypal-server-sdk` (version `2.4.0`, import name `paypalserversdk`). They are agent instructions. The FastAPI application does not call that SDK: `bi-escales/backend/requirements.txt` does not list `paypal-server-sdk`, and `bi-escales/backend/app/` does not import `paypalserversdk`.

## Vendored skills

Eight Python skills from upstream `skills/python/*` are vendored byte-identical into `bi-escales/backend/.cursor/skills/paypal-server-sdk/`:

| Skill | In this repository |
| --- | --- |
| `python-getting-started` | [SKILL.md](../../backend/.cursor/skills/paypal-server-sdk/python-getting-started/SKILL.md) |
| `python-client-initialization` | [SKILL.md](../../backend/.cursor/skills/paypal-server-sdk/python-client-initialization/SKILL.md) |
| `python-authentication` | [SKILL.md](../../backend/.cursor/skills/paypal-server-sdk/python-authentication/SKILL.md), [reference.md](../../backend/.cursor/skills/paypal-server-sdk/python-authentication/reference.md) |
| `python-calling-endpoints` | [SKILL.md](../../backend/.cursor/skills/paypal-server-sdk/python-calling-endpoints/SKILL.md) |
| `python-models` | [SKILL.md](../../backend/.cursor/skills/paypal-server-sdk/python-models/SKILL.md) |
| `python-error-handling` | [SKILL.md](../../backend/.cursor/skills/paypal-server-sdk/python-error-handling/SKILL.md) |
| `python-configuration-resilience` | [SKILL.md](../../backend/.cursor/skills/paypal-server-sdk/python-configuration-resilience/SKILL.md) |
| `python-testing` | [SKILL.md](../../backend/.cursor/skills/paypal-server-sdk/python-testing/SKILL.md) |

[SOURCE.md](../../backend/.cursor/skills/paypal-server-sdk/SOURCE.md) records the upstream repository, commit `6aa057126f0d4709a42e15002aab832a94935d92`, and the SHA-256 of each vendored file (section **SHA-256 of vendored files**). Those nine digests match the files in this repository: eight `SKILL.md` files and `python-authentication/reference.md`.

## Why they are vendored

Cursor Cloud Agents only load skills that are in the repository. The eight Python skills are vendored so those agents can load them. [SOURCE.md](../../backend/.cursor/skills/paypal-server-sdk/SOURCE.md) states that reason.

## PayPal server code

The **PayPal server code** section of [AGENTS.md](../../../AGENTS.md) is the rule for any Python change that calls PayPal. PayPal stays sandbox (`PAYPAL_ENV=sandbox`).

1. Load [`python-getting-started`](../../backend/.cursor/skills/paypal-server-sdk/python-getting-started/SKILL.md) first, then the other `python-*` skills under `bi-escales/backend/.cursor/skills/paypal-server-sdk/` as needed. Marketplace `python-integrate-paypal` skills target a different SDK, so this rule does not use them.
2. Depend on `paypal-server-sdk==2.4.0` and import `paypalserversdk`.
3. Write or refresh `bi-escales/backend/paypal-plan.md` with the PayPal operations to call, method signatures, error types, and any duplicate-claim or idempotency rows before editing application code. That plan file is absent from this repository.
4. Name the vendored `python-*` skills used in the pull request body.

## License

Upstream has no LICENSE file at that commit; `plugin.json` declares MIT.

[SOURCE.md](../../backend/.cursor/skills/paypal-server-sdk/SOURCE.md) records the same check for commit `6aa057126f0d4709a42e15002aab832a94935d92`: the upstream repository contains no `LICENSE` file, and root `plugin.json` declares `"license": "MIT"`.

## Next

Later tasks, not present in this repository:

- **APIM-2** — read paths on the PayPal Server SDK.
- **APIM-3** — money path on the PayPal Server SDK.

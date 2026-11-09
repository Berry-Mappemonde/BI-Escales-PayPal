# Backend tests

## Default CI behaviour

Pytest runs with **no live network** to LLM providers (NIM, OpenRouter, Anthropic, Nebius) or PayPal unless you opt in.

Set `ESCALES_RUN_LIVE=1` locally to run tests marked `@pytest.mark.live` (real NIM or PayPal sandbox calls). CI does not set this variable.

Use `monkeypatch.setenv` / `monkeypatch.delenv` for env overrides so values do not leak across tests. Avoid direct `os.environ[...] =` writes.

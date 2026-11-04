"""Deterministic PayPal-Request-Id values (one key per pledge + action)."""


def paypal_request_id(reference_id: str, action: str) -> str:
    ref = str(reference_id or "").strip()[:64] or "unknown"
    act = str(action or "action").strip()[:32]
    return f"{act}-{ref}"[:127]

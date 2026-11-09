"""Known SPA client paths (mirrors frontend `src/routes/clientRoutes.ts`)."""
from __future__ import annotations

# Normalized paths without leading or trailing slashes (empty string = `/`).
KNOWN_CLIENT_ROUTES: frozenset[str] = frozenset(
    {
        "",
        "en",
        "fr",
        "escales/wishlists",
        "en/escales/wishlists",
        "fr/escales/wishlists",
    }
)


def normalize_client_path(full_path: str) -> str:
    """Collapse ``/``, ``/en/``, and ``en`` to the same normalized form."""
    return (full_path or "").strip().strip("/")


def is_known_client_route(full_path: str) -> bool:
    return normalize_client_path(full_path) in KNOWN_CLIENT_ROUTES

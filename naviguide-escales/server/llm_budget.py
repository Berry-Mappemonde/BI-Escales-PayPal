"""Budget journalier des appels LLM (plan Nemotron § 0 / § 3).

Compteurs par niveau (`nano` / `fast` / `write` / `judge`) dans `pearl_store.kv`,
clé logique `llm-budget:<date>:<tier>`. Au plafond : aucun appel réseau
(la cascade rend `source=budget`). L’USD est une estimation d’après la
grille Token Factory du 20 sept. 2026, jamais un chiffre produit par un modèle.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

NS = "llm-budget"
LAST_SOURCE_NS = "llm"
LAST_SOURCE_KEY = "last-source"
LAST_SOURCE_BY_TIER_KEY = "last-source-by-tier"
LAST_MODEL_BY_TIER_KEY = "last-model-by-tier"
LAST_ERROR_KEY = "last-error"
LAST_ERRORS_BY_TIER_KEY = "last-errors-by-tier"
LAST_ERROR_AT_KEY = "last-error-at"
FALLBACK_PROVIDERS = ("nim", "openrouter", "claude")

_tf_quota_until = 0.0
_tf_quota_lock = threading.Lock()


def pause_tokenfactory_for_quota() -> None:
    """Pause Token Factory after an exhausted-credit response (default: 10 min)."""
    global _tf_quota_until
    try:
        pause_s = max(0.0, float(os.environ.get("NAVIGUIDE_TF_QUOTA_PAUSE_S", "600")))
    except (TypeError, ValueError):
        pause_s = 600.0
    if pause_s <= 0:
        return
    with _tf_quota_lock:
        _tf_quota_until = time.time() + pause_s


def tokenfactory_quota_paused() -> bool:
    with _tf_quota_lock:
        return time.time() < _tf_quota_until


def tokenfactory_quota_status() -> dict[str, Any]:
    with _tf_quota_lock:
        until = _tf_quota_until
    if time.time() >= until:
        return {"state": "ok", "until": None}
    return {"state": "exhausted", "until": datetime.fromtimestamp(until, timezone.utc).isoformat()}

TIERS = ("nano", "fast", "write", "deep", "judge")

# Nebius Token Factory — deprecations November 2026 (serverless).
# https://docs.tokenfactory.nebius.com/model-deprecations-november-2026
DEPRECATED_TOKEN_FACTORY_MODELS = frozenset({
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/nemotron-3-super-120b-a12b",
})

# Tokens / jour — resserrés le 28 sept. (facture Nebius du mois : 6,58 $ sur 60 $ de crédits, dont 5,19 $ de
# Nemotron Ultra pour un badge que personne ne voyait) : fast ≈ 0,05 $/j, write ≈ 0,08 $/j.
# Ultra (palier judge) a 60 000 tokens/jour dans les défauts ; le mode
# `NAVIGUIDE_LLM_MODE=off` (CI, tests automatisés) bloque encore tout appel, plafond ou pas.
DEFAULT_CAPS = {
    # JSON courts (intention, ids). Même prix unitaire que Lightning : le plafond
    # reste sous le palier fast, les appels tiennent en quelques centaines de tokens.
    "nano": 100_000,
    "fast": 200_000,
    # Relevés réels du 28 oct. (PR #126) : un film rédigé intégral = ~18 000 tokens write
    # + ~15 000 tokens Ultra (édition + relecture, palier judge). À 60 000, un seul juge
    # (film + quelques questions « Raisonnement ») coupait Ultra pour tous jusqu'à minuit UTC.
    # Dimensionné pour la période de jugement (1er-15 déc.) : ~15 films intégraux / jour.
    "write": 450_000,
    "deep": 150_000,
    "judge": 250_000,
}

# Garde-fou : coût maximal d'une journée aux plafonds par défaut, en comptant TOUS les
# tokens au prix de sortie (borne haute). ~1,68 $/j → ~80 $ sur les 47 jours jusqu'au
# 15 déc. : la réserve de crédits des juges reste couverte. Un test vérifie la borne.
MAX_DEFAULT_DAY_USD = 1.75

# Appels Ultra du chat / jour (geste explicite seulement). En plus du plafond tokens judge.
DEFAULT_CHAT_ULTRA_PER_DAY = 10
_ENV_CHAT_ULTRA = "NAVIGUIDE_CHAT_ULTRA_PER_DAY"
# Frein en dollars estimés. Absent, vide, non numérique ou ≤ 0 = pas de coupure
# (voulu, le temps de mesurer). Aucun montant n'est écrit dans le dépôt.
_ENV_DAILY_USD = "NAVIGUIDE_LLM_DAILY_USD"

# Mode LLM (NAVIGUIDE_LLM_MODE) — décision du porteur du 28 sept. : « Nemotron seulement quand je le dis ou
# quand c'est utile ».
#   off        : aucun appel payant, jamais (CI, machines de dev).
#   on-demand  : (défaut) seulement sur une action de l'utilisateur — question au chat, clic « Rédigé » —
#                jamais en arrière-plan (préchauffage des récits, écriture du film, phrase de la revue,
#                remplisseur du stock).
#   all        : tout, comme avant (à poser explicitement sur le poste pour une démo complète).
_MODES = ("off", "on-demand", "all")
_BACKGROUND: ContextVar[bool] = ContextVar("naviguide_llm_background", default=False)
# RG11A : le remplisseur écrit le rédigé comme une étape « sur demande différée »
# (on-demand + processus arrière-plan). Mode off reste interdit.
_DEFERRED: ContextVar[bool] = ContextVar("naviguide_llm_deferred", default=False)


def mode() -> str:
    raw = (os.environ.get("NAVIGUIDE_LLM_MODE") or "on-demand").strip().lower().replace("_", "-")
    return raw if raw in _MODES else "on-demand"


def in_background() -> bool:
    """Vrai dans une tâche d'arrière-plan (préchauffage, remplisseur) — ou dans un processus lancé avec
    NAVIGUIDE_LLM_BACKGROUND=1 (le remplisseur du stock)."""
    if (os.environ.get("NAVIGUIDE_LLM_BACKGROUND") or "").strip() in ("1", "true", "yes"):
        return True
    return bool(_BACKGROUND.get())


@contextmanager
def background():
    """À poser autour d'un travail d'arrière-plan : sous le mode on-demand, la cascade n'appelle rien."""
    token = _BACKGROUND.set(True)
    try:
        yield
    finally:
        _BACKGROUND.reset(token)


@contextmanager
def deferred_demand():
    """Écriture du rédigé par le remplisseur : étape « sur demande différée ».

    Autorise le palier *write* même si le processus est marqué arrière-plan,
    tant que le mode n'est pas `off`. Les paliers nano / fast / judge restent bloqués.
    """
    token = _DEFERRED.set(True)
    try:
        yield
    finally:
        _DEFERRED.reset(token)


def llm_allowed_here(tier: str | None = None) -> bool:
    """Le mode autorise-t-il un appel payant ICI (avant même le plafond) ?"""
    m = mode()
    if m == "off":
        return False
    if m == "all":
        return True
    if _DEFERRED.get() and (tier is None or normalize_tier(tier) == "write"):
        return True
    return not in_background()

# $/million tokens (entrée, sortie) — plan § 0.
PRICES_PER_M = {
    # Nano : grille du 20 sept. (même ordre que Lightning ; id catalogue confirmé ensuite).
    "nano": (0.06, 0.24),
    "fast": (0.06, 0.24),
    "write": (0.30, 0.90),
    "deep": (1.00, 3.00),
    "judge": (1.00, 3.00),
}

DEFAULT_MODELS = {
    # Nano 30B → Nemotron 3.5 Lightning (Nov. 2026 deprecation).
    "nano": "nvidia/Nemotron-3_5-Lightning",
    "fast": "nvidia/Nemotron-3_5-Lightning",
    # Super 120B → Nemotron 3.5 Super VL (Nov. 2026 deprecation).
    "write": "nvidia/Nemotron-3.5-Super-VL",
    "deep": "nvidia/Nemotron-3-Ultra-550b-a55b",
    "judge": "nvidia/Nemotron-3-Ultra-550b-a55b",
}

DEFAULT_MAX_TOKENS = {
    "nano": 256,
    "fast": 1024,
    "write": 400,
    # NVIDIA Ultra Day-0: max_tokens caps thinking + answer; 512 is too small
    # if enable_thinking stays on. Official Ultra example uses 2048.
    "deep": 2048,
    "judge": 2048,
}

SOURCE_FOR_TIER = {
    "nano": "nemotron-lightning",  # Nano 30B retiré : le palier sert Lightning 3.5
    "fast": "nemotron-lightning",
    "write": "nemotron-super-vl",
    "deep": "nemotron-ultra",
    "judge": "nemotron-ultra",
}

_ENV_CAP = {
    "nano": "NAVIGUIDE_LLM_DAILY_TOKENS_NANO",
    "fast": "NAVIGUIDE_LLM_DAILY_TOKENS_FAST",
    "write": "NAVIGUIDE_LLM_DAILY_TOKENS_WRITE",
    "deep": "NAVIGUIDE_LLM_DAILY_TOKENS_DEEP",
    "judge": "NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE",
}
_ENV_MODEL = {
    "nano": "NAVIGUIDE_TF_MODEL_NANO",
    "fast": "NAVIGUIDE_TF_MODEL_FAST",
    "write": "NAVIGUIDE_TF_MODEL_WRITE",
    "deep": "NAVIGUIDE_TF_MODEL_DEEP",
    "judge": "NAVIGUIDE_TF_MODEL_JUDGE",
}

_LOCK = threading.Lock()


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def normalize_tier(tier: str | None) -> str:
    t = (tier or "write").strip().lower()
    return t if t in TIERS else "write"


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def daily_cap(tier: str) -> int:
    t = normalize_tier(tier)
    return _env_int(_ENV_CAP[t], DEFAULT_CAPS[t])


def model_for(tier: str) -> str:
    t = normalize_tier(tier)
    return (os.environ.get(_ENV_MODEL[t]) or DEFAULT_MODELS[t]).strip() or DEFAULT_MODELS[t]


def configured_models() -> dict[str, str]:
    """Modèles Token Factory configurés par palier (override env inclus)."""
    return {t: model_for(t) for t in TIERS}


def max_tokens_for(tier: str) -> int:
    t = normalize_tier(tier)
    return _env_int(f"NAVIGUIDE_TF_MAX_TOKENS_{t.upper()}", DEFAULT_MAX_TOKENS[t]) or DEFAULT_MAX_TOKENS[t]


def source_for(tier: str) -> str:
    return SOURCE_FOR_TIER[normalize_tier(tier)]


def estimate_usd(tier: str, prompt_tokens: int, completion_tokens: int) -> float:
    inn, out = PRICES_PER_M[normalize_tier(tier)]
    usd = (max(0, int(prompt_tokens)) / 1_000_000.0) * inn + (
        max(0, int(completion_tokens)) / 1_000_000.0
    ) * out
    return round(usd, 8)


def _empty() -> dict[str, Any]:
    return {"tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "usd": 0.0}


def _kv_key(tier: str, day: str | None = None) -> str:
    return f"{day or today()}:{normalize_tier(tier)}"


def get_usage(tier: str, day: str | None = None) -> dict[str, Any]:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(NS, _kv_key(tier, day))
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return _empty()
    out = _empty()
    for k in out:
        try:
            out[k] = int(val[k]) if k != "usd" else float(val[k])
        except (TypeError, ValueError, KeyError):
            pass
    if out["tokens"] <= 0:
        out["tokens"] = int(out["prompt_tokens"]) + int(out["completion_tokens"])
    return out


def daily_usd_cap() -> float | None:
    """Plafond dollar du jour. None = pas de coupure (absent, vide, non numérique, ≤ 0)."""
    raw = (os.environ.get(_ENV_DAILY_USD) or "").strip()
    if not raw:
        return None
    try:
        val = float(raw)
    except ValueError:
        return None
    if val <= 0 or val != val:
        return None
    return val


def today_usd(day: str | None = None) -> float:
    """USD estimé du jour, tous paliers LLM confondus (pas Tavily)."""
    return round(sum(float(get_usage(t, day)["usd"]) for t in TIERS), 8)


def _upcoming_call_usd(tier: str) -> float:
    """Coût estimé d'un appel au palier (sortie = max_tokens). Sans montant en dur."""
    return estimate_usd(tier, 0, max_tokens_for(tier))


def allow(tier: str) -> bool:
    """False si le mode l'interdit ici (off, ou arrière-plan en on-demand), si le compteur
    tokens du jour est au plafond, ou si l'USD estimé du jour + le coût de l'appel
    dépasseraient NAVIGUIDE_LLM_DAILY_USD — dans tous les cas : aucun appel réseau,
    la cascade rend `source=budget`."""
    if not llm_allowed_here(tier):
        return False
    used = get_usage(tier)
    if int(used["tokens"]) >= daily_cap(tier):
        return False
    cap = daily_usd_cap()
    if cap is not None and today_usd() + _upcoming_call_usd(tier) > cap:
        return False
    return True


def chat_ultra_cap() -> int:
    return _env_int(_ENV_CHAT_ULTRA, DEFAULT_CHAT_ULTRA_PER_DAY)


def _chat_ultra_key(day: str | None = None) -> str:
    return f"{day or today()}:chat-ultra"


def chat_ultra_usage(day: str | None = None) -> dict[str, Any]:
    """Compteur d'appels Ultra du chat (geste explicite), distinct des tokens judge."""
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(NS, _chat_ultra_key(day))
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return {"calls": 0}
    try:
        return {"calls": max(0, int(val.get("calls") or 0))}
    except (TypeError, ValueError):
        return {"calls": 0}


def allow_chat_ultra() -> bool:
    """Ultra du chat : mode + tokens judge + plafond d'appels NAVIGUIDE_CHAT_ULTRA_PER_DAY."""
    if not allow("judge"):
        return False
    return int(chat_ultra_usage()["calls"]) < chat_ultra_cap()


def record_chat_ultra() -> dict[str, Any]:
    """Compte un appel Ultra du chat (avant ou après l'aller-retour réseau)."""
    import pearl_store  # noqa: PLC0415

    with _LOCK:
        cur = chat_ultra_usage()
        cur["calls"] = int(cur["calls"]) + 1
        pearl_store.kv_put(NS, _chat_ultra_key(), cur)
        return dict(cur)


def record(tier: str, prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
    """Add one successful Token Factory call to today's counter."""
    import pearl_store  # noqa: PLC0415

    t = normalize_tier(tier)
    pt = max(0, int(prompt_tokens))
    ct = max(0, int(completion_tokens))
    add_usd = estimate_usd(t, pt, ct)
    def update(raw):
        cur = raw if isinstance(raw, dict) else _empty()
        cur = {**_empty(), **cur}
        cur["prompt_tokens"] = int(cur["prompt_tokens"]) + pt
        cur["completion_tokens"] = int(cur["completion_tokens"]) + ct
        cur["tokens"] = int(cur["prompt_tokens"]) + int(cur["completion_tokens"])
        cur["calls"] = int(cur["calls"]) + 1
        cur["usd"] = round(float(cur["usd"]) + add_usd, 8)
        return cur
    return dict(pearl_store.kv_update(NS, _kv_key(t), update))


def _last_source_by_tier_raw() -> dict[str, str]:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(LAST_SOURCE_NS, LAST_SOURCE_BY_TIER_KEY)
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in val.items():
        if k in TIERS and isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def last_source_by_tier() -> dict[str, str]:
    """Dernière source réelle par palier (LT2) — pour `/ici/warm/status`."""
    return dict(_last_source_by_tier_raw())


def _last_model_by_tier_raw() -> dict[str, str]:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(LAST_SOURCE_NS, LAST_MODEL_BY_TIER_KEY)
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in val.items():
        if k in TIERS and isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def last_model_by_tier() -> dict[str, str]:
    """Dernier id modèle Token Factory servi par palier — `/ici/warm/status`."""
    return dict(_last_model_by_tier_raw())


def remember_served_model(model_id: str | None, tier: str | None = None) -> None:
    """Id catalogue renvoyé par Token Factory pour ce palier (badge / warm status)."""
    import pearl_store  # noqa: PLC0415

    mid = (model_id or "").strip()
    if not mid or tier is None:
        return
    t = normalize_tier(tier)
    by = _last_model_by_tier_raw()
    by[t] = mid
    pearl_store.kv_put(LAST_SOURCE_NS, LAST_MODEL_BY_TIER_KEY, by)


def remember_source(source: str | None, tier: str | None = None) -> None:
    """Last provider that produced a text (not `cache`, so the UI keeps the model)."""
    import pearl_store  # noqa: PLC0415

    src = (source or "").strip()
    if not src or src == "cache":
        return
    pearl_store.kv_put(LAST_SOURCE_NS, LAST_SOURCE_KEY, src)
    if tier is not None:
        t = normalize_tier(tier)
        by = _last_source_by_tier_raw()
        by[t] = src
        pearl_store.kv_put(LAST_SOURCE_NS, LAST_SOURCE_BY_TIER_KEY, by)


def last_source() -> str | None:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(LAST_SOURCE_NS, LAST_SOURCE_KEY)
    val = (hit or {}).get("value")
    return val if isinstance(val, str) and val.strip() else None


def _errors_by_tier_raw() -> dict[str, list[dict[str, str]]]:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(LAST_SOURCE_NS, LAST_ERRORS_BY_TIER_KEY)
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    for k, v in val.items():
        if k not in TIERS or not isinstance(v, list):
            continue
        clean = [x for x in v if isinstance(x, dict) and (x.get("provider") or x.get("reason"))]
        if clean:
            out[k] = clean
    return out


def _merge_tier_errors(by: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    for t in TIERS:
        merged.extend(by.get(t) or [])
    return merged


def _sync_legacy_errors(by: dict[str, list[dict[str, str]]]) -> None:
    import pearl_store  # noqa: PLC0415

    merged = _merge_tier_errors(by)
    if merged:
        pearl_store.kv_put(LAST_SOURCE_NS, LAST_ERROR_KEY, merged)
    else:
        pearl_store.kv_delete(LAST_SOURCE_NS, LAST_ERROR_KEY)
        pearl_store.kv_delete(LAST_SOURCE_NS, LAST_ERROR_AT_KEY)


def clear_tier_errors(tier: str) -> None:
    """Efface les erreurs d'un palier au premier succès Token Factory (LT2)."""
    import pearl_store  # noqa: PLC0415

    t = normalize_tier(tier)
    by = _errors_by_tier_raw()
    if t not in by:
        return
    del by[t]
    pearl_store.kv_put(LAST_SOURCE_NS, LAST_ERRORS_BY_TIER_KEY, by)
    _sync_legacy_errors(by)


def remember_cascade_errors(hops: list[dict[str, str]], tier: str | None = None) -> None:
    """Every hop that failed in the last cascade (TF HTTP body first)."""
    import pearl_store  # noqa: PLC0415

    clean: list[dict[str, str]] = []
    for hop in hops or []:
        if not isinstance(hop, dict):
            continue
        prov = str(hop.get("provider") or "").strip()
        why = " ".join(str(hop.get("reason") or "").split())[:240]
        if prov or why:
            clean.append({"provider": prov, "reason": why})
    if not clean:
        return
    t = normalize_tier(tier)
    by = _errors_by_tier_raw()
    by[t] = clean
    pearl_store.kv_put(LAST_SOURCE_NS, LAST_ERRORS_BY_TIER_KEY, by)
    pearl_store.kv_put(
        LAST_SOURCE_NS,
        LAST_ERROR_AT_KEY,
        datetime.now(timezone.utc).isoformat(),
    )
    pearl_store.kv_put(LAST_SOURCE_NS, LAST_ERROR_KEY, clean)
    _sync_legacy_errors(by)


def remember_cascade_error(provider: str, reason: str, tier: str | None = None) -> None:
    remember_cascade_errors([{"provider": provider, "reason": reason}], tier=tier)


def last_error_at() -> str | None:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(LAST_SOURCE_NS, LAST_ERROR_AT_KEY)
    val = (hit or {}).get("value")
    return val if isinstance(val, str) and val.strip() else None


def last_errors() -> list[dict[str, str]] | None:
    import pearl_store  # noqa: PLC0415

    by = _errors_by_tier_raw()
    if by:
        merged = _merge_tier_errors(by)
        return merged or None
    hit = pearl_store.kv_get(LAST_SOURCE_NS, LAST_ERROR_KEY)
    val = (hit or {}).get("value")
    if isinstance(val, list):
        out = [x for x in val if isinstance(x, dict) and (x.get("provider") or x.get("reason"))]
        return out or None
    if isinstance(val, dict) and (val.get("provider") or val.get("reason")):
        return [{"provider": str(val.get("provider") or ""), "reason": str(val.get("reason") or "")}]
    return None


def last_error() -> dict[str, str] | None:
    """Prefer Token Factory so a Lightning HTTP body stays visible after NIM."""
    errs = last_errors()
    if not errs:
        return None
    for item in errs:
        if item.get("provider") == "tokenfactory":
            return item
    return errs[0]


def _tavily_empty() -> dict[str, Any]:
    return {"credits": 0, "calls": 0, "lastAt": None, "lastPort": None}


def _tavily_port_name(port: str | None) -> str | None:
    """Nom d'escale seulement : pas de requête, pas de clé."""
    name = " ".join(str(port or "").split())
    if not name or len(name) > 80:
        return None
    low = name.lower()
    if "tvly-" in low or low.startswith("sk-") or "api_key" in low or "bearer " in low:
        return None
    return name


def _tavily_persist(cur: dict[str, Any]) -> dict[str, Any]:
    stored: dict[str, Any] = {
        "credits": int(cur.get("credits") or 0),
        "calls": int(cur.get("calls") or 0),
    }
    at = cur.get("lastAt")
    if isinstance(at, str) and at.strip():
        stored["lastAt"] = at.strip()
    port = _tavily_port_name(cur.get("lastPort") if isinstance(cur.get("lastPort"), str) else None)
    if port:
        stored["lastPort"] = port
    return stored


def _tavily_key(day: str | None = None) -> str:
    return f"{day or today()}:tavily"


def tavily_usage(day: str | None = None) -> dict[str, Any]:
    """Credits consumed today (1 credit per Tavily HTTP call)."""
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(NS, _tavily_key(day))
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return _tavily_empty()
    out = _tavily_empty()
    for k in ("credits", "calls"):
        try:
            out[k] = int(val[k])
        except (TypeError, ValueError, KeyError):
            pass
    at = val.get("lastAt")
    if isinstance(at, str) and at.strip():
        out["lastAt"] = at.strip()
    port = _tavily_port_name(val.get("lastPort") if isinstance(val.get("lastPort"), str) else None)
    if port:
        out["lastPort"] = port
    return out


DEFAULT_TAVILY_CAP = 80


def tavily_cap() -> int:
    return _env_int("NAVIGUIDE_TAVILY_DAILY_CREDITS", DEFAULT_TAVILY_CAP)


def allow_tavily() -> bool:
    """False when today's Tavily credits are at/over the cap — no network."""
    return int(tavily_usage()["credits"]) < tavily_cap()


def _fallback_empty() -> dict[str, int]:
    return {p: 0 for p in FALLBACK_PROVIDERS}


def _fallback_key(day: str | None = None) -> str:
    return f"{day or today()}:fallback"


def fallback_usage(day: str | None = None) -> dict[str, int]:
    """Repli NIM / OpenRouter / Claude du jour (LT2)."""
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(NS, _fallback_key(day))
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return _fallback_empty()
    out = _fallback_empty()
    for k in out:
        try:
            out[k] = max(0, int(val.get(k) or 0))
        except (TypeError, ValueError):
            pass
    return out


def record_fallback(provider: str, tier: str | None = None) -> dict[str, int]:
    """Compte un succès après échec Token Factory (palier ignoré pour l'agrégat jour)."""
    import pearl_store  # noqa: PLC0415

    prov = (provider or "").strip().lower()
    if prov not in _fallback_empty():
        return fallback_usage()
    with _LOCK:
        cur = fallback_usage()
        cur[prov] = int(cur[prov]) + 1
        pearl_store.kv_put(NS, _fallback_key(), cur)
        return dict(cur)


def _retry_super_key(day: str | None = None) -> str:
    return f"{day or today()}:retry-super"


def retry_super_usage(day: str | None = None) -> dict[str, int]:
    """Seconds essais Super (palier fast, LT1) du jour."""
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(NS, _retry_super_key(day))
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return {"count": 0}
    try:
        return {"count": max(0, int(val.get("count") or 0))}
    except (TypeError, ValueError):
        return {"count": 0}


def record_retry_super() -> dict[str, int]:
    import pearl_store  # noqa: PLC0415

    with _LOCK:
        cur = retry_super_usage()
        nxt = {"count": int(cur["count"]) + 1}
        pearl_store.kv_put(NS, _retry_super_key(), nxt)
        return dict(nxt)


def record_tavily(credits: int = 1, port: str | None = None) -> dict[str, Any]:
    """Add one Tavily search/extract call (1 credit / call)."""
    import pearl_store  # noqa: PLC0415

    add = max(0, int(credits))
    with _LOCK:
        cur = tavily_usage()
        cur["credits"] = int(cur["credits"]) + add
        cur["calls"] = int(cur["calls"]) + 1
        cur["lastAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        name = _tavily_port_name(port)
        if name:
            cur["lastPort"] = name
        pearl_store.kv_put(NS, _tavily_key(), _tavily_persist(cur))
        return dict(cur)


def remember_tavily_port(port: str | None) -> None:
    """Mémorise le port du dernier appel. Jamais la requête, jamais la clé."""
    import pearl_store  # noqa: PLC0415

    name = _tavily_port_name(port)
    if not name:
        return
    with _LOCK:
        cur = tavily_usage()
        cur["lastPort"] = name
        if not cur.get("lastAt"):
            cur["lastAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        pearl_store.kv_put(NS, _tavily_key(), _tavily_persist(cur))


# --- Latence mesurée par palier (C1-a) -------------------------------------
# Durée de l'aller-retour HTTP Token Factory (time.monotonic autour du POST),
# par palier du modèle réellement appelé. On garde les derniers échantillons
# du jour (UTC) pour une médiane ; aucune donnée de prompt n'est stockée.
LATENCY_SAMPLES = 51


def _latency_key(day: str | None = None) -> str:
    return f"{day or today()}:latency"


def _latency_raw(day: str | None = None) -> dict[str, dict[str, Any]]:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(NS, _latency_key(day))
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in val.items():
        if k not in TIERS or not isinstance(v, dict):
            continue
        samples = [int(x) for x in (v.get("samples") or []) if isinstance(x, (int, float)) and x >= 0]
        try:
            calls = max(0, int(v.get("calls") or len(samples)))
        except (TypeError, ValueError):
            calls = len(samples)
        try:
            timeouts = max(0, int(v.get("timeouts") or 0))
        except (TypeError, ValueError):
            timeouts = 0
        out[k] = {"samples": samples[-LATENCY_SAMPLES:], "calls": calls, "timeouts": timeouts}
        for error_key in ("networkErrors", "httpErrors"):
            errors = v.get(error_key) or []
            if isinstance(errors, list):
                out[k][error_key] = [dict(e) for e in errors[-LATENCY_SAMPLES:] if isinstance(e, dict)]
    return out


def record_latency(tier: str, ms: float) -> None:
    """Un appel Token Factory réussi (HTTP < 400) a pris `ms` millisecondes."""
    import pearl_store  # noqa: PLC0415

    t = normalize_tier(tier)
    try:
        val = int(round(float(ms)))
    except (TypeError, ValueError):
        return
    if val < 0:
        return
    def update(raw):
        cur = raw if isinstance(raw, dict) else {}
        cur = {k: dict(v) for k, v in cur.items() if k in TIERS and isinstance(v, dict)}
        row = cur.get(t) or {"samples": [], "calls": 0, "timeouts": 0}
        row["samples"] = (list(row["samples"]) + [val])[-LATENCY_SAMPLES:]
        row["calls"] = int(row["calls"]) + 1
        cur[t] = row
        return cur
    pearl_store.kv_update(NS, _latency_key(), update)


def record_latency_timeout(tier: str) -> None:
    """Un appel Token Factory a échoué par timeout (queue ou HTTP)."""
    import pearl_store  # noqa: PLC0415

    t = normalize_tier(tier)
    def update(raw):
        cur = raw if isinstance(raw, dict) else {}
        cur = {k: dict(v) for k, v in cur.items() if k in TIERS and isinstance(v, dict)}
        row = cur.get(t) or {"samples": [], "calls": 0, "timeouts": 0}
        row["timeouts"] = int(row["timeouts"]) + 1
        cur[t] = row
        return cur
    pearl_store.kv_update(NS, _latency_key(), update)


def record_latency_error(tier: str, kind: str, ms: float, status: int | None = None) -> None:
    """Record a failed TF request separately from successful latency samples."""
    import pearl_store  # noqa: PLC0415

    if kind not in {"networkErrors", "httpErrors"}:
        return
    t = normalize_tier(tier)
    try:
        duration = max(0, int(round(float(ms))))
    except (TypeError, ValueError):
        return

    def update(raw):
        cur = raw if isinstance(raw, dict) else {}
        cur = {k: dict(v) for k, v in cur.items() if k in TIERS and isinstance(v, dict)}
        row = cur.setdefault(t, {"samples": [], "calls": 0, "timeouts": 0})
        entries = list(row.get(kind) or [])
        error = {"ms": duration}
        if kind == "httpErrors":
            error["status"] = int(status or 0)
        entries = (entries + [error])[-LATENCY_SAMPLES:]
        row[kind] = entries
        cur[t] = row
        return cur

    pearl_store.kv_update(NS, _latency_key(), update)


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else int(round((s[mid - 1] + s[mid]) / 2))


def latency_status(day: str | None = None) -> dict[str, dict[str, int]]:
    """`{tier: {lastMs, medianMs, calls, timeouts?}}` pour les paliers appelés aujourd'hui."""
    out: dict[str, dict[str, Any]] = {}
    for t, row in _latency_raw(day).items():
        samples = row["samples"]
        calls = int(row["calls"])
        timeouts = int(row.get("timeouts", 0))
        if not samples and timeouts == 0 and not row.get("networkErrors") and not row.get("httpErrors"):
            continue
        entry: dict[str, int] = {"calls": calls, "samples": len(samples)}
        if samples:
            entry["lastMs"] = samples[-1]
            entry["medianMs"] = _median(samples) or 0
        if timeouts > 0:
            entry["timeouts"] = timeouts
        for key in ("networkErrors", "httpErrors"):
            errors = row.get(key) or []
            if errors:
                entry[key] = {"count": len(errors), "last": dict(errors[-1])}
        out[t] = entry
    return out


# --- Garde de disponibilité des modèles (C1-b) -------------------------------
# Un id configuré absent du catalogue Token Factory de son hôte : la cascade
# prend un autre Nemotron TF présent (libellé réel) ou passe au repli suivant.
# Compteur du jour par palier demandé, avec l'id manquant et le remplaçant.
def _guard_key(day: str | None = None) -> str:
    return f"{day or today()}:model-missing"


def model_missing_usage(day: str | None = None) -> dict[str, dict[str, Any]]:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(NS, _guard_key(day))
    val = (hit or {}).get("value")
    if not isinstance(val, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in val.items():
        if k in TIERS and isinstance(v, dict) and v.get("model"):
            try:
                count = max(0, int(v.get("count") or 0))
            except (TypeError, ValueError):
                count = 0
            out[k] = {
                "model": str(v.get("model")),
                "substitute": str(v["substitute"]) if v.get("substitute") else None,
                "substituteTier": str(v["substituteTier"]) if v.get("substituteTier") else None,
                "count": count,
            }
    return out


def record_model_missing(
    tier: str, model: str, substitute_tier: str | None = None, substitute: str | None = None,
) -> dict[str, Any]:
    """Compte un appel dont le modèle configuré manquait au catalogue de son hôte."""
    import pearl_store  # noqa: PLC0415

    t = normalize_tier(tier)
    with _LOCK:
        cur = model_missing_usage()
        row = cur.get(t) or {"count": 0}
        row.update({
            "model": (model or "").strip(),
            "substitute": (substitute or "").strip() or None,
            "substituteTier": normalize_tier(substitute_tier) if substitute_tier else None,
            "count": int(row.get("count") or 0) + 1,
        })
        cur[t] = row
        pearl_store.kv_put(NS, _guard_key(), cur)
        return dict(row)


def worst_case_day_usd(caps: dict[str, int] | None = None) -> float:
    """Borne haute d'une journée : tous les tokens au plafond, facturés au prix de sortie."""
    c = caps if caps is not None else {t: daily_cap(t) for t in TIERS}
    return round(sum(int(c[t]) * PRICES_PER_M[t][1] / 1_000_000 for t in TIERS), 6)


def caps_status() -> dict[str, Any]:
    """Plafonds effectifs (env inclus) et reste du jour — pour vérifier que les juges
    ne tombent pas sur `source=budget`. Aucun montant de solde n'est lu ni écrit."""
    tokens = {t: daily_cap(t) for t in TIERS}
    remaining = {t: max(0, tokens[t] - int(get_usage(t)["tokens"])) for t in TIERS}
    usd_cap = daily_usd_cap()
    return {
        "tokens": tokens,
        "remaining": remaining,
        "dailyUsd": usd_cap,
        "worstCaseDayUsd": worst_case_day_usd(tokens),
        "tavilyCredits": tavily_cap(),
    }


def status() -> dict[str, Any]:
    """Shape for `/ici/warm/status` → `llm: {tier: {tokens, calls, usd}}`."""
    out: dict[str, Any] = {}
    for t in TIERS:
        u = get_usage(t)
        out[t] = {
            "tokens": int(u["tokens"]),
            "calls": int(u["calls"]),
            "usd": float(u["usd"]),
        }
    tv = tavily_usage()
    out["tavily"] = {
        "credits": int(tv["credits"]),
        "calls": int(tv["calls"]),
        "lastAt": tv.get("lastAt"),
        "lastPort": tv.get("lastPort"),
    }
    out["caps"] = caps_status()
    ultra = chat_ultra_usage()
    out["chatUltra"] = {"calls": int(ultra["calls"]), "cap": chat_ultra_cap()}
    src = last_source()
    if src:
        out["lastSource"] = src
    by_tier = last_source_by_tier()
    if by_tier:
        out["lastSourceByTier"] = by_tier
    out["fallback"] = fallback_usage()
    out["retrySuper"] = int(retry_super_usage()["count"])
    out["tfQuota"] = tokenfactory_quota_status()
    out["configuredModels"] = configured_models()
    lat = latency_status()
    if lat:
        out["latency"] = lat
    out["modelGuard"] = model_guard_status()
    by_model = last_model_by_tier()
    if by_model:
        out["lastModelByTier"] = by_model
    errs = last_errors()
    if errs:
        out["lastErrors"] = errs
        out["lastError"] = last_error()
        at = last_error_at()
        if at:
            out["lastErrorAt"] = at
    return out


def model_guard_status() -> dict[str, Any]:
    """Garde de disponibilité (cache seulement, aucun appel réseau)."""
    import tf_catalog  # noqa: PLC0415

    return {
        "enabled": tf_catalog.enabled(),
        "catalogs": tf_catalog.status(),
        "missing": model_missing_usage(),
    }

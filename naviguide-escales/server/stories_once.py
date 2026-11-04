"""Récits du voyage officiel, préparés une fois (job ``stories_177``).

L'inventaire vient des événements de la route (perles déjà en stock), pas d'une
liste figée. Le commentaire historique parle d'environ 177 appels : le compte
réel est celui de ``inventory``. La chaîne est celle du clic Rédigé : Super
écrit, Ultra édite, un autre appel juge, Lightning traduit. Pas de relecture
payante en plus : elle reste sur le clic. ``ici_warm`` ne lance pas ce job.

Chaque récit est rangé sous ``stories/pg1.json`` dans le dossier du stock
officiel (révision dans le nom et dans le document). Un récit déjà complet
(français et anglais) ne rappelle pas le modèle.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

JOB = "stories_177"
REV = "pg1"
# Le lot dit « 177 ». Ce n'est pas une constante du code : ici_warm parle
# d'environ 177 appels Super, retirés du préchauffage. On compare, on ne plaque pas.
BATCH_FIGURE = 177

# Forme locale d'un appel, calée sur les plafonds déjà écrits dans la chaîne
# (une phrase : plancher 400, juge 128, traduction plancher 256). Pas une sortie de modèle.
_STEPS = (
    ("w", "write", 512, 400),
    ("e", "judge", 512, 400),
    ("j", "judge", 256, 128),
    ("t", "write", 2048, 2048),
)
_STEP = {step: (tier, prompt, completion) for step, tier, prompt, completion in _STEPS}

_INVENTORY: list[dict[str, Any]] | None = None
_COMPUTED: tuple[dict[str, Any], ...] | None = None
_CASCADE = None


def set_inventory(rows: list[dict[str, Any]] | None) -> None:
    """Liste imposée (tests). ``None`` retrouve le calcul sur la route."""
    global _INVENTORY, _COMPUTED
    _INVENTORY = None if rows is None else [dict(row) for row in rows]
    _COMPUTED = None


def set_cascade(fn) -> None:
    """Cascade factice. ``None`` retrouve ``cascade_text`` (réservé à ``--run``)."""
    global _CASCADE
    _CASCADE = fn


def reset_inventory_cache() -> None:
    global _COMPUTED
    _COMPUTED = None


def _digest(stable_key: str) -> str:
    return hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:32]


def _call_id(step: str, stable_key: str) -> str:
    return f"{step}{_digest(stable_key)}"


def stories_from_events(events: list | None) -> list[dict[str, Any]]:
    """Clés stables, dédoublonnées, triées. Même forme que le client."""
    found: dict[str, dict[str, Any]] = {}
    saw_exit = False
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        kind, event = ev.get("kind"), ev.get("event")
        row: dict[str, Any] | None = None
        if kind == "zee" and event == "enter" and ev.get("mrgid"):
            row = _zee(ev)
        elif kind == "zee" and event == "exit":
            saw_exit = True
        elif kind == "amp" and event in {"enter", "nearby"} and ev.get("siteId"):
            row = _amp(ev)
        elif kind == "poe" and event == "passed" and ev.get("name"):
            row = _poe(ev)
        if row is not None:
            found.setdefault(str(row["stableKey"]), row)
    if saw_exit:
        # Le client ne demande qu'une sortie, vers la haute mer.
        exit_row = _exit()
        found.setdefault(exit_row["stableKey"], exit_row)
    return sorted(found.values(), key=lambda row: str(row["stableKey"]))


def _zee(ev: dict) -> dict[str, Any]:
    mrgid = ev.get("mrgid")
    name = ev.get("name")
    stable = f"zee-enter:{mrgid}"
    return {
        "type": "zee-enter",
        "stableKey": stable,
        "name": name or "",
        "event": {
            "type": "zee-enter",
            "name": name,
            "stableKey": stable,
            "payload": {"zee": {"name": name, "mrgid": mrgid}},
        },
    }


def _exit() -> dict[str, Any]:
    stable = "zee-exit:high-seas"
    return {
        "type": "zee-exit",
        "stableKey": stable,
        "name": "",
        "event": {"type": "zee-exit", "stableKey": stable, "payload": {"zee": None}},
    }


def _amp(ev: dict) -> dict[str, Any]:
    site = str(ev.get("siteId"))
    name = ev.get("name")
    typ = "amp-enter" if ev.get("event") == "enter" else "amp-ahead"
    stable = f"{typ}:{site}"
    nm = ev.get("nm")
    return {
        "type": typ,
        "stableKey": stable,
        "name": name or "",
        "event": {
            "type": typ,
            "name": name,
            "stableKey": stable,
            "whenNm": nm,
            "payload": {
                "amp": {"name": name, "site_id": site, "nm": nm, "inside": typ == "amp-enter"},
                "whenNm": nm,
            },
        },
    }


def _poe(ev: dict) -> dict[str, Any]:
    name = str(ev.get("name"))
    mrgid = ev.get("mrgid") or "x"
    stable = f"poe-ahead:{mrgid}:{name}"
    return {
        "type": "poe-ahead",
        "stableKey": stable,
        "name": name,
        "event": {
            "type": "poe-ahead",
            "name": name,
            "stableKey": stable,
            "payload": {"poe": {"name": name}, "zee": {"mrgid": ev.get("mrgid")}},
        },
    }


def _phrase(story: dict) -> str:
    text = str(story.get("rules") or "").strip()
    if not text:
        from film_script import phrase_for_ici_event  # noqa: PLC0415

        text = (phrase_for_ici_event(story.get("event") or {}, "fr") or "").strip()
    if text and text[-1] not in ".!?…":
        text += "."
    return text


def _with_rules(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        text = _phrase(row)
        if not text:
            continue
        item = dict(row)
        item["rules"] = text
        found.setdefault(str(item["stableKey"]), item)
    return [found[key] for key in sorted(found)]


def _official_points() -> list:
    try:
        from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415
        from voyage_store import load_voyage  # noqa: PLC0415

        voy = load_voyage(OFFICIAL_VOYAGE_ID)
    except Exception:
        return []
    points = (voy or {}).get("points") if isinstance(voy, dict) else None
    return points if isinstance(points, list) else []


@contextmanager
def _readonly_pearls() -> Iterator[bool]:
    """Lecture du stock de perles sans journal d'écriture."""
    import pearl_store  # noqa: PLC0415

    path = pearl_store.db_path()
    if not path.is_file():
        yield False
        return
    original = pearl_store._connect
    holder: dict[str, Any] = {"conn": None}

    def ro():
        if holder["conn"] is None:
            holder["conn"] = sqlite3.connect(
                f"file:{path.resolve()}?immutable=1",
                uri=True,
                check_same_thread=False,
            )
        return holder["conn"]

    pearl_store._connect = ro
    try:
        yield True
    finally:
        pearl_store._connect = original
        conn = holder["conn"]
        if conn is not None:
            conn.close()


def _compute() -> list[dict[str, Any]]:
    points = _official_points()
    if not points:
        return []
    from ici_warm import route_events_from_pearls  # noqa: PLC0415

    with _readonly_pearls():
        events = route_events_from_pearls(points)
    return _with_rules(stories_from_events(events))


def inventory() -> list[dict[str, Any]]:
    """Liste stable et triée. Vide si la route ou les perles manquent."""
    global _COMPUTED
    if _INVENTORY is not None:
        return _with_rules(_INVENTORY)
    if _COMPUTED is None:
        _COMPUTED = tuple(_compute())
    return [dict(row) for row in _COMPUTED]


def route_stamp(rows: list[dict[str, Any]] | None = None) -> str:
    keys = [str(row.get("stableKey") or "") for row in (rows if rows is not None else inventory())]
    raw = "\n".join(keys)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _store_root() -> Path | None:
    env = (os.environ.get("NAVIGUIDE_OFFICIAL_STORE_DIR") or "").strip()
    if env:
        return Path(env)
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
        return None
    try:
        import official_store  # noqa: PLC0415
    except Exception:
        return None
    return official_store.DEFAULT_DISK


def result_path(*, mkdir: bool = False) -> Path | None:
    root = _store_root()
    if root is None:
        return None
    path = Path(root) / "stories" / f"{REV}.json"
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load() -> dict | None:
    path = result_path()
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _save(doc: dict) -> None:
    path = result_path(mkdir=True)
    if path is None:
        raise OSError("stock officiel indisponible")
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _blank(stamp: str) -> dict[str, Any]:
    return {"rev": REV, "route": stamp, "job": JOB, "stories": {}}


def _doc(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    stamp = route_stamp(rows)
    doc = load()
    if not isinstance(doc, dict) or doc.get("rev") != REV or doc.get("route") != stamp:
        return _blank(stamp)
    if not isinstance(doc.get("stories"), dict):
        doc["stories"] = {}
    return doc


def _row(doc: dict, stable_key: str) -> dict[str, Any]:
    stories = doc.setdefault("stories", {})
    row = stories.get(stable_key)
    if not isinstance(row, dict):
        row = {}
        stories[stable_key] = row
    return row


def _slot_text(row: dict, lang: str) -> str:
    slot = row.get(lang)
    if isinstance(slot, dict):
        return str(slot.get("text") or "").strip()
    return ""


def _put_slot(row: dict, lang: str, text: str, source: str, **extra: Any) -> None:
    slot = {"text": text, "source": source or ""}
    slot.update({k: v for k, v in extra.items() if v})
    row[lang] = slot


def _kv_text(story: dict, lang: str) -> tuple[str, str] | None:
    try:
        import story_cache  # noqa: PLC0415
    except Exception:
        return None
    body = dict(story.get("event") or {})
    body["type"] = story.get("type")
    body["stableKey"] = story.get("stableKey")
    body["lang"] = lang
    hit = story_cache.get_cached(body)
    text = str((hit or {}).get("text") or "").strip()
    if not text:
        return None
    source = str((hit or {}).get("nvidia") or (hit or {}).get("engine") or "cache")
    return text, source


def _complete(row: dict) -> bool:
    return bool(_slot_text(row, "fr") and _slot_text(row, "en"))


def _absorb_kv(row: dict, story: dict) -> bool:
    changed = False
    for lang in ("fr", "en"):
        if _slot_text(row, lang):
            continue
        found = _kv_text(story, lang)
        if not found:
            continue
        text, source = found
        _put_slot(row, lang, text, source)
        changed = True
    return changed


def prepared(body: dict | None) -> dict | None:
    """Texte déjà préparé pour cette clé, ou ``None`` (le service reste à la demande)."""
    if not isinstance(body, dict):
        return None
    try:
        import story_cache  # noqa: PLC0415
    except Exception:
        return None
    key = story_cache.story_key(body)
    if not key or "|" not in key:
        return None
    parts = key.split("|")
    if len(parts) < 3:
        return None
    stable, lang = parts[1], parts[-1]
    doc = load()
    if not isinstance(doc, dict) or doc.get("rev") != REV or doc.get("route") != route_stamp():
        return None
    stories = doc.get("stories")
    if not isinstance(stories, dict):
        return None
    row = stories.get(stable)
    if not isinstance(row, dict):
        return None
    text = _slot_text(row, "en" if lang == "en" else "fr")
    if not text:
        return None
    slot = row.get("en" if lang == "en" else "fr")
    source = str((slot or {}).get("source") or "cache")
    out = {
        "status": "ready",
        "text": text,
        "engine": source,
        "source": source,
        "cascade": "tokenfactory-openrouter-claude",
        "tavily": None,
        "nvidia": source,
        "cached": True,
    }
    reviewed = (slot or {}).get("reviewedBy")
    if reviewed:
        out["reviewedBy"] = reviewed
    return out


def _cascade():
    if _CASCADE is not None:
        return _CASCADE
    from story_cascade import cascade_text  # noqa: PLC0415

    return cascade_text


def _run(coro):
    return asyncio.run(coro)


def _plan_dict(story: dict) -> dict[str, Any]:
    text = _phrase(story)
    name = story.get("name") or ""
    return {
        "chapters": [{
            "id": story.get("stableKey"),
            "text": text,
            "fromName": name,
            "toName": name,
        }],
        "targetSeconds": 0,
    }


def _chapter_text(plan: dict | None) -> str:
    if not isinstance(plan, dict):
        return ""
    chapters = [c for c in (plan.get("chapters") or []) if isinstance(c, dict)]
    if not chapters:
        return ""
    return str(chapters[0].get("text") or "").strip()


def _story_for(call_id: str, rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    step = call_id[:1]
    if step not in _STEP or len(call_id) < 2:
        raise KeyError(call_id)
    digest = call_id[1:]
    for row in rows:
        if _digest(str(row.get("stableKey") or "")) == digest:
            return step, row
    raise KeyError(call_id)


def _record(step: str) -> None:
    import llm_budget  # noqa: PLC0415

    tier, prompt, completion = _STEP[step]
    llm_budget.record(tier, prompt, completion)


def _write(story: dict, row: dict) -> None:
    from film_script import write_stored_plan  # noqa: PLC0415

    if not _phrase(story):
        return
    plan, _stats = _run(write_stored_plan(
        _plan_dict(story), lang="fr", cascade=_cascade(), seconds=0,
    ))
    _record("w")
    text = _chapter_text(plan)
    if not text:
        raise RuntimeError("rédaction vide")
    source = str((plan or {}).get("source") or "")
    _put_slot(row, "fr", text, source)
    row["frSuper"] = {"text": text, "source": source}


def _edit(story: dict, row: dict) -> None:
    from film_script import edit_written_once  # noqa: PLC0415

    if row.get("editDone"):
        return
    fr = _slot_text(row, "fr")
    row["editDone"] = True
    if not fr:
        return
    super_plan = {"chapters": [{"id": story.get("stableKey"), "text": fr}], "source": (row.get("fr") or {}).get("source")}
    edited = _run(edit_written_once(super_plan, _plan_dict(story), cascade=_cascade()))
    _record("e")
    text = _chapter_text(edited)
    if text:
        row["edit"] = {"text": text, "source": str((edited or {}).get("source") or "")}
    else:
        row["edit"] = None


def _judge(story: dict, row: dict) -> None:
    from film_script import REVIEWED_BY_ULTRA, judge_written_once  # noqa: PLC0415

    if row.get("judged") is not None:
        return
    candidate = row.get("edit") if isinstance(row.get("edit"), dict) else None
    text = str((candidate or {}).get("text") or "").strip()
    if not text:
        row["judged"] = False
        return
    plan = {"chapters": [{"id": story.get("stableKey"), "text": text}]}
    ok = bool(_run(judge_written_once(plan, cascade=_cascade())))
    _record("j")
    row["judged"] = ok
    if not ok:
        super_slot = row.get("frSuper") if isinstance(row.get("frSuper"), dict) else None
        if super_slot and super_slot.get("text"):
            _put_slot(row, "fr", str(super_slot["text"]), str(super_slot.get("source") or ""))
        return
    _put_slot(
        row, "fr", text,
        str(candidate.get("source") or (row.get("fr") or {}).get("source") or ""),
        reviewedBy=REVIEWED_BY_ULTRA,
    )


def _translate(story: dict, row: dict) -> None:
    from film_script import write_film_chain  # noqa: PLC0415

    if _slot_text(row, "en"):
        return
    if not _slot_text(row, "fr") or not _phrase(story):
        return
    en_raw = _plan_dict(story)
    if not en_raw:
        return
    _, en_plan, _stats = _run(
        write_film_chain(en_raw, seconds=0, lang="en", cascade=_cascade()),
    )
    if not en_plan or not (en_plan.get("chapters") or []):
        return
    _record("t")
    text = _chapter_text(en_plan)
    if not text:
        return
    _put_slot(row, "en", text, str((en_plan or {}).get("source") or ""))


def execute_call(call: Any) -> dict[str, Any]:
    """Une étape de la chaîne. Récit déjà complet : aucun appel."""
    rows = inventory()
    step, story = _story_for(str(call.call_id), rows)
    doc = _doc(rows)
    row = _row(doc, str(story["stableKey"]))
    row["type"] = story.get("type")
    if _absorb_kv(row, story):
        _save(doc)
    if _complete(row):
        return {"id": call.call_id, "cached": True}
    if step == "w":
        if not _slot_text(row, "fr"):
            _write(story, row)
    elif step == "e":
        _edit(story, row)
    elif step == "j":
        _judge(story, row)
    else:
        _translate(story, row)
    _save(doc)
    return {"id": call.call_id, "cached": False}


def plan_calls() -> list[Any]:
    import one_shot  # noqa: PLC0415

    planned = []
    for story in inventory():
        stable = str(story["stableKey"])
        for step, tier, prompt, completion in _STEPS:
            planned.append(one_shot.PlannedCall(_call_id(step, stable), tier, prompt, completion))
    return planned


def estimate_extra() -> str:
    n = len(inventory())
    differs = "yes" if n != BATCH_FIGURE else "no"
    lines = [
        f"stories: {n}",
        f"batch_figure: {BATCH_FIGURE}",
        f"batch_figure_differs: {differs}",
        "calls_per_story: 4",
        "roles: write edit judge translate",
        "langs: fr en",
    ]
    return "\n".join(lines) + "\n"


def register_job() -> None:
    import one_shot  # noqa: PLC0415

    if JOB in one_shot.REGISTRY:
        return
    one_shot.register(one_shot.Job(JOB, plan_calls, execute_call, estimate_extra))

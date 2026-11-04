"""Passage unique : perles du voyage officiel, ajout seul, plafond mémoire.

Le chauffeur de fond (`ici_warm.start_background`) n'est pas lancé.
`--estimate` ne persiste rien. `--run` reprend après un arrêt et refuse
un second passage simultané. Une perle qui exigerait un LLM, Nebius ou
Tavily est sautée et comptée à part.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

log = logging.getLogger("naviguide-simulator.pearls-warm")

JOB = "pearls_warm"
SAMPLE = 20
RESTORED_MOMENTS = 1142
# Sous MemoryMax=2G de l'unité : on s'arrête avant que systemd ne tue.
MEMORY_MAX_DEFAULT = 1600 * 1024 * 1024
ENV_DIR = "NAVIGUIDE_ONE_SHOT_DIR"
ENV_MEMORY = "NAVIGUIDE_PEARLS_WARM_MEMORY_MAX"
ENV_FLOOR = "NAVIGUIDE_PEARLS_WARM_MOMENT_FLOOR"

_THREAD = threading.Lock()
_STATUS_KEYS = (
    "state",
    "done",
    "skipped",
    "remaining",
    "llmSkipped",
    "lastError",
    "found",
    "routePoints",
)


class PearlsWarmError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Refused(PearlsWarmError):
    pass


class Stopped(PearlsWarmError):
    pass


class Failed(PearlsWarmError):
    pass


class NeedsLlm(Exception):
    """La perle ne peut pas être calculée sans LLM, Nebius ou Tavily."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _data_root(*, mkdir: bool) -> Path:
    raw = (os.environ.get(ENV_DIR) or "").strip()
    path = Path(raw).expanduser() if raw else Path.home() / ".local" / "share" / "naviguide" / "one-shot"
    resolved = path.resolve()
    repo = _repo_root().resolve()
    if resolved == repo or repo in resolved.parents:
        raise Refused("bad-dir", "le dossier de verrou doit être hors dépôt")
    if mkdir:
        resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _job_dir(*, mkdir: bool) -> Path:
    path = _data_root(mkdir=mkdir) / JOB
    if mkdir:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _idle() -> dict[str, Any]:
    return {
        "state": "idle",
        "done": 0,
        "skipped": 0,
        "remaining": 0,
        "llmSkipped": 0,
        "lastError": None,
        "found": None,
        "routePoints": None,
    }


def _scrub(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    out = []
    for token in value.split():
        if "/" in token or token.startswith("~") or (len(token) > 2 and token[1] == ":"):
            out.append("…")
        else:
            out.append(token)
    return " ".join(out)[:300]


def public_status() -> dict[str, Any]:
    """Bloc `pearlsWarm` : aucun chemin privé."""
    base = _idle()
    try:
        path = _job_dir(mkdir=False) / "status.json"
        if not path.is_file():
            return base
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return base
    if not isinstance(raw, dict):
        return base
    for key in _STATUS_KEYS:
        if key not in raw:
            continue
        base[key] = _scrub(raw[key])
    for key in ("done", "skipped", "remaining", "llmSkipped"):
        try:
            base[key] = max(0, int(base[key]))
        except (TypeError, ValueError):
            base[key] = 0
    for key in ("found", "routePoints"):
        if base[key] is None:
            continue
        try:
            base[key] = max(0, int(base[key]))
        except (TypeError, ValueError):
            base[key] = None
    if base["state"] not in {"idle", "running", "stopped", "done", "error", "refused"}:
        base["state"] = "idle"
    if base["lastError"] is not None and not isinstance(base["lastError"], str):
        base["lastError"] = None
    return base


def _atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = text.encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC, 0o600)
    try:
        view = data
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("écriture incomplète")
            view = view[written:]
        os.fsync(fd)
    except Exception:
        os.close(fd)
        tmp.unlink(missing_ok=True)
        raise
    os.close(fd)
    os.replace(tmp, path)


def _publish(**fields: Any) -> None:
    body = _idle()
    body.update(fields)
    safe = {key: _scrub(body.get(key)) for key in _STATUS_KEYS}
    _atomic(_job_dir(mkdir=True) / "status.json", safe)


def memory_cap() -> int:
    raw = (os.environ.get(ENV_MEMORY) or "").strip()
    if not raw:
        return MEMORY_MAX_DEFAULT
    return max(1, int(raw))


def memory_bytes() -> int:
    """Octets du cgroup (ce que MemoryMax surveille), sinon RSS du processus."""
    current = _cgroup_current()
    if current is not None:
        return current
    return _rss_bytes()


def _cgroup_current() -> int | None:
    try:
        text = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        rel = parts[2].strip()
        candidate = Path("/sys/fs/cgroup/memory.current") if rel in ("", "/") else Path("/sys/fs/cgroup") / rel.lstrip("/") / "memory.current"
        try:
            return int(candidate.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return None


def _rss_bytes() -> int:
    import resource
    import sys
    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return rss
    return rss * 1024


def moment_base() -> int:
    raw = (os.environ.get(ENV_FLOOR) or "").strip()
    if raw == "":
        return RESTORED_MOMENTS
    return max(0, int(raw))


def required_moments(before: int) -> int:
    """1142 restaurés avant le split, plus les moments ajoutés depuis."""
    base = moment_base()
    if before >= base:
        return before
    return base


def counts() -> dict[str, int]:
    import pearl_store  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

    return {
        "pearls": int((pearl_store.count_pearls() or {}).get("total") or 0),
        "moments": int(pearl_store.count_moments(OFFICIAL_VOYAGE_ID)),
    }


def _bag_ready(bag: dict) -> bool:
    amps = bag.get("amp")
    if not isinstance(amps, list):
        return False
    if not amps:
        return True
    return all(isinstance(item, dict) and "source" in item for item in amps)


def _cell(lat: float, lon: float) -> tuple[float, float]:
    from ici_engine import _pearl_cell  # noqa: PLC0415

    return _pearl_cell(lat, lon)


def inventory() -> list[dict[str, Any]]:
    """Positions stables, triées, dédupliquées par cellule."""
    from ici_warm import sample_route_nm  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415
    from voyage_store import load_voyage  # noqa: PLC0415

    voy = load_voyage(OFFICIAL_VOYAGE_ID) or {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for point in sample_route_nm(voy.get("points") or []):
        lat, lon = float(point["lat"]), float(point["lon"])
        la, lo = _cell(lat, lon)
        cell = f"{la:.2f}:{lo:.2f}"
        if cell in seen:
            continue
        seen.add(cell)
        rows.append({
            "id": cell,
            "lat": lat,
            "lon": lon,
            "sailNm": float(point.get("sailNm") or 0),
        })
    rows.sort(key=lambda row: (round(row["sailNm"], 2), row["id"]))
    return rows


def cached_valid(pearl: dict[str, Any]) -> bool:
    """Vrai si une perle fraîche et riche est déjà lisible, ancien format compris."""
    from ici_engine import _fresh, resolve_pearl_row  # noqa: PLC0415

    row, _key = resolve_pearl_row(float(pearl["lat"]), float(pearl["lon"]), 30.0)
    if not row or not isinstance(row.get("bag"), dict):
        return False
    if row.get("kind") != "rich":
        return False
    if not _fresh({"ts": row.get("ts"), "kind": row.get("kind")}):
        return False
    return _bag_ready(row["bag"])


def canonical_key(pearl: dict[str, Any]) -> str:
    from ici_engine import thin_cache_key  # noqa: PLC0415

    return thin_cache_key(float(pearl["lat"]), float(pearl["lon"]), 30.0)


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def plan() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    pearls = inventory()
    pending = [pearl for pearl in pearls if not cached_valid(pearl)]
    ids = [pearl["id"] for pearl in pearls]
    body = {
        "job": JOB,
        "ids": ids,
        "toCompute": len(pending),
        "inventory": _fingerprint({"ids": ids}),
    }
    shown = {key: body[key] for key in ("job", "ids", "toCompute")}
    body["fingerprint"] = _fingerprint(shown)
    return pearls, pending, body


def _guard(before: dict[str, int], outcome: dict[str, str], total: int) -> None:
    now = counts()
    if now["pearls"] >= before["pearls"] and now["moments"] >= before["moments"]:
        return
    done, skipped, llm_skipped = _tally(outcome)
    message = (
        f"refus : un compte baisse "
        f"(perles {before['pearls']}→{now['pearls']}, "
        f"moments {before['moments']}→{now['moments']})"
    )
    _publish(
        state="refused",
        done=done,
        skipped=skipped,
        remaining=max(0, total - len(outcome)),
        llmSkipped=llm_skipped,
        lastError=message,
        routePoints=total,
    )
    raise Refused("count-down", message)


def coverage(pearls: list[dict[str, Any]]) -> tuple[int, int]:
    from ici_engine import resolve_pearl_row  # noqa: PLC0415

    found = 0
    for pearl in pearls:
        row, key = resolve_pearl_row(float(pearl["lat"]), float(pearl["lon"]), 30.0)
        if key and row and isinstance(row.get("bag"), dict):
            found += 1
    return found, len(pearls)


def assert_consistent(
    *,
    found: int,
    route_points: int,
    moments_before: int,
    moments_now: int,
    pearls_before: int,
    pearls_now: int,
) -> None:
    problems: list[str] = []
    if found < route_points:
        problems.append(f"perles trouvées {found}/{route_points}")
    need = required_moments(moments_before)
    if moments_now < need:
        problems.append(
            f"moments {moments_now} < {need} "
            f"(plancher {moment_base()} + les moments ajoutés depuis la restauration)"
        )
    if moments_now < moments_before:
        problems.append(f"moments en baisse {moments_before}→{moments_now}")
    if pearls_now < pearls_before:
        problems.append(f"perles en baisse {pearls_before}→{pearls_now}")
    if problems:
        raise Failed("consistency", "échec : " + " ; ".join(problems))


@contextmanager
def _no_store_writes() -> Iterator[None]:
    import official_store  # noqa: PLC0415
    import pearl_store  # noqa: PLC0415

    saved = (
        pearl_store.put_pearl,
        pearl_store.insert_pearl_if_absent,
        pearl_store.delete_pearl,
        pearl_store.replace_moments,
        pearl_store.kv_put,
        pearl_store.kv_delete,
        official_store.put,
    )

    def refuse(*_a: Any, **_k: Any) -> bool:
        raise Refused("estimate-write", "estimation : écriture refusée")

    def noop(*_a: Any, **_k: Any) -> bool:
        return False

    pearl_store.put_pearl = refuse
    pearl_store.insert_pearl_if_absent = refuse
    pearl_store.delete_pearl = refuse
    pearl_store.replace_moments = refuse
    pearl_store.kv_put = noop
    pearl_store.kv_delete = refuse
    official_store.put = refuse
    try:
        yield
    finally:
        (
            pearl_store.put_pearl,
            pearl_store.insert_pearl_if_absent,
            pearl_store.delete_pearl,
            pearl_store.replace_moments,
            pearl_store.kv_put,
            pearl_store.kv_delete,
            official_store.put,
        ) = saved


@contextmanager
def _llm_trap() -> Iterator[None]:
    import llm_budget  # noqa: PLC0415

    saved = (llm_budget.record, llm_budget.record_tavily, llm_budget.record_chat_ultra)

    def blocked(*_a: Any, **_k: Any) -> None:
        raise NeedsLlm()

    llm_budget.record = blocked
    llm_budget.record_tavily = blocked
    llm_budget.record_chat_ultra = blocked
    try:
        yield
    finally:
        llm_budget.record, llm_budget.record_tavily, llm_budget.record_chat_ultra = saved


def _shell(pearl: dict[str, Any]) -> dict[str, Any]:
    from ici_engine import empty_dossier  # noqa: PLC0415

    bag = empty_dossier(float(pearl["lat"]), float(pearl["lon"]), 30.0)
    bag["amp"] = []
    bag["pearl"] = "rich"
    return bag


def real_fill(pearl: dict[str, Any]) -> dict[str, Any] | None:
    """Calcul sans LLM. Interdit pendant pytest (aucun appel réseau)."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError("remplissage réel interdit pendant les tests")
    from ici_engine import _fill_dossier  # noqa: PLC0415
    from ici_warm import _run_coro  # noqa: PLC0415

    def _call() -> Any:
        return _run_coro(lambda: _fill_dossier(
            float(pearl["lat"]), float(pearl["lon"]), 30.0,
            None, None, None, None, True, True,
        ))

    with _llm_trap():
        bag = _call()
    if not isinstance(bag, dict) or bag.get("ampFallback") or not _bag_ready(bag):
        return None
    return bag


def _sample_fill(pearl: dict[str, Any]) -> dict[str, Any] | None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return _shell(pearl)
    return real_fill(pearl)


def _measure(pending: list[dict[str, Any]], fill: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    sample = pending[:SAMPLE]
    before_mem = int(memory_bytes())
    started = time.perf_counter()
    kept: list[Any] = []
    before_counts = counts()
    with _no_store_writes():
        for pearl in sample:
            try:
                kept.append(fill(pearl))
            except Exception:
                kept.append(None)
    after_counts = counts()
    if after_counts != before_counts:
        raise Refused("estimate-write", "estimation : un compte a changé")
    del kept
    return {
        "sample": len(sample),
        "sampleSeconds": round(time.perf_counter() - started, 6),
        "sampleRssBytes": max(0, int(memory_bytes()) - before_mem),
    }


def estimate(*, fill: Callable[[dict[str, Any]], Any] | None = None) -> dict[str, Any]:
    """Compte les perles à calculer et mesure un échantillon de 20. N'écrit pas."""
    _pearls, pending, body = plan()
    measured = _measure(pending, fill or _sample_fill)
    return {**body, **measured, "cached": len(body["ids"]) - body["toCompute"]}


def format_estimate(est: dict[str, Any]) -> str:
    lines = [
        f"job: {est['job']}",
        f"perles: {len(est['ids'])}",
        f"a_calculer: {est['toCompute']}",
        f"deja_valides: {est.get('cached', 0)}",
        f"echantillon: {est['sample']}",
        f"memoire_octets: {est['sampleRssBytes']}",
        f"duree_s: {est['sampleSeconds']}",
        f"empreinte: {est['fingerprint']}",
    ]
    return "\n".join(lines) + "\n"


@contextmanager
def _hold() -> Iterator[None]:
    if not _THREAD.acquire(blocking=False):
        raise Refused("busy", "un passage est déjà en cours")
    fd = None
    try:
        directory = _job_dir(mkdir=True)
        fd = os.open(directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused("busy", "un passage est déjà en cours") from exc
        yield
    finally:
        if fd is not None:
            os.close(fd)
        _THREAD.release()


def _load_progress(inventory_fp: str) -> dict[str, str]:
    path = _job_dir(mkdir=False) / "progress.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Failed("progress", "avancement illisible") from exc
    if not isinstance(raw, dict) or raw.get("inventory") != inventory_fp:
        raise Failed("progress", "l'avancement ne correspond pas à cet inventaire")
    outcome = raw.get("outcome")
    if not isinstance(outcome, dict):
        raise Failed("progress", "avancement illisible")
    return {str(key): str(value) for key, value in outcome.items()}


def _save_progress(inventory_fp: str, outcome: dict[str, str]) -> None:
    _atomic(
        _job_dir(mkdir=True) / "progress.json",
        {"inventory": inventory_fp, "outcome": outcome},
    )


def _done_blocks(inventory_fp: str) -> bool:
    path = _job_dir(mkdir=False) / ".done"
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refused("done", "verrou de réussite illisible") from exc
    return isinstance(raw, dict) and raw.get("inventory") == inventory_fp


def _over_memory() -> bool:
    try:
        used = int(memory_bytes())
    except Exception as exc:
        raise Stopped("memory", "arrêt propre : mémoire illisible") from exc
    return used >= memory_cap()


def _tally(outcome: dict[str, str]) -> tuple[int, int, int]:
    done = sum(1 for value in outcome.values() if value == "done")
    skipped = sum(1 for value in outcome.values() if value == "skipped")
    llm_skipped = sum(1 for value in outcome.values() if value == "llm")
    return done, skipped, llm_skipped


def run(
    *,
    fill: Callable[[dict[str, Any]], Any] | None = None,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Écrit chaque perle manquante, ou s'arrête proprement avant le plafond."""
    filler = fill or real_fill
    with _hold():
        pearls, _pending, body = plan()
        if not pearls:
            message = "aucune perle à préparer sur la route officielle"
            _publish(state="error", lastError=message)
            raise Failed("empty", message)
        token = (fingerprint or "").strip().lower()
        if token and token != body["fingerprint"]:
            raise Refused("bad-fingerprint", "empreinte différente de l'estimation")
        if _done_blocks(body["inventory"]):
            raise Refused("done", "passage déjà terminé pour cet inventaire")
        outcome = _load_progress(body["inventory"])
        before = counts()
        last_error = None
        total = len(pearls)
        for pearl in pearls:
            if pearl["id"] in outcome:
                continue
            if _over_memory():
                done, skipped, llm_skipped = _tally(outcome)
                message = "arrêt propre avant le plafond mémoire"
                _save_progress(body["inventory"], outcome)
                _publish(
                    state="stopped",
                    done=done,
                    skipped=skipped,
                    remaining=total - len(outcome),
                    llmSkipped=llm_skipped,
                    lastError=message,
                    found=None,
                    routePoints=total,
                )
                log.warning("%s", message)
                raise Stopped("memory", message)
            if cached_valid(pearl):
                outcome[pearl["id"]] = "skipped"
                _save_progress(body["inventory"], outcome)
                _guard(before, outcome, total)
                continue
            try:
                with _llm_trap():
                    bag = filler(pearl)
            except NeedsLlm:
                outcome[pearl["id"]] = "llm"
                last_error = "perle sautée : LLM requis"
                _save_progress(body["inventory"], outcome)
                _guard(before, outcome, total)
                continue
            if not isinstance(bag, dict) or bag.get("ampFallback") or not _bag_ready(bag):
                last_error = "perle non prête — non écrite"
                continue
            key = canonical_key(pearl)
            if key.endswith(":a0"):
                last_error = "signature de couche absente — perle non écrite"
                continue
            import pearl_store  # noqa: PLC0415

            if pearl_store.get_pearl(key):
                outcome[pearl["id"]] = "skipped"
                _save_progress(body["inventory"], outcome)
                _guard(before, outcome, total)
                continue
            inserted = pearl_store.insert_pearl_if_absent(
                key, bag, "rich", float(pearl["lat"]), float(pearl["lon"]),
            )
            if not inserted and not pearl_store.get_pearl(key):
                last_error = "écriture non faite"
                continue
            outcome[pearl["id"]] = "done" if inserted else "skipped"
            _save_progress(body["inventory"], outcome)
            _guard(before, outcome, total)
        done, skipped, llm_skipped = _tally(outcome)
        now = counts()
        found, route_points = coverage(pearls)
        try:
            assert_consistent(
                found=found,
                route_points=route_points,
                moments_before=before["moments"],
                moments_now=now["moments"],
                pearls_before=before["pearls"],
                pearls_now=now["pearls"],
            )
        except Failed as exc:
            _publish(
                state="error",
                done=done,
                skipped=skipped,
                remaining=total - len(outcome),
                llmSkipped=llm_skipped,
                lastError=str(exc),
                found=found,
                routePoints=route_points,
            )
            raise
        _atomic(
            _job_dir(mkdir=True) / ".done",
            {"inventory": body["inventory"], "job": JOB},
        )
        progress = _job_dir(mkdir=False) / "progress.json"
        if progress.is_file():
            progress.unlink()
        _publish(
            state="done",
            done=done,
            skipped=skipped,
            remaining=0,
            llmSkipped=llm_skipped,
            lastError=last_error,
            found=found,
            routePoints=route_points,
        )
        return {
            "job": JOB,
            "done": done,
            "skipped": skipped,
            "llmSkipped": llm_skipped,
            "found": found,
            "routePoints": route_points,
        }


def _push_env(updates: dict[str, str]) -> dict[str, str | None]:
    old = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    return old


def _pop_env(old: dict[str, str | None]) -> None:
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="pearls_warm.py")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--estimate", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--i-have-read-the-estimate", dest="fingerprint", default="")
    args = parser.parse_args(argv)
    # Le processus du passage ne rallume ni le chauffeur, ni un LLM, ni Tavily.
    old = _push_env({
        "NAVIGUIDE_ICI_WARM": "0",
        "NAVIGUIDE_LLM_MODE": "off",
        "NAVIGUIDE_TAVILY_WATCH": "0",
    })
    try:
        if args.estimate:
            sys.stdout.write(format_estimate(estimate()))
            return 0
        run(fingerprint=args.fingerprint or None)
        return 0
    except Stopped as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Failed as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("échec du passage ; avancement conservé", file=sys.stderr)
        return 1
    finally:
        _pop_env(old)

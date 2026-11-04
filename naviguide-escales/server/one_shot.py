"""Passages uniques : estimation sans appel, empreinte, verrou, reprise.

Le registre contient ``fixture`` (aucun réseau), ``vl_route_bm``
(aucun réseau dans ``plan``) et ``stories_177`` (chaîne du clic, aucun
appel dans ``plan``). ``execute`` réalise un appel prévu ; c'est à lui
d'enregistrer la dépense via ``llm_budget.record`` (le socle ne le fait pas,
pour ne pas compter deux fois).

``--run`` exige l'empreinte sha256 de l'estimation. Un fichier ``.done`` dans
le dossier de données du poste (hors dépôt) interdit de relancer : il se
retire à la main. Il n'y a pas de ``--force``. Au plafond (``llm_budget.allow``),
l'avancement est écrit et les appels déjà faits ne sont pas rejoués.
Cette écriture est synchronisée sur le disque avant de passer à l'appel
suivant : un arrêt brutal ensuite ne les fait pas repayer.

Un seul passage s'exécute à la fois : ``<job>/.lock`` est pris en exclusif
non bloquant après le contrôle de l'empreinte. Le second lancement échoue
sans appel. Ce verrou d'exécution est celui du descripteur : le noyau le
libère si le processus meurt. Le fichier ``.done`` reste le verrou de réussite.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import llm_budget

ENV_DIR = "NAVIGUIDE_ONE_SHOT_DIR"
FIXTURE_JOB = "fixture"

_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class OneShotError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Refused(OneShotError):
    pass


class StoppedAtCap(OneShotError):
    def __init__(self, call_id: str, completed: list[str], reason: str = "cap"):
        super().__init__("stopped", _stop_message(call_id, reason))
        self.call_id = call_id
        self.completed = list(completed)
        self.reason = reason


def _stop_message(call_id: str, reason: str) -> str:
    if reason == "mode":
        return f"arrêté avant {call_id} : le mode interdit l'appel"
    if reason == "tokens":
        return f"arrêté au plafond de jetons avant {call_id}"
    if reason == "usd":
        return f"arrêté au plafond du jour avant {call_id}"
    return f"arrêté au plafond avant {call_id}"


def _block_reason(tier: str) -> str:
    """Pourquoi ``allow`` est faux. Même ordre que ``llm_budget.allow``."""
    if not llm_budget.llm_allowed_here(tier):
        return "mode"
    used = llm_budget.get_usage(tier)
    if int(used["tokens"]) >= llm_budget.daily_cap(tier):
        return "tokens"
    cap = llm_budget.daily_usd_cap()
    if cap is not None:
        reserve = llm_budget.estimate_usd(tier, 0, llm_budget.max_tokens_for(tier))
        if llm_budget.today_usd() + reserve > cap:
            return "usd"
    return "cap"


@dataclass(frozen=True, slots=True)
class PlannedCall:
    call_id: str
    tier: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(slots=True)
class Job:
    name: str
    plan: Callable[[], list[PlannedCall]]
    execute: Callable[[PlannedCall], Any]
    # Lignes ajoutées après l'estimation. Hors empreinte : le plan ne change pas.
    estimate_extra: Callable[[], str] | None = None


REGISTRY: dict[str, Job] = {}


def register(job: Job) -> None:
    name = _valid_name(job.name)
    if name in REGISTRY:
        raise OneShotError("duplicate-job", "job déjà enregistré")
    REGISTRY[name] = job


def _valid_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise OneShotError("unknown-job", "job inconnu")
    return name


def _require(name: str) -> Job:
    job = REGISTRY.get(_valid_name(name))
    if job is None:
        raise OneShotError("unknown-job", "job inconnu")
    return job


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _data_root(*, mkdir: bool) -> Path:
    raw = (os.environ.get(ENV_DIR) or "").strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        path = Path.home() / ".local" / "share" / "naviguide" / "one-shot"
    resolved = path.resolve()
    repo = _repo_root().resolve()
    if resolved == repo or repo in resolved.parents:
        raise OneShotError("bad-dir", "le dossier de verrou doit être hors dépôt")
    if mkdir:
        resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def data_dir() -> Path:
    return _data_root(mkdir=True)


def _job_dir(name: str, *, mkdir: bool) -> Path:
    return _data_root(mkdir=mkdir) / name


def lock_path(job_name: str) -> Path:
    return _job_dir(_valid_name(job_name), mkdir=False) / ".done"


def progress_path(job_name: str) -> Path:
    return _job_dir(_valid_name(job_name), mkdir=False) / "progress.json"


def lock_exists(job_name: str) -> bool:
    return lock_path(job_name).is_file()


def fingerprint_for(payload: dict[str, Any]) -> str:
    """sha256 du JSON canonique de l'estimation, champ ``fingerprint`` exclu."""
    body = {k: v for k, v in payload.items() if k != "fingerprint"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _caps_snapshot() -> dict[str, Any]:
    return {
        "tokens": {tier: llm_budget.daily_cap(tier) for tier in llm_budget.TIERS},
        "usd": llm_budget.daily_usd_cap(),
    }


def _plan(job: Job) -> list[PlannedCall]:
    planned = list(job.plan())
    seen: set[str] = set()
    out: list[PlannedCall] = []
    for call in planned:
        if not isinstance(call, PlannedCall):
            raise OneShotError("bad-plan", "le plan doit lister des PlannedCall")
        if not _CALL_ID.fullmatch(call.call_id):
            raise OneShotError("bad-plan", "identifiant d'appel refusé")
        if call.call_id in seen:
            raise OneShotError("bad-plan", "identifiants d'appel en double")
        seen.add(call.call_id)
        out.append(
            PlannedCall(
                call.call_id,
                llm_budget.normalize_tier(call.tier),
                max(0, int(call.prompt_tokens)),
                max(0, int(call.completion_tokens)),
            )
        )
    return out


def _estimate_from(job: Job, planned: list[PlannedCall]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    prompt = 0
    completion = 0
    usd = 0.0
    for call in planned:
        part = llm_budget.estimate_usd(call.tier, call.prompt_tokens, call.completion_tokens)
        items.append(
            {
                "id": call.call_id,
                "tier": call.tier,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "usd": part,
            }
        )
        prompt += call.prompt_tokens
        completion += call.completion_tokens
        usd = round(usd + part, 8)
    body: dict[str, Any] = {
        "job": job.name,
        "calls": len(items),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "tokens": prompt + completion,
        "usd": usd,
        "caps": _caps_snapshot(),
        "items": items,
    }
    body["fingerprint"] = fingerprint_for(body)
    return body


def build_estimate(job_name: str) -> dict[str, Any]:
    """Estimation seule. N'appelle pas ``execute`` et n'ouvre pas le dossier de verrou."""
    job = _require(job_name)
    return _estimate_from(job, _plan(job))


def format_estimate(est: dict[str, Any]) -> str:
    caps = est["caps"]
    token_caps = ",".join(f"{tier}={caps['tokens'][tier]}" for tier in llm_budget.TIERS)
    usd_cap = caps["usd"]
    usd_text = "absent" if usd_cap is None else format(float(usd_cap), ".8f")
    items = " ".join(
        f"{item['id']}:{item['tier']}:{item['prompt_tokens']}:{item['completion_tokens']}"
        for item in est["items"]
    )
    lines = [
        f"job: {est['job']}",
        f"calls: {est['calls']}",
        f"tokens: {est['tokens']}",
        f"prompt_tokens: {est['prompt_tokens']}",
        f"completion_tokens: {est['completion_tokens']}",
        f"usd: {format(float(est['usd']), '.8f')}",
        f"daily_token_caps: {token_caps}",
        f"daily_usd_cap: {usd_text}",
        f"items: {items}",
        f"fingerprint: {est['fingerprint']}",
    ]
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    """Remplace ``path`` par un fichier 0600, synchronisé avant le retour."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
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
    dir_fd = os.open(path.parent, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _load_progress(job_name: str, fingerprint: str) -> list[str]:
    path = progress_path(job_name)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OneShotError(
            "bad-progress",
            "avancement illisible ; suppression manuelle seulement",
        ) from exc
    if not isinstance(raw, dict):
        raise OneShotError(
            "bad-progress",
            "avancement illisible ; suppression manuelle seulement",
        )
    if raw.get("fingerprint") != fingerprint:
        raise OneShotError(
            "progress-mismatch",
            "l'avancement ne correspond pas à cette empreinte ; suppression manuelle seulement",
        )
    done = raw.get("completed")
    if not isinstance(done, list) or not all(isinstance(item, str) for item in done):
        raise OneShotError(
            "bad-progress",
            "avancement illisible ; suppression manuelle seulement",
        )
    return list(done)


def _save_progress(job_name: str, fingerprint: str, completed: list[str]) -> None:
    payload = {"completed": completed, "fingerprint": fingerprint, "job": job_name}
    _atomic_write(progress_path(job_name), json.dumps(payload, sort_keys=True) + "\n")


def _save_done(job_name: str, fingerprint: str, completed: list[str]) -> None:
    payload = {"completed": completed, "fingerprint": fingerprint, "job": job_name}
    _atomic_write(lock_path(job_name), json.dumps(payload, sort_keys=True) + "\n")


@contextmanager
def _hold_run_lock(job_name: str) -> Iterator[None]:
    """Exclusif non bloquant sur ``<job>/.lock``.

    Le fichier reste en place : seul le descripteur porte le verrou, donc
    la mort du processus le libère. On ne le supprime pas (un nouveau
    fichier serait un autre verrou).
    """
    directory = _job_dir(job_name, mkdir=True)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused("busy", "un passage est déjà en cours") from exc
        yield
    finally:
        os.close(fd)


def run(job_name: str, fingerprint: str) -> dict[str, Any]:
    """Exécute les appels restants si l'empreinte est celle de l'estimation."""
    token = (fingerprint or "").strip().lower()
    if not token:
        raise Refused("missing-fingerprint", "empreinte manquante")
    job = _require(job_name)
    planned = _plan(job)
    est = _estimate_from(job, planned)
    if token != est["fingerprint"]:
        raise Refused("bad-fingerprint", "empreinte différente de l'estimation")
    with _hold_run_lock(job.name):
        if lock_exists(job.name):
            raise Refused(
                "locked",
                "verrou de réussite présent ; suppression manuelle seulement",
            )
        known = [call.call_id for call in planned]
        known_set = set(known)
        completed = _load_progress(job.name, est["fingerprint"])
        if any(call_id not in known_set for call_id in completed):
            raise OneShotError(
                "bad-progress",
                "avancement hors plan ; suppression manuelle seulement",
            )
        ordered: list[str] = []
        seen: set[str] = set()
        for call_id in completed:
            if call_id not in seen:
                ordered.append(call_id)
                seen.add(call_id)
        for call in planned:
            if call.call_id in seen:
                continue
            if not llm_budget.allow(call.tier):
                _save_progress(job.name, est["fingerprint"], ordered)
                raise StoppedAtCap(call.call_id, ordered, _block_reason(call.tier))
            job.execute(call)
            ordered.append(call.call_id)
            seen.add(call.call_id)
            _save_progress(job.name, est["fingerprint"], ordered)
        _save_done(job.name, est["fingerprint"], ordered)
        progress = progress_path(job.name)
        if progress.is_file():
            progress.unlink()
        return {"job": job.name, "completed": ordered}


def format_run(result: dict[str, Any]) -> str:
    ids = ",".join(result["completed"])
    return f"job: {result['job']}\ncompleted: {ids}\nlock: ok\n"


def _fixture_plan() -> list[PlannedCall]:
    return [
        PlannedCall("step-1", "fast", 32, 8),
        PlannedCall("step-2", "fast", 32, 8),
        PlannedCall("step-3", "fast", 32, 8),
    ]


def _fixture_execute(call: PlannedCall) -> dict[str, str]:
    """Job de test : aucun réseau, aucune dépense."""
    return {"id": call.call_id, "ok": "1"}


def _install_fixture() -> None:
    register(
        Job(
            FIXTURE_JOB,
            _fixture_plan,
            _fixture_execute,
        )
    )


def _install_vl_route() -> None:
    import vl_route  # noqa: PLC0415

    vl_route.register_job()


def _install_stories() -> None:
    import stories_once  # noqa: PLC0415

    stories_once.register_job()


_install_fixture()
_install_vl_route()
_install_stories()


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="one_shot.py",
        description=(
            "Estime un passage unique sans appel, ou l'exécute sous empreinte. "
            "Pas d'option pour forcer : supprimer le fichier .done à la main pour relancer. "
            "Un second passage simultané est refusé sans appel."
        ),
    )
    parser.add_argument("--job", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--estimate", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--i-have-read-the-estimate", dest="fingerprint")
    args = parser.parse_args(argv)
    if args.estimate and args.fingerprint:
        print("l'estimation ne prend pas d'empreinte", file=sys.stderr)
        return 2
    if args.run and not (args.fingerprint or "").strip():
        print("empreinte manquante", file=sys.stderr)
        return 2
    try:
        if args.estimate:
            est = build_estimate(args.job)
            text = format_estimate(est)
            extra_fn = _require(args.job).estimate_extra
            if extra_fn is not None:
                extra = extra_fn() or ""
                if extra and not extra.endswith("\n"):
                    extra += "\n"
                text += extra
            sys.stdout.write(text)
            return 0
        result = run(args.job, args.fingerprint or "")
    except StoppedAtCap as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OneShotError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print("échec d'un appel ; avancement conservé", file=sys.stderr)
        return 1
    sys.stdout.write(format_run(result))
    return 0

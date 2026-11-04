"""Pipeline météo asynchrone partagé.

Tous les fournisseurs passent ici : tâche de rafraîchissement dédupliquée,
état durable (pending / ready / error) et cache par cellule 0,25° + cycle GFS.
Les handlers répondent tout de suite ; le client actualise à faible cadence.

Une file asyncio (NAVIGUIDE_WEATHER_PIPELINE, allumée par défaut)
borne chaque fournisseur, met en cache (fournisseur, cellule 0,25°, heure UTC)
et expose pending / ready / unavailable. Une exception ou un dépassement
devient unavailable, jamais une erreur de page. L'ancien chemin à fils des
fournisseurs météo est retiré : 0, off, false ou no ne le restaurent pas.

Le pipeline **transporte** les champs déjà convertis par les loaders
(hindcast, Copernicus getWind / getWave / getCurrent, forecast_cube, saildocs).
Il ne recalcule pas les vecteurs. Conventions (cahier § 20) :

- 1 m/s = 1,943844 kn (1 kn = 1 852 m/h)
- vent et vagues : direction **« de »** (météorologique), atan2(-u, -v)
- courant : direction **« vers »** (océanographique), atan2(uo, vo) ;
  uo = 1, vo = 0 → 90° (est)
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import multiprocessing
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from saildocs import last_ready_cycle, to_iso
from longitude import wrap_lon

log = logging.getLogger("naviguide-simulator.weather")

CELL_DEG = 0.25
CACHE_MAX = 256
WAIT_POLL_S = 0.02

Loader = Callable[[], dict]

_http_transport = None


def bind_weather_transport(transport) -> None:
    """Les tests branchent un MockTransport. Jamais le transport async d’un AsyncClient."""
    global _http_transport
    if transport is not None and type(transport).__name__ != "MockTransport":
        transport = None
    _http_transport = transport


def weather_http_transport():
    return _http_transport


def weather_cell(lat: float, lon: float) -> tuple[int, int]:
    wrapped = wrap_lon(lon)
    return (
        math.floor((float(lat) + 90.0) / CELL_DEG),
        math.floor((wrapped + 180.0) / CELL_DEG),
    )


def cell_center(i: int, j: int) -> tuple[float, float]:
    lat = (i * CELL_DEG) - 90.0 + CELL_DEG / 2.0
    lon = (j * CELL_DEG) - 180.0 + CELL_DEG / 2.0
    return lat, lon


def forecast_cycle(when=None) -> str:
    return to_iso(last_ready_cycle(when))


def cache_key(provider: str, lat: float, lon: float, when=None) -> tuple[str, int, int, str]:
    i, j = weather_cell(lat, lon)
    return (provider, i, j, forecast_cycle(when))


def _cell_public(i: int, j: int) -> dict:
    lat, lon = cell_center(i, j)
    return {"i": i, "j": j, "deg": CELL_DEG, "lat": round(lat, 5), "lon": round(lon, 5)}


def _lru_set(cache: dict, key, value) -> None:
    if key in cache:
        cache.pop(key)
    elif len(cache) >= CACHE_MAX:
        cache.pop(next(iter(cache)))
    cache[key] = value


class WeatherPipeline:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._route_lock = threading.Lock()
        self._cache: dict[tuple, dict] = {}
        self._inflight: dict[tuple, threading.Thread] = {}

    def clear(self) -> None:
        events = []
        with self._lock:
            for thread in self._inflight.values():
                done = getattr(thread, "_bridge_done", None)
                if done is not None:
                    events.append(done)
            self._cache.clear()
            self._inflight.clear()
        for done in events:
            done.set()
        bind_weather_transport(None)
        if _ASYNC_QUEUE is not None:
            _ASYNC_QUEUE.clear()

    def peek(self, provider: str, lat: float, lon: float, when=None) -> Optional[dict]:
        key = cache_key(provider, lat, lon, when)
        with self._lock:
            hit = self._cache.get(key)
            return dict(hit) if hit else None

    def provider_busy(self, provider: str) -> bool:
        with self._lock:
            return any(
                key[0] == provider and thread.is_alive()
                for key, thread in self._inflight.items()
            )

    def refreshing(self, provider: str, lat: float, lon: float, when=None) -> bool:
        key = cache_key(provider, lat, lon, when)
        with self._lock:
            thread = self._inflight.get(key)
            return bool(thread and thread.is_alive())

    def kick(
        self,
        provider: str,
        lat: float,
        lon: float,
        loader: Loader,
        *,
        when=None,
        force: bool = False,
    ) -> bool:
        """Démarre au plus un rafraîchissement pour cette clé cellule/cycle."""
        key = cache_key(provider, lat, lon, when)
        with self._lock:
            thread = self._inflight.get(key)
            if thread and thread.is_alive():
                return False
            hit = self._cache.get(key)
            if not force and hit and hit.get("status") in {"ready", "error"}:
                return False
            started = threading.Thread(
                target=self._run,
                args=(key, loader),
                name=f"naviguide-wx-{provider}-{key[1]}-{key[2]}",
                daemon=True,
            )
            self._inflight[key] = started
            pending = self._pending_record(key, refreshing=True, prev=hit)
            _lru_set(self._cache, key, pending)
            started.start()
        return True

    def snapshot(
        self,
        provider: str,
        lat: float,
        lon: float,
        loader: Loader,
        *,
        when=None,
        force: bool = False,
    ) -> dict:
        """Réponse immédiate. Lance le loader hors chemin si la cellule/cycle manque."""
        key = cache_key(provider, lat, lon, when)
        stale = self._stale_ready(provider, key[1], key[2], key[3])
        with self._lock:
            hit = self._cache.get(key)
            thread = self._inflight.get(key)
            busy = bool(thread and thread.is_alive())
            if hit and hit.get("status") in {"ready", "error"} and not force:
                return self._public(hit, lat, lon, refreshing=busy)
            if busy:
                if stale:
                    return self._public(stale, lat, lon, refreshing=True)
                return self._public(hit or self._pending_record(key, True), lat, lon, refreshing=True)
        self.kick(provider, lat, lon, loader, when=when, force=force)
        if stale and not force:
            return self._public(stale, lat, lon, refreshing=True)
        with self._lock:
            hit = self._cache.get(key)
            thread = self._inflight.get(key)
            busy = bool(thread and thread.is_alive())
        if hit and hit.get("status") in {"ready", "error"}:
            return self._public(hit, lat, lon, refreshing=False)
        return self._public(hit or self._pending_record(key, True), lat, lon, refreshing=busy or True)

    def snapshot_group(
        self,
        jobs: Iterable[tuple[str, str, Loader]],
        lat: float,
        lon: float,
        *,
        when=None,
        force: bool = False,
    ) -> dict:
        parts: dict[str, dict] = {}
        for name, provider, loader in jobs:
            parts[name] = self.snapshot(provider, lat, lon, loader, when=when, force=force)
        statuses = [part.get("status") for part in parts.values()]
        if any(status == "pending" for status in statuses) or not statuses:
            overall = "pending"
        elif any(status == "ready" for status in statuses):
            overall = "ready"
        elif any(status == "error" for status in statuses):
            overall = "error"
        else:
            overall = "absent"
        cycle = next((part.get("cycle") for part in parts.values() if part.get("cycle")), forecast_cycle(when))
        return {
            "status": overall,
            "refreshing": any(bool(part.get("refreshing")) for part in parts.values()),
            "cycle": cycle,
            "cell": _cell_public(*weather_cell(lat, lon)),
            **parts,
        }

    def _start_hold(self, key: tuple, done: threading.Event) -> threading.Thread:
        """Fil vivant tant que le chargeur asyncio n'a pas écrit le cache à fils.

        `wait_ready` / `wait_providers` s'appuient sur ce fil : les tests et le
        composite HTTP attendent la même cellule qu'avant.
        """

        def _hold() -> None:
            done.wait(120)

        thread = threading.Thread(target=_hold, name=f"naviguide-wx-bridge-{key[0]}", daemon=True)
        thread._bridge_done = done  # type: ignore[attr-defined]
        with self._lock:
            self._inflight[key] = thread
            prev = self._cache.get(key)
            _lru_set(self._cache, key, self._pending_record(key, True, prev=prev))
        thread.start()
        return thread

    def _release_hold(self, key: tuple, thread: threading.Thread, done: threading.Event) -> None:
        with self._lock:
            if self._inflight.get(key) is thread:
                self._inflight.pop(key, None)
        done.set()

    def forget_failure(self, provider: str, lat: float, lon: float, when=None) -> None:
        key = cache_key(provider, lat, lon, when)
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit.get("status") == "error":
                self._cache.pop(key, None)

    def _mirror_record(self, key: tuple, record: dict) -> None:
        with self._lock:
            _lru_set(self._cache, key, record)

    def _record_from_queue_view(self, key: tuple, view: dict, *, refreshing: bool) -> dict:
        """Même forme que le pipeline à fils : `unavailable` redevient `error`."""
        status = view.get("status") or "pending"
        if status == "unavailable":
            status = "error"
        data = {
            field: value
            for field, value in view.items()
            if field not in {"status", "provider", "cell", "hour", "refreshing"}
        }
        error = None
        if status == "error":
            error = data.get("reason") or view.get("reason")
        return {
            "status": status,
            "provider": key[0],
            "cycle": key[3],
            "cell": view.get("cell") or _cell_public(key[1], key[2]),
            "data": data or None,
            "error": error,
            "refreshing": refreshing,
        }

    def snapshot_via_async(
        self,
        provider: str,
        lat: float,
        lon: float,
        loader: Loader,
        *,
        when=None,
        force: bool = False,
    ) -> dict:
        """File asyncio, réponse au format du pipeline à fils (parité des valeurs)."""
        queue = get_async_weather_queue()
        key = cache_key(provider, lat, lon, when)
        with self._route_lock:
            cached = None if force else queue.cached_status(provider, lat, lon, when)
            if cached in {"ready", "unavailable"}:
                view = queue.layer(provider, lat, lon, when)
                record = self._record_from_queue_view(key, view, refreshing=False)
                self._mirror_record(key, record)
                return self._public(record, lat, lon, refreshing=False)
            if cached == "pending":
                with self._lock:
                    hit = self._cache.get(key)
                return self._public(hit or self._pending_record(key, True), lat, lon, refreshing=True)

            done = threading.Event()
            thread = self._start_hold(key, done)

            def wrapped():
                try:
                    data = loader() or {}
                    if not isinstance(data, dict):
                        data = {}
                    self._mirror_record(key, {
                        "status": "ready",
                        "provider": key[0],
                        "cycle": key[3],
                        "cell": _cell_public(key[1], key[2]),
                        "data": dict(data),
                        "error": None,
                        "updated_at": time.monotonic(),
                    })
                    return data
                except Exception as exc:
                    reason = getattr(exc, "reason", None) or type(exc).__name__
                    self._mirror_record(key, {
                        "status": "error",
                        "provider": key[0],
                        "cycle": key[3],
                        "cell": _cell_public(key[1], key[2]),
                        "data": None,
                        "error": reason,
                        "updated_at": time.monotonic(),
                    })
                    raise
                finally:
                    self._release_hold(key, thread, done)

            try:
                submitted = queue.submit(provider, lat, lon, wrapped, when=when, force=force)
            except Exception:
                self._release_hold(key, thread, done)
                raise
            if not submitted:
                self._release_hold(key, thread, done)

        view = queue.layer(provider, lat, lon, when)
        if view.get("status") in {"ready", "unavailable"}:
            record = self._record_from_queue_view(key, view, refreshing=False)
            self._mirror_record(key, record)
            return self._public(record, lat, lon, refreshing=False)
        with self._lock:
            hit = self._cache.get(key)
        return self._public(hit or self._pending_record(key, True), lat, lon, refreshing=True)

    def wait_ready(
        self,
        provider: str,
        lat: float,
        lon: float,
        *,
        when=None,
        timeout: float = 2.0,
    ) -> dict:
        deadline = time.monotonic() + timeout
        key = cache_key(provider, lat, lon, when)
        while time.monotonic() < deadline:
            with self._lock:
                hit = self._cache.get(key)
                thread = self._inflight.get(key)
                busy = bool(thread and thread.is_alive())
            if hit and hit.get("status") in {"ready", "error"} and not busy:
                return self._public(hit, lat, lon, refreshing=False)
            time.sleep(WAIT_POLL_S)
        with self._lock:
            hit = self._cache.get(key)
        return self._public(hit or self._pending_record(key, True), lat, lon, refreshing=True)

    def wait_providers(
        self,
        providers: Iterable[str],
        lat: float,
        lon: float,
        *,
        when=None,
        timeout: float = 3.0,
    ) -> None:
        deadline = time.monotonic() + timeout
        for provider in providers:
            remain = max(0.05, deadline - time.monotonic())
            self.wait_ready(provider, lat, lon, when=when, timeout=remain)

    def _run(self, key: tuple, loader: Loader) -> None:
        try:
            data = loader() or {}
            record = {
                "status": "ready",
                "provider": key[0],
                "cycle": key[3],
                "cell": _cell_public(key[1], key[2]),
                "data": dict(data),
                "error": None,
                "updated_at": time.monotonic(),
            }
            with self._lock:
                _lru_set(self._cache, key, record)
        except Exception as exc:
            log.warning("météo %s cellule %s,%s: %s", key[0], key[1], key[2], exc)
            record = {
                "status": "error",
                "provider": key[0],
                "cycle": key[3],
                "cell": _cell_public(key[1], key[2]),
                "data": None,
                "error": getattr(exc, "reason", None) or f"{type(exc).__name__}",
                "updated_at": time.monotonic(),
            }
            with self._lock:
                _lru_set(self._cache, key, record)
        finally:
            with self._lock:
                if self._inflight.get(key) is threading.current_thread():
                    self._inflight.pop(key, None)

    def _stale_ready(self, provider: str, i: int, j: int, cycle: str) -> Optional[dict]:
        with self._lock:
            best = None
            for key, hit in self._cache.items():
                if key[0] != provider or key[1] != i or key[2] != j:
                    continue
                if hit.get("status") != "ready":
                    continue
                if key[3] == cycle:
                    return dict(hit)
                if best is None or str(key[3]) > str(best.get("cycle") or ""):
                    best = dict(hit)
            return best

    def _pending_record(self, key: tuple, refreshing: bool, prev: Optional[dict] = None) -> dict:
        return {
            "status": "pending",
            "provider": key[0],
            "cycle": key[3],
            "cell": _cell_public(key[1], key[2]),
            "data": dict((prev or {}).get("data") or {}) or None,
            "error": None,
            "updated_at": time.monotonic(),
            "refreshing": refreshing,
        }

    def _public(self, record: dict, lat: float, lon: float, *, refreshing: bool) -> dict:
        body: dict[str, Any] = dict(record.get("data") or {})
        body["status"] = record.get("status") or "pending"
        body["refreshing"] = refreshing or bool(record.get("refreshing"))
        body["provider"] = record.get("provider")
        body["cycle"] = record.get("cycle")
        body["cell"] = record.get("cell")
        body.setdefault("latitude", lat)
        body.setdefault("longitude", lon)
        if record.get("error") and not body.get("reason"):
            body["reason"] = record["error"]
        return body


_PIPELINE = WeatherPipeline()


def get_pipeline() -> WeatherPipeline:
    return _PIPELINE


# Délai max d'un fournisseur sur la file asyncio. Même ordre que le client
# Open-Meteo du GRIB (20 s) : la page est déjà repartie, le travail s'arrête.
DEFAULT_PROVIDER_TIMEOUT_S = 20.0
# Au-delà, un « pending » ne veut plus rien dire : la couche passe unavailable.
PENDING_MAX_AGE_S = 60.0
# Le processus enfant a ce délai pour se terminer après kill().
PROCESS_KILL_GRACE_S = 2.0


_FLAG_OFF = {"0", "false", "no", "off"}


def weather_pipeline_enabled() -> bool:
    """Vrai par défaut. 0 / off / false / no ne réouvrent pas l'ancien chemin."""
    raw = os.getenv("NAVIGUIDE_WEATHER_PIPELINE")
    if raw is None or not str(raw).strip():
        return True
    return str(raw).strip().lower() not in _FLAG_OFF


def hour_stamp(when=None) -> str:
    if not isinstance(when, datetime):
        when = datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return when.strftime("%Y-%m-%dT%H")


def layer_cache_key(provider: str, lat: float, lon: float, when=None) -> tuple:
    """(fournisseur, cellule, heure). La cellule est le couple d'indices 0,25°."""
    return (str(provider), weather_cell(lat, lon), hour_stamp(when))


class ProviderError(RuntimeError):
    """Échec rapporté par un processus enfant ; `reason` est le type d'origine."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


class ProcessJob:
    """Travail exécuté dans un processus enfant, tué à l'échéance.

    `target` vaut « module:fonction » (retrouvé par son nom dans l'enfant) ;
    `args` / `kwargs` doivent être sérialisables.
    """

    def __init__(self, target: str, *args, **kwargs) -> None:
        module, _, name = str(target).partition(":")
        if not module or not name:
            raise ValueError(f"cible invalide: {target!r}")
        self.target = str(target)
        self.args = tuple(args)
        self.kwargs = dict(kwargs)

    def __repr__(self) -> str:
        return f"ProcessJob({self.target!r})"


def _process_entry(conn, target: str, args: tuple, kwargs: dict) -> None:
    try:
        module, _, name = target.partition(":")
        fn = getattr(importlib.import_module(module), name)
        data = fn(*args, **kwargs)
        conn.send(("ok", data if isinstance(data, dict) else {}))
    except BaseException as exc:  # noqa: BLE001 - tout remonte au parent
        try:
            conn.send(("error", type(exc).__name__, str(exc)[:500]))
        except Exception:
            pass
    finally:
        conn.close()


def run_process_job(job: ProcessJob, timeout: float) -> dict:
    """Lance `job` dans un enfant « spawn » ; le tue à l'échéance (TimeoutError)."""
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_process_entry,
        args=(child, job.target, job.args, job.kwargs),
        name=f"naviguide-wx-{job.target}",
        daemon=True,
    )
    proc.start()
    child.close()
    try:
        if not parent.poll(max(0.0, float(timeout))):
            raise TimeoutError(job.target)
        try:
            message = parent.recv()
        except EOFError as exc:
            raise ProviderError("ProcessDied", f"exit {proc.exitcode}") from exc
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join(PROCESS_KILL_GRACE_S)
        parent.close()
    if message[0] == "ok":
        return message[1]
    raise ProviderError(message[1], message[2])


def _accepts_cancel(fn) -> bool:
    try:
        return "cancel" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


class AsyncWeatherQueue:
    """File asyncio : un travail par clé, délai max par fournisseur, cache LRU."""

    def __init__(
        self,
        *,
        default_timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_S,
        timeouts: Optional[dict] = None,
        pending_max_age_s: float = PENDING_MAX_AGE_S,
    ) -> None:
        self._pending_max_age = float(pending_max_age_s)
        self._epoch = 0
        # Références fortes : une tâche asyncio sans référence peut disparaître.
        self._tasks: set[asyncio.Task] = set()
        self._default_timeout = float(default_timeout_s)
        self._timeouts = {str(k): float(v) for k, v in (timeouts or {}).items()}
        self._cache: dict[tuple, dict] = {}
        self._inflight: set[tuple] = set()
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[asyncio.Queue] = None
        self._ready = threading.Event()
        self._closed = False

    def timeout_for(self, provider: str) -> float:
        return self._timeouts.get(str(provider), self._default_timeout)

    def clear(self) -> None:
        """Oublie le cache. Un travail déjà lancé n'écrit plus après cet appel."""
        with self._lock:
            self._epoch += 1
            self._cache.clear()
            self._inflight.clear()

    def _stale_pending(self, hit: Optional[dict]) -> bool:
        if not hit or hit.get("status") != "pending":
            return False
        since = hit.get("since")
        return since is not None and time.monotonic() - float(since) > self._pending_max_age

    def forget_failure(self, provider: str, lat: float, lon: float, when=None) -> bool:
        """Oublie un échec (unavailable) déjà terminé. Un succès ou un travail en cours reste."""
        key = layer_cache_key(provider, lat, lon, when)
        with self._lock:
            if key in self._inflight:
                return False
            hit = self._cache.get(key)
            if hit and hit.get("status") == "unavailable":
                self._cache.pop(key, None)
                return True
        return False

    def cached_status(self, provider: str, lat: float, lon: float, when=None) -> Optional[str]:
        """ready / unavailable d'abord ; un pending trop vieux devient unavailable."""
        key = layer_cache_key(provider, lat, lon, when)
        with self._lock:
            hit = self._cache.get(key)
            inflight = key in self._inflight
        if hit and hit.get("status") in {"ready", "unavailable"}:
            return hit.get("status")
        if self._stale_pending(hit):
            return "unavailable"
        if inflight or (hit and hit.get("status") == "pending"):
            return "pending"
        return None

    def provider_busy(self, provider: str) -> bool:
        with self._lock:
            return any(
                key[0] == provider and not self._stale_pending(self._cache.get(key))
                for key in self._inflight
            )

    def layer(self, provider: str, lat: float, lon: float, when=None) -> dict:
        key = layer_cache_key(provider, lat, lon, when)
        with self._lock:
            hit = self._cache.get(key)
            inflight = key in self._inflight
        if hit and hit.get("status") in {"ready", "unavailable"}:
            return self._public(hit)
        if self._stale_pending(hit):
            return self._public({**hit, "status": "unavailable", "reason": "stale_pending"})
        if inflight or (hit and hit.get("status") == "pending"):
            return self._public(hit or self._pending_record(key))
        return self._public(self._absent_record(key))

    def submit(
        self,
        provider: str,
        lat: float,
        lon: float,
        loader: Loader,
        *,
        when=None,
        force: bool = False,
    ) -> bool:
        """Enfile au plus un travail. Retour immédiat. Ne lève pas."""
        key = None
        epoch = None
        try:
            key = layer_cache_key(provider, lat, lon, when)
            with self._lock:
                if self._closed:
                    return False
                if key in self._inflight:
                    return False
                hit = self._cache.get(key)
                if not force and hit and hit.get("status") in {"ready", "unavailable"}:
                    return False
                self._inflight.add(key)
                _lru_set(self._cache, key, self._pending_record(key))
                epoch = self._epoch
            self._ensure()
            job = {"key": key, "loader": loader, "timeout": self.timeout_for(provider), "epoch": epoch}
            asyncio.run_coroutine_threadsafe(self._queue.put(job), self._loop).result(timeout=2.0)
            return True
        except Exception as exc:
            log.warning("file météo %s: %s", provider, exc)
            if key is not None:
                self._store(key, "unavailable", None, type(exc).__name__, epoch)
            return False

    def snapshot(
        self,
        provider: str,
        lat: float,
        lon: float,
        loader: Loader,
        *,
        when=None,
        force: bool = False,
    ) -> dict:
        self.submit(provider, lat, lon, loader, when=when, force=force)
        return self.layer(provider, lat, lon, when=when)

    def wait_layer(
        self,
        provider: str,
        lat: float,
        lon: float,
        *,
        when=None,
        timeout: float = 2.0,
    ) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            view = self.layer(provider, lat, lon, when=when)
            if view.get("status") in {"ready", "unavailable"}:
                return view
            time.sleep(0.01)
        return self.layer(provider, lat, lon, when=when)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        loop = self._loop
        if loop is not None and loop.is_running() and self._queue is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._queue.put(None), loop).result(timeout=1.0)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _ensure(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                wait = not self._ready.is_set()
            else:
                self._ready.clear()
                self._thread = threading.Thread(
                    target=self._run_loop,
                    name="naviguide-wx-async",
                    daemon=True,
                )
                self._thread.start()
                wait = True
        if wait and not self._ready.wait(2.0):
            raise RuntimeError("async weather queue did not start")

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        async def _main() -> None:
            self._queue = asyncio.Queue()
            self._ready.set()
            await self._worker(self._queue)

        loop.create_task(_main())
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _worker(self, queue: asyncio.Queue) -> None:
        while True:
            job = await queue.get()
            if job is None:
                return
            task = asyncio.create_task(self._run_job(job))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_job(self, job: dict) -> None:
        key = job["key"]
        loader = job["loader"]
        timeout = float(job["timeout"])
        epoch = job.get("epoch")
        cancel = threading.Event()
        try:
            if isinstance(loader, ProcessJob):
                # L'enfant est tué à l'échéance : rien ne continue en fond.
                data = await asyncio.to_thread(run_process_job, loader, timeout)
            else:
                call = (lambda: loader(cancel=cancel)) if _accepts_cancel(loader) else loader
                data = await asyncio.wait_for(asyncio.to_thread(call), timeout=timeout)
            if not isinstance(data, dict):
                data = {}
            self._store(key, "ready", data, None, epoch)
        except TimeoutError:
            # Arrêt coopératif pour un chargeur en fil qui lit `cancel`.
            cancel.set()
            self._store(key, "unavailable", None, "timeout", epoch)
        except Exception as exc:
            log.warning("météo async %s: %s", key[0], exc)
            self._store(key, "unavailable", None, getattr(exc, "reason", None) or type(exc).__name__, epoch)
        finally:
            with self._lock:
                if epoch is None or epoch == self._epoch:
                    self._inflight.discard(key)

    def _store(self, key: tuple, status: str, data, reason, epoch=None) -> None:
        record = {
            "status": status,
            "provider": key[0],
            "cell": _cell_public(key[1][0], key[1][1]),
            "hour": key[2],
            "data": dict(data or {}) or None,
            "reason": reason,
        }
        with self._lock:
            if epoch is not None and epoch != self._epoch:
                return
            _lru_set(self._cache, key, record)
            if status in {"ready", "unavailable"}:
                self._inflight.discard(key)

    def _pending_record(self, key: tuple) -> dict:
        return {
            "status": "pending",
            "since": time.monotonic(),
            "provider": key[0],
            "cell": _cell_public(key[1][0], key[1][1]),
            "hour": key[2],
            "data": None,
            "reason": None,
        }

    def _absent_record(self, key: tuple) -> dict:
        return {
            "status": "unavailable",
            "provider": key[0],
            "cell": _cell_public(key[1][0], key[1][1]),
            "hour": key[2],
            "data": None,
            "reason": None,
        }

    def _public(self, record: dict) -> dict:
        body: dict[str, Any] = dict(record.get("data") or {})
        body["status"] = record.get("status") or "pending"
        body["provider"] = record.get("provider")
        body["cell"] = record.get("cell")
        body["hour"] = record.get("hour")
        if record.get("reason") and not body.get("reason"):
            body["reason"] = record["reason"]
        return body


_ASYNC_QUEUE: Optional[AsyncWeatherQueue] = None
_ASYNC_GUARD = threading.Lock()


def get_async_weather_queue() -> AsyncWeatherQueue:
    global _ASYNC_QUEUE
    with _ASYNC_GUARD:
        if _ASYNC_QUEUE is None or _ASYNC_QUEUE._closed:
            _ASYNC_QUEUE = AsyncWeatherQueue()
        return _ASYNC_QUEUE


def _assemble_group(parts: dict, lat: float, lon: float, when=None) -> dict:
    statuses = [part.get("status") for part in parts.values()]
    if any(status == "pending" for status in statuses) or not statuses:
        overall = "pending"
    elif any(status == "ready" for status in statuses):
        overall = "ready"
    elif any(status == "error" for status in statuses):
        overall = "error"
    else:
        overall = "absent"
    cycle = next((part.get("cycle") for part in parts.values() if part.get("cycle")), forecast_cycle(when))
    return {
        "status": overall,
        "refreshing": any(bool(part.get("refreshing")) for part in parts.values()),
        "cycle": cycle,
        "cell": _cell_public(*weather_cell(lat, lon)),
        **parts,
    }


def route_snapshot(
    provider: str,
    lat: float,
    lon: float,
    loader: Loader,
    *,
    when=None,
    force: bool = False,
) -> dict:
    """Seul chemin : la file asyncio. Le pipeline à fils ne sert plus ces fournisseurs."""
    return get_pipeline().snapshot_via_async(provider, lat, lon, loader, when=when, force=force)


def forget_failed_layer(provider: str, lat: float, lon: float, *, when=None) -> None:
    """Pour un amont qui gère lui-même sa panne (Blue Intelligence : pause de l'atlas),
    l'échec ne doit pas rester en cache jusqu'à l'heure suivante."""
    if get_async_weather_queue().forget_failure(provider, lat, lon, when):
        get_pipeline().forget_failure(provider, lat, lon, when)


def route_snapshot_group(
    jobs: Iterable[tuple[str, str, Loader]],
    lat: float,
    lon: float,
    *,
    when=None,
    force: bool = False,
) -> dict:
    parts = {
        name: route_snapshot(provider, lat, lon, loader, when=when, force=force)
        for name, provider, loader in jobs
    }
    return _assemble_group(parts, lat, lon, when)

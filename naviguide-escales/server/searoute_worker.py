"""Searoute in a child process, with a hard deadline.

A thread cannot be stopped once searoute is running, so a timed-out call kept
computing in the background. Here each call runs in a worker process; when the
deadline passes, that process is killed, so no work outlives the request.
Idle workers are kept (searoute loads its graph once per process).
"""
from __future__ import annotations

import atexit
import importlib
import multiprocessing
import threading
import time

TIMED_OUT = object()


class WorkerDied(RuntimeError):
    """The worker process went away mid-call (not an answer from searoute)."""

_MAX_IDLE = 2
# At most this many searoute processes run at once; a call waits its turn
# within its own deadline, then gives up (TIMED_OUT) without starting one.
MAX_BUSY = 4
_CTX = multiprocessing.get_context("spawn")


def _resolve(target: str):
    module, _, name = target.partition(":")
    return getattr(importlib.import_module(module), name)


def _serve(conn) -> None:
    """Child loop: receive (target, args), send back ("ok", value) or ("error", text)."""
    funcs: dict = {}
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        target, args = msg
        try:
            fn = funcs.get(target)
            if fn is None:
                fn = funcs[target] = _resolve(target)
            conn.send(("ok", fn(*args)))
        except Exception as exc:  # noqa: BLE001 — reported to the caller
            conn.send(("error", f"{type(exc).__name__}: {exc}"))


class _Worker:
    def __init__(self) -> None:
        self.conn, child = _CTX.Pipe()
        self.proc = _CTX.Process(target=_serve, args=(child,), daemon=True)
        self.proc.start()
        child.close()

    def kill(self) -> None:
        try:
            self.proc.kill()
        finally:
            self.proc.join(timeout=2)
            self.conn.close()

    def close(self) -> None:
        try:
            self.conn.send(None)
        except (OSError, ValueError):
            pass
        self.proc.join(timeout=2)
        if self.proc.is_alive():
            self.proc.kill()
            self.proc.join(timeout=2)
        self.conn.close()


class ProcessRunner:
    """Runs `module:function` calls in worker processes, killed on timeout."""

    def __init__(self, max_idle: int = _MAX_IDLE, max_busy: int = MAX_BUSY) -> None:
        self._idle: list[_Worker] = []
        self._slots = threading.BoundedSemaphore(max(1, int(max_busy)))
        self.max_busy = max(1, int(max_busy))
        self._lock = threading.Lock()
        self._max_idle = max_idle

    def _take(self) -> _Worker:
        with self._lock:
            while self._idle:
                worker = self._idle.pop()
                if worker.proc.is_alive():
                    return worker
                worker.conn.close()
        return _Worker()

    def _give(self, worker: _Worker) -> None:
        with self._lock:
            if len(self._idle) < self._max_idle:
                self._idle.append(worker)
                return
        worker.close()

    def run(self, target: str, args: tuple, timeout_s: float):
        """Value of target(*args); TIMED_OUT after timeout_s; raises RuntimeError on a child error."""
        started = time.monotonic()
        if not self._slots.acquire(timeout=max(0.0, float(timeout_s))):
            return TIMED_OUT
        try:
            left = float(timeout_s) - (time.monotonic() - started)
            if left <= 0:
                return TIMED_OUT
            return self._run(target, args, left)
        finally:
            self._slots.release()

    def _run(self, target: str, args: tuple, timeout_s: float):
        worker = self._take()
        try:
            worker.conn.send((target, args))
            if not worker.conn.poll(float(timeout_s)):
                worker.kill()
                return TIMED_OUT
            status, value = worker.conn.recv()
        except (EOFError, OSError, BrokenPipeError) as exc:
            worker.kill()
            raise WorkerDied(f"searoute worker died: {exc}") from exc
        except BaseException:
            # Interrupted (cancel, KeyboardInterrupt, SystemExit) while the
            # child computes: kill it, it must not outlive the call.
            worker.kill()
            raise
        self._give(worker)
        if status != "ok":
            raise RuntimeError(value)
        return value

    def shutdown(self) -> None:
        with self._lock:
            idle, self._idle = self._idle, []
        for worker in idle:
            worker.close()


RUNNER = ProcessRunner()
atexit.register(RUNNER.shutdown)

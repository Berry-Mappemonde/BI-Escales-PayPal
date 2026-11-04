"""Double of a weather job, run in the real child process by the tests.

It writes a « started » file, then waits for a « release » file (or 10 s), so
a test can hold the job in flight across process boundaries.
"""
import os
import time


def slow_refresh(started_path: str, release_path: str, *_args, **_kwargs) -> dict:
    with open(started_path, "a", encoding="utf-8") as fh:
        fh.write(f"{os.getpid()}\n")
    deadline = time.monotonic() + 10.0
    while not os.path.exists(release_path) and time.monotonic() < deadline:
        time.sleep(0.02)
    return {"child": os.getpid()}

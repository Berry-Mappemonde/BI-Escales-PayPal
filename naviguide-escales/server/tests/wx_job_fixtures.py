"""Travaux de test pour le processus enfant de la file météo (contexte spawn)."""
import os
import time


def sleep_then_touch(path: str, seconds: float) -> dict:
    time.sleep(seconds)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("still running")
    return {"late": True}


def answer(value: int) -> dict:
    return {"windKnots": value, "pid": os.getpid()}


def fail() -> dict:
    raise ValueError("provider down")

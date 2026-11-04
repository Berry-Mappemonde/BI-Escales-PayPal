"""Payment mode selection (AUTHORIZE vs VAULT)."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import AUTH_MAX_DAYS
from app.escales.payment_mode import days_until_arrival, select_payment_mode


def test_days_until_arrival():
    now = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.timezone.utc)
    assert days_until_arrival("2026-11-10T08:00:00+00:00", now=now) == 5
    assert days_until_arrival("2026-11-04T08:00:00+00:00", now=now) == 0
    assert days_until_arrival(None, now=now) is None


def test_select_authorize_when_vault_disabled(monkeypatch):
    monkeypatch.delenv("ESCALES_VAULT_ENABLED", raising=False)
    far = "2027-05-15T08:00:00+00:00"
    assert select_payment_mode(far) == "AUTHORIZE"


def test_select_vault_when_horizon_at_least_29_days(monkeypatch):
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    now = dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc)
    horizon = (now + dt.timedelta(days=AUTH_MAX_DAYS)).isoformat()
    assert select_payment_mode(horizon, now=now) == "VAULT"
    near = (now + dt.timedelta(days=AUTH_MAX_DAYS - 1)).isoformat()
    assert select_payment_mode(near, now=now) == "AUTHORIZE"

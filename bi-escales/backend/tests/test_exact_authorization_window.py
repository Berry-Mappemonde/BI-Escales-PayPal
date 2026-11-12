"""PAY-05: real instants, not rounded calendar dates, control authorization."""
import asyncio
import datetime as dt
import pytest
from app.escales import departure_clock as clock
from app.escales.payment_mode import resolve_pledge_mode


@pytest.mark.parametrize("capture_on", ["arrival", "departure"])
@pytest.mark.parametrize("seconds,too_early", [(695*3600-1, False), (695*3600, False),
    (695*3600+1, True), (696*3600, True), (719*3600, True)])
def test_exact_utc_window(monkeypatch, capture_on, seconds, too_early):
    now = dt.datetime(2026, 11, 12, 12, tzinfo=dt.timezone.utc)
    anchor = now + dt.timedelta(seconds=seconds)
    # The same instant expressed in another offset must give the same result.
    text = anchor.astimezone(dt.timezone(dt.timedelta(hours=2))).isoformat()
    async def timing(*args, **kwargs):
        return {"meta": {"capture_on": capture_on, f"{capture_on}_iso": text}}
    monkeypatch.setattr(clock, "timing_milestone", timing)
    monkeypatch.setattr(clock, "simulated_now", lambda: now)
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    async def run():
        if too_early:
            with pytest.raises(ValueError, match="29 days"):
                await clock.refuse_early_authorization({}, now=now)
        else:
            await clock.refuse_early_authorization({}, now=now)
        assert await resolve_pledge_mode({}) == ("VAULT" if too_early else "AUTHORIZE")
        monkeypatch.setenv("ESCALES_VAULT_ENABLED", "0")
        if too_early:
            with pytest.raises(ValueError, match="29 days"):
                await resolve_pledge_mode({})
    asyncio.run(run())


@pytest.mark.parametrize("capture_on", ["arrival", "departure"])
@pytest.mark.parametrize("naive", [False, True])
@pytest.mark.parametrize("seconds", [-1, 0, 1])
def test_capture_utc_naive_and_offset_clocks(monkeypatch, capture_on, naive, seconds):
    anchor = dt.datetime(2026, 11, 12, 12, tzinfo=dt.timezone.utc)
    now = anchor + dt.timedelta(seconds=seconds)
    now = now.replace(tzinfo=None) if naive else now.astimezone(dt.timezone(dt.timedelta(hours=-3)))
    async def timing(*args, **kwargs):
        return {"meta": {"capture_on": capture_on, f"{capture_on}_iso": anchor.isoformat()}}
    monkeypatch.setattr(clock, "timing_milestone", timing)
    monkeypatch.setattr(clock, "simulated_now", lambda: now)
    async def run():
        if seconds < 0:
            with pytest.raises(ValueError, match="stop arrival" if capture_on == "arrival" else "leg departure"):
                await clock.refuse_early_capture({})
        else:
            await clock.refuse_early_capture({})
    asyncio.run(run())


@pytest.mark.parametrize("capture_on", ["arrival", "departure"])
@pytest.mark.parametrize("seconds", [695*3600, 695*3600+1])
def test_naive_authorization_clock_is_utc(monkeypatch, capture_on, seconds):
    now = dt.datetime(2026, 11, 12, 12)
    anchor = now + dt.timedelta(seconds=seconds)
    async def timing(*args, **kwargs):
        return {"meta": {"capture_on": capture_on, f"{capture_on}_iso": anchor.isoformat()}}
    monkeypatch.setattr(clock, "timing_milestone", timing)
    monkeypatch.setattr(clock, "simulated_now", lambda: now)
    async def run():
        if seconds > 695*3600:
            with pytest.raises(ValueError, match="one-hour safety margin before " + ("stop arrival" if capture_on == "arrival" else "leg departure")):
                await clock.refuse_early_authorization({})
        else:
            await clock.refuse_early_authorization({})
    asyncio.run(run())

"""PAY-05: real instants, not rounded calendar dates, control authorization."""
import asyncio
import datetime as dt
import pytest
from app.escales import departure_clock as clock
from app.escales.payment_mode import resolve_pledge_mode


@pytest.mark.parametrize("capture_on", ["arrival", "departure"])
@pytest.mark.parametrize("seconds,too_early", [(696*3600-1, False), (696*3600, False),
    (696*3600+1, True), (719*3600, True)])
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

"""Demo routes: sandbox only.

Two families live here.

* **Judge moment, stop-wide** (``/stops/…``): simulate arrival, cancel and reset for the
  demo stop. They act on every pledge of the stop, so they stay behind the treasurer
  key (``x-admin-key``), like every other money route (HamidZ11 review on #149).
* **Own pledges** (``/pledges/…``, issue #145): a visitor without the key plays the
  treasurer on pledges made from their own browser, and only those. Ownership is
  proved with the pledge's ``client_key`` on every call; see ``app.escales.demo_play``.

The demo flag and sandbox checks apply to both.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.responses import Response

from app.escales import demo_play

from app.escales.config import demo_treasurer_enabled, demo_treasurer_env_forbidden, escales_enabled
from app.escales.demo_stop import (
    DEMO_STOP_MILESTONE_ID,
    demo_cancel_stop,
    demo_reset_stop,
    demo_simulate_arrival,
)
from app.escales.rate_limit import RateLimited, client_ip, hit_demo
from app.escales.paypal_client import PayPalError
from app.escales.pledges import (
    IllegalTransition,
    PledgeAlreadyFullyRefunded,
    PledgeNotFound,
    RefundRequestKeyRequired,
)
from app.routers.escales import _as_http, _money_http, _paypal, _public_pledge, _require_treasurer


class _EnabledRoute(APIRoute):
    def get_route_handler(self):
        inner = super().get_route_handler()

        async def guard(request: Request) -> Response:
            if not escales_enabled():
                raise HTTPException(status_code=404, detail="Not Found")
            return await inner(request)

        return guard


router = APIRouter(prefix="/api/escales/demo", route_class=_EnabledRoute, tags=["escales-demo"])


def _demo_forbidden_http() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail="Demo treasurer requires PAYPAL_ENV=sandbox and ESCALES_ENV other than production",
    )


def _require_demo_judge(request: Request) -> None:
    if demo_treasurer_env_forbidden():
        raise _demo_forbidden_http()
    if not demo_treasurer_enabled():
        raise HTTPException(status_code=403, detail="Demo treasurer is not enabled")
    # Money moves (capture / void) and a stop-wide flag: treasurer key only.
    _require_treasurer(request)


def _require_demo_stop(milestone_id: str) -> str:
    token = (milestone_id or "").strip()
    if token != DEMO_STOP_MILESTONE_ID:
        raise HTTPException(status_code=404, detail="Demo stop not available")
    return token


def _enforce_demo_rate(request: Request) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    host = request.client.host if request.client else ""
    ip = client_ip(forwarded, host)
    try:
        hit_demo(ip)
    except RateLimited as exc:
        retry = str(exc.retry_after)
        raise HTTPException(
            status_code=429,
            detail="Too many demo requests",
            headers={"Retry-After": retry},
        ) from exc


@router.post("/stops/{milestone_id}/simulate-arrival")
async def post_simulate_arrival(milestone_id: str, request: Request):
    _require_demo_judge(request)
    _enforce_demo_rate(request)
    mid = _require_demo_stop(milestone_id)
    try:
        return await demo_simulate_arrival(mid, _paypal())
    except ValueError as exc:
        raise _as_http(exc) from exc


@router.post("/stops/{milestone_id}/cancel")
async def post_cancel_stop(milestone_id: str, request: Request):
    _require_demo_judge(request)
    _enforce_demo_rate(request)
    mid = _require_demo_stop(milestone_id)
    return await demo_cancel_stop(mid, _paypal())


@router.post("/stops/{milestone_id}/reset")
async def post_reset_stop(milestone_id: str, request: Request):
    _require_demo_judge(request)
    _enforce_demo_rate(request)
    mid = _require_demo_stop(milestone_id)
    return await demo_reset_stop(mid)


# --- Own pledges: a visitor plays the treasurer on what their own browser pledged (#145) ---

# How many pledges one browser may ask about in a single call.
OWN_PLEDGES_MAX = 50


class OwnPledgeIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    key: str = Field(..., min_length=1, max_length=108)


class OwnPledgesIn(BaseModel):
    pledges: list[OwnPledgeIn] = Field(default_factory=list)


def _require_demo_player(request: Request) -> None:
    """Demo treasurer mode on, sandbox, not production. No treasurer key is asked for or used."""
    if demo_treasurer_env_forbidden():
        raise _demo_forbidden_http()
    if not demo_treasurer_enabled():
        raise HTTPException(status_code=403, detail="Demo treasurer is not enabled")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    host = request.client.host if request.client else ""
    return client_ip(forwarded, host)


def _limit(bucket: str) -> None:
    try:
        hit_demo(bucket)
    except RateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many demo requests",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


def _pledge_key(request: Request) -> str:
    return (request.headers.get(demo_play.PLEDGE_KEY_HEADER) or "").strip()


async def _own(pledge_id: str, request: Request) -> dict:
    """Guard of every own-pledge action: mode, rate limit (browser and IP), then ownership."""
    _require_demo_player(request)
    key = _pledge_key(request)
    # Limited before the ownership check, so guessing keys is throttled too.
    _limit(f"play-ip:{_client_ip(request)}")
    if key:
        _limit(f"play-key:{demo_play.key_fingerprint(key)}")
    try:
        return await demo_play.owned_pledge(pledge_id, key)
    except demo_play.DemoPlayRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _played(doc: dict) -> dict:
    """The redacted pledge row of the demo queue, plus where this pledge stands in the loop."""
    from app.routers.escales import _demo_pledge_row

    return {"pledge": _demo_pledge_row(_public_pledge(doc)), "play": demo_play.play_view(doc)}


@router.post("/pledges/own")
async def post_own_pledges(body: OwnPledgesIn, request: Request):
    """Which of these pledges this browser may play with, and what it may do next on each.

    The browser sends the ids and keys it remembers. A pair that does not prove
    ownership is left out, without saying why. Read-only.
    """
    _require_demo_player(request)
    _limit(f"own-ip:{_client_ip(request)}")
    if len(body.pledges) > OWN_PLEDGES_MAX:
        raise HTTPException(status_code=422, detail=f"at most {OWN_PLEDGES_MAX} pledges per call")
    own: list[dict] = []
    for item in body.pledges:
        try:
            doc = await demo_play.owned_pledge(item.id, item.key)
        except demo_play.DemoPlayRefused:
            continue
        own.append(demo_play.play_view(doc))
    return {"own": own}


@router.post("/pledges/{pledge_id}/simulate-arrival")
async def post_own_simulate_arrival(pledge_id: str, request: Request):
    """The boat arrives, for this pledge only. The shared clock and other pledges do not move."""
    pledge = await _own(pledge_id, request)
    try:
        return _played(await demo_play.simulate_arrival(pledge))
    except demo_play.DemoPlayOutOfOrder as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/pledges/{pledge_id}/approve")
async def post_own_approve(pledge_id: str, request: Request):
    """The visitor approves the capture of this pledge. Nothing is approved for the stop."""
    pledge = await _own(pledge_id, request)
    try:
        return _played(await demo_play.approve(pledge))
    except demo_play.DemoPlayOutOfOrder as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/pledges/{pledge_id}/capture")
async def post_own_capture(pledge_id: str, request: Request):
    """Capture in the PayPal sandbox, through the treasurer's own capture code path."""
    pledge = await _own(pledge_id, request)
    try:
        return _played(await demo_play.capture(pledge, _paypal()))
    except demo_play.DemoPlayOutOfOrder as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _money_http(exc) from exc


@router.post("/pledges/{pledge_id}/void")
async def post_own_void(pledge_id: str, request: Request):
    """Release the hold in the PayPal sandbox, through the treasurer's own void code path."""
    pledge = await _own(pledge_id, request)
    try:
        return _played(await demo_play.void(pledge, _paypal()))
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _money_http(exc) from exc


@router.post("/pledges/{pledge_id}/refund")
async def post_own_refund(pledge_id: str, request: Request):
    """Refund a captured pledge in the PayPal sandbox, through the treasurer's own refund code path."""
    pledge = await _own(pledge_id, request)
    try:
        return _played(await demo_play.refund(pledge, _paypal()))
    except PledgeAlreadyFullyRefunded as exc:
        raise HTTPException(status_code=409, detail="pledge already fully refunded") from exc
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError, RefundRequestKeyRequired) as exc:
        raise _money_http(exc) from exc


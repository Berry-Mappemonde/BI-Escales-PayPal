"""Judge-moment demo routes: sandbox treasurer only, no admin key."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from starlette.responses import Response

from app.escales.config import demo_treasurer_enabled, demo_treasurer_env_forbidden, escales_enabled
from app.escales.demo_stop import (
    DEMO_STOP_MILESTONE_ID,
    demo_cancel_stop,
    demo_reset_stop,
    demo_simulate_arrival,
)
from app.escales.rate_limit import RateLimited, client_ip, hit_demo
from app.routers.escales import _as_http, _paypal


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

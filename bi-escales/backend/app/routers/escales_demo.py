"""Judge-moment demo routes: sandbox treasurer only, no admin key."""
from __future__ import annotations

from typing import Annotated

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
from app.openapi_metadata import path_param, route_docs
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

_DEMO_STOP = DEMO_STOP_MILESTONE_ID


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


def _stop_param(title: str):
    return path_param(
        "Sandbox demo stop id. Only dep-la-rochelle is accepted.",
        _DEMO_STOP,
        title,
    )


@router.post(
    "/stops/{milestone_id}/simulate-arrival",
    operation_id="demo_simulate_arrival",
    **route_docs(
        "Simulate arrival at the demo stop",
        "Sandbox clock settlement for the demo stop.",
        {
            "milestone_id": _DEMO_STOP,
            "now": "2026-11-12T12:00:00Z",
            "captain_review_approved_at": "2026-11-12T12:00:00Z",
            "actions": [],
        },
        schema_description="Demo arrival result. Settlement uses the sandbox PayPal client.",
        validation_loc=["path", "milestone_id"],
    ),
)
async def post_simulate_arrival(
    milestone_id: Annotated[str, _stop_param("Demo simulate-arrival milestone id")],
    request: Request,
):
    """Sandbox only: approve the Captain review and run the departure clock for the demo stop."""
    _require_demo_judge(request)
    _enforce_demo_rate(request)
    mid = _require_demo_stop(milestone_id)
    try:
        return await demo_simulate_arrival(mid, _paypal())
    except ValueError as exc:
        raise _as_http(exc) from exc


@router.post(
    "/stops/{milestone_id}/cancel",
    operation_id="demo_cancel_stop",
    **route_docs(
        "Cancel the sandbox demo stop",
        "Demo stop marked cancelled. Authorized pledges are voided in sandbox.",
        {"milestone_id": _DEMO_STOP, "demo_cancelled": True, "actions": []},
        schema_description="Cancel result for the demo stop.",
        validation_loc=["path", "milestone_id"],
    ),
)
async def post_cancel_stop(
    milestone_id: Annotated[str, _stop_param("Demo cancel-stop milestone id")],
    request: Request,
):
    """Sandbox only: mark the demo stop cancelled and void its authorized pledges."""
    _require_demo_judge(request)
    _enforce_demo_rate(request)
    mid = _require_demo_stop(milestone_id)
    return await demo_cancel_stop(mid, _paypal())


@router.post(
    "/stops/{milestone_id}/reset",
    operation_id="demo_reset_stop",
    **route_docs(
        "Reset the sandbox demo stop",
        "Demo cancelled flag cleared. No PayPal call.",
        {"milestone_id": _DEMO_STOP, "demo_cancelled": False, "actions": []},
        schema_description="Reset result for the demo stop.",
        validation_loc=["path", "milestone_id"],
    ),
)
async def post_reset_stop(
    milestone_id: Annotated[str, _stop_param("Demo reset-stop milestone id")],
    request: Request,
):
    """Sandbox only: clear the demo cancelled flag. Does not move funds."""
    _require_demo_judge(request)
    _enforce_demo_rate(request)
    mid = _require_demo_stop(milestone_id)
    return await demo_reset_stop(mid)

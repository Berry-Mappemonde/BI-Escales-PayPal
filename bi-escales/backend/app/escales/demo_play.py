"""Demo treasurer: a visitor plays the treasurer on the pledges made from their own browser.

Sandbox only, and only while demo treasurer mode is on (issue #145). The visitor takes
one of their own pledges through the treasurer loop: simulate the boat's arrival for
that pledge, approve, then capture or void, and refund a captured one.

Two rules hold everything together:

* **Ownership.** A pledge id is never enough. The browser must present the pledge's
  ``client_key`` (the ``PayPal-Request-Id`` it chose when it created the pledge, which no
  response ever returns), and the pledge must have been created under demo mode
  (``demo_playable``). Everything else is refused.
* **Scope.** The simulated arrival and the approval are written on that one pledge.
  The shared voyage clock, the stop's milestone, the Captain's stored review and every
  other pledge are untouched.

Capture, void and refund run through the same service functions as the treasurer's
keyed routes; nothing about how PayPal is called is defined here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from typing import Any, Optional

from .departure_clock import _parse_moment, timing_milestone
from .ledger import now_iso
from .pledges import capture_pledge, get_ledger, refund_pledge, void_pledge

PLEDGE_KEY_HEADER = "x-pledge-key"
PLAYABLE_FIELD = "demo_playable"
STATE_FIELD = "demo_play"

# Statuses in which money is held and the treasurer loop can still be played.
_HELD = frozenset({"authorized", "capture_failed", "vaulted", "charge_failed"})
# Statuses a void still applies to (the keyed void accepts the same ones).
_VOIDABLE = frozenset({"authorized", "vaulted"})
_REFUNDABLE = frozenset({"captured", "partially_refunded"})


class DemoPlayRefused(Exception):
    """Not this browser's pledge, or not a pledge the demo may act on. HTTP 403."""


class DemoPlayOutOfOrder(Exception):
    """A step asked for before the one it depends on. HTTP 409."""


def key_fingerprint(key: str) -> str:
    """A short, non-reversible name for a pledge key (rate-limit buckets, never logged raw)."""
    return hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()[:24]


async def mark_playable(pledge: dict) -> dict:
    """Mark a freshly created pledge as one its own browser may play with. Idempotent."""
    if pledge.get(PLAYABLE_FIELD) is True or not str(pledge.get("client_key") or "").strip():
        return pledge
    fresh = await get_ledger().get_pledge(str(pledge.get("_id") or ""))
    if not fresh or fresh.get(PLAYABLE_FIELD) is True:
        return fresh or pledge
    fresh[PLAYABLE_FIELD] = True
    return await get_ledger().save_pledge(fresh)


def _owns(pledge: Optional[dict], key: str) -> bool:
    if not pledge or pledge.get(PLAYABLE_FIELD) is not True:
        return False
    stored = str(pledge.get("client_key") or "")
    presented = str(key or "")
    if not stored or not presented:
        return False
    return secrets.compare_digest(stored.encode("utf-8"), presented.encode("utf-8"))


async def owned_pledge(pledge_id: str, key: str) -> dict:
    """The pledge, if this key proves the browser made it. One refusal for every other case.

    An unknown id, a wrong key, a missing key and a pledge that is not playable all
    raise the same error, so the answer never says whether a pledge id exists.
    """
    pledge = await get_ledger().get_pledge(str(pledge_id or "").strip())
    if not _owns(pledge, key):
        raise DemoPlayRefused("this pledge was not made from this browser")
    return pledge


def _state(pledge: dict) -> dict:
    raw = pledge.get(STATE_FIELD)
    return dict(raw) if isinstance(raw, dict) else {}


def play_view(pledge: dict) -> dict:
    """What the demo page needs for one owned pledge: where it stands and what may be done next."""
    state = _state(pledge)
    status = str(pledge.get("status") or "")
    arrival = state.get("arrival_at")
    approved = state.get("approved_at")
    actions: list[str] = []
    if status in _HELD:
        if not arrival:
            actions.append("simulate_arrival")
        elif not approved:
            actions.append("approve")
        else:
            actions.append("capture")
    if status in _VOIDABLE:
        actions.append("void")
    if status in _REFUNDABLE:
        actions.append("refund")
    return {
        "pledge_id": pledge.get("_id"),
        "status": status,
        "arrival_simulated_at": arrival or None,
        "approved_at": approved or None,
        "actions": actions,
    }


async def _save_state(pledge: dict, patch: dict, history: str) -> dict:
    fresh = await get_ledger().get_pledge(str(pledge["_id"])) or pledge
    state = _state(fresh)
    state.update(patch)
    fresh[STATE_FIELD] = state
    fresh["history"] = list(fresh.get("history") or []) + [history]
    return await get_ledger().save_pledge(fresh)


async def _anchor(pledge: dict) -> Optional[dt.datetime]:
    """When this pledge may be captured: the stop's arrival, or the leg's departure for a cabin."""
    doc = await timing_milestone(pledge, read_only=True)
    meta = (doc or {}).get("meta") if isinstance((doc or {}).get("meta"), dict) else {}
    raw = meta.get("departure_iso") if meta.get("capture_on") == "departure" else meta.get("arrival_iso")
    return _parse_moment(str(raw or ""))


async def simulate_arrival(pledge: dict) -> dict:
    """The boat has arrived, for this pledge only. No PayPal call, no clock change."""
    if str(pledge.get("status") or "") not in _HELD:
        raise DemoPlayOutOfOrder("this pledge is not held: there is no arrival to wait for")
    if _state(pledge).get("arrival_at"):
        return pledge
    anchor = await _anchor(pledge)
    if anchor is None:
        raise DemoPlayOutOfOrder("this pledge has no arrival or departure date to simulate")
    return await _save_state(
        pledge,
        {"arrival_at": anchor.replace(microsecond=0).isoformat(), "arrival_simulated_on": now_iso()},
        "demo_arrival_simulated",
    )


async def approve(pledge: dict) -> dict:
    """The visitor, as treasurer, approves the capture of this pledge. No PayPal call."""
    state = _state(pledge)
    if str(pledge.get("status") or "") not in _HELD:
        raise DemoPlayOutOfOrder("this pledge is not held: there is nothing to approve")
    if not state.get("arrival_at"):
        raise DemoPlayOutOfOrder("simulate the boat's arrival for this pledge before approving")
    if state.get("approved_at"):
        return pledge
    return await _save_state(pledge, {"approved_at": now_iso()}, "demo_approved")


async def capture(pledge: dict, client: Any) -> dict:
    """Capture through the treasurer's own code path, dated at this pledge's simulated arrival."""
    state = _state(pledge)
    arrival = _parse_moment(str(state.get("arrival_at") or ""))
    if arrival is None:
        raise DemoPlayOutOfOrder("simulate the boat's arrival for this pledge before capturing")
    if not state.get("approved_at"):
        raise DemoPlayOutOfOrder("approve this pledge before capturing")
    return await capture_pledge(str(pledge["_id"]), client, effective_at=arrival)


async def void(pledge: dict, client: Any) -> dict:
    """Release the hold through the treasurer's own code path."""
    return await void_pledge(str(pledge["_id"]), client)


async def refund(pledge: dict, client: Any) -> dict:
    """Refund what remains of a captured pledge through the treasurer's own code path."""
    return await refund_pledge(str(pledge["_id"]), client)

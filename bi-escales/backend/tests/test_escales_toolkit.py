"""PayPal Agent Toolkit is optional and off unless ESCALES_TOOLKIT_ENABLED is set."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.audit import list_entries
from app.escales.pledges import reset_ledger
from app.escales.toolkit_tools import (
    TOOLKIT_ORDER_ACTIONS,
    ReadOnlyTools,
    ToolNotAllowed,
    enabled_toolkit_methods,
    readonly_toolkit_configuration,
    toolkit_installed,
)
from app.routers.escales import router, set_paypal_client_factory

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

PLEDGE = {
    "amount_eur": "20.00",
    "description": "20 milles Mayotte",
    "milestone_id": "dep-mayotte",
}


def _purge_toolkit() -> None:
    for name in list(sys.modules):
        if name == "paypal_agent_toolkit" or name.startswith("paypal_agent_toolkit."):
            del sys.modules[name]


def _toolkit_loaded() -> bool:
    return any(
        name == "paypal_agent_toolkit" or name.startswith("paypal_agent_toolkit.")
        for name in sys.modules
    )


class FakePayPal:
    def __init__(self):
        self.calls = []
        self.n = 0

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.calls.append(("create", amount_eur, idempotency_key))
        self.n += 1
        order_id = f"ORDER{self.n}"
        return {
            "id": order_id,
            "status": "CREATED",
            "intent": "AUTHORIZE",
            "links": [{
                "rel": "approve",
                "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
            }],
        }

    def authorize_order(self, order_id):
        self.calls.append(("authorize", order_id))
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{
                        "id": f"AUTH-{order_id}",
                        "expiration_time": "2026-12-01T00:00:00Z",
                    }],
                },
            }],
        }

    def capture_authorization(self, authorization_id, final=True):
        self.calls.append(("capture", authorization_id))
        return {"id": "CAP", "status": "COMPLETED"}

    def void_authorization(self, authorization_id):
        self.calls.append(("void", authorization_id))
        return {}

    def get_order(self, order_id):
        self.calls.append(("orders.get", order_id))
        return {"id": order_id, "status": "APPROVED"}

    def get_authorization(self, authorization_id):
        self.calls.append(("authorizations.get", authorization_id))
        return {"id": authorization_id, "status": "CREATED"}


def _install_fake_toolkit(used: list, forbidden: list) -> None:
    """Register a fake paypal_agent_toolkit. Does not import the real package."""
    _purge_toolkit()

    def allow(client, params):
        for name in (
            "post",
            "delete",
            "capture_authorization",
            "void_authorization",
            "create_authorize_order",
        ):
            assert not hasattr(client, name)
        order = client.get(f"/v2/checkout/orders/{params['order_id']}")
        used.append(("get_order_details", params["order_id"]))
        return json.dumps({
            "message": "read",
            "status": order["status"],
            "raw": order,
        })

    def refuse(client, params):
        forbidden.append(params)
        raise AssertionError("write tool called")

    pkg = types.ModuleType("paypal_agent_toolkit")
    pkg.__path__ = []
    pkg.__package__ = "paypal_agent_toolkit"
    shared = types.ModuleType("paypal_agent_toolkit.shared")
    shared.__path__ = []
    shared.__package__ = "paypal_agent_toolkit.shared"
    tools_mod = types.ModuleType("paypal_agent_toolkit.shared.tools")
    tools_mod.__package__ = "paypal_agent_toolkit.shared"
    tools_mod.tools = [
        {
            "method": "pay_order",
            "actions": {"orders": {"capture": True}},
            "execute": refuse,
        },
        {
            "method": "capture_quietly",
            "actions": {"orders": {"get": True}},
            "execute": refuse,
        },
        {
            "method": "get_order_details",
            "actions": {"orders": {"get": True}},
            "execute": allow,
        },
        {
            "method": "create_order",
            "actions": {"orders": {"create": True}},
            "execute": refuse,
        },
    ]
    config_mod = types.ModuleType("paypal_agent_toolkit.shared.configuration")
    config_mod.__package__ = "paypal_agent_toolkit.shared"

    class Configuration:
        def __init__(self, actions, context=None):
            self.actions = actions
            self.context = context

    class Context:
        def __init__(self, sandbox=True, **kwargs):
            self.sandbox = sandbox

    config_mod.Configuration = Configuration
    config_mod.Context = Context
    pkg.shared = shared
    shared.tools = tools_mod
    shared.configuration = config_mod
    sys.modules["paypal_agent_toolkit"] = pkg
    sys.modules["paypal_agent_toolkit.shared"] = shared
    sys.modules["paypal_agent_toolkit.shared.tools"] = tools_mod
    sys.modules["paypal_agent_toolkit.shared.configuration"] = config_mod


def _assert_fresh_app_import_skips_toolkit() -> None:
    """Import the FastAPI app in a fresh process with the toolkit flag off.

    ``app.main`` constructs the Mongo client at import. The placeholder URL is
    local and startup is not run, so nothing connects.
    """
    script = (
        "import os, sys\n"
        "os.environ['MONGO_URL'] = 'mongodb://127.0.0.1:27017'\n"
        "os.environ['ESCALES_ENABLED'] = '1'\n"
        "os.environ.pop('ESCALES_TOOLKIT_ENABLED', None)\n"
        "import app.main\n"
        "import app.escales.captain\n"
        "import app.escales.paypal_client\n"
        "import app.escales.audit\n"
        "loaded = [\n"
        "    name for name in sys.modules\n"
        "    if name == 'paypal_agent_toolkit'\n"
        "    or name.startswith('paypal_agent_toolkit.')\n"
        "    or 'apimatic' in name.lower()\n"
        "]\n"
        "assert loaded == [], loaded\n"
    )
    env = os.environ.copy()
    env["MONGO_URL"] = "mongodb://127.0.0.1:27017"
    env["ESCALES_ENABLED"] = "1"
    env.pop("ESCALES_TOOLKIT_ENABLED", None)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _ready(client, key):
    created = client.post(
        "/api/escales/pledges",
        json=PLEDGE,
        headers={"PayPal-Request-Id": key},
    )
    assert created.status_code == 200, created.text
    authorized = client.post(f"/api/escales/pledges/{created.json()['id']}/authorize")
    assert authorized.status_code == 200, authorized.text
    return created.json(), authorized.json()


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "FALSE", "  "])
def test_toolkit_flag_off_does_not_import(monkeypatch, value):
    monkeypatch.setenv("ESCALES_TOOLKIT_ENABLED", value)
    _purge_toolkit()
    assert toolkit_installed() is False
    assert enabled_toolkit_methods() == []
    assert readonly_toolkit_configuration() is None
    assert not _toolkit_loaded()


def test_core_has_no_sponsor_import():
    checked = [
        BACKEND / "app" / "main.py",
        BACKEND / "app" / "routers" / "escales.py",
    ]
    checked.extend(
        path
        for path in (BACKEND / "app" / "escales").glob("*.py")
        if path.name != "toolkit_tools.py"
    )
    for path in checked:
        text = path.read_text(encoding="utf-8").lower()
        assert "paypal_agent_toolkit" not in text
        assert "apimatic" not in text
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "paypal-agent-toolkit" not in requirements
    assert "apimatic" not in requirements
    optional = (BACKEND / "requirements-optional.txt").read_text(encoding="utf-8")
    assert "paypal-agent-toolkit==1.11.0" in optional
    assert "ESCALES_TOOLKIT_ENABLED" in optional
    assert "apimatic" not in optional.lower()
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert any(line.strip() == "ESCALES_TOOLKIT_ENABLED=" for line in env.splitlines())
    toolkit = (BACKEND / "app" / "escales" / "toolkit_tools.py").read_text(encoding="utf-8")
    for line in toolkit.splitlines():
        stripped = line.strip()
        if stripped.startswith("import paypal_agent_toolkit") or stripped.startswith("from paypal_agent_toolkit"):
            assert line[:1] in {" ", "\t"}


def test_flag_off_app_and_captain_work_without_the_toolkit(monkeypatch):
    monkeypatch.delenv("ESCALES_TOOLKIT_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    import app.core.llm as llm
    monkeypatch.setattr(llm, "has_llm", lambda settings=None: False)
    _purge_toolkit()
    _assert_fresh_app_import_skips_toolkit()
    assert not _toolkit_loaded()

    reset_ledger()
    fake = FakePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    try:
        with TestClient(app) as client:
            chat = client.post(
                "/api/escales/captain/chat",
                json={"message": "Je veux parrainer 20 milles près de Mayotte"},
            )
            assert chat.status_code == 200
            body = chat.json()
            assert body["suggested_pledge"]["amount_eur"] == "20.00"
            assert body["suggested_pledge"]["intent"] == "AUTHORIZE"
            assert "order_id" not in body

            _created, authorized = _ready(client, "off-1")
            evidence = client.post(
                "/api/escales/milestones/dep-mayotte/evidence",
                json={"met": True, "facts": {"port": "Mayotte"}},
            )
            assert evidence.status_code == 200
            review = client.post("/api/escales/captain/review/dep-mayotte")
            assert review.status_code == 200, review.text
            proposal = review.json()
            assert proposal["proposal"] == "capture"
            assert authorized["id"] in proposal["pledge_ids"]
            names = [call[0] for call in fake.calls]
            assert "orders.get" in names
            assert "authorizations.get" in names
            assert "capture" not in names
            assert "void" not in names
            stored = client.get(f"/api/escales/pledges/{authorized['id']}")
            assert stored.json()["status"] == "authorized"
        entries = asyncio.run(list_entries())
        assert any(entry["kind"] == "proposal" and entry["actor"] == "captain" for entry in entries)
        assert not _toolkit_loaded()
    finally:
        set_paypal_client_factory(None)
        reset_ledger()


def test_flag_on_without_package_falls_back_to_core_gets(monkeypatch):
    monkeypatch.setenv("ESCALES_TOOLKIT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    _purge_toolkit()
    sys.modules["paypal_agent_toolkit"] = None
    try:
        assert toolkit_installed() is False
        assert enabled_toolkit_methods() == []
        assert readonly_toolkit_configuration() is None
        fake = FakePayPal()
        reader = ReadOnlyTools(fake)
        assert reader.get("orders.get", "ORDER1") == {"id": "ORDER1", "status": "APPROVED"}
        assert reader.get("authorizations.get", "AUTH-ORDER1")["status"] == "CREATED"
        assert [call[0] for call in fake.calls] == ["orders.get", "authorizations.get"]
        with pytest.raises(ToolNotAllowed):
            reader.get("orders.capture", "ORDER1")
    finally:
        _purge_toolkit()


def test_flag_on_mocked_toolkit_is_used_and_stays_readonly(monkeypatch):
    monkeypatch.setenv("ESCALES_TOOLKIT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    import app.core.llm as llm
    monkeypatch.setattr(llm, "has_llm", lambda settings=None: False)
    used: list = []
    forbidden: list = []
    _install_fake_toolkit(used, forbidden)
    reset_ledger()
    fake = FakePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    try:
        assert toolkit_installed() is True
        assert enabled_toolkit_methods() == ["get_order_details"]
        configuration = readonly_toolkit_configuration()
        assert configuration.actions == TOOLKIT_ORDER_ACTIONS == {"orders": {"get": True}}
        assert "capture" not in configuration.actions["orders"]

        with TestClient(app) as client:
            _created, authorized = _ready(client, "on-1")
            assert used == []
            evidence = client.post(
                "/api/escales/milestones/dep-mayotte/evidence",
                json={"met": True, "facts": {"port": "Mayotte"}},
            )
            assert evidence.status_code == 200
            review = client.post("/api/escales/captain/review/dep-mayotte")
            assert review.status_code == 200, review.text
            assert review.json()["proposal"] == "capture"
            assert used == [("get_order_details", "ORDER1")]
            assert forbidden == []
            names = [call[0] for call in fake.calls]
            assert "orders.get" in names
            assert "authorizations.get" in names
            assert "capture" not in names
            assert "void" not in names
            stored = client.get(f"/api/escales/pledges/{authorized['id']}")
            assert stored.json()["status"] == "authorized"

        reader = ReadOnlyTools(fake)
        order = reader.get("orders.get", "ORDER1")
        assert order["id"] == "ORDER1"
        assert order["status"] == "APPROVED"
        assert "message" not in order
        with pytest.raises(ToolNotAllowed):
            reader.get("orders.capture", "ORDER1")
        with pytest.raises(ToolNotAllowed):
            reader.get("authorizations.void", "AUTH-ORDER1")
        assert forbidden == []
        assert all(name == "get_order_details" for name, _order in used)
        assert not hasattr(reader, "capture_authorization")
        assert not hasattr(reader, "void_authorization")
    finally:
        set_paypal_client_factory(None)
        reset_ledger()
        _purge_toolkit()

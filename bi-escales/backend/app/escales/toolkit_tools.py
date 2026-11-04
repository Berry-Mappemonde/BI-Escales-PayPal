"""Read-only tools for the Captain.

``paypal-agent-toolkit`` is an optional partner module. It is imported only
when ``ESCALES_TOOLKIT_ENABLED`` is truthy. With the flag off (the default),
orders.get and authorizations.get call the plain REST client and this module
does not import ``paypal_agent_toolkit``.

With the flag on, orders.get is the toolkit's read-only order tool. The
toolkit has no authorization read, so authorizations.get stays on the REST
client. Capture, void, and pay are never exposed. The Captain receives this
object, not the PayPal client.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from .config import toolkit_enabled

ALLOWED_TOOLS = ("orders.get", "authorizations.get")

# Passed to paypal-agent-toolkit when the flag is on and the package is installed.
# capture / create / void stay off.
TOOLKIT_ORDER_ACTIONS = {"orders": {"get": True}}

_WRITE_WORDS = ("capture", "void", "pay", "create", "refund", "delete")
_ORDER_GET_PREFIX = "/v2/checkout/orders/"


class ToolNotAllowed(PermissionError):
    def __init__(self, tool: str):
        self.tool = tool
        super().__init__(f"tool not allowed: {tool}")


class _OrderGetAdapter:
    """GET /v2/checkout/orders/{id} only. The toolkit never receives capture or void."""

    def __init__(self, get_order: Callable[[str], dict]) -> None:
        self._get_order = get_order

    def get(self, uri: str) -> dict:
        path = str(uri).split("?", 1)[0].rstrip("/")
        if not path.startswith(_ORDER_GET_PREFIX):
            raise ToolNotAllowed("orders.get")
        order_id = path[len(_ORDER_GET_PREFIX):]
        if not order_id or "/" in order_id:
            raise ToolNotAllowed("orders.get")
        return self._get_order(order_id)


def _write_method(method: str) -> bool:
    lowered = method.lower()
    return any(word in lowered for word in _WRITE_WORDS)


def _readonly_order_tool(tool: Any) -> bool:
    if not isinstance(tool, dict):
        return False
    if (tool.get("actions") or {}) != TOOLKIT_ORDER_ACTIONS:
        return False
    return not _write_method(str(tool.get("method") or ""))


def _toolkit_tools() -> Optional[list]:
    """Toolkit tool list, or None when the flag is off or the package is absent.

    Does not import ``paypal_agent_toolkit`` unless the flag is on.
    """
    if not toolkit_enabled():
        return None
    try:
        from paypal_agent_toolkit.shared.tools import tools
    except ImportError:
        return None
    return list(tools)


def _order_payload(result: Any) -> dict:
    """Order document from a toolkit tool result. The REST client already returns one."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return {}
    if not isinstance(result, dict):
        return {}
    raw = result.get("raw")
    if isinstance(raw, dict):
        return raw
    return result


def _orders_get_via_toolkit(
    core_get: Callable[[str], dict],
    execute: Callable[..., Any],
) -> Callable[[str], dict]:
    adapter = _OrderGetAdapter(core_get)

    def orders_get(order_id: str) -> dict:
        return _order_payload(execute(adapter, {"order_id": order_id}))

    return orders_get


class ReadOnlyTools:
    """orders.get and authorizations.get. The client object is not retained."""

    def __init__(self, client: Any) -> None:
        orders_get: Callable[[str], dict] = client.get_order
        authorizations_get: Callable[[str], dict] = client.get_authorization
        for tool in _toolkit_tools() or []:
            if not _readonly_order_tool(tool):
                continue
            execute = tool.get("execute")
            if not callable(execute):
                continue
            orders_get = _orders_get_via_toolkit(orders_get, execute)
            break
        self._calls = {
            "orders.get": orders_get,
            "authorizations.get": authorizations_get,
        }

    def allowed(self) -> tuple[str, ...]:
        return ALLOWED_TOOLS

    def get(self, tool: str, resource_id: str) -> dict:
        call = self._calls.get(tool)
        if call is None:
            raise ToolNotAllowed(tool)
        return call(resource_id)


def toolkit_installed() -> bool:
    """True when the flag is on and paypal-agent-toolkit imports.

    The flag-off path does not import the package, even if it is installed.
    """
    if not toolkit_enabled():
        return False
    try:
        import paypal_agent_toolkit  # noqa: F401
    except ImportError:
        return False
    return True


def readonly_toolkit_configuration() -> Optional[Any]:
    """Toolkit configuration limited to orders.get, or None when the flag is off."""
    if not toolkit_enabled():
        return None
    try:
        from paypal_agent_toolkit.shared.configuration import Configuration, Context
    except ImportError:
        return None
    return Configuration(actions=dict(TOOLKIT_ORDER_ACTIONS), context=Context(sandbox=True))


def enabled_toolkit_methods() -> list[str]:
    """Toolkit method names this configuration would expose. Writes are dropped.

    Returns an empty list without importing the toolkit when the flag is off.
    """
    tools = _toolkit_tools()
    if not tools:
        return []
    names: list[str] = []
    for tool in tools:
        if not _readonly_order_tool(tool):
            continue
        names.append(str(tool.get("method") or ""))
    return names


def exposed_tools() -> tuple[str, ...]:
    """The only tools the Captain can call."""
    return ALLOWED_TOOLS

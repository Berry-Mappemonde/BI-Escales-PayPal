"""Read-only PayPal toolkit wrappers for the Captain."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from .config import toolkit_enabled
from .paypal_client import PayPalClient
from .paypal_limits import PayPalCallBudget, PayPalCallLimitExceeded

ALLOWED_TOOLS = (
    "orders.get",
    "authorizations.get",
    "disputes.list",
    "transactions.search",
    "invoices.list",
)

TOOLKIT_ORDER_ACTIONS = {"orders": {"get": True}}

_WRITE_WORDS = ("capture", "void", "pay", "create", "refund", "delete")
_ORDER_GET_PREFIX = "/v2/checkout/orders/"


class ToolNotAllowed(PermissionError):
    def __init__(self, tool: str):
        self.tool = tool
        super().__init__(f"tool not allowed: {tool}")


class _OrderGetAdapter:
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
    if not toolkit_enabled():
        return None
    try:
        from paypal_agent_toolkit.shared.tools import tools
    except ImportError:
        return None
    return list(tools)


def _order_payload(result: Any) -> dict:
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
    """Read-only PayPal lookups. Never capture, void, or refund."""

    def __init__(self, client: Any) -> None:
        self._budget = PayPalCallBudget()
        self._http_metered = isinstance(client, PayPalClient)
        if self._http_metered:
            client.captain_budget = self._budget
        orders_get: Callable[[str], dict] = client.get_order
        authorizations_get: Callable[[str], dict] = client.get_authorization
        self.uses_toolkit = False
        for tool in _toolkit_tools() or []:
            if not _readonly_order_tool(tool):
                continue
            execute = tool.get("execute")
            if not callable(execute):
                continue
            orders_get = _orders_get_via_toolkit(orders_get, execute)
            self.uses_toolkit = True
            break
        self.call_log: list[dict[str, str]] = []
        self._calls: dict[str, Callable[..., dict]] = {
            "orders.get": lambda resource_id: orders_get(resource_id),
            "authorizations.get": lambda resource_id: authorizations_get(resource_id),
            "disputes.list": lambda resource_id="": client.list_disputes(),
            "transactions.search": lambda resource_id: client.search_transactions(
                start_date=resource_id.split("|", 1)[0],
                end_date=resource_id.split("|", 1)[1] if "|" in resource_id else resource_id,
            ),
            "invoices.list": lambda resource_id="1": client.list_invoices(page=int(resource_id or "1")),
        }

    def allowed(self) -> tuple[str, ...]:
        return ALLOWED_TOOLS

    def get(self, tool: str, resource_id: str = "") -> dict:
        call = self._calls.get(tool)
        if call is None:
            raise ToolNotAllowed(tool)
        if self._budget.remaining <= 0:
            raise PayPalCallLimitExceeded("PayPal read limit reached for this turn (3 calls)")
        if not self._http_metered:
            self._budget.consume()
        result = call(resource_id)
        self.call_log.append({"tool": tool, "resource_id": resource_id})
        return result


def toolkit_installed() -> bool:
    if not toolkit_enabled():
        return False
    try:
        import paypal_agent_toolkit  # noqa: F401
    except ImportError:
        return False
    return True


def readonly_toolkit_configuration() -> Optional[Any]:
    if not toolkit_enabled():
        return None
    try:
        from paypal_agent_toolkit.shared.configuration import Configuration, Context
    except ImportError:
        return None
    return Configuration(actions=dict(TOOLKIT_ORDER_ACTIONS), context=Context(sandbox=True))


def enabled_toolkit_methods() -> list[str]:
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
    return ALLOWED_TOOLS

"""OpenAPI documentation helpers.

These builders only shape the generated spec. They do not add validation.
"""
from __future__ import annotations

import warnings
from typing import Any, Optional

from fastapi import Path, Query


def _quiet_param(factory, **kwargs):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="`example` has been deprecated",
            category=DeprecationWarning,
        )
        return factory(**kwargs)


def path_param(description: str, example: str, title: str):
    """Path parameter metadata. The value stays a required string."""
    return _quiet_param(
        Path,
        description=description,
        example=example,
        examples=[example],
        title=title,
        json_schema_extra={"example": example},
    )


def query_param(description: str, example: Any, title: str):
    """Query parameter metadata. Required-ness stays on the default."""
    examples = [example] if example is not None else None
    extra = {"example": example} if example is not None else None
    return _quiet_param(
        Query,
        description=description,
        example=example,
        examples=examples,
        title=title,
        json_schema_extra=extra,
    )


def with_example(example: dict[str, Any]):
    """Attach a model example and describe anyOf branches without changing types."""

    def apply(schema: dict[str, Any]) -> None:
        schema["example"] = example
        schema["examples"] = [example]
        for prop in (schema.get("properties") or {}).values():
            if not isinstance(prop, dict):
                continue
            for branch in prop.get("anyOf") or []:
                if not isinstance(branch, dict):
                    continue
                if branch.get("type") == "null":
                    branch.setdefault("description", "Null when this value is omitted.")
                    branch.setdefault("example", None)
                    branch.setdefault("examples", [None])
                else:
                    parent = prop.get("description")
                    if parent:
                        branch.setdefault("description", parent)
                    if "example" in prop:
                        branch.setdefault("example", prop["example"])
            items = prop.get("items")
            if isinstance(items, dict) and "description" not in items:
                items["description"] = prop.get("description") or "One entry in the list."

    return apply


def json_success(description: str, schema_description: str, example: Any = None) -> dict[str, Any]:
    media: dict[str, Any] = {"schema": {"description": schema_description}}
    if example is not None:
        media["example"] = example
    return {"description": description, "content": {"application/json": media}}


def validation_error(loc: list[Any]) -> dict[str, Any]:
    return {
        "description": "Validation error",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/HTTPValidationError"},
                "example": {
                    "detail": [
                        {"loc": loc, "msg": "Field required", "type": "missing"}
                    ]
                },
            }
        },
    }


def route_docs(
    summary: str,
    response_description: str,
    example: Any | None = None,
    *,
    schema_description: str,
    validation_loc: Optional[list[Any]] = None,
    body_description: Optional[str] = None,
    body_example: Any = None,
) -> dict[str, Any]:
    """Decorator kwargs: summary, response text, and optional body docs."""
    # 422 stays FastAPI's generated response so HTTPValidationError remains a component.
    # validation_loc is accepted for callers and is not written into the spec here.
    del validation_loc
    responses: dict[int, dict[str, Any]] = {
        200: json_success(response_description, schema_description, example),
    }
    documented: dict[str, Any] = {
        "summary": summary,
        "response_description": response_description,
        "responses": responses,
    }
    if body_description is not None:
        media: dict[str, Any] = {}
        if body_example is not None:
            media["example"] = body_example
        documented["openapi_extra"] = {
            "requestBody": {
                "description": body_description,
                "content": {"application/json": media},
            }
        }
    return documented


def describe_framework_schemas(schema: dict[str, Any]) -> None:
    """Describe FastAPI's generated validation-error components."""
    components = (schema.get("components") or {}).get("schemas") or {}
    validation = components.get("ValidationError")
    if isinstance(validation, dict):
        validation.setdefault("description", "One request validation error.")
        props = validation.get("properties") or {}
        notes = {
            "loc": "Where the error occurred, as strings or array indexes.",
            "msg": "Human-readable validation message.",
            "type": "Machine-readable validation error type.",
        }
        for key, text in notes.items():
            field = props.get(key)
            if isinstance(field, dict):
                field.setdefault("description", text)
                if key == "msg":
                    field["title"] = "Validation message"
                    field.setdefault("example", "Field required")
                elif key == "type":
                    field.setdefault("example", "missing")
        loc = props.get("loc")
        if isinstance(loc, dict):
            loc.setdefault("example", ["body", "amount_eur"])
            items = loc.get("items")
            if isinstance(items, dict):
                for branch in items.get("anyOf") or []:
                    if not isinstance(branch, dict):
                        continue
                    if branch.get("type") == "string":
                        branch.setdefault("description", "Location path segment.")
                        branch.setdefault("example", "body")
                    elif branch.get("type") == "integer":
                        branch.setdefault("description", "Array index in the location path.")
                        branch.setdefault("example", 0)
    http_error = components.get("HTTPValidationError")
    if isinstance(http_error, dict):
        http_error.setdefault(
            "description",
            "Request validation failed. The detail list names each problem.",
        )
        http_error.setdefault(
            "example",
            {"detail": [{"loc": ["body", "amount_eur"], "msg": "Field required", "type": "missing"}]},
        )
        detail = (http_error.get("properties") or {}).get("detail")
        if isinstance(detail, dict):
            detail.setdefault("description", "Validation errors for this request.")

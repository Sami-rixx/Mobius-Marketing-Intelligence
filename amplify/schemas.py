"""JSON-schema loading and validation.

Every agent output and every versioned content file passes through here. Validation errors
are reported with the exact JSON path so a failure is debuggable from a phone screen.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError as JSSchemaError
from referencing import Registry as RefRegistry
from referencing import Resource

from .config import RepoPaths
from .errors import SchemaError

SCHEMA_FILES = {
    "content-item": "content-item.schema.json",
    "claims-registry": "claims-registry.schema.json",
    "claims-update": "claims-update.schema.json",
    "weekly-plan": "weekly-plan.schema.json",
    "research-notes": "research-notes.schema.json",
    "qa-report": "qa-report.schema.json",
    "analytics-update": "analytics-update.schema.json",
    "analytics-raw": "analytics-raw.schema.json",
    "edit-proposal": "edit-proposal.schema.json",
    "decisions": "decisions.schema.json",
}

_format_checker = FormatChecker()


def schema_path(paths: RepoPaths, name: str) -> Path:
    try:
        filename = SCHEMA_FILES[name]
    except KeyError as exc:
        raise SchemaError(name, [f"unknown schema name (known: {sorted(SCHEMA_FILES)})"]) from exc
    return paths.schemas / filename


@lru_cache(maxsize=32)
def _load_schema_file(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise SchemaError(path.name, [f"schema file missing: {path}"])
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        Draft202012Validator.check_schema(raw)
    except JSSchemaError as exc:  # pragma: no cover - schemas are validated in CI too
        raise SchemaError(path.name, [f"invalid schema: {exc.message}"]) from exc
    return raw


def load_schema(paths: RepoPaths, name: str) -> dict[str, Any]:
    return _load_schema_file(str(schema_path(paths, name)))


@lru_cache(maxsize=8)
def _reference_registry(schema_dir: str) -> RefRegistry:
    """Register every local schema by ``$id`` so cross-file ``$ref`` resolves offline."""
    registry = RefRegistry()
    for path in sorted(Path(schema_dir).glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        schema_id = raw.get("$id")
        if schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(raw))
    return registry


def build_validator(paths: RepoPaths, name: str) -> Draft202012Validator:
    return Draft202012Validator(
        load_schema(paths, name),
        registry=_reference_registry(str(paths.schemas)),
        format_checker=_format_checker,
    )


def _format_problem(error: Any) -> str:
    location = "/".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def validate(instance: Any, paths: RepoPaths, name: str) -> None:
    """Validate ``instance`` against a named schema; raise :class:`SchemaError`."""
    validator = build_validator(paths, name)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if errors:
        raise SchemaError(name, [_format_problem(e) for e in errors])


def problems(instance: Any, paths: RepoPaths, name: str) -> list[str]:
    """Non-raising variant, used by validators and tests."""
    try:
        validate(instance, paths, name)
    except SchemaError as exc:
        return exc.problems
    return []


def is_valid(instance: Any, paths: RepoPaths, name: str) -> bool:
    return not problems(instance, paths, name)


def summarise(problems_list: Iterable[str], limit: int = 8) -> str:
    items = list(problems_list)
    shown = items[:limit]
    if len(items) > limit:
        shown.append(f"... and {len(items) - limit} more")
    return "; ".join(shown)

"""Content items: loading, validation, status transitions (docs/03).

The transition table is the anti-accident device: an agent cannot approve content, and
nothing can be marked published without a human recording a real URL afterwards.
"""

from __future__ import annotations

import datetime as _dt
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .config import RepoPaths, WEEK_RE, parse_week
from .errors import SchemaError, TransitionError
from .schemas import validate

STATUSES = ("draft", "in_review", "approved", "rejected", "published")

# actor -> {from_status: {allowed_to_statuses}}
TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "producer": {"draft": {"draft"}, "rejected": {"draft"}},
    "qa-editor": {"draft": {"in_review", "rejected"}, "rejected": {"rejected"}},
    "system": {},
    "samuel": {
        "in_review": {"approved", "rejected"},
        "approved": {"rejected", "published"},
        "rejected": {"draft"},
        "draft": {"rejected"},
    },
}

# The only status a human signature creates. Used by tests and callers that must be explicit.
FOUNDER_ONLY_STATUSES = {"approved", "published"}


def check_transition(current: str, new: str, actor: str) -> None:
    if current not in STATUSES or new not in STATUSES:
        raise TransitionError(f"unknown status transition {current!r} -> {new!r}")
    allowed = TRANSITIONS.get(actor)
    if allowed is None:
        raise TransitionError(f"unknown actor {actor!r}; cannot change content status")
    if new in FOUNDER_ONLY_STATUSES and actor != "samuel":
        raise TransitionError(
            f"{actor!r} may not set status {new!r}: only Samuel's review decisions "
            "approve or publish content (docs/03-content-schema.md)"
        )
    if new == current and actor in {"producer", "qa-editor"}:
        return
    if new not in allowed.get(current, set()):
        raise TransitionError(
            f"{actor!r} may not move content from {current!r} to {new!r} "
            f"(allowed: {sorted(allowed.get(current, set())) or 'nothing'})"
        )


def week_of_item(item: dict[str, Any]) -> str:
    week = item.get("week")
    if week:
        parse_week(week)
        return str(week)
    content_id = str(item.get("content_id", ""))
    guess = content_id[:8]
    if WEEK_RE.match(guess):
        parse_week(guess)
        return guess
    raise TransitionError(f"cannot determine week for item {content_id!r}")


def item_path(paths: RepoPaths, content_id: str, directory: Path | None = None) -> Path:
    base = directory or paths.drafts
    return base / f"{content_id}.yaml"


def load_item(path: Path, paths: RepoPaths) -> dict[str, Any]:
    if not path.exists():
        raise SchemaError("content-item", [f"content item not found: {path}"])
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SchemaError("content-item", [f"{path.name}: invalid YAML: {exc}"]) from exc
    if not isinstance(raw, dict):
        raise SchemaError("content-item", [f"{path.name}: must be a YAML mapping"])
    validate(raw, paths, "content-item")
    return raw


def load_items(directory: Path, paths: RepoPaths, *, week: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not directory.exists():
        return items
    for path in sorted(directory.glob("*.yaml")):
        item = load_item(path, paths)
        if week and week_of_item(item) != week:
            continue
        items.append(item)
    return items


def dump_item(item: dict[str, Any]) -> str:
    return yaml.safe_dump(item, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False)


def save_item(
    item: dict[str, Any],
    path: Path,
    paths: RepoPaths,
    *,
    actor: str,
    previous: dict[str, Any] | None = None,
) -> Path:
    """Validate and atomically write an item, enforcing actor/status rules first."""
    check_transition(previous.get("status", "draft") if previous else "draft", item.get("status", "draft"), actor)
    if previous and previous.get("content_id") != item.get("content_id"):
        raise TransitionError("content_id may not change once written")
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    item.setdefault("created_at", previous.get("created_at") if previous else now)
    item["updated_at"] = now
    validate(item, paths, "content-item")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dump_item(item))
        os.replace(tmp, path)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink()
    return path


def create_item(
    item: dict[str, Any], paths: RepoPaths, *, directory: Path | None = None, actor: str = "producer"
) -> Path:
    if item.get("status") != "draft":
        raise TransitionError("new content items must start as draft (docs/03)")
    target = item_path(paths, str(item["content_id"]), directory)
    if target.exists():
        raise TransitionError(f"refusing to overwrite existing draft: {target.name}")
    return save_item(item, target, paths, actor=actor, previous=None)

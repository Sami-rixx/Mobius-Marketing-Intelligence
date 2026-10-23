"""Samuel's review session — the only place content becomes approved (docs/03, docs/04).

Approval and publication are distinct states:

* only ``decided_by="samuel"`` can move ``in_review`` -> ``approved``;
* ``approved`` -> ``published`` happens only when Samuel records a real URL *after* he has
  posted the item himself. Nothing here can post anything.

Every decision is appended to ``content/review/decisions-<week>.yaml`` — never rewritten.
Edits are stored as before/after text: that history is the Edit Loop's training signal.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from . import content as content_mod
from .brand import BrandMaterials
from .config import RepoPaths
from .errors import GateFailure, TransitionError
from .lint import REASON_CODES, lint_item
from .registry import Registry
from .schemas import validate

FOUNDER = "samuel"


def decisions_path(paths: RepoPaths, week: str) -> Path:
    return paths.review / f"decisions-{week}.yaml"


def load_decisions(paths: RepoPaths, week: str) -> dict[str, Any]:
    path = decisions_path(paths, week)
    if not path.exists():
        payload = {"week": week, "decisions": []}
        validate(payload, paths, "decisions")
        return payload
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {"week": week, "decisions": []}
    except yaml.YAMLError as exc:
        raise GateFailure(f"{path.name} is not valid YAML: {exc}") from exc
    validate(payload, paths, "decisions")
    return payload


def _append_decision(paths: RepoPaths, week: str, entry: dict[str, Any]) -> Path:
    payload = load_decisions(paths, week)
    payload["decisions"].append(entry)
    validate(payload, paths, "decisions")
    target = decisions_path(paths, week)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
    return target


def capture_edit_diff(before: str, after: str, field: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"before/{field}",
            tofile=f"after/{field}",
        )
    )


def record_decision(
    *,
    paths: RepoPaths,
    week: str,
    item: dict[str, Any],
    decision: str,
    registry: Registry,
    materials: BrandMaterials,
    note: str | None = None,
    reason_code: str | None = None,
    edits: list[dict[str, str]] | None = None,
    lint_override: bool = False,
    human_editing_minutes: float | None = None,
    decided_at: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Apply one human decision, capturing edits and reason codes.

    Approving an item that the deterministic lints still block is refused unless
    ``lint_override`` is set *and* a note explains why. Gates are never bypassed silently.
    """
    if decision not in {"approve", "approve_with_edits", "reject"}:
        raise GateFailure(f"unknown decision {decision!r}")
    if item.get("status") != "in_review":
        raise TransitionError(
            f"{item.get('content_id')}: only in_review items can be decided (status is "
            f"{item.get('status')!r})"
        )
    if decision == "reject" and not reason_code:
        raise GateFailure("rejection requires a reason code from the taxonomy (docs/03)")
    if reason_code is not None and reason_code not in REASON_CODES:
        raise GateFailure(
            f"unknown reason code {reason_code!r}; use one of {sorted(REASON_CODES)} (docs/03)"
        )
    if decision == "approve_with_edits" and not edits:
        raise GateFailure("approve_with_edits requires at least one captured edit")
    if lint_override and not (note and len(note.strip()) >= 10):
        raise GateFailure("a lint override requires a note explaining the decision")

    stamp = (decided_at or _dt.datetime.now(_dt.timezone.utc)).replace(microsecond=0)
    entry: dict[str, Any] = {
        "content_id": item["content_id"],
        "decision": decision,
        "decided_by": FOUNDER,
        "decided_at": stamp.isoformat(),
        "reason_code": reason_code,
        "note": note,
        "human_editing_minutes": human_editing_minutes,
    }
    if lint_override:
        entry["lint_override"] = True

    revised = dict(item)
    if decision == "reject":
        revised["status"] = "rejected"
        revised["rejection_reason"] = reason_code
        revised["rejection_note"] = note or "Rejected by Samuel."
    else:
        captured: list[dict[str, str]] = []
        for edit in edits or []:
            field = edit["field"]
            if field not in revised:
                raise GateFailure(f"cannot edit unknown field {field!r}")
            before = str(revised.get(field) or "")
            after = edit["after"]
            captured.append({"field": field, "before": before, "after": after})
            revised[field] = after
        if captured:
            entry["edits"] = captured

        lint = lint_item(revised, materials, registry)
        if lint.blocking and not lint_override:
            raise GateFailure(
                "refusing to approve: blocking lint findings remain -> "
                + "; ".join(f.render() for f in lint.blocking)
                + ". Fix the draft, reject it, or record an explicit lint_override with a note."
            )
        revised["status"] = "approved"
        revised["rejection_reason"] = None
        revised["rejection_note"] = None

    path = content_mod.item_path(paths, item["content_id"])
    content_mod.save_item(revised, path, paths, actor=FOUNDER, previous=item)
    saved = content_mod.load_item(path, paths)
    _append_decision(paths, week, entry)
    return saved


def record_publication(
    *,
    paths: RepoPaths,
    content_id: str,
    platform: str,
    url: str,
    published_at: _dt.datetime | None = None,
    drafts_dir: Path | None = None,
) -> dict[str, Any]:
    """Record a URL Samuel posted himself. This function cannot post anything."""
    path = content_mod.item_path(paths, content_id, drafts_dir)
    item = content_mod.load_item(path, paths)
    if item.get("status") != "approved":
        raise GateFailure(
            f"{content_id}: only approved content can be recorded as published "
            f"(status is {item.get('status')!r}). Approval is not publication."
        )
    if not url.startswith(("https://", "http://")):
        raise GateFailure("a published URL must be a real http(s) URL")
    revised = dict(item)
    revised["published_urls"] = {**(item.get("published_urls") or {}), platform: url}
    revised["status"] = "published"
    content_mod.save_item(revised, path, paths, actor=FOUNDER, previous=item)
    return content_mod.load_item(path, paths)


def run_interactive_review(
    *,
    paths: RepoPaths,
    week: str,
    registry: Registry,
    materials: BrandMaterials,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    require_tty: bool = True,
    drafts_dir: Path | None = None,
) -> dict[str, Any]:
    """The founder's `make review` loop. Human-in-the-loop by construction."""
    if require_tty and not sys.stdin.isatty():
        raise GateFailure(
            "review must run interactively (no TTY detected). Approvals are human decisions; "
            "use `python -m amplify review --week W --show` in CI, or run it on your phone/terminal."
        )
    items = [
        i
        for i in content_mod.load_items(drafts_dir or paths.drafts, paths, week=week)
        if i.get("status") == "in_review"
    ]
    output_fn(f"Week {week}: {len(items)} item(s) awaiting your decision.")
    summary: dict[str, Any] = {"week": week, "approved": [], "rejected": [], "skipped": []}
    for item in items:
        output_fn("")
        output_fn(f"--- {item['content_id']} ({item['format']}) ---")
        output_fn(f"hook: {item.get('hook')}")
        output_fn(f"script:\n{item.get('script')}")
        lint = lint_item(item, materials, registry)
        if lint.blocking:
            output_fn("BLOCKING LINT:")
            for finding in lint.blocking:
                output_fn(f"  - {finding.render()}")
        else:
            output_fn("lint: clean")
        answer = input_fn("decision [a]pprove / [r]eject / [s]kip: ").strip().lower()
        if answer.startswith("s") or answer == "":
            summary["skipped"].append(item["content_id"])
            continue
        if answer.startswith("r"):
            code = input_fn("reason code (VOICE/UNVERIFIED_CLAIM/OFF_BRAND/WEAK_HOOK/WRONG_AUDIENCE/TOO_GENERIC/PERSONAL): ").strip()
            note = input_fn("note (optional): ").strip() or None
            record_decision(
                paths=paths, week=week, item=item, decision="reject", registry=registry,
                materials=materials, reason_code=code, note=note,
            )
            summary["rejected"].append(item["content_id"])
            continue
        if answer.startswith("a"):
            confirm = input_fn(
                f"Type APPROVE {item['content_id']} to confirm (approval is your signature): "
            ).strip()
            if confirm != f"APPROVE {item['content_id']}":
                output_fn("not confirmed; skipped.")
                summary["skipped"].append(item["content_id"])
                continue
            record_decision(
                paths=paths, week=week, item=item, decision="approve", registry=registry,
                materials=materials,
            )
            summary["approved"].append(item["content_id"])
            output_fn("approved. Nothing has been posted — publish manually when you choose.")
            continue
        summary["skipped"].append(item["content_id"])
    return summary


def first_pass_approval_rate(paths: RepoPaths, weeks: Iterable[str] | None = None) -> float | None:
    """Share of decisions that were a clean approval (no edits). None when no data."""
    files = sorted(paths.review.glob("decisions-*.yaml"))
    if weeks:
        wanted = set(weeks)
        files = [f for f in files if f.stem.replace("decisions-", "") in wanted]
    total = 0
    clean = 0
    for path in files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for decision in payload.get("decisions") or []:
            total += 1
            if decision.get("decision") == "approve":
                clean += 1
    if total == 0:
        return None
    return round(clean / total, 4)


def editing_minutes_total(paths: RepoPaths, week: str) -> float | None:
    payload = load_decisions(paths, week)
    values = [
        float(d["human_editing_minutes"])
        for d in payload["decisions"]
        if isinstance(d.get("human_editing_minutes"), (int, float))
    ]
    return round(sum(values), 2) if values else None

"""Evidence Keeper write path.

The Evidence Keeper is the *sole* writer of ``claims/registry.json`` (docs/02). This module
is the only code that calls :meth:`Registry.write`, and it refuses to register a
``personal_statement`` claim without Samuel's explicit, interactive approval.

A proposal is data, not a side effect: an agent or the founder can produce
``content/review/<week>-claims-proposal.json`` and it changes nothing until
:func:`apply_proposal` runs.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from .config import Config, RepoPaths
from .errors import ClaimError, GateFailure, SchemaError
from .registry import Registry, apply_operations, validate_claim
from .schemas import validate


def proposal_path(paths: RepoPaths, week: str) -> Path:
    return paths.review / f"{week}-claims-proposal.json"


def _normalise(operations: list[dict[str, Any]], config: Config) -> list[dict[str, Any]]:
    """Fill the documented defaults so a proposal is reviewable as-is."""
    today = _dt.date.today()
    days = int(config.registry.get("default_expiry_days", 180))
    normalised: list[dict[str, Any]] = []
    for op in operations:
        claim = dict(op["claim"])
        if op["op"] != "expire":
            claim.setdefault("verified_by", "samuel")
            claim.setdefault("verified_date", today.isoformat())
            claim.setdefault(
                "expires", (today + _dt.timedelta(days=days)).isoformat()
            )
        normalised.append({"op": op["op"], "claim": claim})
    return normalised


def build_proposal(
    paths: RepoPaths,
    config: Config,
    registry: Registry,
    *,
    week: str,
    rationale: str,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "generated_by": "evidence-keeper",
        "week": week,
        "rationale": rationale,
        "operations": _normalise(operations, config),
    }
    validate(payload, paths, "claims-update")
    # Dry-run the policy (not the write) so a bad proposal never reaches the registry.
    clone = Registry(entries={k: dict(v) for k, v in registry.entries.items()}, source=None)
    apply_operations(clone, payload["operations"], paths=paths, config=config, approved_by_founder=True)
    return payload


def save_proposal(paths: RepoPaths, payload: dict[str, Any], *, suffix: str | None = None) -> Path:
    target = proposal_path(paths, payload["week"])
    if suffix:
        target = target.with_name(f"{payload['week']}-claims-proposal-{suffix}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def load_proposal(path: Path, paths: RepoPaths) -> dict[str, Any]:
    if not path.exists():
        raise GateFailure(f"claims proposal not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError("claims-update", [f"{path.name}: invalid JSON: {exc}"]) from exc
    validate(payload, paths, "claims-update")
    return payload


def requires_founder_approval(payload: dict[str, Any]) -> list[str]:
    return [
        op["claim"]["claim_id"]
        for op in payload["operations"]
        if op["claim"].get("evidence_type") == "personal_statement"
    ]


def apply_proposal(
    paths: RepoPaths,
    config: Config,
    payload: dict[str, Any],
    *,
    approved_by_founder: bool,
) -> dict[str, Any]:
    """Validate, apply and persist the registry. Returns a summary for the log/digest."""
    registry = Registry.load(paths)
    personal = requires_founder_approval(payload)
    if personal and not approved_by_founder:
        raise GateFailure(
            "this proposal registers personal_statement claims ("
            + ", ".join(personal)
            + "). Samuel must approve them explicitly before they become reusable "
            "(docs/01-architecture.md)."
        )
    before = set(registry.entries)
    apply_operations(
        registry,
        payload["operations"],
        paths=paths,
        config=config,
        approved_by_founder=approved_by_founder,
    )
    for entry in registry.entries.values():
        validate_claim(entry, paths)
    written = registry.write(paths.claims, authorized_by="evidence-keeper")
    return {
        "written": str(written),
        "added": sorted(set(registry.entries) - before),
        "total": len(registry.entries),
        "quarantined": sorted(
            claim_id for claim_id, entry in registry.entries.items() if entry.get("quarantined")
        ),
    }


def registry_report(registry: Registry, *, as_of: _dt.date | None = None, soon_days: int = 30) -> list[dict[str, Any]]:
    as_of = as_of or _dt.date.today()
    rows: list[dict[str, Any]] = []
    for claim_id in sorted(registry.entries):
        entry = registry.entries[claim_id]
        state = registry.status(claim_id, as_of)
        expires = entry.get("expires")
        soon = False
        if expires:
            soon = (parse_date_safe(expires) - as_of).days <= soon_days
        rows.append(
            {
                "claim_id": claim_id,
                "state": state,
                "expires": expires,
                "expiring_soon": soon,
                "evidence_type": entry.get("evidence_type"),
                "statement": entry.get("statement"),
            }
        )
    return rows


def parse_date_safe(value: Any) -> _dt.date:
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError:
        return _dt.date.min


def evidence_operations(
    *,
    claim_id: str,
    statement: str,
    evidence_type: str,
    evidence_ref: str,
    expires: str | None,
    op: str = "add",
    founder_approved_date: str | None = None,
    op_note: str | None = None,
    base_claim: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the operations list for a founder-registered claim.

    ``op="expire"`` (quarantine) needs ``base_claim``: the proposal carries the real entry
    plus the quarantine reason, so reviewers can see exactly what was withdrawn.
    """
    if op == "expire":
        if not base_claim:
            raise ClaimError([f"{claim_id}: quarantining needs the existing claim as base_claim"])
        claim = dict(base_claim)
        claim["quarantine_reason"] = op_note or "quarantined by Evidence Keeper"
        today = _dt.date.today().isoformat()
        claim["expires"] = min(str(claim.get("expires") or today), today)
        return [{"op": "expire", "claim": claim}]
    claim: dict[str, Any] = {
        "claim_id": claim_id,
        "statement": statement,
        "evidence_type": evidence_type,
        "evidence_ref": evidence_ref,
        "verified_by": "samuel",
        "verified_date": _dt.date.today().isoformat(),
    }
    if expires:
        claim["expires"] = expires
    if evidence_type == "personal_statement":
        if not founder_approved_date:
            raise ClaimError(
                [f"{claim_id}: personal_statement claims need Samuel's approval date before registration"],
                [claim_id],
            )
        claim["founder_approval"] = {
            "approved_by": "samuel",
            "approved_date": founder_approved_date,
            "note": op_note or "Approved during evidence registration.",
        }
    return [{"op": op, "claim": claim}]

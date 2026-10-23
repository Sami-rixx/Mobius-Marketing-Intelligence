"""The Claims Registry — the truth layer (docs/01-architecture.md).

Rules encoded here:

* Every factual public statement must cite an entry that exists, is unexpired and is not
  quarantined.
* Only the Evidence Keeper writes the registry. :meth:`Registry.write` refuses any other
  caller, so no other agent can quietly mint a fact.
* A ``personal_statement`` claim requires Samuel's recorded approval before it becomes
  reusable (schema-enforced, plus :func:`apply_operations`).
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import Config, RepoPaths, load_config, parse_date
from .errors import ClaimError, ConfigError, SchemaError
from .schemas import validate

VALID_EVIDENCE_TYPES = (
    "repo_commit",
    "ci_run",
    "deployed_url",
    "artifact",
    "screenshot",
    "personal_statement",
)

AUTHORISED_WRITER = "evidence-keeper"


@dataclass
class Registry:
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    version: int = 1
    updated: str | None = None
    source: Path | None = None

    # -- loading -----------------------------------------------------------
    @classmethod
    def load(cls, paths: RepoPaths, *, path: Path | str | None = None) -> "Registry":
        target = Path(path) if path else paths.claims
        if not target.exists():
            raise ClaimError([f"claims registry not found: {target}"])
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ClaimError([f"claims registry is not valid JSON: {target}: {exc}"]) from exc
        try:
            validate(raw, paths, "claims-registry")
        except SchemaError as exc:
            raise ClaimError([f"claims registry failed schema validation: {p}" for p in exc.problems]) from exc

        entries: dict[str, dict[str, Any]] = {}
        for entry in raw["entries"]:
            claim_id = entry["claim_id"]
            if claim_id in entries:
                raise ClaimError([f"duplicate claim_id in registry: {claim_id}"])
            if parse_date(entry["expires"], "expires") < parse_date(entry["verified_date"], "verified_date"):
                raise ClaimError([f"{claim_id}: expires is before verified_date"])
            entries[claim_id] = entry
        return cls(entries=entries, version=raw["version"], updated=raw["updated"], source=target)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated": self.updated,
            "entries": [self.entries[key] for key in sorted(self.entries)],
        }

    # -- queries -----------------------------------------------------------
    def get(self, claim_id: str) -> dict[str, Any] | None:
        return self.entries.get(claim_id)

    def status(self, claim_id: str, as_of: _dt.date | None = None) -> str:
        entry = self.entries.get(claim_id)
        if entry is None:
            return "missing"
        as_of = as_of or _dt.date.today()
        if entry.get("quarantined"):
            return "quarantined"
        try:
            expires = parse_date(entry["expires"])
        except (KeyError, ConfigError):
            return "invalid"
        return "expired" if expires < as_of else "valid"

    def is_valid(self, claim_id: str, as_of: _dt.date | None = None) -> bool:
        return self.status(claim_id, as_of) == "valid"

    def valid_claims(self, as_of: _dt.date | None = None) -> list[dict[str, Any]]:
        return [entry for cid, entry in sorted(self.entries.items()) if self.is_valid(cid, as_of)]

    def require(self, claim_ids: Iterable[str], as_of: _dt.date | None = None) -> None:
        """Raise :class:`ClaimError` unless every claim id is usable."""
        problems: list[str] = []
        bad: list[str] = []
        for claim_id in claim_ids:
            state = self.status(claim_id, as_of)
            if state == "valid":
                continue
            bad.append(claim_id)
            if state == "missing":
                problems.append(f"{claim_id}: not present in claims/registry.json")
            elif state == "expired":
                problems.append(f"{claim_id}: expired on {self.entries[claim_id]['expires']}")
            elif state == "quarantined":
                problems.append(f"{claim_id}: quarantined ({self.entries[claim_id].get('quarantine_reason') or 'no reason recorded'})")
            else:
                problems.append(f"{claim_id}: unusable entry ({state})")
        if problems:
            raise ClaimError(problems, bad)

    def next_claim_id(self) -> str:
        numbers = [int(cid.split("-")[1]) for cid in self.entries if cid.startswith("CLM-")]
        return f"CLM-{(max(numbers) + 1) if numbers else 1:03d}"

    # -- writing (Evidence Keeper only) ------------------------------------
    def write(self, path: Path | None = None, *, authorized_by: str) -> Path:
        if authorized_by != AUTHORISED_WRITER:
            raise ClaimError(
                [
                    "the Claims Registry has exactly one writer: the Evidence Keeper "
                    f"(got {authorized_by!r}). See docs/02-agent-contracts.md."
                ]
            )
        target = path or self.source
        if target is None:
            raise ClaimError(["no target path for registry write"])
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        payload["updated"] = _dt.date.today().isoformat()
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.source = target
        self.updated = payload["updated"]
        return target


def validate_claim(claim: dict[str, Any], paths: RepoPaths) -> None:
    """Validate a single claim by wrapping it in a one-entry registry."""
    validate(
        {"version": 1, "updated": _dt.date.today().isoformat(), "entries": [claim]},
        paths,
        "claims-registry",
    )


def registry_summary(registry: Registry, as_of: _dt.date | None = None) -> str:
    as_of = as_of or _dt.date.today()
    states: dict[str, int] = {}
    for claim_id in registry.entries:
        states[registry.status(claim_id, as_of)] = states.get(registry.status(claim_id, as_of), 0) + 1
    if not registry.entries:
        return "Claims Registry: 0 entries — no fact may be stated publicly yet."
    parts = ", ".join(f"{count} {state}" for state, count in sorted(states.items()))
    return f"Claims Registry: {len(registry.entries)} entries ({parts}) as of {as_of.isoformat()}"


def _default_expiry(verified: _dt.date, config: Config) -> str:
    days = int(config.registry.get("default_expiry_days", 180))
    return (verified + _dt.timedelta(days=days)).isoformat()


def apply_operations(
    registry: Registry,
    operations: list[dict[str, Any]],
    *,
    paths: RepoPaths,
    config: Config,
    approved_by_founder: bool = False,
    as_of: _dt.date | None = None,
) -> Registry:
    """Apply Evidence Keeper operations in memory, with hard policy checks.

    ``approved_by_founder`` must be True when the batch *registers* a new
    ``personal_statement`` claim: those are facts only Samuel can verify, so they require
    his explicit approval at registration time (docs/01, docs/02).
    """
    today = as_of or _dt.date.today()
    for op in operations:
        if op.get("op") not in {"add", "update", "expire"}:
            raise ClaimError([f"unsupported operation {op.get('op')!r}"])
        claim = dict(op.get("claim") or {})
        claim_id = claim.get("claim_id")
        if not claim_id:
            raise ClaimError(["operation missing claim.claim_id"])

        if claim.get("evidence_type") == "personal_statement":
            approval = claim.get("founder_approval") or {}
            if not approved_by_founder or approval.get("approved_by") != "samuel":
                raise ClaimError(
                    [
                        f"{claim_id}: personal_statement claims require Samuel's explicit approval "
                        "before they become reusable (docs/01, docs/02). Re-run with founder approval."
                    ],
                    [claim_id],
                )

        if op["op"] == "expire":
            if claim_id not in registry.entries:
                raise ClaimError([f"{claim_id}: cannot expire a claim that does not exist"])
            entry = dict(registry.entries[claim_id])
            entry["quarantined"] = True
            entry["quarantine_reason"] = claim.get("quarantine_reason") or "quarantined by Evidence Keeper"
            entry["expires"] = min(entry["expires"], today.isoformat())
            registry.entries[claim_id] = entry
            continue

        claim.setdefault("verified_by", "samuel")
        claim.setdefault("verified_date", today.isoformat())
        claim.setdefault("expires", _default_expiry(parse_date(claim["verified_date"]), config))
        validate_claim(claim, paths)

        if op["op"] == "add":
            if claim_id in registry.entries:
                raise ClaimError([f"{claim_id}: already exists; use op=update"], [claim_id])
        else:
            if claim_id not in registry.entries:
                raise ClaimError([f"{claim_id}: cannot update a claim that does not exist"], [claim_id])
        registry.entries[claim_id] = claim
    return registry


def load_registry(paths: RepoPaths, *, path: Path | str | None = None) -> Registry:
    return Registry.load(paths, path=path)


def load_config_and_registry(paths: RepoPaths, registry_path: Path | str | None = None) -> tuple[Config, Registry]:
    config = load_config(root=paths.root)
    return config, load_registry(paths, path=registry_path)

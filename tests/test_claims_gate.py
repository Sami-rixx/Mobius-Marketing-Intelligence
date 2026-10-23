"""The Claims Registry gate — the Proof-of-Work principle, tested.

Includes the permanent planted-false-claim guardrail proof.
"""

from __future__ import annotations

import datetime as _dt
import json

import pytest

from amplify import guardrail
from amplify.errors import ClaimError, SchemaError
from amplify.lint import claims_lint, lint_item
from amplify.registry import apply_operations
from amplify.validate import validate_repo
from tests.conftest import review_item

CLM_101 = review_item(claims=["CLM-101"])
TODAY = _dt.date(2026, 10, 23)


def codes(item, registry, materials):
    return lint_item(item, materials, registry, as_of=TODAY).codes


# ---------------------------------------------------------------- the guardrail proof
def test_planted_false_claim_is_caught(paths):
    result = guardrail.assert_caught(paths, as_of=TODAY)
    assert result["caught"] is True
    assert "UNVERIFIED_CLAIM" in result["codes"]
    assert any("CLM-999" in message for message in result["blocking"])


def test_planted_false_claim_is_schema_valid(paths):
    """The lie is well-formed: only the claims gate can catch it."""
    import yaml

    raw = yaml.safe_load((paths.fixtures / "planted-false-claim.yaml").read_text())
    from amplify.schemas import problems

    assert problems(raw, paths, "content-item") == []


def test_repo_validation_catches_planted_false_claim_when_supplied(paths):
    """This is exactly what Content CI does with any content file in the PR."""
    report = validate_repo(paths, as_of=TODAY, extra_items=[paths.fixtures / "planted-false-claim.yaml"])
    assert not report.ok
    assert any("CLM-999" in error for error in report.errors)


# ---------------------------------------------------------------- claim states
def test_missing_claim_is_rejected(demo_registry, materials):
    item = review_item(claims=["CLM-999"])
    assert "UNVERIFIED_CLAIM" in codes(item, demo_registry, materials)


def test_expired_claim_is_rejected(demo_registry, materials):
    item = review_item(claims=["CLM-102"])
    findings = claims_lint(item, demo_registry, as_of=TODAY)
    assert findings
    assert "expired" in findings[0].message


def test_expiry_boundary_is_respected(demo_registry):
    """`expires` is inclusive: a claim is usable on its expiry date and dead the day after."""
    assert demo_registry.is_valid("CLM-101", _dt.date(2027, 4, 1))
    assert not demo_registry.is_valid("CLM-101", _dt.date(2027, 4, 2))


def test_quarantined_claim_is_rejected(demo_registry, materials):
    item = review_item(claims=["CLM-103"])
    findings = claims_lint(item, demo_registry, as_of=TODAY)
    assert findings and "quarantined" in findings[0].message


def test_valid_evidenced_claim_passes(demo_registry, materials):
    assert "UNVERIFIED_CLAIM" not in codes(CLM_101, demo_registry, materials)


def test_empty_claims_on_reviewable_item_is_rejected(materials, demo_registry):
    item = dict(CLM_101)
    item["claims"] = []
    findings = claims_lint(item, demo_registry, as_of=TODAY)
    assert findings and "no claims cited" in findings[0].message


def test_registry_require_lists_every_problem(demo_registry):
    with pytest.raises(ClaimError) as excinfo:
        demo_registry.require(["CLM-999", "CLM-102", "CLM-103"])
    message = str(excinfo.value)
    assert "not present" in message and "expired" in message and "quarantined" in message


# ---------------------------------------------------------------- single-writer rule
def test_registry_write_requires_the_evidence_keeper(demo_registry, tmp_path):
    with pytest.raises(ClaimError):
        demo_registry.write(tmp_path / "registry.json", authorized_by="producer")
    assert not (tmp_path / "registry.json").exists()


def test_registry_write_by_evidence_keeper_persists(demo_registry, tmp_path):
    target = demo_registry.write(tmp_path / "registry.json", authorized_by="evidence-keeper")
    written = json.loads(target.read_text())
    assert {entry["claim_id"] for entry in written["entries"]} == set(demo_registry.entries)


def test_only_evidence_keeper_module_calls_registry_write():
    """Static check: no other engine module writes the registry."""
    import pathlib

    offenders = []
    for path in (pathlib.Path(__file__).parents[1] / "amplify").glob("*.py"):
        if path.name in {"registry.py", "evidence_keeper.py"}:
            continue
        if ".write(" in path.read_text(encoding="utf-8") and "registry" in path.read_text(encoding="utf-8").lower():
            text = path.read_text(encoding="utf-8")
            if "registry.write(" in text or "registry.write (" in text:
                offenders.append(path.name)
    assert offenders == []


# ---------------------------------------------------------------- personal statements
def personal_claim(claim_id="CLM-777", with_approval=True):
    claim = {
        "claim_id": claim_id,
        "statement": "I study Korean on weekday mornings before build work",
        "evidence_type": "personal_statement",
        "evidence_ref": "founder statement, recorded in review session",
        "verified_by": "samuel",
        "verified_date": "2026-10-20",
        "expires": "2027-04-20",
    }
    if with_approval:
        claim["founder_approval"] = {
            "approved_by": "samuel",
            "approved_date": "2026-10-20",
            "note": "approved in the review session",
        }
    return claim


def test_personal_statement_requires_founder_approval(paths, config, empty_registry):
    operations = [{"op": "add", "claim": personal_claim(with_approval=False)}]
    with pytest.raises((ClaimError, SchemaError)):
        apply_operations(
            empty_registry, operations, paths=paths, config=config, approved_by_founder=True
        )


def test_personal_statement_is_refused_without_founder_flag(paths, config, empty_registry):
    operations = [{"op": "add", "claim": personal_claim(with_approval=True)}]
    with pytest.raises(ClaimError):
        apply_operations(
            empty_registry, operations, paths=paths, config=config, approved_by_founder=False
        )


def test_personal_statement_registers_with_founder_approval(paths, config, empty_registry):
    operations = [{"op": "add", "claim": personal_claim(with_approval=True)}]
    registry = apply_operations(
        empty_registry, operations, paths=paths, config=config, approved_by_founder=True
    )
    assert registry.is_valid("CLM-777", _dt.date(2026, 10, 23))


def test_quarantine_operation_expires_the_claim(paths, config, demo_registry):
    before = dict(demo_registry.entries["CLM-101"])
    operations = [
        {
            "op": "expire",
            "claim": {
                **before,
                "quarantine_reason": "evidence link 404s",
            },
        }
    ]
    registry = apply_operations(
        demo_registry, operations, paths=paths, config=config, approved_by_founder=False
    )
    assert registry.status("CLM-101", _dt.date(2026, 10, 23)) == "quarantined"


def test_duplicate_claim_add_is_refused(paths, config, demo_registry):
    operations = [{"op": "add", "claim": dict(demo_registry.entries["CLM-101"])}]
    with pytest.raises(ClaimError):
        apply_operations(demo_registry, operations, paths=paths, config=config, approved_by_founder=False)

"""The planted false-claim proof (docs/03 "guardrail proof").

A truth layer that has never been seen catching anything is assumed broken. This module runs
the *real* validators against a deliberately fabricated draft that cites claim CLM-999 —
which exists nowhere — and requires the pipeline to reject it.

Used by:
* ``tests/test_claims_gate.py`` (runs in CI on every content/claims PR);
* ``python -m amplify guardrail`` (one command Samuel can run from his phone).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import yaml

from .brand import load_brand
from .config import RepoPaths
from .errors import ClaimError, SchemaError
from .lint import lint_item
from .registry import Registry
from .schemas import validate

PLANTED_ITEM = "planted-false-claim.yaml"
DEMO_REGISTRY = "demo/registry.json"


def load_fixture_registry(paths: RepoPaths, name: str = DEMO_REGISTRY) -> Registry:
    path = paths.fixtures / name
    if not path.exists():
        raise ClaimError([f"fixture registry missing: {path}"])
    return Registry.load(paths, path=path)


def evaluate_planted_false_claim(
    paths: RepoPaths, *, as_of: _dt.date | None = None
) -> dict[str, Any]:
    as_of = as_of or _dt.date.today()
    registry = load_fixture_registry(paths)
    item_path = paths.fixtures / PLANTED_ITEM
    if not item_path.exists():
        raise SchemaError("content-item", [f"planted fixture missing: {item_path}"])
    raw = yaml.safe_load(item_path.read_text(encoding="utf-8"))
    validate(raw, paths, "content-item")  # the lie is well-formed; only the claim is false
    materials = load_brand(paths)
    lint = lint_item(raw, materials, registry, as_of=as_of)
    return {
        "content_id": raw.get("content_id"),
        "claims": raw.get("claims"),
        "blocking": [finding.render() for finding in lint.blocking],
        "codes": lint.codes,
        "caught": "UNVERIFIED_CLAIM" in lint.codes,
    }


def assert_caught(paths: RepoPaths, *, as_of: _dt.date | None = None) -> dict[str, Any]:
    result = evaluate_planted_false_claim(paths, as_of=as_of)
    if not result["caught"]:
        raise AssertionError(
            "GUARDRAIL FAILURE: the planted false claim was NOT rejected. "
            "The truth layer is broken; do not merge."
        )
    return result

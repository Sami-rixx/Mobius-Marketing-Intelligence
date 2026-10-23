"""Rubric maths, the 70 threshold and mandatory rejection reason codes (docs/03)."""

from __future__ import annotations


import pytest

from amplify.lint import LintResult
from amplify.scoring import (
    apply_gates,
    build_qa_item,
    composite,
    heuristic_subscores,
    load_rubric,
    lowest_dimension,
)
from amplify.schemas import problems
from tests.conftest import review_item


@pytest.fixture()
def rubric(paths):
    return load_rubric(paths)


def clean_lint() -> LintResult:
    return LintResult()


def test_weights_sum_to_one_hundred(rubric):
    assert sum(d["weight"] for d in rubric["dimensions"]) == 100
    assert rubric["threshold"] == 70


def test_composite_uses_documented_weights(rubric):
    subscores = {
        "hook_strength": 100,
        "specificity_evidence": 0,
        "clarity": 0,
        "brand_fit": 0,
        "platform_fit": 0,
    }
    assert composite(subscores, rubric) == 25.0


def test_composite_all_hundreds(rubric):
    subscores = {d["id"]: 100 for d in rubric["dimensions"]}
    assert composite(subscores, rubric) == 100.0


def test_exactly_at_threshold_passes(rubric):
    subscores = {
        "hook_strength": 70,
        "specificity_evidence": 70,
        "clarity": 70,
        "brand_fit": 70,
        "platform_fit": 70,
    }
    gate = apply_gates(subscores, clean_lint(), rubric)
    assert gate["composite"] == 70.0
    assert gate["threshold_met"] is True
    assert gate["verdict"] == "pass"
    assert gate["reason_codes"] == []


def test_below_threshold_auto_rejects_with_a_reason_code(rubric):
    subscores = {
        "hook_strength": 60,
        "specificity_evidence": 80,
        "clarity": 60,
        "brand_fit": 60,
        "platform_fit": 60,
    }
    gate = apply_gates(subscores, clean_lint(), rubric)
    assert gate["composite"] < 70
    assert gate["verdict"] == "reject"
    assert gate["reason_codes"], "a rejection without a reason code is invalid output"


def test_low_hook_alone_forces_weak_hook_rejection(rubric):
    subscores = {
        "hook_strength": 20,
        "specificity_evidence": 100,
        "clarity": 100,
        "brand_fit": 100,
        "platform_fit": 100,
    }
    gate = apply_gates(subscores, clean_lint(), rubric)
    assert gate["verdict"] == "reject"
    assert "WEAK_HOOK" in gate["reason_codes"]


@pytest.mark.parametrize(
    "dimension,code",
    [
        ("hook_strength", "WEAK_HOOK"),
        ("specificity_evidence", "TOO_GENERIC"),
        ("brand_fit", "OFF_BRAND"),
        ("platform_fit", "WRONG_AUDIENCE"),
    ],
)
def test_lowest_dimension_maps_to_a_documented_reason_code(dimension, code):
    subscores = {"hook_strength": 90, "specificity_evidence": 90, "clarity": 90, "brand_fit": 90, "platform_fit": 90}
    subscores[dimension] = 10
    assert lowest_dimension(subscores) == dimension
    from amplify.scoring import DIMENSION_REASON

    assert DIMENSION_REASON[dimension] == code


def test_lint_rejection_always_wins_over_a_high_score(rubric, materials, demo_registry):
    item = review_item(script="This product is production-ready. 132 tests at commit 59a5a6d.")
    from amplify.lint import lint_item

    lint = lint_item(item, materials, demo_registry)
    gate = apply_gates({d["id"]: 100 for d in rubric["dimensions"]}, lint, rubric)
    assert gate["verdict"] == "reject"
    assert "OFF_BRAND" in gate["reason_codes"]


def test_heuristic_scoring_is_deterministic(materials, demo_registry):
    from amplify.lint import lint_item

    item = review_item()
    lint = lint_item(item, materials, demo_registry)
    assert heuristic_subscores(item, lint, materials) == heuristic_subscores(item, lint, materials)


def test_qa_report_is_schema_valid(paths, rubric, materials, demo_registry):
    from amplify.lint import lint_item

    item = review_item()
    entry = build_qa_item(item, lint_item(item, materials, demo_registry), rubric, materials)
    report = {"generated_by": "qa-editor", "week": "2026-W43", "threshold": 70, "items": [entry]}
    assert problems(report, paths, "qa-report") == []


def test_rejected_qa_entry_without_reason_codes_is_invalid(paths, rubric, materials, demo_registry):
    from amplify.lint import lint_item

    item = review_item()
    entry = build_qa_item(item, lint_item(item, materials, demo_registry), rubric, materials)
    entry["verdict"] = "reject"
    entry["reason_codes"] = []
    report = {"generated_by": "qa-editor", "week": "2026-W43", "threshold": 70, "items": [entry]}
    assert any("reason_codes" in problem for problem in problems(report, paths, "qa-report"))


def test_repo_validation_rejects_in_review_below_threshold(paths, rubric, tmp_path):
    """The threshold lives in the rubric, not the schema — validate_repo must enforce it."""
    from amplify import content as content_mod
    from amplify.validate import validate_repo

    item = review_item(composite=50.0)
    target = tmp_path / f"{item['content_id']}.yaml"
    target.write_text(content_mod.dump_item(item), encoding="utf-8")
    report = validate_repo(paths, extra_items=[target])
    assert any("auto-reject threshold" in error for error in report.errors)

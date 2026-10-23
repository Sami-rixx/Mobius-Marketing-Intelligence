"""Canned agent outputs satisfy the real schemas and the real lints."""

from __future__ import annotations

import json

import pytest

from amplify.lint import lint_item
from amplify.schemas import problems

WEEK = "2026-W43"


def load(name):
    return json.loads((__import__("pathlib").Path(__file__).parent / "fixtures" / "dryrun" / name).read_text())


def test_research_fixture_is_schema_valid(paths):
    assert problems(load(f"{WEEK}-researcher.json"), paths, "research-notes") == []


def test_plan_fixture_is_schema_valid(paths):
    assert problems(load(f"{WEEK}-strategist.json"), paths, "weekly-plan") == []


@pytest.mark.parametrize("suffix", ["hero", "tt", "ig", "fb", "s1", "s2"])
def test_producer_fixtures_are_schema_valid(paths, suffix):
    assert problems(load(f"{WEEK}-producer-{suffix}.json"), paths, "content-item") == []


def test_plan_only_cites_valid_claims(demo_registry):
    plan = load(f"{WEEK}-strategist.json")
    claim_ids = list(plan["hero"]["claims"])
    for item in plan["supporting"]:
        claim_ids += item["claims"]
    demo_registry.require(claim_ids)


def test_passing_fixtures_really_pass_the_lints(demo_registry, materials):
    for suffix in ("hero", "tt", "ig", "fb", "s1"):
        item = load(f"{WEEK}-producer-{suffix}.json")
        item["week"] = WEEK
        lint = lint_item(item, materials, demo_registry)
        assert lint.ok, (suffix, lint.messages())


def test_generic_fixture_is_rejected_by_the_lints(demo_registry, materials):
    item = load(f"{WEEK}-producer-s2.json")
    item["week"] = WEEK
    lint = lint_item(item, materials, demo_registry)
    assert "TOO_GENERIC" in lint.codes


def test_agent_prompts_keep_the_operational_boundaries():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "agents"
    producer = (root / "producer.md").read_text(encoding="utf-8").lower()
    qa = (root / "qa-editor.md").read_text(encoding="utf-8").lower()
    keeper = (root / "evidence-keeper.md").read_text(encoding="utf-8").lower()
    analyst = (root / "growth-analyst.md").read_text(encoding="utf-8").lower()

    assert "you cannot approve" in producer or "cannot approve" in producer
    assert "never rewrite" in qa
    assert "sole writer" in keeper
    assert "no invented metrics" in analyst or "never estimate" in analyst

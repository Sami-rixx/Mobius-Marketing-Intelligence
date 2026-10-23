"""Agent boundaries are enforced in code, not only in prompts (docs/02).

Producer cannot approve. QA cannot rewrite. Evidence Keeper cannot register a personal
statement without Samuel. Growth Analyst cannot invent a number.
"""

from __future__ import annotations

import copy
import json

import pytest

from amplify import agents
from amplify.client import Completion
from amplify.errors import StopCondition

WEEK = "2026-W43"


class FakeClient:
    mode = "live"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete_json(self, **kwargs):
        self.calls += 1
        return Completion(payload=copy.deepcopy(self.payload), prompt_tokens=1, completion_tokens=1, model="fake", mode="live")


def hero_fixture(paths):
    return json.loads((paths.fixtures / "dryrun" / f"{WEEK}-producer-hero.json").read_text())


def plan_fixture(paths):
    return json.loads((paths.fixtures / "dryrun" / f"{WEEK}-strategist.json").read_text())


def produce(paths, config, demo_registry, materials, payload):
    client = FakeClient(payload)
    with pytest.raises(StopCondition) as excinfo:
        agents.run_producer(
            client=client,
            config=config,
            paths=paths,
            week=WEEK,
            plan={"theme": "phone-to-product"},
            plan_item={
                "format": "FMT-01",
                "working_title": "t",
                "angle": "a sufficiently long angle for the assignment",
                "claims": ["CLM-101"],
            },
            expected_content_id=f"{WEEK}-FMT01-HERO",
            platforms=["youtube"],
            registry=demo_registry,
            materials=materials,
            deriv_of=None,
        )
    return client, excinfo


def test_producer_may_not_return_an_approved_item(paths, config, demo_registry, materials):
    payload = hero_fixture(paths)
    payload["status"] = "approved"
    payload["scores"] = {
        "hook_strength": 90, "specificity_evidence": 90, "clarity": 90,
        "brand_fit": 90, "platform_fit": 90, "composite": 90,
    }
    client, excinfo = produce(paths, config, demo_registry, materials, payload)
    assert client.calls == config.budgets.max_retries_per_task + 1
    assert "status 'draft'" in str(excinfo.value)


def test_producer_cannot_approve_even_with_a_schema_valid_payload(paths, config, demo_registry, materials):
    """Defence in depth: the schema rejects approved-without-scores, the agent check rejects
    approved-with-scores. Either way the Producer cannot approve."""
    payload = hero_fixture(paths)
    payload["status"] = "approved"
    _, excinfo = produce(paths, config, demo_registry, materials, payload)
    assert "scores" in str(excinfo.value)


def test_producer_may_not_change_the_content_id(paths, config, demo_registry, materials):
    payload = hero_fixture(paths)
    payload["content_id"] = f"{WEEK}-FMT02-OTHER"
    _, excinfo = produce(paths, config, demo_registry, materials, payload)
    assert "expected" in str(excinfo.value)


def test_producer_may_not_cite_unknown_claims(paths, config, demo_registry, materials):
    payload = hero_fixture(paths)
    payload["claims"] = ["CLM-999"]
    _, excinfo = produce(paths, config, demo_registry, materials, payload)
    assert "CLM-999" in str(excinfo.value)


def test_producer_may_not_write_a_derivative_for_a_hero_assignment(paths, config, demo_registry, materials):
    payload = hero_fixture(paths)
    payload["deriv_of"] = f"{WEEK}-FMT01-HERO"
    _, excinfo = produce(paths, config, demo_registry, materials, payload)
    assert "deriv_of" in str(excinfo.value)


def test_strategist_may_not_cite_expired_claims(paths, config):
    from amplify.registry import Registry

    plan = plan_fixture(paths)
    plan["hero"]["claims"] = ["CLM-102"]
    registry = Registry.load(paths, path=paths.fixtures / "demo" / "registry.json")
    with pytest.raises(StopCondition) as excinfo:
        agents.run_strategist(
            client=FakeClient(plan),
            config=config,
            paths=paths,
            week=WEEK,
            research={"week": WEEK, "findings": [{"finding": "x", "source": "y"}]},
            registry=registry,
        )
    assert "unusable claims" in str(excinfo.value)
    assert "expired" in str(excinfo.value)


def test_strategist_stops_without_research(config, paths, demo_registry):
    with pytest.raises(StopCondition):
        agents.run_strategist(
            client=FakeClient(plan_fixture(paths)),
            config=config,
            paths=paths,
            week=WEEK,
            research={"week": WEEK, "findings": []},
            registry=demo_registry,
        )


def test_evidence_keeper_cannot_self_approve_a_personal_statement(paths, config, demo_registry):
    proposal = {
        "generated_by": "evidence-keeper",
        "week": WEEK,
        "rationale": "The founder told me something only he can verify, and I want to register it.",
        "operations": [
            {
                "op": "add",
                "claim": {
                    "claim_id": "CLM-801",
                    "statement": "I study Korean on weekday mornings before build work",
                    "evidence_type": "personal_statement",
                    "evidence_ref": "founder statement",
                    "verified_by": "samuel",
                    "verified_date": "2026-10-20",
                    "expires": "2027-04-20",
                },
            }
        ],
    }
    with pytest.raises(StopCondition) as excinfo:
        agents.run_evidence_keeper(
            client=FakeClient(proposal),
            config=config,
            paths=paths,
            week=WEEK,
            registry=demo_registry,
            evidence_index={"links": []},
        )
    assert "founder" in str(excinfo.value).lower()


def test_qa_report_has_no_rewrite_channel(paths):
    from amplify.schemas import problems

    entry = {
        "content_id": f"{WEEK}-FMT01-HERO",
        "verdict": "pass",
        "reason_codes": [],
        "subscores": {
            "hook_strength": 90, "specificity_evidence": 90, "clarity": 90,
            "brand_fit": 90, "platform_fit": 90,
        },
        "composite": 90,
        "lint": {"claims": [], "brand": [], "voice": []},
        "edit_suggestions": [],
        "notes": None,
        "rewritten_script": "QA silently improved the draft",
    }
    report = {"generated_by": "qa-editor", "week": WEEK, "threshold": 70, "items": [entry]}
    assert any("rewritten_script" in problem for problem in problems(report, paths, "qa-report"))


def test_qa_reject_without_reason_code_is_invalid_output(paths):
    from amplify.schemas import problems

    entry = {
        "content_id": f"{WEEK}-FMT01-HERO",
        "verdict": "reject",
        "reason_codes": [],
        "subscores": {
            "hook_strength": 50, "specificity_evidence": 50, "clarity": 50,
            "brand_fit": 50, "platform_fit": 50,
        },
        "composite": 50,
        "lint": {"claims": [], "brand": [], "voice": []},
        "edit_suggestions": [],
        "notes": None,
    }
    report = {"generated_by": "qa-editor", "week": WEEK, "threshold": 70, "items": [entry]}
    assert any("reason_codes" in problem for problem in problems(report, paths, "qa-report"))


def test_run_weekly_refuses_a_fixture_registry_for_live_clients(paths, config):
    from amplify.cycle import run_weekly

    class Live:
        mode = "live"

        def complete_json(self, **kwargs):  # pragma: no cover
            raise AssertionError("must not be called")

    with pytest.raises(StopCondition):
        run_weekly(
            paths=paths,
            config=config,
            client=Live(),
            week=WEEK,
            registry_path=paths.fixtures / "demo" / "registry.json",
        )

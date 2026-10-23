"""GitHub Actions workflows: syntactically valid, visible failures, no secret leakage,
and structurally incapable of publishing content (docs/06)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
FILES = sorted(WORKFLOWS.glob("*.yml"))


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_workflows_exist():
    names = {path.name for path in FILES}
    assert {"tests.yml", "content-ci.yml", "weekly.yml", "analytics.yml"} <= names


def triggers(data: dict) -> dict:
    """PyYAML parses the bare key `on:` as boolean True (YAML 1.1); accept both."""
    return data.get("on") or data.get(True) or {}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_workflow_is_valid_yaml_with_triggers_and_jobs(path):
    data = load(path)
    assert isinstance(data, dict)
    assert triggers(data), "missing trigger"
    jobs = data.get("jobs")
    assert isinstance(jobs, dict) and jobs, "workflow has no jobs"
    for job in jobs.values():
        assert "runs-on" in job
        steps = job.get("steps")
        assert isinstance(steps, list) and steps, "job has no steps"
        assert all("uses" in step or "run" in step for step in steps)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_step_is_allowed_to_fail_silently(path):
    text = path.read_text(encoding="utf-8")
    assert "continue-on-error: true" not in text
    for job in load(path)["jobs"].values():
        assert job.get("continue-on-error") is not True
        for step in job["steps"]:
            assert step.get("continue-on-error") is not True


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_workflows_do_not_embed_secrets(path):
    text = path.read_text(encoding="utf-8")
    # Only secret *references* are allowed, never literal credentials.
    assert not re.search(r"(?i)(api[_-]?key|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{12,}", text)
    assert "MISTRAL_API_KEY" not in text or "secrets.MISTRAL_API_KEY" in text


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_workflows_cannot_publish_or_deploy(path):
    """Check executable steps, not prose: no workflow may publish, push or deploy."""
    forbidden = ("git push", "gh pr create", "gh release", "deploy ", "twine upload", "docker push")
    for job in load(path)["jobs"].values():
        for step in job["steps"]:
            command = str(step.get("run", "")).lower()
            for term in forbidden:
                assert term not in command, f"{path.name} step runs {term!r}"
        permissions = job.get("permissions")
        assert permissions in (None, {}, {"contents": "read"})


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_workflow_permissions_are_read_only(path):
    data = load(path)
    if "permissions" in data:
        assert data["permissions"] == {"contents": "read"}


def test_tests_workflow_runs_the_guardrail_and_the_suite():
    text = (WORKFLOWS / "tests.yml").read_text(encoding="utf-8")
    assert "pytest" in text
    assert "amplify guardrail" in text
    assert "amplify validate" in text


def test_content_ci_proves_the_planted_claim_is_rejected():
    text = (WORKFLOWS / "content-ci.yml").read_text(encoding="utf-8")
    assert "planted-false-claim.yaml" in text
    assert "test_claims_gate.py" in text
    assert "content/**" in text and "claims/**" in text


def test_weekly_workflow_is_safe_by_default():
    data = load(WORKFLOWS / "weekly.yml")
    job = data["jobs"]["cycle"]
    assert "ENGINE_SCHEDULE_ENABLED" in job["if"]
    assert "workflow_dispatch" in job["if"]
    cron = triggers(data)["schedule"]
    assert cron == [{"cron": "0 3 * * 4"}], "Thursday 06:00 EAT is 03:00 UTC"
    text = (WORKFLOWS / "weekly.yml").read_text(encoding="utf-8")
    assert "--dry-run" in text and "--live" in text
    assert "permissions:\n  contents: read" in text


def test_analytics_workflow_requires_real_pasted_stats():
    data = load(WORKFLOWS / "analytics.yml")
    assert triggers(data).keys() == {"workflow_dispatch"}
    text = (WORKFLOWS / "analytics.yml").read_text(encoding="utf-8")
    assert "does not invent metrics" in text
    assert "analytics/raw/${week}.yaml" in text


def test_weekly_workflow_fails_when_live_is_requested_without_a_key():
    text = (WORKFLOWS / "weekly.yml").read_text(encoding="utf-8")
    assert "live cycle requested but MISTRAL_API_KEY secret is not set" in text


def test_gitignore_protects_runtime_state_and_secrets():
    ignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    for entry in (".env", "analytics/marketing.sqlite", "__pycache__", "content/dry-run/"):
        assert entry in ignore

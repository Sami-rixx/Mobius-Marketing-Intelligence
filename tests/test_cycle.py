"""The weekly cycle end to end, with fixtures only (zero API cost).

Proves: gates run, failures are visible and DEGRADED, drafts are not overwritten, budgets are
enforced, and the cycle can never approve or publish anything.
"""

from __future__ import annotations

import datetime as _dt
import json

import pytest

from amplify.client import DryRunClient
from amplify.cycle import run_weekly
from amplify.errors import StopCondition
from tests.conftest import ROOT, temp_repo

WEEK = "2026-W43"
NOW = _dt.datetime(2026, 10, 22, 3, 0, tzinfo=_dt.timezone.utc)


@pytest.fixture()
def sandbox(tmp_path, paths):
    root = temp_repo(tmp_path, paths)
    return {"paths": root, "registry": paths.fixtures / "demo" / "registry.json"}


def dry_client(paths, config, *, fixtures=None):
    return DryRunClient(
        fixtures or (paths.fixtures / "dryrun"),
        config=config,
        usage_path=paths.usage_log,
    )


def run(paths, config, sandbox, *, fixtures=None, client=None):
    root = sandbox["paths"]
    return run_weekly(
        paths=root,
        config=config,
        client=client or dry_client(root, config, fixtures=fixtures),
        week=WEEK,
        now=NOW,
        registry_path=sandbox["registry"],
        drafts_dir=root.drafts,
    )


def test_dry_run_completes_and_scores_every_item(paths, config, sandbox):
    result = run(paths, config, sandbox)
    assert result.degraded is False, [f.reason for f in result.failures]
    statuses = {item["content_id"]: item["status"] for item in result.items}
    assert statuses["2026-W43-FMT01-HERO"] == "in_review"
    assert statuses["2026-W43-FMT01-HERO-TT"] == "in_review"
    assert statuses["2026-W43-FMT03-S2"] == "rejected", "the generic draft must be rejected"
    for item in result.items:
        if item["status"] in {"in_review", "rejected"}:
            assert item["scores"]["composite"] > 0
    assert result.exit_code == 0, "a QA rejection is normal operation, not a degraded cycle"


def test_cycle_never_approves_or_publishes(paths, config, sandbox):
    result = run(paths, config, sandbox)
    for item in result.items:
        assert item["status"] not in {"approved", "published"}
        assert item["published_urls"] == {}


def test_digest_and_issue_text_are_written(paths, config, sandbox):
    result = run(paths, config, sandbox)
    digest = result.digest_path.read_text(encoding="utf-8")
    assert "review digest — OK" in digest
    assert "Nothing in this repo posts" in digest
    assert "TOO_GENERIC" in digest
    assert result.issue_path is None


def test_missing_fixture_produces_a_visible_degraded_week(paths, config, sandbox, tmp_path):
    empty = tmp_path / "empty-fixtures"
    empty.mkdir()
    result = run(paths, config, sandbox, fixtures=empty)
    assert result.degraded is True
    assert result.exit_code == 1
    assert result.failures and result.failures[0].step == "researcher"
    assert "DEGRADED" in result.digest_path.read_text(encoding="utf-8")
    assert result.issue_path is not None
    assert "is DEGRADED" in result.issue_path.read_text(encoding="utf-8")
    steps = {failure.step for failure in result.failures}
    assert {"researcher", "strategist", "producer", "qa-editor"} <= steps


def test_existing_drafts_are_preserved_on_rerun(paths, config, sandbox):
    first = run(paths, config, sandbox)
    hero_path = sandbox["paths"].drafts / "2026-W43-FMT01-HERO.yaml"
    original = hero_path.read_text(encoding="utf-8")
    mtime = hero_path.stat().st_mtime_ns
    second = run(paths, config, sandbox)
    assert hero_path.read_text(encoding="utf-8") == original
    assert hero_path.stat().st_mtime_ns == mtime
    assert len(first.items) == len(second.items)


def test_live_cycle_refuses_when_budget_is_exhausted(paths, config, sandbox):
    class LiveishClient:
        mode = "live"

        def complete_json(self, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("no API call may happen when the budget is exhausted")

    root = sandbox["paths"]
    month = NOW.strftime("%Y-%m")
    root.usage_log.write_text(
        json.dumps(
            {
                "ts": f"{month}-01T00:00:00+00:00",
                "mode": "live",
                "total_tokens": config.budgets.monthly_max_tokens + 1,
                "cost_estimate_usd": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_weekly(
        paths=root,
        config=config,
        client=LiveishClient(),
        week=WEEK,
        now=NOW,
        registry_path=None,
        drafts_dir=root.drafts,
    )
    assert result.degraded is True
    assert any("budget" in failure.reason.lower() for failure in result.failures)
    assert result.items == []


def test_fixture_registry_is_refused_for_live_cycles(paths, config, sandbox):
    class LiveishClient:
        mode = "live"

        def complete_json(self, **kwargs):  # pragma: no cover
            raise AssertionError("must not be called")

    with pytest.raises(StopCondition):
        run_weekly(
            paths=sandbox["paths"],
            config=config,
            client=LiveishClient(),
            week=WEEK,
            now=NOW,
            registry_path=sandbox["registry"],
            drafts_dir=sandbox["paths"].drafts,
        )


def test_dry_run_costs_nothing_but_is_still_logged(paths, config, sandbox):
    run(paths, config, sandbox)
    records = [
        json.loads(line)
        for line in sandbox["paths"].usage_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records, "dry-run usage should still be logged for traceability"
    assert all(record["mode"] == "dry_run" for record in records)
    assert all(record["total_tokens"] == 0 for record in records)
    assert all(record["cost_estimate_usd"] == 0.0 for record in records)


def test_agent_prompts_are_real_files():
    for name in (
        "researcher.md",
        "strategist.md",
        "evidence-keeper.md",
        "producer.md",
        "qa-editor.md",
        "growth-analyst.md",
    ):
        text = (ROOT / "agents" / name).read_text(encoding="utf-8")
        assert "Hard limits" in text or "Stop-condition" in text

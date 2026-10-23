"""Analytics: no invented metrics, guarded scores.json, honest decision rule (docs/05)."""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3

import pytest
import yaml

from amplify import content as content_mod
from amplify.errors import GateFailure, StopCondition
from amplify.ingest import (
    STANDARD_METRICS,
    classify_hook,
    decide_themes,
    ingest_week,
    write_scores,
)
from amplify.review import record_decision
from tests.conftest import review_item, temp_repo

WEEK = "2026-W43"
NOW = _dt.datetime(2026, 10, 26, 21, 0, tzinfo=_dt.timezone.utc)


def published_item(content_id: str, *, theme="phone-to-product", hook=None, audience=None):
    item = review_item(content_id=content_id)
    item["status"] = "published"
    item["published_urls"] = {"tiktok": "https://example.org/post/1"}
    item["theme"] = theme
    if hook:
        item["hook"] = hook
    if audience:
        item["audience"] = audience
    return item


@pytest.fixture()
def repo(tmp_path, paths):
    root = temp_repo(tmp_path, paths)
    items = [
        published_item("2026-W43-FMT01-HERO", theme="phone-to-product"),
        published_item("2026-W43-FMT01-HERO-TT", theme="phone-to-product", hook="132 tests failed. Watch the fix."),
        published_item("2026-W43-FMT02-S1", theme="verification-files", hook="An import is not a workflow run."),
    ]
    for item in items:
        (root.drafts / f"{item['content_id']}.yaml").write_text(content_mod.dump_item(item), encoding="utf-8")
    raw = {
        "week": WEEK,
        "source": "fixture: platform export copied by hand",
        "items": [
            {"content_id": "2026-W43-FMT01-HERO", "platform": "tiktok", "metrics": {"views": 1200, "likes": 40, "comments": 5}},
            {"content_id": "2026-W43-FMT01-HERO-TT", "platform": "tiktok", "metrics": {"views": 800, "likes": 10}},
            {"content_id": "2026-W43-FMT02-S1", "platform": "tiktok", "metrics": {"views": 400}},
        ],
        "human_editing_minutes": 45,
        "workflow_runs": 4,
        "workflow_failures": 1,
        "qualified_inquiries_blueprint": 0,
    }
    (root.raw_stats / f"{WEEK}.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    decisions = {
        "week": WEEK,
        "decisions": [
            {
                "content_id": item["content_id"],
                "decision": "approve",
                "decided_by": "samuel",
                "decided_at": "2026-10-23T09:00:00+00:00",
                "reason_code": None,
                "note": None,
                "human_editing_minutes": 15.0,
            }
            for item in items
        ],
    }
    (root.review / f"decisions-{WEEK}.yaml").write_text(yaml.safe_dump(decisions), encoding="utf-8")
    return {"paths": root, "raw": raw}


def ingest(repo, config):
    return ingest_week(paths=repo["paths"], config=config, week=WEEK, now=NOW)


def test_supplied_metrics_are_stored_and_others_stay_unknown(repo, config):
    update = ingest(repo, config)
    connection = sqlite3.connect(repo["paths"].sqlite)
    try:
        rows = dict(
            connection.execute(
                "SELECT metric, value FROM performance WHERE content_id=? AND platform='tiktok'",
                ("2026-W43-FMT01-HERO",),
            ).fetchall()
        )
    finally:
        connection.close()
    assert rows["views"] == 1200
    assert rows["likes"] == 40
    assert rows["saves"] is None, "unsupplied metrics are unknown, never estimated"
    assert "2026-W43-FMT01-HERO:tiktok/saves" in update["unknowns"]
    stored_metrics = {metric for metric in rows}
    assert stored_metrics == set(STANDARD_METRICS) | {"saves"}


def test_no_metric_is_invented_anywhere(repo, config):
    update = ingest(repo, config)
    assert all(value is None or value >= 0 for row in update["rows"] for value in row["metrics"].values())
    for row in update["rows"]:
        for value in row["metrics"].values():
            assert value is None or isinstance(value, (int, float))
    # cost is unknown because no prices are configured
    assert update["memo"]["guardrail_metrics"]["api_cost_per_run_usd"] is None
    assert update["memo"]["guardrail_metrics"]["cost_per_usable_item_usd"] is None


def test_guardrail_metrics_use_supplied_values(repo, config):
    update = ingest(repo, config)
    guardrails = update["memo"]["guardrail_metrics"]
    assert guardrails["workflow_failure_rate"] == 0.25
    assert guardrails["qualified_inquiries_blueprint"] == 0
    assert guardrails["human_editing_minutes_per_item"] == 15.0
    assert guardrails["first_pass_approval_rate"] == 1.0
    assert guardrails["reach_per_published_item"] == 800.0  # mean of supplied views
    assert guardrails["engagement_per_published_item"] == 27.5


def test_scores_json_is_written_only_by_the_growth_analyst(repo):
    with pytest.raises(GateFailure):
        write_scores(repo["paths"], {"version": 1}, authorized_by="producer")
    path = write_scores(repo["paths"], {"version": 1}, authorized_by="growth-analyst")
    assert json.loads(path.read_text())["version"] == 1


def test_scores_json_contains_real_rollups(repo, config):
    ingest(repo, config)
    scores = json.loads(repo["paths"].scores.read_text())
    themes = {row["key"]: row for row in scores["themes"]}
    assert themes["phone-to-product"]["score"] == 1000.0  # mean(1200, 800)
    assert themes["phone-to-product"]["samples"] == 2
    assert themes["verification-files"]["score"] == 400.0
    assert scores["decision_rule"]["format"].startswith("never killed")


def test_memo_is_grounded_in_supplied_numbers(repo, config):
    update = ingest(repo, config)
    text = update["memo"]["text"]
    assert "1000" in text and "400" in text
    assert "unknown" in text.lower()
    assert update["memo"]["question"] == "What should we do more of — with evidence?"


def test_invented_number_in_a_memo_is_rejected():
    from amplify.agents import check_memo_grounding

    update = {
        "generated_by": "growth-analyst",
        "week": WEEK,
        "rows": [{"content_id": "x", "platform": "tiktok", "metrics": {"views": 400}}],
        "unknowns": [],
        "aggregates": {"themes": [{"key": "t", "score": 400, "samples": 1, "cycles": 1}], "formats": [], "hooks": []},
        "memo": {
            "question": "What should we do more of — with evidence?",
            "text": "Views grew to 9999 this week.",
            "guardrail_metrics": {},
            "decisions": [],
        },
    }
    with pytest.raises(StopCondition) as excinfo:
        check_memo_grounding(update)
    assert "9999" in str(excinfo.value)


def test_ingest_refuses_unknown_content_ids(repo, config):
    raw = dict(repo["raw"])
    raw["items"] = [{"content_id": "2026-W43-FMT99-GHOST", "platform": "tiktok", "metrics": {"views": 1}}]
    repo["paths"].raw_stats.joinpath(f"{WEEK}.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(GateFailure):
        ingest(repo, config)


def test_ingest_refuses_without_pasted_stats(tmp_path, paths, config):
    root = temp_repo(tmp_path, paths)
    with pytest.raises(GateFailure) as excinfo:
        ingest_week(paths=root, config=config, week=WEEK, now=NOW)
    assert "will not invent them" in str(excinfo.value)


def test_decision_rule_continues_above_median_and_cuts_below():
    themes = [
        {"key": "strong", "score": 1000.0, "samples": 3, "cycles": 3},
        {"key": "weak", "score": 100.0, "samples": 3, "cycles": 3},
        {"key": "thin", "score": None, "samples": 0, "cycles": 1},
    ]
    decisions = {d["theme"]: d["action"] for d in decide_themes(themes)}
    assert decisions["strong"] == "continue_for_3_cycles"
    assert decisions["weak"] == "cut"
    assert decisions["thin"] == "insufficient_data"


def test_decision_rule_never_kills_a_format(repo, config):
    update = ingest(repo, config)
    decided_keys = {decision["theme"] for decision in update["memo"]["decisions"]}
    assert all("FMT" not in key for key in decided_keys)


@pytest.mark.parametrize(
    "hook,family",
    [
        ("132 tests failed. Watch the fix.", "receipt-first"),
        ("Why does the timetable break every term?", "question"),
        ("I built this on a 4G phone.", "personal-story"),
        ("Three receipts from one week.", "receipt-first"),
    ],
)
def test_hook_families_are_deterministic(hook, family):
    assert classify_hook(hook) == family


def test_first_pass_approval_rate_reflects_zero_edits(repo, materials, demo_registry):
    item = review_item()
    path = repo["paths"].drafts / f"{item['content_id']}.yaml"
    path.write_text(content_mod.dump_item(item))
    loaded = content_mod.load_item(path, repo["paths"])
    record_decision(
        paths=repo["paths"], week=WEEK, item=loaded, decision="approve",
        registry=demo_registry, materials=materials,
    )
    update_guess = 1.0
    from amplify.review import first_pass_approval_rate

    assert first_pass_approval_rate(repo["paths"]) == update_guess

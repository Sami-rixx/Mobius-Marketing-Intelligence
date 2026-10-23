"""Budgets, weeks and config honesty come from config.yaml, never hardcoded (docs/06)."""

from __future__ import annotations

import datetime as _dt

import pytest

from amplify.config import (
    Budgets,
    ConfigError,
    current_week,
    load_config,
    parse_week,
    week_from_date,
    week_start,
)
from amplify.usage import assert_budget_available, estimate_cost, usage_record


def test_real_config_has_documented_budgets(config):
    assert config.budgets.monthly_max_tokens == 2_000_000
    assert config.budgets.per_item_max_tokens == 8_000
    assert config.budgets.max_retries_per_task == 2
    assert config.models["default"] == "mistral-medium-3.5"


def test_qa_editor_uses_the_documented_qa_judge_model(config):
    assert config.model_for("qa-editor") == config.models["qa_judge"]
    assert config.model_for("producer") == config.models["default"]


def test_pricing_is_empty_so_cost_is_never_invented(config):
    assert config.pricing == {}
    assert estimate_cost("mistral-medium-3.5", 1000, 500, config.pricing) is None


def test_cost_is_computed_only_from_configured_prices():
    pricing = {"m": {"input_per_mtok_usd": 1.0, "output_per_mtok_usd": 2.0}}
    assert estimate_cost("m", 1_000_000, 500_000, pricing) == 2.0
    assert estimate_cost("unknown-model", 1000, 1000, pricing) is None


def test_missing_budget_key_fails_loudly(tmp_path, paths):
    config = (paths.config_file).read_text(encoding="utf-8")
    broken = tmp_path / "config.yaml"
    kept = [
        line for line in config.splitlines(keepends=True)
        if "max_retries_per_task" not in line
    ]
    broken.write_text("".join(kept), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(broken)


def test_negative_retries_are_refused():
    with pytest.raises(ConfigError):
        Budgets(monthly_max_tokens=1, per_item_max_tokens=1, max_retries_per_task=-1)


@pytest.mark.parametrize("week", ["2026-W43", "2025-W01", "2026-W53"])
def test_valid_week_parsing(week):
    year, number = parse_week(week)
    assert year >= 2025 and 1 <= number <= 53


@pytest.mark.parametrize("week", ["2026-43", "2026-W99", "W43", "", None])
def test_invalid_week_is_rejected(week):
    with pytest.raises(ConfigError):
        parse_week(week)


def test_week_arithmetic():
    assert week_from_date(_dt.date(2026, 10, 22)) == "2026-W43"
    assert week_start("2026-W43") == _dt.date(2026, 10, 19)
    assert current_week(_dt.date(2026, 10, 22)) == "2026-W43"


def test_budget_exhaustion_is_detected(tmp_path):
    path = tmp_path / "usage.jsonl"
    budgets = Budgets(monthly_max_tokens=10, per_item_max_tokens=5, max_retries_per_task=2)
    path.write_text(
        __import__("json").dumps(
            usage_record(
                mode="live", week="2026-W43", task_id="t", agent="producer", model="m",
                prompt_tokens=6, completion_tokens=6, cost_estimate_usd=None,
                now=_dt.datetime(2026, 10, 2, tzinfo=_dt.timezone.utc),
            )
        )
        + "\n"
    )
    with pytest.raises(Exception) as excinfo:
        assert_budget_available(path, budgets, today=_dt.date(2026, 10, 22))
    assert "budget" in str(excinfo.value).lower()


def test_dry_run_tokens_do_not_consume_the_budget(tmp_path):
    path = tmp_path / "usage.jsonl"
    budgets = Budgets(monthly_max_tokens=10, per_item_max_tokens=5, max_retries_per_task=2)
    path.write_text(
        __import__("json").dumps(
            usage_record(
                mode="dry_run", week="2026-W43", task_id="t", agent="producer", model="dry-run",
                prompt_tokens=0, completion_tokens=0, cost_estimate_usd=0.0,
                now=_dt.datetime(2026, 10, 2, tzinfo=_dt.timezone.utc),
            )
        )
        + "\n"
    )
    assert assert_budget_available(path, budgets, today=_dt.date(2026, 10, 22)) == 0

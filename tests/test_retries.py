"""Capped retries, failure logging and no endless loops (docs/06 failure policy)."""

from __future__ import annotations

import dataclasses

import pytest

from amplify import agents
from amplify.config import Budgets
from amplify.errors import PermanentError, StopCondition, TransientError


def valid_research(week: str = "2026-W43") -> dict:
    return {
        "generated_by": "researcher",
        "week": week,
        "brief": "A standing brief for the test",
        "findings": [
            {
                "finding": "A sourced finding used by the retry tests",
                "source": "https://example.org/source",
                "confidence": "medium",
                "verified": False,
                "suggested_use": "Use it in a plan",
            }
        ],
        "gaps": [],
    }


class ScriptedClient:
    """Returns/raises a scripted sequence, and records every call."""

    mode = "live"

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def complete_json(self, **kwargs):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        from amplify.client import Completion

        return Completion(payload=item, prompt_tokens=10, completion_tokens=5, model="fake", mode="live")


def with_retries(config, retries: int):
    return dataclasses.replace(
        config,
        budgets=Budgets(
            monthly_max_tokens=config.budgets.monthly_max_tokens,
            per_item_max_tokens=config.budgets.per_item_max_tokens,
            max_retries_per_task=retries,
        ),
    )


def run(client, config, paths):
    return agents.run_task(
        agent="researcher",
        task_id="2026-W43-researcher",
        week="2026-W43",
        inputs={"week": "2026-W43"},
        client=client,
        config=config,
        paths=paths,
    )


def test_transient_failure_is_retried_then_succeeds(config, paths):
    client = ScriptedClient([TransientError("503"), valid_research()])
    result = run(client, with_retries(config, 2), paths)
    assert result.attempts == 2
    assert client.calls == 2


def test_retries_stop_at_the_configured_limit(config, paths):
    client = ScriptedClient([TransientError("503")] * 10)
    with pytest.raises(StopCondition) as excinfo:
        run(client, with_retries(config, 2), paths)
    assert client.calls == 3, "max_retries_per_task=2 means 3 attempts total"
    assert "failed after 3 attempts" in str(excinfo.value)


def test_zero_retries_means_one_attempt(config, paths):
    client = ScriptedClient([TransientError("timeout")] * 5)
    with pytest.raises(StopCondition):
        run(client, with_retries(config, 0), paths)
    assert client.calls == 1


def test_permanent_failure_is_not_retried(config, paths):
    client = ScriptedClient([PermanentError("401"), valid_research()])
    with pytest.raises(StopCondition) as excinfo:
        run(client, with_retries(config, 2), paths)
    assert client.calls == 1
    assert "non-retriable" in str(excinfo.value)


def test_schema_invalid_output_is_retried_then_fails_visibly(config, paths):
    broken = valid_research()
    del broken["findings"]
    client = ScriptedClient([broken, broken, broken, valid_research()])
    with pytest.raises(StopCondition) as excinfo:
        run(client, with_retries(config, 2), paths)
    assert client.calls == 3
    assert "schema" in str(excinfo.value).lower() or "findings" in str(excinfo.value)


def test_check_failure_is_treated_as_a_failed_attempt(config, paths):
    calls = {"n": 0}

    def check(_payload):
        calls["n"] += 1
        raise StopCondition("researcher", "domain check refused")

    client = ScriptedClient([valid_research()] * 3)
    with pytest.raises(StopCondition) as excinfo:
        agents.run_task(
            agent="researcher",
            task_id="2026-W43-researcher",
            week="2026-W43",
            inputs={},
            client=client,
            config=with_retries(config, 2),
            paths=paths,
            check=check,
        )
    assert client.calls == 3
    assert calls["n"] == 3
    assert "domain check refused" in str(excinfo.value)


def test_failure_reason_lists_every_attempt(config, paths):
    client = ScriptedClient([TransientError("first"), TransientError("second"), TransientError("third")])
    with pytest.raises(StopCondition) as excinfo:
        run(client, with_retries(config, 2), paths)
    message = str(excinfo.value)
    assert "attempt 1" in message and "attempt 2" in message and "attempt 3" in message

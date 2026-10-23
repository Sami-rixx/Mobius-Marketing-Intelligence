"""Token usage, budgets and cost honesty (docs/06-limits.md).

* Every API call appends one JSON line to ``analytics/usage.jsonl``.
* ``analytics/usage.jsonl`` is committed, so cost history lives with the content history.
* A cost number is recorded only when real prices exist in ``amplify/config.yaml``.
  Missing prices produce ``null`` — never an invented number.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Iterable

from .config import Budgets, Config
from .errors import BudgetExceeded

USAGE_FIELDS = (
    "ts", "mode", "week", "task_id", "agent", "model",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "cost_estimate_usd", "attempt", "outcome",
)


def usage_record(
    *,
    mode: str,
    week: str | None,
    task_id: str,
    agent: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_estimate_usd: float | None,
    attempt: int = 1,
    outcome: str = "ok",
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    stamp = (now or _dt.datetime.now(_dt.timezone.utc)).replace(microsecond=0).isoformat()
    return {
        "ts": stamp,
        "mode": mode,
        "week": week,
        "task_id": task_id,
        "agent": agent,
        "model": model,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "total_tokens": int(prompt_tokens) + int(completion_tokens),
        "cost_estimate_usd": cost_estimate_usd,
        "attempt": attempt,
        "outcome": outcome,
    }


def estimate_cost(
    model: str, prompt_tokens: int, completion_tokens: int, pricing: dict[str, Any]
) -> float | None:
    prices = pricing.get(model) or {}
    try:
        input_price = float(prices["input_per_mtok_usd"])
        output_price = float(prices["output_per_mtok_usd"])
    except (KeyError, TypeError, ValueError):
        return None
    cost = (prompt_tokens / 1_000_000) * input_price + (completion_tokens / 1_000_000) * output_price
    return round(cost, 6)


def append_usage(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def read_usage(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number} is not valid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{number} is not a JSON object")
        records.append(record)
    return records


def _month_of(stamp: str) -> str:
    return str(stamp)[:7]


def tokens_for_month(path: Path, month: str, *, include_dry_run: bool = False) -> int:
    total = 0
    for record in read_usage(path):
        if not include_dry_run and record.get("mode") == "dry_run":
            continue
        if _month_of(record.get("ts", "")) == month:
            total += int(record.get("total_tokens") or 0)
    return total


def assert_budget_available(
    path: Path, budgets: Budgets, *, today: _dt.date | None = None
) -> int:
    month = (today or _dt.date.today()).strftime("%Y-%m")
    used = tokens_for_month(path, month)
    if used >= budgets.monthly_max_tokens:
        raise BudgetExceeded(
            f"monthly token budget exhausted: {used}/{budgets.monthly_max_tokens} tokens used in "
            f"{month} (analytics/usage.jsonl). Cycle refused to start (docs/06-limits.md)."
        )
    return used


def summarise_usage(path: Path, *, month: str | None = None) -> dict[str, Any]:
    records = [r for r in read_usage(path) if month is None or _month_of(r.get("ts", "")) == month]
    live = [r for r in records if r.get("mode") != "dry_run"]
    tokens = sum(int(r.get("total_tokens") or 0) for r in live)
    costs = [r.get("cost_estimate_usd") for r in live]
    known_costs = [float(c) for c in costs if isinstance(c, (int, float))]
    return {
        "calls": len(live),
        "tokens": tokens,
        "cost_usd": round(sum(known_costs), 6) if known_costs and len(known_costs) == len(live) else None,
        "cost_known": bool(live) and len(known_costs) == len(live),
        "by_agent": _by_agent(live),
    }


def _by_agent(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        bucket = grouped.setdefault(str(record.get("agent")), {"calls": 0, "tokens": 0})
        bucket["calls"] += 1
        bucket["tokens"] += int(record.get("total_tokens") or 0)
    return grouped


def cost_per_item(config: Config, usage_path: Path, *, month: str | None = None, items: int = 0) -> float | None:
    summary = summarise_usage(usage_path, month=month)
    if not summary["cost_known"] or items <= 0:
        return None
    return round(float(summary["cost_usd"]) / items, 6)

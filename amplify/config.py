"""Configuration, budgets, week arithmetic and repository paths.

Budgets and model choices come from amplify/config.yaml — never hardcoded
(AGENTS.md, docs/06-limits.md).
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")

@dataclass(frozen=True)
class Budgets:
    monthly_max_tokens: int
    per_item_max_tokens: int
    max_retries_per_task: int

    def __post_init__(self) -> None:
        if self.monthly_max_tokens <= 0:
            raise ConfigError("budgets.monthly_max_tokens must be > 0")
        if self.per_item_max_tokens <= 0:
            raise ConfigError("budgets.per_item_max_tokens must be > 0")
        if self.max_retries_per_task < 0:
            raise ConfigError("budgets.max_retries_per_task must be >= 0")


@dataclass(frozen=True)
class Config:
    models: dict[str, str]
    budgets: Budgets
    pricing: dict[str, Any]
    registry: dict[str, Any]
    raw: dict[str, Any]

    # docs/06 names the QA judge `qa_judge`; the agent is `qa-editor`.
    MODEL_ALIASES = {"qa-editor": "qa_judge"}

    def model_for(self, agent: str) -> str:
        key = self.MODEL_ALIASES.get(agent, agent)
        model = self.models.get(key) or self.models.get("default")
        if not model:
            raise ConfigError(f"no model configured for agent {agent!r} and no models.default")
        return model


def parse_week(week: str) -> tuple[int, int]:
    """Parse an ISO week string like ``2026-W43``."""
    match = WEEK_RE.match(str(week))
    if not match:
        raise ConfigError(f"invalid week {week!r}; expected YYYY-Www (e.g. 2026-W43)")
    year, number = int(match.group(1)), int(match.group(2))
    if not 1 <= number <= 53:
        raise ConfigError(f"invalid ISO week number in {week!r}")
    return year, number


def current_week(today: _dt.date | None = None) -> str:
    today = today or _dt.date.today()
    iso = today.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_from_date(day: _dt.date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_start(week: str) -> _dt.date:
    """Monday of the ISO week."""
    year, number = parse_week(week)
    return _dt.date.fromisocalendar(year, number, 1)


def parse_date(value: str, field: str = "date") -> _dt.date:
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError as exc:  # pragma: no cover - message covered by tests
        raise ConfigError(f"{field} is not an ISO date: {value!r}") from exc


@dataclass(frozen=True)
class RepoPaths:
    root: Path

    @property
    def amplify(self) -> Path:
        return self.root / "amplify"

    @property
    def config_file(self) -> Path:
        return self.amplify / "config.yaml"

    @property
    def schemas(self) -> Path:
        return self.root / "schemas"

    @property
    def agents(self) -> Path:
        return self.root / "agents"

    @property
    def brand(self) -> Path:
        return self.root / "brand"

    @property
    def claims(self) -> Path:
        return self.root / "claims" / "registry.json"

    @property
    def claims_evidence(self) -> Path:
        return self.root / "claims" / "evidence"

    @property
    def strategy(self) -> Path:
        return self.root / "strategy"

    @property
    def scores(self) -> Path:
        return self.strategy / "scores.json"

    @property
    def research(self) -> Path:
        return self.strategy / "research"

    @property
    def plans(self) -> Path:
        return self.strategy / "plans"

    @property
    def content(self) -> Path:
        return self.root / "content"

    @property
    def drafts(self) -> Path:
        return self.content / "drafts"

    @property
    def review(self) -> Path:
        return self.content / "review"

    @property
    def calendar(self) -> Path:
        return self.content / "calendar"

    @property
    def analytics(self) -> Path:
        return self.root / "analytics"

    @property
    def raw_stats(self) -> Path:
        return self.analytics / "raw"

    @property
    def usage_log(self) -> Path:
        return self.analytics / "usage.jsonl"

    @property
    def sqlite(self) -> Path:
        return self.analytics / "marketing.sqlite"

    @property
    def fixtures(self) -> Path:
        return self.root / "tests" / "fixtures"


def repo_paths(root: str | Path | None = None) -> RepoPaths:
    return RepoPaths(Path(root).resolve() if root else Path(__file__).resolve().parent.parent)


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"{where}.{key} is required")
    return mapping[key]


def load_config(path: str | Path | None = None, *, root: str | Path | None = None) -> Config:
    config_path = Path(path) if path else repo_paths(root).config_file
    if not config_path.exists():
        raise ConfigError(f"config file not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config file must contain a mapping: {config_path}")

    models = _require(raw, "models", "config")
    if not isinstance(models, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in models.items()):
        raise ConfigError("config.models must be a mapping of agent name -> model id")
    if not models.get("default"):
        raise ConfigError("config.models.default is required")

    budgets_raw = _require(raw, "budgets", "config")
    if not isinstance(budgets_raw, dict):
        raise ConfigError("config.budgets must be a mapping")
    budgets = Budgets(
        monthly_max_tokens=int(_require(budgets_raw, "monthly_max_tokens", "budgets")),
        per_item_max_tokens=int(_require(budgets_raw, "per_item_max_tokens", "budgets")),
        max_retries_per_task=int(_require(budgets_raw, "max_retries_per_task", "budgets")),
    )

    pricing = raw.get("pricing") or {}
    if not isinstance(pricing, dict):
        raise ConfigError("config.pricing must be a mapping (may be empty)")
    registry_cfg = raw.get("registry") or {}
    if not isinstance(registry_cfg, dict):
        raise ConfigError("config.registry must be a mapping")

    return Config(models=dict(models), budgets=budgets, pricing=pricing, registry=registry_cfg, raw=dict(raw))

"""Repository-wide validation — the local twin of Content CI (docs/03).

Checks, in order of blast radius:

1. schemas themselves are valid JSON Schema;
2. config loads, budgets are sane;
3. the Claims Registry is schema-valid and internally consistent;
4. brand materials parse (fingerprint block, voice library, lint rules);
5. every content item validates, is lintable, and has legal status/scores;
6. every decision record validates;
7. agent prompt files exist for all six agents (no fake agents).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml
from jsonschema import Draft202012Validator

from . import content as content_mod
from .agents import PROMPT_FILES, load_prompt
from .brand import load_brand
from .config import Config, RepoPaths, load_config
from .errors import AmplifyError, ClaimError, ConfigError, SchemaError
from .lint import lint_item
from .registry import Registry, load_registry, registry_summary
from .scoring import load_rubric
from .schemas import SCHEMA_FILES, load_schema, validate


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines: list[str] = []
        for key, value in self.checked.items():
            lines.append(f"checked {value} {key}")
        for warning in self.warnings:
            lines.append(f"WARN  {warning}")
        for error in self.errors:
            lines.append(f"ERROR {error}")
        lines.append("valid" if self.ok else f"INVALID ({len(self.errors)} error(s))")
        return "\n".join(lines)


def _content_dirs(paths: RepoPaths) -> list[Path]:
    candidates = [paths.drafts, paths.content / "approved", paths.content / "published"]
    return [path for path in candidates if path.exists()]


def validate_repo(
    paths: RepoPaths,
    *,
    as_of: _dt.date | None = None,
    extra_items: Iterable[Path] = (),
) -> ValidationReport:
    as_of = as_of or _dt.date.today()
    report = ValidationReport()

    # 1. schemas -----------------------------------------------------------
    for name in SCHEMA_FILES:
        try:
            load_schema(paths, name)
            Draft202012Validator.check_schema(load_schema(paths, name))
        except (SchemaError, AmplifyError) as exc:
            report.errors.append(f"schema {name}: {exc}")
        except Exception as exc:  # jsonschema SchemaError
            report.errors.append(f"schema {name}: {exc}")
    report.checked["schemas"] = len(SCHEMA_FILES)
    try:
        rubric = load_rubric(paths)
        report.checked["rubric dimensions"] = len(rubric["dimensions"])
    except ConfigError as exc:
        report.errors.append(f"rubric: {exc}")

    # 2. config ------------------------------------------------------------
    config: Config | None = None
    try:
        config = load_config(root=paths.root)
    except ConfigError as exc:
        report.errors.append(f"config: {exc}")

    # 3. registry ----------------------------------------------------------
    registry: Registry | None = None
    try:
        registry = load_registry(paths)
        report.checked["claims"] = len(registry.entries)
        if not registry.entries:
            report.warnings.append(
                "claims/registry.json is empty: no factual claim can be published yet. "
                "Register evidence with `python -m amplify evidence add`."
            )
    except ClaimError as exc:
        report.errors.append(f"claims registry: {exc}")

    # 4. brand -------------------------------------------------------------
    materials = None
    try:
        materials = load_brand(paths)
        report.checked["voice samples"] = len(materials.samples)
        if not materials.calibrated:
            report.warnings.append(
                "voice fingerprint is uncalibrated (no real samples or calibrated=false): "
                "similarity is advisory and Samuel reviews register manually"
            )
    except (ConfigError, AmplifyError, OSError) as exc:
        report.errors.append(f"brand: {exc}")

    # 5. content -----------------------------------------------------------
    item_files: list[Path] = []
    for directory in _content_dirs(paths):
        item_files.extend(sorted(directory.glob("*.yaml")))
    item_files.extend(sorted(Path(p) for p in extra_items))
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for path in item_files:
        try:
            item = content_mod.load_item(path, paths)
        except SchemaError as exc:
            report.errors.append(f"{path.name}: {exc}")
            continue
        if item["content_id"] in seen:
            report.errors.append(f"{path.name}: duplicate content_id {item['content_id']}")
        seen.add(item["content_id"])
        items.append(item)
        if registry is not None and materials is not None:
            lint = lint_item(item, materials, registry, as_of=as_of)
            for finding in lint.blocking:
                report.errors.append(f"{path.name}: {finding.render()}")
            for finding in lint.warnings:
                report.warnings.append(f"{path.name}: {finding.render()}")
        if item.get("status") == "in_review":
            scores = item.get("scores") or {}
            if not scores or scores.get("composite") is None:
                report.errors.append(f"{path.name}: in_review without QA subscores")
            elif float(scores["composite"]) < 70:
                report.errors.append(
                    f"{path.name}: in_review with composite {scores['composite']} < 70 (auto-reject threshold)"
                )
    report.checked["content items"] = len(items)
    if materials is not None:
        from .lint import atomization_lint

        for content_id, findings in atomization_lint(items).items():
            for finding in findings:
                report.errors.append(f"{content_id}: {finding.render()}")

    # 6. decisions ---------------------------------------------------------
    decision_files = sorted(paths.review.glob("decisions-*.yaml")) if paths.review.exists() else []
    for path in decision_files:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            validate(payload, paths, "decisions")
        except (yaml.YAMLError, SchemaError) as exc:
            report.errors.append(f"{path.name}: {exc}")
    report.checked["decision files"] = len(decision_files)

    # 7. agent prompts -----------------------------------------------------
    for agent in PROMPT_FILES:
        try:
            load_prompt(paths, agent)
        except AmplifyError as exc:
            report.errors.append(f"agent {agent}: {exc}")
        except OSError as exc:
            report.errors.append(f"agent {agent}: {exc}")
    report.checked["agent prompts"] = len(PROMPT_FILES)

    if config is not None:
        report.checked["budget monthly tokens"] = config.budgets.monthly_max_tokens
        if not config.pricing:
            report.warnings.append(
                "pricing is empty in amplify/config.yaml: cost metrics will be null (unknown), "
                "never estimated"
            )

    if registry is not None:
        report.warnings.append(registry_summary(registry, as_of))
    return report

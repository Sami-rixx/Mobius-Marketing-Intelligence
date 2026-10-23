"""The weekly cycle (docs/01 data flow, docs/04 cadence).

One hero asset, its platform-native derivatives, and 2-3 supporting items. Every step's
failure is contained: it stops that branch, is logged, and marks the week's digest
DEGRADED. Nothing is silently skipped, and nothing is retried forever.

The cycle never publishes, never approves, and never writes the Claims Registry.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import agents, content as content_mod
from .brand import BrandMaterials, load_brand
from .client import SupportsCompletion
from .config import Config, RepoPaths, current_week, parse_week, week_start
from .digest import render_digest, render_issue_text, render_plan_comment
from .errors import AmplifyError, SchemaError, StopCondition
from .evidence_keeper import registry_report
from .registry import Registry, load_registry
from .scoring import load_rubric
from .schemas import validate
from .usage import assert_budget_available, summarise_usage

LOGGER = logging.getLogger("amplify.cycle")

DERIVATIVE_CODES = {
    "youtube": "YT",
    "tiktok": "TT",
    "instagram": "IG",
    "facebook": "FB",
    "shorts": "SH",
}


@dataclass
class Failure:
    step: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"step": self.step, "reason": self.reason}


@dataclass
class CycleResult:
    week: str
    degraded: bool
    failures: list[Failure] = field(default_factory=list)
    digest_path: Path | None = None
    issue_path: Path | None = None
    plan_path: Path | None = None
    qa_path: Path | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[Path] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.degraded else 0


class WeeklyCycle:
    def __init__(
        self,
        *,
        paths: RepoPaths,
        config: Config,
        client: SupportsCompletion,
        now: _dt.datetime | None = None,
        brief: str | None = None,
        registry_path: Path | None = None,
        drafts_dir: Path | None = None,
    ):
        self.paths = paths
        self.registry_path = registry_path
        self.drafts_dir = drafts_dir or paths.drafts
        self.config = config
        self.client = client
        self.now = now or _dt.datetime.now(_dt.timezone.utc)
        self.brief = brief
        self.failures: list[Failure] = []
        self.artifacts: list[Path] = []

    # -- helpers -----------------------------------------------------------
    def _fail(self, step: str, exc: BaseException) -> None:
        message = f"{type(exc).__name__}: {exc}"
        LOGGER.error("cycle step %s failed: %s", step, message)
        self.failures.append(Failure(step=step, reason=message))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.artifacts.append(path)
        return path

    def _write_text(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        self.artifacts.append(path)
        return path

    # -- main --------------------------------------------------------------
    def run(self, week: str) -> CycleResult:
        parse_week(week)
        result = CycleResult(week=week, degraded=False)

        try:
            if self.client.mode == "live":
                used = assert_budget_available(self.paths.usage_log, self.config.budgets)
                LOGGER.info("budget check ok: %s tokens used this month", used)
            registry = load_registry(self.paths, path=self.registry_path)
            materials = load_brand(self.paths)
            rubric = load_rubric(self.paths)
        except (AmplifyError, OSError) as exc:
            self._fail("preflight", exc)
            return self._finish(result, week, plan=None, items=[], qa_report=None, registry=_empty_registry())

        # 1. Researcher ----------------------------------------------------
        research: dict[str, Any] | None = None
        try:
            research = self._research(week)
        except (AmplifyError, OSError, KeyError) as exc:
            self._fail("researcher", exc)

        # 2. Strategist ----------------------------------------------------
        plan: dict[str, Any] | None = None
        if research is not None:
            try:
                plan = self._plan(week, research, registry)
            except (AmplifyError, OSError, KeyError) as exc:
                self._fail("strategist", exc)
        else:
            self.failures.append(Failure(step="strategist", reason="skipped: no research notes (see researcher failure)"))

        # 3. Producer ------------------------------------------------------
        items: list[dict[str, Any]] = []
        if plan is not None:
            items = self._produce(week, plan, registry, materials)
        else:
            self.failures.append(Failure(step="producer", reason="skipped: no approved plan (see strategist failure)"))

        # 4. QA / Editor ---------------------------------------------------
        qa_report: dict[str, Any] | None = None
        if items:
            try:
                qa_report = self._qa(week, items, registry, materials, rubric)
                items = self._apply_verdicts(week, items, qa_report)
            except (AmplifyError, OSError, KeyError) as exc:
                self._fail("qa-editor", exc)
        else:
            self.failures.append(Failure(step="qa-editor", reason="skipped: no drafts were produced"))

        return self._finish(result, week, plan=plan, items=items, qa_report=qa_report, registry=registry)

    # -- steps -------------------------------------------------------------
    def _research(self, week: str) -> dict[str, Any]:
        run = agents.run_researcher(
            client=self.client, config=self.config, paths=self.paths, week=week, brief=self.brief
        )
        payload = run.payload
        payload["week"] = week
        validate(payload, self.paths, "research-notes")
        self._write_json(self.paths.research / f"{week}-notes.json", payload)
        LOGGER.info("researcher: %s findings, %s gaps", len(payload["findings"]), len(payload["gaps"]))
        return payload

    def _plan(self, week: str, research: dict[str, Any], registry: Registry) -> dict[str, Any]:
        run = agents.run_strategist(
            client=self.client,
            config=self.config,
            paths=self.paths,
            week=week,
            research=research,
            registry=registry,
        )
        plan = run.payload
        plan["week"] = week
        validate(plan, self.paths, "weekly-plan")
        for item in [plan.get("hero")] + list(plan.get("supporting") or []):
            if item and item.get("claims"):
                registry.require(item["claims"])
        self._write_json(self.paths.plans / f"{week}-plan.json", plan)
        self._write_text(self.paths.review / f"{week}-plan.md", render_plan_comment(week, plan))
        return plan

    def _assignments(self, week: str, plan: dict[str, Any]) -> list[dict[str, Any]]:
        """Turn the plan into deterministic content assignments (atomization rule)."""
        assignments: list[dict[str, Any]] = []
        hero = plan.get("hero")
        if hero:
            fmt = hero["format"]
            fmt_code = fmt.replace("-", "")
            hero_id = f"{week}-{fmt_code}-HERO"
            platforms = [d["platform"] for d in hero.get("derivatives") or []]
            primary = _primary_platform(self.paths, fmt)
            if primary and primary not in platforms:
                platforms = [primary] + platforms
            assignments.append(
                {
                    "content_id": hero_id,
                    "plan_item": hero,
                    "platforms": platforms,
                    "deriv_of": None,
                    "theme": hero.get("theme"),
                    "working_title": hero.get("working_title"),
                }
            )
            for derivative in hero.get("derivatives") or []:
                platform = derivative["platform"]
                if platform == primary and len(platforms) > 1:
                    continue
                code = DERIVATIVE_CODES.get(platform, platform[:2].upper())
                assignments.append(
                    {
                        "content_id": f"{hero_id}-{code}",
                        "plan_item": hero,
                        "platforms": [platform],
                        "deriv_of": hero_id,
                        "theme": hero.get("theme"),
                        "working_title": f"{hero.get('working_title')} — {platform} cut",
                    }
                )
        for index, supporting in enumerate(plan.get("supporting") or [], start=1):
            fmt_code = supporting["format"].replace("-", "")
            assignments.append(
                {
                    "content_id": f"{week}-{fmt_code}-S{index}",
                    "plan_item": supporting,
                    "platforms": list(supporting.get("platforms") or []),
                    "deriv_of": None,
                    "theme": supporting.get("theme") or plan.get("theme"),
                    "working_title": supporting.get("working_title"),
                }
            )
        return assignments

    def _produce(
        self, week: str, plan: dict[str, Any], registry: Registry, materials: BrandMaterials
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for assignment in self._assignments(week, plan):
            content_id = assignment["content_id"]
            if content_mod.item_path(self.paths, content_id, self.drafts_dir).exists():
                LOGGER.warning("draft %s already exists; preserving the existing file", content_id)
                try:
                    items.append(
                        content_mod.load_item(
                            content_mod.item_path(self.paths, content_id, self.drafts_dir), self.paths
                        )
                    )
                except SchemaError as exc:
                    self._fail(f"producer:{content_id}", exc)
                continue
            try:
                run = agents.run_producer(
                    client=self.client,
                    config=self.config,
                    paths=self.paths,
                    week=week,
                    plan={"theme": assignment.get("theme")},
                    plan_item={
                        **assignment["plan_item"],
                        "working_title": assignment["plan_item"]["working_title"],
                    },
                    expected_content_id=content_id,
                    platforms=assignment["platforms"],
                    registry=registry,
                    materials=materials,
                    deriv_of=assignment["deriv_of"],
                )
                item = run.payload
                item["campaign"] = str(item.get("campaign") or plan.get("campaign") or f"{week.lower()}-proof-of-work")
                item["week"] = week
                item["deriv_of"] = assignment["deriv_of"]
                path = content_mod.create_item(item, self.paths, directory=self.drafts_dir, actor="producer")
                items.append(content_mod.load_item(path, self.paths))
                LOGGER.info("produced %s -> %s", content_id, path.name)
            except (AmplifyError, OSError, KeyError) as exc:
                self._fail(f"producer:{content_id}", exc)
        # include any pre-existing items for this week so QA scores them too
        try:
            existing = content_mod.load_items(self.drafts_dir, self.paths, week=week)
        except SchemaError as exc:
            self._fail("producer:existing-items", exc)
            existing = []
        known = {item["content_id"] for item in items}
        items.extend(item for item in existing if item["content_id"] not in known)
        return items

    def _qa(
        self,
        week: str,
        items: list[dict[str, Any]],
        registry: Registry,
        materials: BrandMaterials,
        rubric: dict[str, Any],
    ) -> dict[str, Any]:
        from .lint import atomization_lint

        cross = atomization_lint(items)
        report, raw = agents.run_qa_editor(
            client=self.client,
            config=self.config,
            paths=self.paths,
            week=week,
            items=items,
            registry=registry,
            materials=materials,
            deterministic=self.client.mode == "dry_run",
            extra_findings=cross,
        )
        self._write_json(self.paths.review / f"{week}-qa.json", report)
        if self.client.mode != "dry_run":
            self._write_json(self.paths.review / f"{week}-qa-raw.json", raw)
        LOGGER.info(
            "qa: %s pass / %s reject",
            sum(1 for i in report["items"] if i["verdict"] == "pass"),
            sum(1 for i in report["items"] if i["verdict"] == "reject"),
        )
        return report

    def _apply_verdicts(
        self, week: str, items: list[dict[str, Any]], qa_report: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """QA decides status; Samuel still decides approval. Never the reverse."""
        verdicts = {entry["content_id"]: entry for entry in qa_report["items"]}
        updated: list[dict[str, Any]] = []
        for item in items:
            verdict = verdicts.get(item["content_id"])
            if verdict is None:
                self._fail(f"qa:{item['content_id']}", StopCondition("qa-editor", "item missing from QA report"))
                updated.append(item)
                continue
            if item["status"] not in {"draft", "rejected"}:
                updated.append(item)
                continue
            try:
                revised = dict(item)
                revised["scores"] = {**verdict["subscores"], "composite": verdict["composite"]}
                if verdict["verdict"] == "pass":
                    revised["status"] = "in_review"
                    revised["rejection_reason"] = None
                    revised["rejection_note"] = None
                else:
                    revised["status"] = "rejected"
                    revised["rejection_reason"] = verdict["reason_codes"][0]
                    revised["rejection_note"] = "; ".join(verdict["edit_suggestions"])[:800]
                path = content_mod.item_path(self.paths, item["content_id"], self.drafts_dir)
                content_mod.save_item(revised, path, self.paths, actor="qa-editor", previous=item)
                updated.append(content_mod.load_item(path, self.paths))
            except (AmplifyError, OSError) as exc:
                self._fail(f"qa:{item['content_id']}", exc)
                updated.append(item)
        return updated

    # -- wrap up -----------------------------------------------------------
    def _finish(
        self,
        result: CycleResult,
        week: str,
        *,
        plan: dict[str, Any] | None,
        items: list[dict[str, Any]],
        qa_report: dict[str, Any] | None,
        registry: Registry,
    ) -> CycleResult:
        result.failures = list(self.failures)
        result.degraded = bool(self.failures)
        result.items = items
        try:
            expiring = [
                row
                for row in registry_report(registry, as_of=self.now.date(), soon_days=30)
                if row["expiring_soon"] and row["state"] == "valid"
            ]
        except Exception:  # pragma: no cover - defensive: digest must still render
            expiring = []
        usage = summarise_usage(self.paths.usage_log, month=self.now.strftime("%Y-%m"))
        digest = render_digest(
            week=week,
            plan=plan,
            items=items,
            qa_report=qa_report,
            failures=[failure.as_dict() for failure in result.failures],
            registry=registry,
            usage=usage,
            expiring=expiring,
            generated_at=self.now,
        )
        result.digest_path = self._write_text(self.paths.review / f"{week}-digest.md", digest)
        if result.degraded:
            issue = render_issue_text(
                week=week,
                failures=[failure.as_dict() for failure in result.failures],
                artifacts=[str(path.relative_to(self.paths.root)) for path in self.artifacts],
            )
            result.issue_path = self._write_text(self.paths.review / f"{week}-issue.md", issue)
        result.plan_path = self.paths.plans / f"{week}-plan.json" if plan else None
        result.qa_path = self.paths.review / f"{week}-qa.json" if qa_report else None
        result.artifacts = list(self.artifacts)
        return result


def _primary_platform(paths: RepoPaths, fmt: str) -> str | None:
    try:
        rules = json.loads((paths.brand / "lint-rules.json").read_text(encoding="utf-8"))
        required = rules.get("platform_format_rules", {}).get(fmt) or []
        return required[0] if required else None
    except (OSError, json.JSONDecodeError):
        return None


def _empty_registry() -> Registry:
    return Registry(entries={}, version=1, updated=None, source=None)


def run_weekly(
    *,
    paths: RepoPaths,
    config: Config,
    client: SupportsCompletion,
    week: str | None = None,
    brief: str | None = None,
    now: _dt.datetime | None = None,
    registry_path: Path | None = None,
    drafts_dir: Path | None = None,
) -> CycleResult:
    week = week or current_week((now or _dt.datetime.now(_dt.timezone.utc)).date())
    parse_week(week)
    week_start(week)  # validates a real ISO week
    if registry_path is not None and client.mode == "live":
        raise StopCondition(
            "system",
            "a fixture registry may not be used for a live cycle: real content needs real evidence",
        )
    cycle = WeeklyCycle(
        paths=paths,
        config=config,
        client=client,
        now=now,
        brief=brief,
        registry_path=registry_path,
        drafts_dir=drafts_dir,
    )
    return cycle.run(week)

"""The six marketing-agent contracts, implemented as plain Python functions (docs/02).

Each function:

1. runs the documented stop-conditions *before* spending a token;
2. calls the model with the agent's system prompt and structured inputs;
3. validates the output against its JSON schema;
4. enforces the agent's hard limits in code, not just in the prompt.

Nothing here writes content, approves content, or edits the registry. Those are separate,
narrowly-permitted operations (``content.create_item``, ``review``, ``evidence_keeper``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import yaml

from .brand import BrandMaterials, render_fingerprint_for_prompt
from .client import Completion, SupportsCompletion
from .config import Config, RepoPaths
from .errors import ClaimError, PermanentError, SchemaError, StopCondition, TransientError
from .registry import Registry, apply_operations
from .scoring import build_qa_item, load_rubric
from .schemas import load_schema, validate

LOGGER = logging.getLogger("amplify.agents")

PROMPT_FILES = {
    "researcher": "researcher.md",
    "strategist": "strategist.md",
    "evidence-keeper": "evidence-keeper.md",
    "producer": "producer.md",
    "qa-editor": "qa-editor.md",
    "growth-analyst": "growth-analyst.md",
}

SCHEMA_FOR_AGENT = {
    "researcher": "research-notes",
    "strategist": "weekly-plan",
    "evidence-keeper": "claims-update",
    "producer": "content-item",
    "qa-editor": "qa-report",
    "growth-analyst": "analytics-update",
}


@dataclass
class TaskRun:
    agent: str
    task_id: str
    payload: dict[str, Any]
    attempts: int
    completions: list[Completion] = field(default_factory=list)


def load_prompt(paths: RepoPaths, agent: str) -> str:
    filename = PROMPT_FILES.get(agent)
    if not filename:
        raise StopCondition(agent, f"no system prompt registered for agent {agent!r}")
    path = paths.agents / filename
    if not path.exists():
        raise StopCondition(agent, f"system prompt missing: agents/{filename}")
    prompt = path.read_text(encoding="utf-8").strip()
    if len(prompt.split()) < 40:
        raise StopCondition(agent, f"system prompt too thin to be a contract: agents/{filename}")
    return prompt


def run_task(
    *,
    agent: str,
    task_id: str,
    week: str | None,
    inputs: dict[str, Any],
    client: SupportsCompletion,
    config: Config,
    paths: RepoPaths,
    max_tokens: int | None = None,
    check: Callable[[dict[str, Any]], None] | None = None,
) -> TaskRun:
    """Call an agent with capped retries and strict schema validation."""
    schema_name = SCHEMA_FOR_AGENT[agent]
    schema = load_schema(paths, schema_name)
    prompt = load_prompt(paths, agent)
    attempts_allowed = config.budgets.max_retries_per_task + 1
    completions: list[Completion] = []
    failures: list[str] = []

    for attempt in range(1, attempts_allowed + 1):
        try:
            completion = client.complete_json(
                system_prompt=prompt,
                user_payload=inputs,
                schema=schema,
                schema_name=schema_name,
                task_id=task_id,
                agent=agent,
                week=week,
                max_tokens=max_tokens or config.budgets.per_item_max_tokens,
                attempt=attempt,
            )
        except PermanentError as exc:
            raise StopCondition(agent, f"{task_id}: non-retriable failure: {exc}") from exc
        except TransientError as exc:
            failures.append(f"attempt {attempt}: {exc}")
            LOGGER.warning("task=%s attempt=%s transient failure: %s", task_id, attempt, exc)
            continue

        completions.append(completion)
        try:
            validate(completion.payload, paths, schema_name)
            if check is not None:
                check(completion.payload)
        except (SchemaError, ClaimError, StopCondition) as exc:
            failures.append(f"attempt {attempt}: {exc}")
            LOGGER.warning("task=%s attempt=%s rejected output: %s", task_id, attempt, exc)
            continue

        if attempt > 1:
            LOGGER.info("task=%s succeeded on attempt %s", task_id, attempt)
        return TaskRun(agent=agent, task_id=task_id, payload=completion.payload, attempts=attempt, completions=completions)

    raise StopCondition(
        agent,
        f"{task_id}: failed after {attempts_allowed} attempts "
        f"(retry cap {config.budgets.max_retries_per_task}). Failures: " + " | ".join(failures),
    )


# ------------------------------------------------------------------ shared inputs
def vision_excerpt(paths: RepoPaths) -> str:
    path = paths.root / "docs" / "00-vision.md"
    if not path.exists():
        raise StopCondition("system", "docs/00-vision.md is missing: agents must read the vision")
    return path.read_text(encoding="utf-8")


def format_playbook(paths: RepoPaths) -> str:
    path = paths.root / "docs" / "04-cadence.md"
    if not path.exists():
        raise StopCondition("system", "docs/04-cadence.md is missing: format playbooks unavailable")
    return path.read_text(encoding="utf-8")


def load_scores(paths: RepoPaths) -> dict[str, Any]:
    path = paths.scores
    if not path.exists():
        raise StopCondition("strategist", f"strategy/scores.json missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StopCondition("strategist", f"strategy/scores.json unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise StopCondition("strategist", "strategy/scores.json must be a JSON object")
    return data


def calendar_for_week(paths: RepoPaths, week: str) -> dict[str, Any]:
    if not paths.calendar.exists():
        return {"week": week, "planned_items": []}
    path = paths.calendar / f"{week}.yaml"
    if not path.exists():
        return {"week": week, "planned_items": []}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise StopCondition("strategist", f"calendar {path.name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise StopCondition("strategist", f"calendar {path.name} must be a mapping")
    return data


def registry_evidence(registry: Registry) -> list[dict[str, str]]:
    """Only usable claims are ever shown to an agent that writes public copy."""
    return [
        {
            "claim_id": entry["claim_id"],
            "statement": entry["statement"],
            "evidence_type": entry["evidence_type"],
            "evidence_ref": entry["evidence_ref"],
        }
        for entry in registry.valid_claims()
    ]


# ------------------------------------------------------------------ 1. Researcher
def run_researcher(
    *,
    client: SupportsCompletion,
    config: Config,
    paths: RepoPaths,
    week: str,
    brief: str | None = None,
) -> TaskRun:
    if brief is not None and len(brief.strip()) < 10:
        raise StopCondition("researcher", "brief is too short to research")
    inputs = {
        "week": week,
        "brief": brief
        or "Standing brief: what is happening for Kenyan school administrators and global "
        "indie builders that Möbius Muse could show real, evidenced work about this week?",
        "vision": vision_excerpt(paths),
        "prior_research": _prior_research(paths, week),
        "rules": [
            "Every finding needs a source URL or a repo/CI reference.",
            "Mark competitor claims verified=false until evidenced.",
            "If sources are insufficient, list the gap in `gaps`; never pad.",
        ],
    }
    return run_task(
        agent="researcher",
        task_id=f"{week}-researcher",
        week=week,
        inputs=inputs,
        client=client,
        config=config,
        paths=paths,
    )


def _prior_research(paths: RepoPaths, week: str) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    if not paths.research.exists():
        return history
    for path in sorted(paths.research.glob("*.json"))[-4:]:
        if week in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        history.append({"week": data.get("week", path.stem), "findings": (data.get("findings") or [])[:5]})
    return history


# ------------------------------------------------------------------ 2. Strategist
def run_strategist(
    *,
    client: SupportsCompletion,
    config: Config,
    paths: RepoPaths,
    week: str,
    research: dict[str, Any],
    registry: Registry,
) -> TaskRun:
    scores = load_scores(paths)
    if not research.get("findings"):
        raise StopCondition("strategist", "research notes contain no findings; cannot plan from nothing")
    evidence = registry_evidence(registry)
    inputs = {
        "week": week,
        "vision": vision_excerpt(paths),
        "research": research,
        "scores": scores,
        "calendar": calendar_for_week(paths, week),
        "available_claims": evidence,
        "formats": ["FMT-01", "FMT-02", "FMT-03"],
        "rules": [
            "One hero item plus 2-3 supporting items, or supporting_only=true with a reason.",
            "Cite only claim_id values from available_claims.",
            "Never invent a format, a claim or a product status.",
            "Reference docs/04 playbooks for platform fit and derivative list.",
        ],
    }

    def _check(plan: dict[str, Any]) -> None:
        needed: list[str] = []
        if plan.get("hero"):
            needed += plan["hero"].get("claims") or []
        for item in plan.get("supporting") or []:
            needed += item.get("claims") or []
        try:
            registry.require(needed)
        except ClaimError as exc:
            raise StopCondition("strategist", f"plan cites unusable claims: {exc}") from exc

    return run_task(
        agent="strategist",
        task_id=f"{week}-strategist",
        week=week,
        inputs=inputs,
        client=client,
        config=config,
        paths=paths,
        check=_check,
    )


# ------------------------------------------------------------------ 3. Evidence Keeper
def run_evidence_keeper(
    *,
    client: SupportsCompletion,
    config: Config,
    paths: RepoPaths,
    week: str,
    registry: Registry,
    evidence_index: dict[str, Any],
) -> TaskRun:
    inputs = {
        "week": week,
        "registry": registry.to_dict(),
        "evidence_index": evidence_index,
        "next_claim_id": registry.next_claim_id(),
        "rules": [
            "Propose add/update/expire operations only; never author marketing copy.",
            "Every new claim needs evidence_ref and verified_by=samuel.",
            "personal_statement requires founder_approval; leave it out and the proposal will be refused.",
            "If evidence is stale or ambiguous, propose op=expire with quarantine_reason.",
        ],
    }

    def _check(update: dict[str, Any]) -> None:
        clone = Registry(entries={k: dict(v) for k, v in registry.entries.items()}, source=None)
        try:
            apply_operations(clone, update["operations"], paths=paths, config=config, approved_by_founder=False)
        except (ClaimError, SchemaError) as exc:
            raise StopCondition(
                "evidence-keeper",
                f"proposal violates registry policy (founder approval or evidence missing): {exc}",
            ) from exc

    return run_task(
        agent="evidence-keeper",
        task_id=f"{week}-evidence-keeper",
        week=week,
        inputs=inputs,
        client=client,
        config=config,
        paths=paths,
        check=_check,
    )


# ------------------------------------------------------------------ 4. Producer
def run_producer(
    *,
    client: SupportsCompletion,
    config: Config,
    paths: RepoPaths,
    week: str,
    plan: dict[str, Any],
    plan_item: dict[str, Any],
    expected_content_id: str,
    platforms: list[str],
    registry: Registry,
    materials: BrandMaterials,
    deriv_of: str | None = None,
) -> TaskRun:
    try:
        registry.require(plan_item.get("claims") or [])
    except ClaimError as exc:
        raise StopCondition(
            "producer", f"plan cites unusable claims; request Evidence Keeper input: {exc}"
        ) from exc
    if not materials.fingerprint_raw.strip():
        raise StopCondition("producer", "voice fingerprint is empty; refusing to invent a voice")

    inputs = {
        "week": week,
        "assignment": {
            "content_id": expected_content_id,
            "format": plan_item["format"],
            "working_title": plan_item["working_title"],
            "angle": plan_item["angle"],
            "platforms": platforms,
            "deriv_of": deriv_of,
            "theme": plan.get("theme") or plan_item.get("theme"),
        },
        "available_claims": registry_evidence(registry),
        "brand_fingerprint": render_fingerprint_for_prompt(materials),
        "banned_and_required": (paths.brand / "banned-and-required.md").read_text(encoding="utf-8"),
        "playbook": format_playbook(paths),
        "rules": [
            "Write ONLY from available_claims; cite their ids in `claims`.",
            "status must be 'draft'. You cannot approve content.",
            "Derivatives must re-use the hero's substance but be re-expressed natively.",
            "No canned marketing filler; name real artifacts and numbers.",
            f"content_id must be exactly {expected_content_id!r}.",
        ],
    }

    def _check(item: dict[str, Any]) -> None:
        if item.get("content_id") != expected_content_id:
            raise StopCondition(
                "producer",
                f"produced content_id {item.get('content_id')!r}, expected {expected_content_id!r}",
            )
        if item.get("status") != "draft":
            raise StopCondition("producer", "producer output must have status 'draft'")
        try:
            registry.require(item.get("claims") or [])
        except ClaimError as exc:
            raise StopCondition("producer", f"draft cites unusable claims: {exc}") from exc
        if item.get("deriv_of") != deriv_of:
            raise StopCondition(
                "producer", f"deriv_of must be {deriv_of!r} for this assignment"
            )

    return run_task(
        agent="producer",
        task_id=f"{week}-producer-{expected_content_id.rsplit('-', 1)[-1].lower()}",
        week=week,
        inputs=inputs,
        client=client,
        config=config,
        paths=paths,
        check=_check,
    )


# ------------------------------------------------------------------ 5. QA / Editor
def run_qa_editor(
    *,
    client: SupportsCompletion,
    config: Config,
    paths: RepoPaths,
    week: str,
    items: list[dict[str, Any]],
    registry: Registry,
    materials: BrandMaterials,
    deterministic: bool,
    extra_findings: dict[str, list[Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (final qa report, raw agent payload or deterministic stand-in).

    The final report is always recomputed by :func:`build_qa_item` with the deterministic
    lints plus (when live) the judge's proposed subscores. A judge cannot pass a claim that
    has no receipt, and cannot pass an item below the rubric threshold.
    """
    rubric = load_rubric(paths)
    proposed: dict[str, dict[str, Any]] = {}

    if deterministic:
        raw: dict[str, Any] = {"generated_by": "qa-editor", "week": week, "threshold": rubric["threshold"], "items": []}
    else:
        inputs = {
            "week": week,
            "rubric": rubric,
            "items": items,
            "valid_claims": registry_evidence(registry),
            "banned_and_required": (paths.brand / "banned-and-required.md").read_text(encoding="utf-8"),
            "rules": [
                "Score each item 0-100 on every rubric dimension; be adversarial.",
                "Reject with a reason code from the taxonomy; never rewrite the draft.",
                "If a draft's claim conflicts with the registry, reject; do not adjudicate.",
            ],
        }
        run = run_task(
            agent="qa-editor",
            task_id=f"{week}-qa-editor",
            week=week,
            inputs=inputs,
            client=client,
            config=config,
            paths=paths,
        )
        raw = run.payload
        for entry in raw.get("items") or []:
            if entry.get("content_id"):
                proposed[entry["content_id"]] = entry

    by_id = {item["content_id"]: item for item in items}
    final_items: list[dict[str, Any]] = []
    for content_id, item in by_id.items():
        lint = _lint(item, materials, registry)
        for finding in (extra_findings or {}).get(content_id, []):
            lint.findings.append(finding)
        proposal = proposed.get(content_id)
        subscores = (proposal or {}).get("subscores") if proposal else None
        suggestions = (proposal or {}).get("edit_suggestions") if proposal else None
        entry = build_qa_item(
            item,
            lint,
            rubric,
            materials,
            proposed_subscores=subscores,
            suggestions=suggestions,
        )
        if proposal and proposal.get("verdict") == "reject":
            # QA may always reject; we never overrule a rejection with a score.
            codes = list(entry["reason_codes"])
            for code in proposal.get("reason_codes") or []:
                if code not in codes:
                    codes.append(code)
            entry["verdict"] = "reject"
            entry["reason_codes"] = codes
        final_items.append(entry)

    report = {
        "generated_by": "qa-editor",
        "week": week,
        "threshold": rubric["threshold"],
        "items": final_items,
        "notes": "verdicts recomputed by amplify/scoring.py; QA can reject but never rewrite",
    }
    validate(report, paths, "qa-report")
    return report, raw


def _lint(item: dict[str, Any], materials: BrandMaterials, registry: Registry):
    from .lint import lint_item

    return lint_item(item, materials, registry)


# ------------------------------------------------------------------ 6. Growth Analyst
NUMBER_RE = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)(?![\w.-])")


def numbers_in(text: str) -> set[str]:
    return {match.group(1) for match in NUMBER_RE.finditer(text)}


def allowed_numbers(update: dict[str, Any], *, include_decisions: bool = False) -> set[str]:
    """Every number a memo is allowed to mention: computed values, row values, counts."""
    allowed: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            allowed.add(str(value))
            allowed.add(str(round(float(value), 2)))
            allowed.add(str(int(value)) if float(value).is_integer() else str(value))
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in {"question"}:
                    continue
                collect(item)
        elif isinstance(value, list):
            allowed.add(str(len(value)))
            for item in value:
                collect(item)
        elif isinstance(value, str):
            return

    collect(update.get("rows"))
    collect(update.get("aggregates"))
    collect((update.get("memo") or {}).get("guardrail_metrics"))
    allowed.add(str(len(update.get("unknowns") or [])))
    if include_decisions:
        # Decisions here are engine-computed from the same numbers (ingest).
        collect((update.get("memo") or {}).get("decisions"))
    return allowed


def check_memo_grounding(update: dict[str, Any], *, include_decisions: bool = False) -> None:
    memo = update.get("memo") or {}
    allowed = allowed_numbers(update, include_decisions=include_decisions)
    texts = [str(memo.get("text") or "")]
    texts += [str(d.get("evidence") or "") for d in memo.get("decisions") or []]
    stray: set[str] = set()
    for text in texts:
        for number in numbers_in(text):
            normalised = str(int(float(number))) if float(number).is_integer() else str(float(number))
            if number not in allowed and normalised not in allowed:
                stray.add(number)
    if stray:
        raise StopCondition(
            "growth-analyst",
            "memo states numbers that do not exist in the supplied data: "
            + ", ".join(sorted(stray))
            + ". Metrics are never invented (docs/02, docs/05).",
        )


def run_growth_analyst(
    *,
    client: SupportsCompletion,
    config: Config,
    paths: RepoPaths,
    week: str,
    rows: list[dict[str, Any]],
    aggregates: dict[str, Any],
    guardrail_metrics: dict[str, Any],
    unknowns: list[str],
) -> TaskRun:
    if not rows:
        raise StopCondition("growth-analyst", "no performance rows supplied; nothing to analyse")
    inputs = {
        "week": week,
        "rows": rows,
        "aggregates": aggregates,
        "guardrail_metrics": guardrail_metrics,
        "unknowns": unknowns,
        "rules": [
            "Use only the supplied numbers. Unknown values stay null.",
            "Never estimate reach, conversions, revenue or inquiries.",
            "Every number in memo.text must appear in rows, aggregates or guardrail_metrics.",
            "Decision rule: above-median theme earns 3 more cycles; below-median is cut; "
            "formats are never cut before 3 full cycles.",
        ],
    }
    return run_task(
        agent="growth-analyst",
        task_id=f"{week}-growth-analyst",
        week=week,
        inputs=inputs,
        client=client,
        config=config,
        paths=paths,
        check=check_memo_grounding,
    )

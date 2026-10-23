"""Analytics ingestion and performance learning (docs/05, docs/06).

Hard rules encoded here:

* A metric exists **only** if a platform or Samuel supplied it. Missing values are stored as
  NULL and listed as unknown. Nothing is estimated.
* ``analytics/marketing.sqlite`` is a local, gitignored store; the committed artifacts are
  ``analytics/usage.jsonl``, ``strategy/scores.json`` and the weekly memo.
* ``strategy/scores.json`` has exactly one writer: the Growth Analyst.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import statistics
from pathlib import Path
from typing import Any

import yaml

from . import agents
from .client import SupportsCompletion
from .config import Config, RepoPaths
from .errors import GateFailure, SchemaError
from .review import first_pass_approval_rate, load_decisions
from .schemas import validate
from .usage import summarise_usage

STANDARD_METRICS = (
    "views",
    "impressions",
    "reach",
    "likes",
    "comments",
    "shares",
    "saves",
    "clicks",
    "watch_time_minutes",
    "followers_gained",
)

ENGAGEMENT_METRICS = ("likes", "comments", "shares", "saves")
SCORES_WRITER = "growth-analyst"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
    content_id TEXT PRIMARY KEY,
    format TEXT NOT NULL,
    theme TEXT,
    hook_text TEXT,
    hook_family TEXT,
    platforms TEXT,
    week TEXT NOT NULL,
    status TEXT NOT NULL,
    first_published_at TEXT
);
CREATE TABLE IF NOT EXISTS performance (
    content_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (content_id, platform, metric)
);
CREATE TABLE IF NOT EXISTS usage (
    ts TEXT NOT NULL,
    mode TEXT,
    task_id TEXT,
    agent TEXT,
    model TEXT,
    total_tokens INTEGER,
    cost_estimate_usd REAL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_SQL)
    return connection


def load_raw(paths: RepoPaths, week: str, *, path: Path | None = None) -> dict[str, Any]:
    target = path or (paths.raw_stats / f"{week}.yaml")
    if not target.exists():
        raise GateFailure(
            f"no pasted stats for {week}: expected {target}. Stats must come from a platform or "
            "from Samuel — the engine will not invent them."
        )
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SchemaError("analytics-raw", [f"{target.name}: invalid YAML: {exc}"]) from exc
    validate(raw, paths, "analytics-raw")
    return raw


def classify_hook(hook: str) -> str:
    """Deterministic hook family, used for performance learning."""
    text = (hook or "").strip().lower()
    if not text:
        return "unknown"
    if any(marker in text for marker in ("receipt", "commit", "ci ", "test", "repo", "apk", "screenshot")):
        return "receipt-first"
    if text.endswith("?"):
        return "question"
    if text.startswith(("i ", "my ", "we ")):
        return "personal-story"
    if any(character.isdigit() for character in text):
        return "number-led"
    return "stated-claim"


def upsert_items(connection: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
    for item in items:
        connection.execute(
            """
            INSERT INTO items (content_id, format, theme, hook_text, hook_family, platforms, week, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(content_id) DO UPDATE SET
                format=excluded.format, theme=excluded.theme, hook_text=excluded.hook_text,
                hook_family=excluded.hook_family, platforms=excluded.platforms,
                week=excluded.week, status=excluded.status
            """,
            (
                item["content_id"],
                item["format"],
                item.get("theme") or item.get("campaign"),
                item.get("hook"),
                classify_hook(item.get("hook") or ""),
                ",".join(item.get("platforms") or []),
                item.get("week") or item["content_id"][:8],
                item.get("status"),
            ),
        )
    connection.commit()


def record_performance(
    connection: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
    recorded_at: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Store supplied values, keep everything else unknown."""
    analytics_rows: list[dict[str, Any]] = []
    unknowns: list[str] = []
    for row in rows:
        content_id = row["content_id"]
        platform = row["platform"]
        supplied: dict[str, float | None] = dict(row.get("metrics") or {})
        stored: dict[str, float | None] = {}
        for metric in sorted(set(STANDARD_METRICS) | set(supplied)):
            value = supplied.get(metric)
            if value is None:
                unknowns.append(f"{content_id}:{platform}/{metric}")
            connection.execute(
                """
                INSERT INTO performance (content_id, platform, metric, value, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(content_id, platform, metric) DO UPDATE SET
                    value=excluded.value, recorded_at=excluded.recorded_at
                """,
                (content_id, platform, metric, None if value is None else float(value), recorded_at),
            )
            stored[metric] = value
        analytics_rows.append({"content_id": content_id, "platform": platform, "metrics": stored})
    connection.commit()
    return analytics_rows, unknowns


def _rollup(connection: sqlite3.Connection, column: str) -> list[dict[str, Any]]:
    query = f"""
        SELECT COALESCE(i.{column}, 'unknown') AS key,
               COUNT(p.value) AS samples,
               COUNT(DISTINCT i.week) AS cycles,
               AVG(p.value) AS score
        FROM items i
        JOIN performance p ON p.content_id = i.content_id AND p.metric = 'views' AND p.value IS NOT NULL
        GROUP BY key
        ORDER BY key
    """
    rows = connection.execute(query).fetchall()
    return [
        {
            "key": str(row["key"]),
            "score": round(float(row["score"]), 2) if row["score"] is not None else None,
            "samples": int(row["samples"]),
            "cycles": int(row["cycles"]),
        }
        for row in rows
    ]


def compute_guardrails(
    *,
    paths: RepoPaths,
    week: str,
    raw: dict[str, Any],
    rows: list[dict[str, Any]],
    usage: dict[str, Any],
    published_views: list[float],
    engagement_per_item: list[float],
    usable_items: int,
    reviewed_items: int,
) -> dict[str, float | None]:
    cost = usage.get("cost_usd")
    cost_per_item = None
    if cost is not None and usable_items > 0:
        cost_per_item = round(float(cost) / usable_items, 6)
    editing = raw.get("human_editing_minutes")
    if editing is None:
        editing_total = None
        try:
            payload = load_decisions(paths, week)
            values = [
                float(d["human_editing_minutes"])
                for d in payload["decisions"]
                if isinstance(d.get("human_editing_minutes"), (int, float))
            ]
            editing_total = sum(values) if values else None
        except GateFailure:
            editing_total = None
        if editing_total is not None:
            editing = round(editing_total / reviewed_items, 2) if reviewed_items > 0 else None
    else:
        # A total without a count of reviewed items is not a per-item number: unknown.
        editing = round(float(editing) / reviewed_items, 2) if reviewed_items > 0 else None

    runs = raw.get("workflow_runs")
    failures = raw.get("workflow_failures")
    failure_rate = None
    if isinstance(runs, int) and runs > 0 and isinstance(failures, int):
        failure_rate = round(failures / runs, 4)

    return {
        "first_pass_approval_rate": first_pass_approval_rate(paths),
        "api_cost_per_run_usd": cost,
        "cost_per_usable_item_usd": cost_per_item,
        "human_editing_minutes_per_item": editing,
        "workflow_failure_rate": failure_rate,
        "reach_per_published_item": round(statistics.fmean(published_views), 2) if published_views else None,
        "engagement_per_published_item": round(statistics.fmean(engagement_per_item), 2) if engagement_per_item else None,
        "qualified_inquiries_blueprint": raw.get("qualified_inquiries_blueprint"),
    }


def decide_themes(themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The written decision rule, applied mechanically (docs/05).

    Above-median theme earns 3 more cycles; below-median is cut. A theme with fewer than two
    supplied samples is 'insufficient_data' — not guessed. Formats are not decided here:
    they are never killed before 3 full cycles, and this function deliberately cannot do it.
    """
    scored = [t for t in themes if t["score"] is not None and t["samples"] >= 2]
    if not scored:
        return [
            {"theme": t["key"], "action": "insufficient_data", "evidence": f"{t['samples']} sample(s)"}
            for t in themes
        ]
    median = statistics.median([t["score"] for t in scored])
    decisions: list[dict[str, Any]] = []
    for theme in themes:
        if theme["score"] is None or theme["samples"] < 2:
            decisions.append(
                {
                    "theme": theme["key"],
                    "action": "insufficient_data",
                    "evidence": f"{theme['samples']} sample(s), no score",
                }
            )
        elif theme["score"] >= median:
            decisions.append(
                {
                    "theme": theme["key"],
                    "action": "continue_for_3_cycles",
                    "evidence": f"score {theme['score']} >= median {round(median, 2)} from {theme['samples']} samples",
                }
            )
        else:
            decisions.append(
                {
                    "theme": theme["key"],
                    "action": "cut",
                    "evidence": f"score {theme['score']} < median {round(median, 2)} from {theme['samples']} samples",
                }
            )
    return decisions


def deterministic_memo(
    *,
    week: str,
    aggregates: dict[str, Any],
    guardrails: dict[str, float | None],
    unknowns: list[str],
    decisions: list[dict[str, Any]],
) -> str:
    lines = [f"Week {week}: what should we do more of — with evidence?"]
    for theme in aggregates["themes"]:
        score = theme["score"] if theme["score"] is not None else "unknown"
        lines.append(f"- theme {theme['key']}: mean views {score} across {theme['samples']} samples")
    for fmt in aggregates["formats"]:
        score = fmt["score"] if fmt["score"] is not None else "unknown"
        lines.append(f"- format {fmt['key']}: mean views {score} across {fmt['samples']} samples")
    lines.append(
        f"- {len(unknowns)} metric value(s) were not supplied and remain unknown; none were estimated."
    )
    lines.append(
        "Decision rule: an above-median theme earns 3 more cycles; a below-median theme is cut; "
        "formats are never killed before 3 full cycles."
    )
    for decision in decisions:
        lines.append(f"- {decision['theme']}: {decision['action']} ({decision['evidence']})")
    lines.append(
        "First-pass approval rate: "
        + (
            f"{guardrails['first_pass_approval_rate']}"
            if guardrails["first_pass_approval_rate"] is not None
            else "unknown"
        )
        + "; qualified Blueprint inquiries: "
        + (
            str(guardrails["qualified_inquiries_blueprint"])
            if guardrails["qualified_inquiries_blueprint"] is not None
            else "unknown"
        )
    )
    return "\n".join(lines)


def write_scores(
    paths: RepoPaths,
    scores: dict[str, Any],
    *,
    authorized_by: str,
) -> Path:
    if authorized_by != SCORES_WRITER:
        raise GateFailure(
            "strategy/scores.json is written only by the Growth Analyst "
            f"(got {authorized_by!r}) — docs/02-agent-contracts.md"
        )
    paths.scores.parent.mkdir(parents=True, exist_ok=True)
    paths.scores.write_text(json.dumps(scores, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths.scores


def ingest_week(
    *,
    paths: RepoPaths,
    config: Config,
    week: str,
    raw_path: Path | None = None,
    client: SupportsCompletion | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    raw = load_raw(paths, week, path=raw_path)

    from . import content as content_mod

    week_items = content_mod.load_items(paths.drafts, paths, week=week)
    if not week_items:
        raise GateFailure(f"no content items found for {week}; ingest refuses to invent items")
    by_id = {item["content_id"]: item for item in week_items}

    for row in raw["items"]:
        if row["content_id"] not in by_id:
            raise GateFailure(
                f"stats reference unknown content_id {row['content_id']!r}; fix the raw file "
                "rather than trusting orphan numbers"
            )

    connection = connect(paths.sqlite)
    try:
        upsert_items(connection, week_items)
        analytics_rows, unknowns = record_performance(
            connection, rows=raw["items"], recorded_at=now.isoformat()
        )
        themes = _rollup(connection, "theme")
        formats = _rollup(connection, "format")
        hooks = _rollup(connection, "hook_family")
    finally:
        connection.close()

    published_views: list[float] = []
    engagement: list[float] = []
    for row in raw["items"]:
        item = by_id[row["content_id"]]
        if item.get("status") != "published":
            continue
        metrics = row.get("metrics") or {}
        if metrics.get("views") is not None:
            published_views.append(float(metrics["views"]))
        supplied_engagement = [float(metrics[m]) for m in ENGAGEMENT_METRICS if metrics.get(m) is not None]
        if supplied_engagement:
            engagement.append(sum(supplied_engagement))

    usage = summarise_usage(paths.usage_log, month=now.strftime("%Y-%m"))
    guardrails = compute_guardrails(
        paths=paths,
        week=week,
        raw=raw,
        rows=analytics_rows,
        usage=usage,
        published_views=published_views,
        engagement_per_item=engagement,
        usable_items=len([i for i in week_items if i.get("status") in {"approved", "published"}]),
        reviewed_items=len([
            d for d in (load_decisions(paths, week).get("decisions") or [])
        ]),
    )
    decisions = decide_themes(themes)
    aggregates = {"themes": themes, "formats": formats, "hooks": hooks}

    update: dict[str, Any] = {
        "generated_by": "growth-analyst",
        "week": week,
        "rows": analytics_rows,
        "unknowns": unknowns,
        "aggregates": aggregates,
        "memo": {
            "question": "What should we do more of — with evidence?",
            "text": deterministic_memo(
                week=week,
                aggregates=aggregates,
                guardrails=guardrails,
                unknowns=unknowns,
                decisions=decisions,
            ),
            "guardrail_metrics": guardrails,
            "decisions": decisions,
        },
    }

    if client is not None and client.mode != "dry_run":
        run = agents.run_growth_analyst(
            client=client,
            config=config,
            paths=paths,
            week=week,
            rows=analytics_rows,
            aggregates=aggregates,
            guardrail_metrics=guardrails,
            unknowns=unknowns,
        )
        proposed = run.payload
        # The model may phrase the memo; it may not change a single number or decision.
        update["memo"]["text"] = proposed["memo"]["text"]
        agents.check_memo_grounding(update)
    else:
        agents.check_memo_grounding(update, include_decisions=True)

    validate(update, paths, "analytics-update")
    paths.review.mkdir(parents=True, exist_ok=True)
    review_json = paths.review / f"{week}-analytics.json"
    review_json.write_text(json.dumps(update, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    memo_path = paths.review / f"{week}-analytics-memo.md"
    memo_path.write_text(
        f"# Analytics memo — {week}\n\n{update['memo']['text']}\n", encoding="utf-8"
    )

    scores = {
        "version": 1,
        "updated": now.isoformat(),
        "generated_by": "growth-analyst",
        "source": "analytics/marketing.sqlite (platform/founder-supplied values only)",
        "metric": "views (mean per key, supplied values only)",
        "weeks_observed": sorted({item.get("week") or item["content_id"][:8] for item in week_items}),
        "themes": themes,
        "formats": formats,
        "hooks": hooks,
        "median_theme_score": (
            round(statistics.median([t["score"] for t in themes if t["score"] is not None]), 2)
            if any(t["score"] is not None for t in themes)
            else None
        ),
        "decision_rule": {
            "theme": "above median -> continue_for_3_cycles; below median -> cut",
            "format": "never killed before 3 full cycles",
            "unknown": "missing data stays null; it is never estimated",
        },
    }
    write_scores(paths, scores, authorized_by="growth-analyst")
    update["_artifacts"] = [str(review_json.relative_to(paths.root)), str(memo_path.relative_to(paths.root)), str(paths.scores.relative_to(paths.root))]
    return update

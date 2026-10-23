"""Markdown review digests and GitHub Issue text (docs/01, docs/04).

The digest is the product of a cycle: what was planned, what passed QA, what was rejected
and why, and what Samuel has to decide. It never claims anything was published.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from .registry import Registry

BANNER = (
    "> Nothing in this repo posts, schedules, replies or spends money. Publication is "
    "manual, by Samuel, on each platform."
)


def _fmt_score(entry: dict[str, Any]) -> str:
    subs = entry.get("subscores") or {}
    parts = " · ".join(f"{key} {subs.get(key, '—')}" for key in (
        "hook_strength", "specificity_evidence", "clarity", "brand_fit", "platform_fit"
    ))
    return f"composite **{entry.get('composite', '—')}** ({parts})"


def render_digest(
    *,
    week: str,
    plan: dict[str, Any] | None,
    items: list[dict[str, Any]],
    qa_report: dict[str, Any] | None,
    failures: list[dict[str, str]],
    registry: Registry,
    usage: dict[str, Any] | None = None,
    expiring: list[dict[str, Any]] | None = None,
    generated_at: _dt.datetime | None = None,
) -> str:
    generated_at = generated_at or _dt.datetime.now(_dt.timezone.utc)
    degraded = bool(failures)
    status = "DEGRADED" if degraded else "OK"
    lines: list[str] = []
    lines.append(f"# Week {week} — review digest — {status}")
    lines.append("")
    lines.append(f"_Generated {generated_at.replace(microsecond=0).isoformat()} by the Inevitable Engine._")
    lines.append("")
    lines.append(BANNER)
    lines.append("")

    if degraded:
        lines.append("## DEGRADED — a step failed")
        lines.append("")
        lines.append("This week is incomplete. Nothing below should be treated as a full cycle.")
        lines.append("")
        for failure in failures:
            lines.append(f"- **{failure['step']}**: {failure['reason']}")
        lines.append("")

    lines.append("## Plan")
    lines.append("")
    if plan:
        for line in plan.get("summary_5_lines") or []:
            lines.append(f"- {line}")
        if plan.get("supporting_only"):
            lines.append(f"- Supporting-only week: {plan.get('supporting_only_reason')}")
    else:
        lines.append("- No plan was produced (see DEGRADED section).")
    lines.append("")

    in_review = [item for item in items if item.get("status") == "in_review"]
    rejected = [item for item in items if item.get("status") == "rejected"]
    others = [item for item in items if item.get("status") not in {"in_review", "rejected"}]
    qa_by_id = {entry["content_id"]: entry for entry in (qa_report or {}).get("items", [])}

    lines.append(f"## Ready for Samuel ({len(in_review)})")
    lines.append("")
    if not in_review:
        lines.append("- Nothing passed QA this week.")
    for item in in_review:
        entry = qa_by_id.get(item["content_id"], {})
        lines.append(f"### `{item['content_id']}` — {item['format']} — {item.get('working_title') or item.get('campaign')}")
        lines.append("")
        lines.append(f"- Platforms: {', '.join(item.get('platforms') or [])}")
        lines.append(f"- Hook: “{item.get('hook')}”")
        lines.append(f"- Claims: {', '.join(item.get('claims') or []) or 'none'}")
        lines.append(f"- QA: {_fmt_score(entry)}")
        suggestions = entry.get("edit_suggestions") or []
        if suggestions:
            lines.append("- QA suggestions (QA does not rewrite):")
            for suggestion in suggestions:
                lines.append(f"  - {suggestion}")
        lines.append("")
    lines.append("")

    lines.append(f"## Rejected by QA ({len(rejected)})")
    lines.append("")
    if not rejected:
        lines.append("- None.")
    for item in rejected:
        entry = qa_by_id.get(item["content_id"], {})
        codes = ", ".join(entry.get("reason_codes") or []) or str(item.get("rejection_reason") or "—")
        lines.append(f"- `{item['content_id']}` — reason: **{codes}**")
        if item.get("rejection_note"):
            lines.append(f"  - note: {item['rejection_note']}")
    lines.append("")

    if others:
        lines.append("## Not yet in review")
        lines.append("")
        for item in others:
            lines.append(f"- `{item['content_id']}` — status {item.get('status')}")
        lines.append("")

    lines.append("## Claims used this week")
    lines.append("")
    used: list[str] = []
    for item in items:
        for claim_id in item.get("claims") or []:
            if claim_id not in used:
                used.append(claim_id)
    if not used:
        lines.append("- No claims were cited.")
    for claim_id in used:
        entry = registry.get(claim_id)
        state = registry.status(claim_id)
        if entry:
            lines.append(
                f"- `{claim_id}` ({state}, expires {entry.get('expires')}): {entry.get('statement')}"
            )
        else:
            lines.append(f"- `{claim_id}` — **missing from registry**")
    lines.append("")

    if expiring:
        lines.append("## Evidence expiring soon")
        lines.append("")
        for row in expiring:
            lines.append(f"- `{row['claim_id']}` expires {row['expires']}: {row['statement']}")
        lines.append("")

    if usage is not None:
        cost = usage.get("cost_usd")
        cost_text = f"${cost}" if cost is not None else "unknown (no prices configured — not estimated)"
        lines.append("## Budget")
        lines.append("")
        lines.append(f"- Live API calls this month: {usage.get('calls', 0)}")
        lines.append(f"- Tokens this month: {usage.get('tokens', 0)}")
        lines.append(f"- Cost this month: {cost_text}")
        lines.append("")

    lines.append("## Samuel's decision")
    lines.append("")
    if in_review:
        lines.append("Run:")
        lines.append("")
        lines.append(f"    make review W={week}")
        lines.append("")
        lines.append(
            "Then publish manually, at your own pace, on each platform. Record the real URL "
            "with `python -m amplify mark-published --id <content_id> --platform <platform> --url <url>`."
        )
    else:
        lines.append("Nothing to approve this week.")
    lines.append("")
    return "\n".join(lines)


def render_plan_comment(week: str, plan: dict[str, Any]) -> str:
    lines = [f"## Plan for {week}"]
    lines.append("")
    for line in plan.get("summary_5_lines") or []:
        lines.append(f"- {line}")
    lines.append("")
    hero = plan.get("hero")
    if hero:
        lines.append(f"**Hero:** {hero['format']} — {hero['working_title']}")
        lines.append("")
        lines.append(f"Angle: {hero['angle']}")
        lines.append("")
        lines.append(
            "Derivatives: "
            + ", ".join(f"{d['platform']} ({d['native_form']})" for d in hero.get("derivatives") or [])
        )
        lines.append("")
        lines.append(f"Claims: {', '.join(hero.get('claims') or []) or 'none'}")
    else:
        lines.append(f"**Supporting-only week** — {plan.get('supporting_only_reason')}")
    lines.append("")
    lines.append("Reply with approve/adjust, or edit `strategy/plans/%s-plan.json`." % week)
    return "\n".join(lines)


def render_issue_text(*, week: str, failures: list[dict[str, str]], artifacts: list[str]) -> str:
    lines = [f"### Cycle {week} is DEGRADED", ""]
    lines.append("The Inevitable Engine stopped part of this week's cycle. Nothing was published, scheduled or sent.")
    lines.append("")
    lines.append("**Failures**")
    for failure in failures:
        lines.append(f"- `{failure['step']}`: {failure['reason']}")
    lines.append("")
    if artifacts:
        lines.append("**Artifacts**")
        for artifact in artifacts:
            lines.append(f"- `{artifact}`")
        lines.append("")
    lines.append(
        f"Re-run after fixing the cause: `python -m amplify run-weekly --week {week} --dry-run`."
    )
    return "\n".join(lines)

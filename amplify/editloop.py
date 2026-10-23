"""The controlled learning loop (docs/05).

Captures what Samuel changed and rejected, distils it into ONE proposal, and stops.

* Never edits ``brand/`` directly — the proposal is a PR for Samuel to merge or discard.
* Never invents voice samples: additions are built from text Samuel actually wrote.
* Merging is the training signal; ignoring the PR is also a signal.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

import yaml

from . import content as content_mod
from .config import RepoPaths
from .errors import AmplifyError
from .schemas import validate


def gather(paths: RepoPaths, week: str) -> dict[str, Any]:
    path = paths.review / f"decisions-{week}.yaml"
    edits: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    if path.exists():
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for decision in payload.get("decisions") or []:
            for edit in decision.get("edits") or []:
                edits.append(
                    {
                        "content_id": decision["content_id"],
                        "field": edit["field"],
                        "before": edit["before"],
                        "after": edit["after"],
                        "note": decision.get("note"),
                    }
                )
            if decision.get("decision") == "reject":
                rejections.append(decision)
                code = decision.get("reason_code") or "UNSPECIFIED"
                reason_counts[code] = reason_counts.get(code, 0) + 1
    return {"edits": edits, "rejections": rejections, "reason_counts": reason_counts}


def _context_for(paths: RepoPaths, content_id: str) -> str:
    """Tag an addition by the audience of the item Samuel edited."""
    try:
        item = content_mod.load_item(content_mod.item_path(paths, content_id), paths)
    except AmplifyError:
        return "founder-note"
    audience = " ".join(str(a) for a in item.get("audience") or [])
    if "kenya" in audience:
        return "kenya-audience"
    if "global" in audience:
        return "global-audience"
    return "founder-note"


def build_proposal(paths: RepoPaths, week: str, *, generated_at: _dt.datetime | None = None) -> dict[str, Any]:
    evidence = gather(paths, week)
    additions: list[dict[str, Any]] = []
    for edit in evidence["edits"]:
        after = str(edit["after"]).strip()
        if len(after.split()) < 12:
            continue
        context = _context_for(paths, edit["content_id"])
        additions.append(
            {
                "context": context,
                "source": f"Samuel's edit to {edit['content_id']} / {edit['field']}",
                "text": after,
                "synthetic": False,
            }
        )

    notes: list[str] = []
    if evidence["edits"]:
        notes.append(
            f"Samuel rewrote {len(evidence['edits'])} field(s) this week. The additions below are "
            "his own words, taken verbatim from the review diff — never generated."
        )
    if evidence["reason_counts"]:
        notes.append(
            "Rejections by reason: "
            + ", ".join(f"{code} x{count}" for code, count in sorted(evidence["reason_counts"].items()))
            + ". Rejections with PERSONAL mean Samuel will rewrite; do not patch the system for those."
        )
    if not evidence["edits"] and not evidence["rejections"]:
        notes.append("No edits and no rejections this week: nothing to learn from yet. No patch proposed.")

    pr_body = "\n".join(
        [
            f"## voice: week {week} learnings",
            "",
            "Proposed by the Edit Loop from Samuel's actual review decisions. **Merging is the",
            "training signal.** Nothing here is applied automatically.",
            "",
            "### Evidence",
            f"- edits captured: {len(evidence['edits'])}",
            f"- rejections: {len(evidence['rejections'])}",
            "",
            "### Notes",
            *[f"- {note}" for note in notes],
            "",
            "### Review checklist",
            "- [ ] Voice additions are verbatim Samuel text (no synthetic samples).",
            "- [ ] Fingerprint changes are founder-signed.",
            "- [ ] Producer instruction changes do not weaken any gate.",
        ]
    )
    proposal = {
        "generated_by": "edit-loop",
        "week": week,
        "evidence": {
            "edits": len(evidence["edits"]),
            "rejections": len(evidence["rejections"]),
            "reason_counts": evidence["reason_counts"],
        },
        "voice_library_additions": additions,
        "fingerprint_patch": None,
        "producer_instruction_patch": None,
        "pr_title": f"voice: week {week} learnings",
        "pr_body_markdown": pr_body,
    }
    validate(proposal, paths, "edit-proposal")
    return proposal


def write_proposal(paths: RepoPaths, proposal: dict[str, Any]) -> tuple[Path, Path]:
    week = proposal["week"]
    json_path = paths.review / f"{week}-voice-proposal.json"
    md_path = paths.review / f"{week}-voice-proposal.md"
    json_path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(
        "# " + proposal["pr_title"] + "\n\n" + proposal["pr_body_markdown"] + "\n", encoding="utf-8"
    )
    return json_path, md_path


def next_steps(paths: RepoPaths, proposal: dict[str, Any]) -> list[str]:
    week = proposal["week"]
    branch = f"feat/voice-{week.lower()}"
    return [
        f"git switch -c {branch}",
        "mkdir -p brand/voice-library",
        f"# copy approved additions from content/review/{week}-voice-proposal.json",
        f"git add brand/voice-library content/review/{week}-voice-proposal.json",
        f'git commit -m "voice: week {week} learnings"',
        f"git push -u origin {branch}",
        f'gh pr create --title "voice: week {week} learnings" --body-file content/review/{week}-voice-proposal.md',
    ]

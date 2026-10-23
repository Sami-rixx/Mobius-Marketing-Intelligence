"""Rubric scoring and the QA gate (docs/03).

The gate is not a model. A model may *propose* subscores; :func:`apply_gates` decides the
verdict, and it always wins:

* any blocking lint finding -> reject with that reason code;
* composite below the rubric threshold -> reject (auto-reject < 70);
* a rejected item must carry at least one documented reason code.

The heuristic scorer below is deterministic and used in dry runs and tests. In live mode the
QA judge proposes subscores; the same gate then applies, so a generous judge cannot pass a
falsified claim.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .brand import BrandMaterials
from .config import RepoPaths
from .errors import ConfigError
from .lint import LintResult, has_receipt_signal, item_text, sentences, tokens

RUBRIC_FILE = "rubric.json"

# Lowest-scoring dimension -> documented reason code. The lowest dimension is the most
# actionable explanation of "why did this fail?"; clarity has no dedicated code, so it maps
# to TOO_GENERIC (the documented catch-all for "could be any AI brand").
DIMENSION_REASON = {
    "hook_strength": "WEAK_HOOK",
    "specificity_evidence": "TOO_GENERIC",
    "clarity": "TOO_GENERIC",
    "brand_fit": "OFF_BRAND",
    "platform_fit": "WRONG_AUDIENCE",
}


def load_rubric(paths: RepoPaths) -> dict[str, Any]:
    path = paths.schemas / RUBRIC_FILE
    try:
        rubric = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"rubric file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"rubric file is not valid JSON: {path}: {exc}") from exc
    dims = rubric.get("dimensions") or []
    if sum(int(d["weight"]) for d in dims) != 100:
        raise ConfigError("rubric dimension weights must sum to 100")
    if not isinstance(rubric.get("threshold"), (int, float)):
        raise ConfigError("rubric threshold must be numeric")
    return rubric


def composite(subscores: dict[str, float], rubric: dict[str, Any]) -> float:
    total = 0.0
    for dimension in rubric["dimensions"]:
        total += float(subscores[dimension["id"]]) * float(dimension["weight"]) / 100.0
    return round(total, 2)


def heuristic_subscores(
    item: dict[str, Any], lint: LintResult, materials: BrandMaterials
) -> dict[str, float]:
    """Deterministic editorial proxy. Documented in docs/07-implementation-notes.md."""
    hook = str(item.get("hook") or "")
    text = item_text(item)
    body = str(item.get("script") or "")

    hook_score = 55.0
    hook_length = len(hook)
    if hook_length <= 60:
        hook_score += 20
    elif hook_length <= 100:
        hook_score += 12
    elif hook_length <= 140:
        hook_score += 4
    else:
        hook_score -= 15
    if re.search(r"\d", hook):
        hook_score += 10
    if has_receipt_signal(hook, materials):
        hook_score += 10
    if re.search(r"\b(I|we|my|our)\b", hook):
        hook_score += 5
    if "?" in hook:
        hook_score -= 5
    hook_score = max(0.0, min(100.0, hook_score))

    receipt_hits = sum(
        1
        for pattern in materials.rules.get("required_receipt_signals", [])
        if re.search(pattern, text, re.IGNORECASE)
    )
    specificity = 35.0 + min(3, receipt_hits) * 15 + (10 if len(item.get("claims") or []) >= 2 else 0)
    specificity = max(0.0, min(100.0, specificity))

    sentence_list = sentences(body)
    mean = (sum(len(s.split()) for s in sentence_list) / len(sentence_list)) if sentence_list else 0
    clarity = 95.0
    if mean > 26:
        clarity -= min(35.0, (mean - 26) * 2.5)
    if mean and mean < 6:
        clarity -= 5
    if len(tokens(body)) < 20:
        clarity -= 10
    clarity = max(0.0, min(100.0, clarity))

    brand_fit = 100.0 - 25.0 * len([f for f in lint.findings if f.code == "OFF_BRAND"])
    brand_fit = max(0.0, min(100.0, brand_fit))

    platforms = set(item.get("platforms") or [])
    platform_fit = 70.0
    if item.get("format") == "FMT-01" and "youtube" in platforms:
        platform_fit += 15
    if item.get("format") == "FMT-02" and platforms & {"tiktok", "shorts"}:
        platform_fit += 15
    if item.get("format") == "FMT-03" and platforms & {"facebook", "instagram"}:
        platform_fit += 15
    if len(platforms) >= 3:
        platform_fit += 5
    if len(hook) > 140 and platforms & {"tiktok", "shorts"}:
        platform_fit -= 20
    platform_fit = max(0.0, min(100.0, platform_fit))

    return {
        "hook_strength": round(hook_score, 2),
        "specificity_evidence": round(specificity, 2),
        "clarity": round(clarity, 2),
        "brand_fit": round(brand_fit, 2),
        "platform_fit": round(platform_fit, 2),
    }


def lowest_dimension(subscores: dict[str, float]) -> str:
    return min(subscores, key=lambda key: (subscores[key], key))


def apply_gates(
    subscores: dict[str, float],
    lint: LintResult,
    rubric: dict[str, Any],
) -> dict[str, Any]:
    """Return the authoritative verdict block for one item."""
    comp = composite(subscores, rubric)
    threshold = float(rubric["threshold"])
    codes: list[str] = list(lint.codes)

    if subscores["hook_strength"] < 50 and "WEAK_HOOK" not in codes:
        codes.append("WEAK_HOOK")
    if comp < threshold:
        code = DIMENSION_REASON[lowest_dimension(subscores)]
        if code not in codes:
            codes.append(code)

    verdict = "reject" if codes else "pass"
    return {
        "verdict": verdict,
        "reason_codes": codes,
        "subscores": {key: round(float(value), 2) for key, value in subscores.items()},
        "composite": comp,
        "threshold": threshold,
        "threshold_met": comp >= threshold,
    }


def build_qa_item(
    item: dict[str, Any],
    lint: LintResult,
    rubric: dict[str, Any],
    materials: BrandMaterials,
    *,
    proposed_subscores: dict[str, float] | None = None,
    suggestions: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    subscores = proposed_subscores or heuristic_subscores(item, lint, materials)
    gate = apply_gates(subscores, lint, rubric)
    # Explicit bucketing keeps QA output readable and schema-stable.
    grouped = {
        "claims": [f.render() for f in lint.findings if f.code == "UNVERIFIED_CLAIM"],
        "brand": [f.render() for f in lint.findings if f.code in {"OFF_BRAND", "TOO_GENERIC"}],
        "voice": [f.render() for f in lint.findings if f.code == "VOICE"],
    }
    default_suggestions = [f.render() for f in lint.findings if f.blocking] or [
        "No blocking issues. Send to Samuel for the publication decision."
    ]
    return {
        "content_id": item["content_id"],
        "verdict": gate["verdict"],
        "reason_codes": gate["reason_codes"],
        "subscores": gate["subscores"],
        "composite": gate["composite"],
        "lint": grouped,
        "edit_suggestions": suggestions or default_suggestions,
        "notes": notes or (f"threshold {gate['threshold']}; composite {gate['composite']}"),
    }

"""Deterministic quality gates.

These run in CI and inside the weekly cycle. They are intentionally boring and
deterministic: the same item always gets the same verdict, so a rejection can be explained
on a phone screen and a false claim cannot slip through because a model was in a good mood.

Reason codes come from docs/03-content-schema.md (schemas/rubric.json).
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .brand import BrandMaterials
from .registry import Registry

# docs/03 rejection taxonomy — the only legal rejection reasons.
REASON_CODES = frozenset(
    {
        "VOICE",
        "UNVERIFIED_CLAIM",
        "OFF_BRAND",
        "WEAK_HOOK",
        "WRONG_AUDIENCE",
        "TOO_GENERIC",
        "PERSONAL",
    }
)
BLOCKING_CODES = set(REASON_CODES)
INFO = "INFO"

TEXT_FIELDS = ("hook", "script", "caption", "cta", "visual_brief")
EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF" "\U00002B00-\U00002BFF" "]"
)
HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[a-z0-9']+")
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "you", "your", "are", "was", "were",
    "have", "has", "had", "not", "but", "from", "they", "them", "its", "it's", "our",
    "out", "into", "about", "just", "can", "will", "what", "when", "how", "why", "all",
    "one", "two", "his", "her", "she", "him", "then", "than", "there", "here", "been",
    "being", "because", "while", "where", "who", "whom", "which", "would", "could",
    "should", "very", "more", "most", "much", "some", "any", "only", "also", "like",
}


@dataclass(frozen=True)
class Finding:
    code: str
    rule: str
    message: str
    field: str = ""

    @property
    def blocking(self) -> bool:
        return self.code in BLOCKING_CODES

    def render(self) -> str:
        where = f" [{self.field}]" if self.field else ""
        return f"{self.code} ({self.rule}){where}: {self.message}"


@dataclass
class LintResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if not f.blocking]

    @property
    def codes(self) -> list[str]:
        seen: list[str] = []
        for finding in self.blocking:
            if finding.code not in seen:
                seen.append(finding.code)
        return seen

    @property
    def ok(self) -> bool:
        return not self.blocking

    def extend(self, others: Iterable[Finding]) -> "LintResult":
        self.findings.extend(others)
        return self

    def messages(self) -> list[str]:
        return [f.render() for f in self.findings]


# --------------------------------------------------------------------------- helpers
def item_text(item: dict[str, Any], fields: Iterable[str] = TEXT_FIELDS) -> str:
    return "\n".join(str(item.get(name) or "") for name in fields)


def item_audience_text(item: dict[str, Any]) -> str:
    return " ".join(str(a) for a in item.get("audience") or [])


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term)
    flags = 0
    if term.isupper() and len(term) <= 3:
        # Acronyms such as "GA" must match literally; "ga" appears inside normal words.
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])")
    if " " in term or "-" in term:
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", flags | re.IGNORECASE)
    return re.compile(rf"\b{escaped}\b", flags | re.IGNORECASE)


def find_terms(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if _term_pattern(term).search(text)]


def sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_RE.split(text.strip()) if part.strip()]


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text.lower()))


def tokens(text: str) -> set[str]:
    return {word for word in WORD_RE.findall(text.lower()) if len(word) > 2 and word not in STOPWORDS}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def has_receipt_signal(text: str, materials: BrandMaterials) -> bool:
    for pattern in materials.rules.get("required_receipt_signals", []):
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _status_claim_covers(term: str, item: dict[str, Any], registry: Registry, as_of: _dt.date) -> bool:
    """A product-status word is allowed only when a cited, valid claim states it."""
    pattern = _term_pattern(term)
    for claim_id in item.get("claims") or []:
        entry = registry.get(claim_id)
        if entry is None or not registry.is_valid(claim_id, as_of):
            continue
        if pattern.search(str(entry.get("statement", ""))):
            return True
    return False


# --------------------------------------------------------------------------- lints
def claims_lint(
    item: dict[str, Any], registry: Registry, *, as_of: _dt.date | None = None
) -> list[Finding]:
    as_of = as_of or _dt.date.today()
    findings: list[Finding] = []
    claim_ids = item.get("claims") or []
    if not claim_ids and item.get("status") != "draft":
        findings.append(
            Finding(
                "UNVERIFIED_CLAIM",
                "claims.empty",
                "no claims cited: a reviewable item must show receipts (Proof-of-Work Marketing)",
                "claims",
            )
        )
    for claim_id in claim_ids:
        state = registry.status(claim_id, as_of)
        if state == "valid":
            continue
        if state == "missing":
            message = f"{claim_id} is not in claims/registry.json"
        elif state == "expired":
            message = f"{claim_id} expired on {registry.entries[claim_id]['expires']}"
        elif state == "quarantined":
            message = (
                f"{claim_id} is quarantined: "
                f"{registry.entries[claim_id].get('quarantine_reason') or 'no reason recorded'}"
            )
        else:
            message = f"{claim_id} is unusable ({state})"
        findings.append(Finding("UNVERIFIED_CLAIM", f"claims.{state}", message, "claims"))
    return findings


def brand_lint(
    item: dict[str, Any], materials: BrandMaterials, registry: Registry, *, as_of: _dt.date | None = None
) -> list[Finding]:
    as_of = as_of or _dt.date.today()
    rules = materials.rules
    findings: list[Finding] = []

    for name in TEXT_FIELDS:
        text = str(item.get(name) or "")
        if not text:
            continue

        hits = find_terms(text, rules.get("banned_marketing_phrases", []))
        for hit in hits:
            findings.append(Finding("OFF_BRAND", "brand.banned_phrase", f"banned phrase {hit!r}", name))

        hype = find_terms(text, rules.get("banned_hype_shapes", []))
        for hit in hype:
            findings.append(Finding("OFF_BRAND", "brand.hype_shape", f"banned hype shape {hit!r}", name))

        retired = find_terms(text, rules.get("retired_taglines", []))
        for hit in retired:
            findings.append(
                Finding(
                    "OFF_BRAND",
                    "brand.retired_tagline",
                    f"retired tagline {hit!r}; canonical tagline is "
                    f"{rules.get('canonical_tagline')!r}",
                    name,
                )
            )

        if re.search(r"\binevitable\b", text, re.IGNORECASE):
            canonical = rules.get("canonical_tagline", "Making Ideas Inevitable")
            if canonical not in text:
                findings.append(
                    Finding(
                        "OFF_BRAND",
                        "brand.tagline_variation",
                        f"uses 'inevitable' without the canonical tagline {canonical!r}",
                        name,
                    )
                )

        hard_status = find_terms(text, rules.get("unapproved_product_status_terms", []))
        for hit in hard_status:
            if not _status_claim_covers(hit, item, registry, as_of):
                findings.append(
                    Finding(
                        "OFF_BRAND",
                        "brand.unapproved_status",
                        f"product-status word {hit!r} has no registry receipt",
                        name,
                    )
                )
        soft_status = find_terms(text, rules.get("soft_product_status_terms", []))
        for hit in soft_status:
            if not _status_claim_covers(hit, item, registry, as_of):
                findings.append(
                    Finding(
                        INFO,
                        "brand.softer_status",
                        f"{hit!r} implies progress; only use it with a registry receipt",
                        name,
                    )
                )

        throat = find_terms(text, rules.get("corporate_throat_clearing", []))
        for hit in throat:
            findings.append(
                Finding("VOICE", "voice.throat_clearing", f"corporate phrasing {hit!r}", name)
            )

        if len(EMOJI_RE.findall(text)) > int(rules.get("max_emoji", 2)):
            findings.append(
                Finding("VOICE", "voice.emoji_wall", "too many emoji; they are not evidence", name)
            )

        limit = int(rules.get("max_sentence_words", 45))
        for sentence in sentences(text):
            length = len(sentence.split())
            if length > limit:
                findings.append(
                    Finding(
                        "VOICE",
                        "voice.sentence_length",
                        f"a {length}-word sentence exceeds the {limit}-word limit",
                        name,
                    )
                )
                break

        for hexcode in HEX_RE.findall(text):
            if materials.palette and hexcode.upper() not in materials.palette:
                findings.append(
                    Finding(
                        "OFF_BRAND",
                        "brand.off_palette",
                        f"colour {hexcode} is off-palette (allowed: {', '.join(materials.palette)})",
                        name,
                    )
                )

    receipt_text = item_text(item, ("script", "visual_brief", "hook"))
    if not has_receipt_signal(receipt_text, materials):
        findings.append(
            Finding(
                "TOO_GENERIC",
                "brand.no_receipt",
                "no artifact, number, repo, CI run or claim id appears anywhere: "
                "this could be any AI brand",
                "script",
            )
        )
    return findings


def voice_lint(item: dict[str, Any], materials: BrandMaterials) -> list[Finding]:
    findings: list[Finding] = []
    fingerprint = materials.fingerprint
    text = item_text(item)

    target_mean = (fingerprint.get("sentence_length") or {}).get("target_mean_words")
    if target_mean and sentences(text):
        mean = sum(len(s.split()) for s in sentences(text)) / len(sentences(text))
        if mean > float(target_mean) * 1.35:
            findings.append(
                Finding(
                    "VOICE",
                    "voice.mean_sentence_length",
                    f"mean sentence length {mean:.1f} words, fingerprint target {target_mean}",
                    "script",
                )
            )

    if not materials.calibrated:
        readiness = (
            f"{len(materials.samples)} real voice sample(s); calibrated flag "
            f"{'on' if fingerprint.get('calibrated') else 'off'}"
        )
        findings.append(
            Finding(
                INFO,
                "voice.uncalibrated",
                "voice similarity is not blocking yet — Samuel reviews register himself "
                f"({readiness})",
                "script",
            )
        )
        return findings

    min_jaccard = float((fingerprint.get("similarity") or {}).get("min_jaccard", 0.12))
    library_tokens: set[str] = set()
    for sample in materials.samples:
        library_tokens |= tokens(sample.text)
    similarity = jaccard(tokens(text), library_tokens)
    if similarity < min_jaccard:
        findings.append(
            Finding(
                "VOICE",
                "voice.similarity",
                f"similarity {similarity:.3f} is below the {min_jaccard:.2f} floor set in "
                "brand/voice-fingerprint.md",
                "script",
            )
        )
    return findings


def platform_lint(item: dict[str, Any], materials: BrandMaterials) -> list[Finding]:
    findings: list[Finding] = []
    platform_rules = materials.rules.get("platform_format_rules", {})
    required = platform_rules.get(item.get("format"), [])
    platforms = set(item.get("platforms") or [])
    # The primary-platform rule applies to the hero/original asset. A derivative is
    # *supposed* to live on another platform (docs/04 atomization rule).
    if required and not item.get("deriv_of") and not (platforms & set(required)):
        findings.append(
            Finding(
                "WRONG_AUDIENCE",
                "platform.format_mismatch",
                f"{item.get('format')} must run on one of {required}; got {sorted(platforms)}",
                "platforms",
            )
        )
    if item.get("format") == "FMT-03":
        audience = item_audience_text(item)
        if "kenya" not in audience:
            findings.append(
                Finding(
                    INFO,
                    "platform.kenya_audience",
                    "FMT-03 targets Kenyan school owners but no kenya-* audience is set",
                    "audience",
                )
            )
    return findings


def atomization_lint(items: list[dict[str, Any]]) -> dict[str, list[Finding]]:
    """Derivatives must be native re-expressions, not copy-paste (docs/04).

    Returns findings keyed by content_id so they can join that item's QA report.
    """
    findings: dict[str, list[Finding]] = {}
    by_id = {item.get("content_id"): item for item in items}
    hooks: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        hook = str(item.get("hook") or "").strip().lower()
        if hook:
            hooks.setdefault(hook, []).append(item)
    for hook, sharing in hooks.items():
        if len(sharing) < 2 or len(hook.split()) <= 3:
            continue
        platforms = sorted({p for item in sharing for p in (item.get("platforms") or [])})
        for item in sharing:
            findings.setdefault(item["content_id"], []).append(
                Finding(
                    "VOICE",
                    "atomization.copy_paste_hook",
                    f"the same hook appears in {len(sharing)} items across {platforms}; "
                    "re-express natively per platform (docs/04 atomization rule)",
                    "hook",
                )
            )
    for item in items:
        deriv = item.get("deriv_of")
        if not deriv:
            continue
        hero = by_id.get(deriv)
        if hero is None:
            findings.setdefault(item["content_id"], []).append(
                Finding(
                    "WRONG_AUDIENCE",
                    "atomization.missing_hero",
                    f"derivative cites hero {deriv} which is not in this week's items",
                    "deriv_of",
                )
            )
            continue
        if set(item.get("platforms") or []) == set(hero.get("platforms") or []):
            findings.setdefault(item["content_id"], []).append(
                Finding(
                    "WRONG_AUDIENCE",
                    "atomization.same_platform",
                    "derivative repeats the hero's platforms instead of a platform-native cut",
                    "platforms",
                )
            )
    return findings


def lint_item(
    item: dict[str, Any],
    materials: BrandMaterials,
    registry: Registry,
    *,
    as_of: _dt.date | None = None,
) -> LintResult:
    result = LintResult()
    result.extend(claims_lint(item, registry, as_of=as_of))
    result.extend(brand_lint(item, materials, registry, as_of=as_of))
    result.extend(voice_lint(item, materials))
    result.extend(platform_lint(item, materials))
    return result

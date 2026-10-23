"""Brand, voice, platform and atomization lints (docs/03 rule 3-4, docs/04)."""

from __future__ import annotations


import pytest

from amplify.lint import atomization_lint, brand_lint, platform_lint, voice_lint
from tests.conftest import draft_item, review_item


def findings(item, materials, registry):
    return brand_lint(item, materials, registry)


def rules(item, materials, registry):
    return {finding.rule for finding in findings(item, materials, registry)}


def test_clean_fixture_has_no_brand_findings(demo_registry, materials):
    assert findings(review_item(), materials, demo_registry) == []


@pytest.mark.parametrize("phrase", ["game-changer", "revolutionary", "unlock the power", "Disrupt"])
def test_banned_marketing_phrases_are_caught(phrase, demo_registry, materials):
    item = review_item(hook=f"{phrase}: our new timetable tool")
    result = findings(item, materials, demo_registry)
    assert any(f.code == "OFF_BRAND" and f.rule == "brand.banned_phrase" for f in result)


def test_banned_phrase_matching_is_word_bounded(demo_registry, materials):
    """"10x" is banned; "10x-ray" style text must not break the linter."""
    item = review_item(script="I measured the benchmark at 10 times the baseline. 132 tests agree.")
    assert not any(f.rule == "brand.banned_phrase" for f in findings(item, materials, demo_registry))


def test_retired_tagline_is_caught(demo_registry, materials):
    item = review_item(caption="Möbius Muse — The Inevitable Form")
    result = findings(item, materials, demo_registry)
    assert any(f.rule == "brand.retired_tagline" for f in result)


def test_canonical_tagline_is_allowed(demo_registry, materials):
    item = review_item(caption="Möbius Muse — Making Ideas Inevitable. Commit 59a5a6d.")
    assert not any(f.code == "OFF_BRAND" for f in findings(item, materials, demo_registry))


def test_inevitable_without_canonical_tagline_is_off_brand(demo_registry, materials):
    item = review_item(caption="Making the timetable inevitable. Receipt: CLM-101.")
    result = findings(item, materials, demo_registry)
    assert any(f.rule == "brand.tagline_variation" for f in result)


def test_off_palette_colour_is_caught(demo_registry, materials):
    item = review_item(visual_brief="Deep pink #FF00AA gradient background, terminal screenshot.")
    result = findings(item, materials, demo_registry)
    assert any(f.rule == "brand.off_palette" for f in result)


def test_palette_colour_is_allowed(demo_registry, materials):
    item = review_item(visual_brief="Deep Muse Blue #0A2463 card with the CI badge.")
    assert not any(f.rule == "brand.off_palette" for f in findings(item, materials, demo_registry))


@pytest.mark.parametrize("term", ["production-ready", "battle-tested", "profitable", "thousands of users"])
def test_unapproved_product_status_is_caught(term, demo_registry, materials):
    item = review_item(script=f"The timetable importer is {term}. 132 tests pass at commit 59a5a6d.")
    result = findings(item, materials, demo_registry)
    assert any(f.rule == "brand.unapproved_status" for f in result)


def test_product_status_allowed_when_a_valid_claim_states_it(demo_registry, materials):
    item = review_item(
        claims=["CLM-106"],
        script="The importer has been in production at one school since May. Tests: 132 at commit 59a5a6d.",
    )
    result = findings(item, materials, demo_registry)
    assert not any(f.rule == "brand.unapproved_status" for f in result)


def test_product_status_claim_must_be_valid(demo_registry, materials):
    item = review_item(
        claims=["CLM-102"],
        script="The importer has been in production since May. Commit 59a5a6d, 132 tests.",
    )
    result = findings(item, materials, demo_registry)
    assert any(f.rule == "brand.unapproved_status" for f in result)


def test_generic_ai_phrase_is_caught(demo_registry, materials):
    item = review_item(script="We are thrilled to announce our new AI journey. 132 tests at commit 59a5a6d.")
    assert any(f.rule == "voice.throat_clearing" for f in findings(item, materials, demo_registry))


def test_no_receipt_means_too_generic(demo_registry, materials):
    item = review_item(
        script="Software should be simple. We build tools that help people focus on what matters.",
        visual_brief="A clean graphic.",
        hook="Better software for everyone.",
        claims=["CLM-101"],
    )
    result = findings(item, materials, demo_registry)
    assert any(f.code == "TOO_GENERIC" for f in result)


def test_emoji_wall_is_a_voice_failure(demo_registry, materials):
    item = review_item(caption="Big week 🚀🔥🎉💡 for the importer, commit 59a5a6d")
    result = findings(item, materials, demo_registry)
    assert any(f.rule == "voice.emoji_wall" for f in result)


def test_overlong_sentence_is_a_voice_failure(demo_registry, materials):
    long_sentence = " ".join(["word"] * 60) + "."
    item = review_item(script=f"{long_sentence} Commit 59a5a6d, 132 tests.")
    result = findings(item, materials, demo_registry)
    assert any(f.rule == "voice.sentence_length" for f in result)


def test_uncalibrated_voice_is_reported_not_faked(demo_registry, materials):
    """An uncalibrated fingerprint must never produce a fake similarity verdict."""
    result = voice_lint(review_item(), materials)
    assert [f.rule for f in result if f.code == "INFO"] == ["voice.uncalibrated"]
    assert not [f for f in result if f.blocking]


def test_calibrated_fingerprint_can_reject_on_similarity(demo_registry, materials):
    from amplify.brand import VoiceSample

    materials.fingerprint["calibrated"] = True
    materials.samples = [
        VoiceSample(
            path=__file__,
            context="founder-note",
            source="test",
            text="timetable importer phone build receipt tests commit",
        )
    ] * 3
    assert materials.calibrated is True
    result = voice_lint(review_item(script="Corporate synergy across verticals and paradigms today."), materials)
    assert any(f.rule == "voice.similarity" for f in result)


def test_platform_mismatch_for_format(demo_registry, materials):
    item = draft_item(format="FMT-01", platforms=["tiktok"], deriv_of=None)
    result = platform_lint(item, materials)
    assert any(f.code == "WRONG_AUDIENCE" for f in result)


def test_derivative_may_live_on_another_platform(demo_registry, materials):
    item = draft_item(format="FMT-01", platforms=["tiktok"], deriv_of="2026-W43-FMT01-HERO")
    assert not platform_lint(item, materials)


def test_kenya_audience_hint_for_fmt03(demo_registry, materials):
    item = draft_item(format="FMT-03", platforms=["facebook"], audience=["global-builders"], deriv_of=None)
    result = platform_lint(item, materials)
    assert any(f.rule == "platform.kenya_audience" for f in result)


def test_copy_paste_hook_across_two_platforms_is_caught(demo_registry, materials):
    hero = review_item(content_id="2026-W43-FMT01-HERO")
    derivative = review_item(content_id="2026-W43-FMT01-HERO-TT", platforms=["tiktok"], deriv_of=hero["content_id"])
    derivative["hook"] = hero["hook"]
    findings_by_id = atomization_lint([hero, derivative])
    assert "2026-W43-FMT01-HERO-TT" in findings_by_id
    assert any(f.rule == "atomization.copy_paste_hook" for f in findings_by_id[derivative["content_id"]])


def test_derivative_without_hero_is_caught(demo_registry, materials):
    item = review_item(content_id="2026-W43-FMT01-HERO-TT", platforms=["tiktok"], deriv_of="2026-W43-FMT01-HERO")
    findings_by_id = atomization_lint([item])
    assert any(f.rule == "atomization.missing_hero" for f in findings_by_id[item["content_id"]])


def test_lint_rules_stay_in_sync_with_the_brand_document(paths, materials):
    """Docs drift is a defect: every machine rule must appear in the Markdown."""
    doc = (paths.brand / "banned-and-required.md").read_text(encoding="utf-8").lower()
    for term in (
        materials.rules["banned_marketing_phrases"]
        + materials.rules["unapproved_product_status_terms"]
        + materials.rules["soft_product_status_terms"]
    ):
        assert term.lower() in doc, f"{term!r} is enforced but not documented in brand/banned-and-required.md"
    assert materials.rules["canonical_tagline"].lower() in doc
    for tagline in materials.rules["retired_taglines"]:
        assert tagline.lower() in doc


def test_lint_result_codes_are_unique_and_blocking():
    from amplify.lint import Finding, LintResult

    result = LintResult(findings=[
        Finding("VOICE", "a", "m"),
        Finding("VOICE", "b", "m"),
        Finding("INFO", "c", "m"),
    ])
    assert result.codes == ["VOICE"]
    assert len(result.warnings) == 1

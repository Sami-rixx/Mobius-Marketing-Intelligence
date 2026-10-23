"""Human control: approval, rejection, edits, and approval ≠ publication (docs/03, docs/06)."""

from __future__ import annotations


import pytest
import yaml

from amplify import content as content_mod
from amplify import review as review_mod
from amplify.errors import GateFailure, TransitionError
from amplify.review import (
    first_pass_approval_rate,
    load_decisions,
    record_decision,
    record_publication,
    run_interactive_review,
)
from tests.conftest import review_item, temp_repo


@pytest.fixture()
def repo(tmp_path, paths):
    """Isolated repository root — review tests must never write to the real checkout."""
    return temp_repo(tmp_path, paths)


@pytest.fixture()
def queued(repo):
    """An in_review item on disk inside the isolated repo."""
    item = review_item()
    path = repo.drafts / f"{item['content_id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content_mod.dump_item(item), encoding="utf-8")
    return {"item": content_mod.load_item(path, repo), "path": path, "dir": repo.drafts}


def decide(repo, materials, demo_registry, queued, **kwargs):
    return record_decision(
        paths=repo,
        week="2026-W43",
        item=queued["item"],
        registry=demo_registry,
        materials=materials,
        **kwargs,
    )


def test_samuel_can_approve(repo, materials, demo_registry, queued):
    saved = decide(repo, materials, demo_registry, queued, decision="approve", note="ship it")
    assert saved["status"] == "approved"
    assert saved["published_urls"] == {}, "approval is not publication"
    decisions = load_decisions(repo, "2026-W43")
    assert decisions["decisions"][-1]["decided_by"] == "samuel"


def test_rejection_requires_a_reason_code(repo, materials, demo_registry, queued):
    with pytest.raises(GateFailure):
        decide(repo, materials, demo_registry, queued, decision="reject")
    with pytest.raises(GateFailure):
        decide(repo, materials, demo_registry, queued, decision="reject", reason_code="NOT_A_CODE")


def test_rejection_records_the_reason_code(repo, materials, demo_registry, queued):
    saved = decide(
        repo, materials, demo_registry, queued,
        decision="reject", reason_code="WEAK_HOOK", note="hook starts too slowly",
    )
    assert saved["status"] == "rejected"
    assert saved["rejection_reason"] == "WEAK_HOOK"
    entry = load_decisions(repo, "2026-W43")["decisions"][-1]
    assert entry["reason_code"] == "WEAK_HOOK"


def test_edit_capture_stores_before_and_after(repo, materials, demo_registry, queued):
    before = queued["item"]["hook"]
    saved = decide(
        repo, materials, demo_registry, queued,
        decision="approve_with_edits",
        edits=[{"field": "hook", "after": "I built this on a 4G phone. The commit is below."}],
    )
    assert saved["status"] == "approved"
    entry = load_decisions(repo, "2026-W43")["decisions"][-1]
    assert entry["edits"][0]["before"] == before
    assert entry["edits"][0]["after"].startswith("I built this on a 4G phone")
    diff = review_mod.capture_edit_diff(before, entry["edits"][0]["after"], "hook")
    assert "-" in diff and "+" in diff


def test_editing_an_unknown_field_is_refused(repo, materials, demo_registry, queued):
    with pytest.raises(GateFailure):
        decide(
            repo, materials, demo_registry, queued,
            decision="approve_with_edits",
            edits=[{"field": "auto_publish", "after": "true"}],
        )


def test_blocking_lint_prevents_approval(repo, materials, demo_registry, queued):
    broken = dict(queued["item"])
    broken["script"] = "This is production-ready. 132 tests at commit 59a5a6d."
    broken_path = queued["dir"] / "broken.yaml"
    broken_path.write_text(content_mod.dump_item({**broken, "content_id": "2026-W43-FMT01-BROKEN"}))
    item = content_mod.load_item(broken_path, repo)
    with pytest.raises(GateFailure) as excinfo:
        record_decision(
            paths=repo, week="2026-W43", item=item, decision="approve",
            registry=demo_registry, materials=materials,
        )
    assert "blocking lint" in str(excinfo.value)


def test_lint_override_requires_a_note(repo, materials, demo_registry, queued):
    broken = dict(queued["item"])
    broken["script"] = "This is production-ready. 132 tests at commit 59a5a6d."
    broken["content_id"] = "2026-W43-FMT01-BROKEN"
    path = queued["dir"] / "broken.yaml"
    path.write_text(content_mod.dump_item(broken))
    item = content_mod.load_item(path, repo)
    with pytest.raises(GateFailure):
        record_decision(
            paths=repo, week="2026-W43", item=item, decision="approve",
            registry=demo_registry, materials=materials, lint_override=True,
        )
    saved = record_decision(
        paths=repo, week="2026-W43", item=item, decision="approve",
        registry=demo_registry, materials=materials, lint_override=True,
        note="Product status verified verbally with the school; registry entry follows.",
    )
    assert saved["status"] == "approved"
    assert load_decisions(repo, "2026-W43")["decisions"][-1]["lint_override"] is True


def test_only_in_review_items_can_be_decided(repo, materials, demo_registry, queued):
    draft = dict(queued["item"], status="draft", scores={})
    path = queued["dir"] / "draft.yaml"
    path.write_text(content_mod.dump_item({**draft, "content_id": "2026-W43-FMT01-DRAFT"}))
    item = content_mod.load_item(path, repo)
    with pytest.raises(TransitionError):
        record_decision(
            paths=repo, week="2026-W43", item=item, decision="approve",
            registry=demo_registry, materials=materials,
        )


def test_publication_requires_approval_first(repo, materials, demo_registry, queued):
    with pytest.raises(GateFailure):
        record_publication(
            paths=repo, content_id=queued["item"]["content_id"],
            platform="youtube", url="https://youtu.be/example",
        )


def test_publication_records_a_real_url_after_manual_posting(repo, materials, demo_registry, queued):
    decide(repo, materials, demo_registry, queued, decision="approve")
    saved = record_publication(
        paths=repo,
        content_id=queued["item"]["content_id"],
        platform="youtube",
        url="https://youtu.be/example",
    )
    assert saved["status"] == "published"
    assert saved["published_urls"] == {"youtube": "https://youtu.be/example"}


def test_publication_requires_an_http_url(repo, materials, demo_registry, queued):
    decide(repo, materials, demo_registry, queued, decision="approve")
    with pytest.raises(GateFailure):
        record_publication(
            paths=repo, content_id=queued["item"]["content_id"],
            platform="youtube", url="not-a-url",
        )


def test_interactive_review_refuses_without_a_tty(repo, materials, demo_registry):
    with pytest.raises(GateFailure) as excinfo:
        run_interactive_review(
            paths=repo, week="2026-W403", registry=demo_registry, materials=materials
        )
    assert "interactive" in str(excinfo.value)


def test_interactive_review_can_skip_without_changing_anything(
    repo, materials, demo_registry, queued, monkeypatch
):
    # point the review at the isolated drafts dir by monkeypatching the loader
    monkeypatch.setattr(
        content_mod, "load_items", lambda directory, paths_, week=None: [queued["item"]]
    )
    answers = iter(["s"])
    summary = run_interactive_review(
        paths=repo, week="2026-W43", registry=demo_registry, materials=materials,
        input_fn=lambda prompt: next(answers), output_fn=lambda text: None, require_tty=False,
    )
    assert summary["skipped"] == [queued["item"]["content_id"]]
    decisions = load_decisions(repo, "2026-W43")
    assert all(d["content_id"] != queued["item"]["content_id"] for d in decisions["decisions"])


def test_decisions_file_is_append_only(repo, materials, demo_registry, queued):
    decide(repo, materials, demo_registry, queued, decision="approve")
    path = review_mod.decisions_path(repo, "2026-W43")
    first = path.read_text(encoding="utf-8")
    second_item = review_item(content_id="2026-W43-FMT01-HERO-TT", platforms=["tiktok"], deriv_of="2026-W43-FMT01-HERO")
    path2 = queued["dir"] / "second.yaml"
    path2.write_text(content_mod.dump_item(second_item))
    record_decision(
        paths=repo, week="2026-W43", item=content_mod.load_item(path2, repo),
        decision="reject", reason_code="VOICE", registry=demo_registry, materials=materials,
    )
    after = path.read_text(encoding="utf-8")
    assert after.startswith(first)
    assert len(yaml.safe_load(after)["decisions"]) == 2


def test_first_pass_approval_rate(repo, materials, demo_registry, queued):
    assert first_pass_approval_rate(repo) is None
    decide(repo, materials, demo_registry, queued, decision="approve")
    second = review_item(content_id="2026-W43-FMT01-HERO-TT", platforms=["tiktok"], deriv_of="2026-W43-FMT01-HERO")
    path = queued["dir"] / "second.yaml"
    path.write_text(content_mod.dump_item(second))
    record_decision(
        paths=repo, week="2026-W43", item=content_mod.load_item(path, repo),
        decision="approve_with_edits",
        edits=[{"field": "caption", "after": "132 tests at commit 59a5a6d. Read it yourself."}],
        registry=demo_registry, materials=materials,
    )
    rate = first_pass_approval_rate(repo)
    assert rate is not None and 0.0 <= rate <= 1.0

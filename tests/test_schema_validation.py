"""Malformed content never reaches review (docs/03 rule 1)."""

from __future__ import annotations

import pytest
import yaml

from amplify import content as content_mod
from amplify.errors import SchemaError, TransitionError
from amplify.schemas import problems
from tests.conftest import draft_item, review_item


def test_valid_draft_passes(paths):
    assert problems(draft_item(), paths, "content-item") == []


def test_invalid_yaml_is_rejected(paths, tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("content_id: [unclosed\n  - : :\n", encoding="utf-8")
    with pytest.raises(SchemaError):
        content_mod.load_item(path, paths)


def test_missing_required_field_is_rejected(paths):
    item = draft_item()
    del item["hook"]
    assert any("hook" in problem for problem in problems(item, paths, "content-item"))


def test_wrong_status_enum_is_rejected(paths):
    item = draft_item(status="ready-to-post")
    assert problems(item, paths, "content-item")


def test_unknown_key_is_rejected(paths):
    item = draft_item()
    item["auto_publish"] = True
    assert any("auto_publish" in problem for problem in problems(item, paths, "content-item"))


def test_in_review_requires_subscores(paths):
    item = draft_item(status="in_review")
    assert any("scores" in problem for problem in problems(item, paths, "content-item"))


def test_in_review_requires_at_least_one_claim(paths):
    item = review_item()
    item["claims"] = []
    assert any("claims" in problem for problem in problems(item, paths, "content-item"))


def test_rejected_requires_reason_code(paths):
    item = review_item()
    item["status"] = "rejected"
    item["rejection_reason"] = None
    assert any("rejection_reason" in problem for problem in problems(item, paths, "content-item"))


def test_published_requires_a_url(paths):
    item = review_item()
    item["status"] = "published"
    item["published_urls"] = {}
    assert any("published_urls" in problem for problem in problems(item, paths, "content-item"))


def test_duplicate_claim_ids_are_rejected_by_schema(paths):
    item = review_item(claims=["CLM-101", "CLM-101"])
    assert problems(item, paths, "content-item")


def test_producer_cannot_write_an_approved_item():
    with pytest.raises(TransitionError):
        content_mod.check_transition("draft", "approved", "producer")


def test_producer_cannot_publish():
    with pytest.raises(TransitionError):
        content_mod.check_transition("approved", "published", "producer")


def test_qa_can_reject_but_not_approve():
    content_mod.check_transition("draft", "rejected", "qa-editor")
    with pytest.raises(TransitionError):
        content_mod.check_transition("in_review", "approved", "qa-editor")


def test_samuel_is_the_only_approver():
    content_mod.check_transition("in_review", "approved", "samuel")
    with pytest.raises(TransitionError):
        content_mod.check_transition("in_review", "approved", "system")


def test_illegal_transition_is_refused():
    with pytest.raises(TransitionError):
        content_mod.check_transition("published", "approved", "samuel")


def test_create_item_refuses_to_overwrite(paths, tmp_path):
    item = draft_item()
    content_mod.create_item(item, paths, directory=tmp_path)
    with pytest.raises(TransitionError):
        content_mod.create_item(item, paths, directory=tmp_path)


def test_yaml_round_trip_is_stable(paths, tmp_path):
    item = draft_item()
    path = content_mod.create_item(item, paths, directory=tmp_path)
    loaded = content_mod.load_item(path, paths)
    assert loaded["content_id"] == item["content_id"]
    assert yaml.safe_load(path.read_text())["status"] == "draft"

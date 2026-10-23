"""The controlled learning loop never edits brand/ itself (docs/05)."""

from __future__ import annotations

import hashlib
import json

import pytest

from amplify import content as content_mod
from amplify import editloop
from amplify.review import record_decision
from amplify.schemas import problems
from tests.conftest import review_item, temp_repo

WEEK = "2026-W43"


@pytest.fixture()
def repo(tmp_path, paths):
    root = temp_repo(tmp_path, paths)
    item = review_item()
    path = root.drafts / f"{item['content_id']}.yaml"
    path.write_text(content_mod.dump_item(item), encoding="utf-8")
    return {"paths": root, "item": content_mod.load_item(path, root)}


def test_proposal_is_schema_valid_and_founder_gated(repo, paths, materials, demo_registry):
    record_decision(
        paths=repo["paths"], week=WEEK, item=repo["item"], decision="approve_with_edits",
        registry=demo_registry, materials=materials,
        edits=[{
            "field": "hook",
            "after": "I built the timetable importer on a 4G phone, and the commit is right here in the description.",
        }],
    )
    proposal = editloop.build_proposal(repo["paths"], WEEK)
    assert problems(proposal, paths, "edit-proposal") == []
    assert proposal["pr_title"] == f"voice: week {WEEK} learnings"
    assert proposal["evidence"]["edits"] == 1
    additions = proposal["voice_library_additions"]
    assert additions and additions[0]["synthetic"] is False
    assert "4G phone" in additions[0]["text"], "additions must be Samuel's own words"
    assert additions[0]["context"] in {"kenya-audience", "founder-note"}


def test_kenya_items_tag_additions_as_kenya_audience(repo, paths, materials, demo_registry):
    item = dict(repo["item"])
    item["audience"] = ["kenya-school-owners"]
    path = repo["paths"].drafts / "kenya.yaml"
    path.write_text(content_mod.dump_item({**item, "content_id": "2026-W43-FMT03-S9"}))
    kenya = content_mod.load_item(path, repo["paths"])
    record_decision(
        paths=repo["paths"], week=WEEK, item=kenya, decision="approve_with_edits",
        registry=demo_registry, materials=materials,
        edits=[{"field": "caption", "after": "For school administrators in Kenya: here is the clash list, and here is the commit behind it."}],
    )
    proposal = editloop.build_proposal(repo["paths"], WEEK)
    assert any(a["context"] == "kenya-audience" for a in proposal["voice_library_additions"])


def test_global_only_items_are_tagged_founder_note(repo, paths, materials, demo_registry):
    item = dict(repo["item"])
    item["audience"] = ["global-builders"]
    path = repo["paths"].drafts / "global.yaml"
    path.write_text(content_mod.dump_item({**item, "content_id": "2026-W43-FMT02-S8"}))
    global_item = content_mod.load_item(path, repo["paths"])
    record_decision(
        paths=repo["paths"], week=WEEK, item=global_item, decision="approve_with_edits",
        registry=demo_registry, materials=materials,
        edits=[{"field": "hook", "after": "An import is not a workflow run, and here is the Actions tab that proves it, commit included."}],
    )
    proposal = editloop.build_proposal(repo["paths"], WEEK)
    assert proposal["voice_library_additions"][0]["context"] == "global-audience"


def test_no_edits_means_no_invented_samples(repo, paths, materials, demo_registry):
    record_decision(
        paths=repo["paths"], week=WEEK, item=repo["item"], decision="reject",
        registry=demo_registry, materials=materials, reason_code="PERSONAL",
        note="I will rewrite this myself.",
    )
    proposal = editloop.build_proposal(repo["paths"], WEEK)
    assert proposal["voice_library_additions"] == []
    assert proposal["fingerprint_patch"] is None
    assert proposal["evidence"]["rejections"] == 1
    assert "PERSONAL" in proposal["evidence"]["reason_counts"]


def test_editloop_never_modifies_brand_files(repo):
    brand_dir = repo["paths"].brand
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in brand_dir.rglob("*")
        if path.is_file()
    }
    proposal = editloop.build_proposal(repo["paths"], WEEK)
    editloop.write_proposal(repo["paths"], proposal)
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in brand_dir.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_proposal_files_are_written_for_review(repo):
    proposal = editloop.build_proposal(repo["paths"], WEEK)
    json_path, md_path = editloop.write_proposal(repo["paths"], proposal)
    assert json.loads(json_path.read_text())["generated_by"] == "edit-loop"
    body = md_path.read_text(encoding="utf-8")
    assert "Merging is the" in body and "training signal" in body
    steps = editloop.next_steps(repo["paths"], proposal)
    assert any("gh pr create" in step for step in steps)
    assert all("git push --force" not in step for step in steps)

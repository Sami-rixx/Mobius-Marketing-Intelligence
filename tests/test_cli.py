"""CLI behaviour: safe defaults, visible failures, human-only operations."""

from __future__ import annotations

import json

import pytest

from amplify.cli import main
from tests.conftest import temp_repo

WEEK = "2026-W43"


@pytest.fixture()
def repo(tmp_path, paths):
    return temp_repo(tmp_path, paths)


def test_validate_exits_zero_on_a_clean_repository(repo, capsys):
    assert main(["--root", str(repo.root), "validate"]) == 0
    assert "valid" in capsys.readouterr().out


def test_validate_exits_non_zero_when_a_claim_is_false(repo, paths, capsys):
    code = main(
        [
            "--root",
            str(repo.root),
            "validate",
            "--path",
            str(paths.fixtures / "planted-false-claim.yaml"),
        ]
    )
    assert code == 1
    assert "CLM-999" in capsys.readouterr().out


def test_guardrail_command_proves_the_gate(repo, capsys):
    assert main(["--root", str(repo.root), "guardrail"]) == 0
    assert "GUARDRAIL OK" in capsys.readouterr().out


def test_dry_run_is_the_default_and_writes_a_digest(repo, capsys):
    code = main(["--root", str(repo.root), "run-weekly", "--week", WEEK])
    out = capsys.readouterr().out
    assert code == 0
    assert "zero API cost" in out
    assert (repo.review / f"{WEEK}-digest.md").exists()


def test_dry_run_never_uses_the_real_registry_without_saying_so(repo, capsys):
    main(["--root", str(repo.root), "run-weekly", "--week", WEEK])
    out = capsys.readouterr().out
    assert "SYNTHETIC fixture registry" in out


def test_live_run_refuses_without_an_api_key(repo, monkeypatch, capsys):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    code = main(["--root", str(repo.root), "run-weekly", "--week", WEEK, "--live"])
    assert code == 1
    assert "MISTRAL_API_KEY" in capsys.readouterr().err


def test_mark_published_refuses_unapproved_content(repo, capsys):
    main(["--root", str(repo.root), "run-weekly", "--week", WEEK])
    capsys.readouterr()
    code = main(
        [
            "--root", str(repo.root), "mark-published",
            "--id", "2026-W43-FMT01-HERO", "--platform", "youtube",
            "--url", "https://youtu.be/example",
            "--drafts", str(repo.content / "dry-run"),
        ]
    )
    assert code == 1
    assert "only approved content" in capsys.readouterr().err


def test_review_show_lists_the_queue_without_deciding(repo, capsys):
    main(["--root", str(repo.root), "run-weekly", "--week", WEEK])
    capsys.readouterr()
    code = main(
        [
            "--root", str(repo.root), "review", "--week", WEEK, "--show",
            "--drafts", str(repo.content / "dry-run"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "item(s) in review" in out
    assert not (repo.review / f"decisions-{WEEK}.yaml").exists()


def test_review_refuses_without_a_tty(repo):
    code = main(["--root", str(repo.root), "review", "--week", WEEK])
    assert code == 1


def test_evidence_add_and_list(repo, capsys):
    code = main(
        [
            "--root", str(repo.root), "evidence", "add",
            "--claim-id", "CLM-201",
            "--statement", "The engine has a test suite that runs without network access",
            "--evidence-type", "repo_commit",
            "--evidence-ref", "github.com/Sami-rixx/Mobius-Marketing-Intelligence @ 0000000",
            "--expires", "2027-04-01",
        ]
    )
    assert code == 0, capsys.readouterr().err
    registry = json.loads(repo.claims.read_text())
    assert [entry["claim_id"] for entry in registry["entries"]] == ["CLM-201"]
    assert registry["entries"][0]["verified_by"] == "samuel"

    capsys.readouterr()
    assert main(["--root", str(repo.root), "evidence", "list"]) == 0
    assert "CLM-201" in capsys.readouterr().out


def test_personal_statement_requires_a_terminal_confirmation(repo):
    code = main(
        [
            "--root", str(repo.root), "evidence", "add",
            "--statement", "I study Korean before build work",
            "--evidence-type", "personal_statement",
            "--evidence-ref", "founder statement",
        ]
    )
    assert code == 1
    registry = json.loads(repo.claims.read_text())
    assert registry["entries"] == []


def test_quarantine_command(repo, capsys):
    main(
        [
            "--root", str(repo.root), "evidence", "add",
            "--claim-id", "CLM-202",
            "--statement", "A claim that will be quarantined by the Evidence Keeper",
            "--evidence-type", "screenshot",
            "--evidence-ref", "claims/evidence/CLM-202.png",
        ]
    )
    capsys.readouterr()
    code = main(
        [
            "--root", str(repo.root), "evidence", "quarantine",
            "--claim-id", "CLM-202", "--reason", "screenshot is unreadable",
        ]
    )
    assert code == 0, capsys.readouterr().err
    entry = json.loads(repo.claims.read_text())["entries"][0]
    assert entry["quarantined"] is True
    assert entry["quarantine_reason"] == "screenshot is unreadable"


def test_ingest_without_stats_fails_visibly(repo, capsys):
    code = main(["--root", str(repo.root), "ingest", "--week", WEEK, "--no-agent"])
    assert code == 1
    assert "will not invent them" in capsys.readouterr().err


def test_editloop_command_writes_a_proposal(repo, capsys):
    main(["--root", str(repo.root), "run-weekly", "--week", WEEK])
    capsys.readouterr()
    code = main(["--root", str(repo.root), "editloop", "--week", WEEK])
    out = capsys.readouterr().out
    assert code == 0
    assert (repo.review / f"{WEEK}-voice-proposal.json").exists()
    assert "No brand file was modified" in out


def test_version(repo, capsys):
    assert main(["version"]) == 0
    assert "amplify" in capsys.readouterr().out

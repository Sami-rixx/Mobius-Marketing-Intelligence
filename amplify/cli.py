"""Command line interface: ``python -m amplify <command>``.

Safety defaults:

* ``run-weekly`` is a zero-cost dry run unless ``--live`` is passed explicitly.
* ``review`` refuses to run without a TTY: approvals are human decisions.
* ``mark-published`` only *records* a URL Samuel already posted. The engine cannot post.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path
from typing import Any, Sequence

from . import content as content_mod
from . import editloop, evidence_keeper, guardrail
from .brand import load_brand
from .client import DryRunClient, MistralClient
from .config import RepoPaths, current_week, load_config, repo_paths
from .cycle import run_weekly
from .errors import AmplifyError, ClaimError, GateFailure
from .ingest import ingest_week
from .registry import load_registry, registry_summary
from .review import (
    load_decisions,
    record_publication,
    run_interactive_review,
)
from .validate import validate_repo

LOGGER = logging.getLogger("amplify")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m amplify",
        description="The Inevitable Engine — Möbius Muse's AI marketing intelligence engine.",
    )
    parser.add_argument("--root", default=None, help="repository root (defaults to this checkout)")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate schemas, registry, brand, content, decisions")
    validate.add_argument("--path", action="append", default=[], help="extra content file to validate")
    validate.add_argument("--as-of", default=None, help="ISO date for claim expiry checks")

    cycle = sub.add_parser("run-weekly", help="run one weekly cycle (dry run by default)")
    cycle.add_argument("--week", default=None, help="ISO week, e.g. 2026-W43 (default: current)")
    cycle.add_argument("--dry-run", action="store_true", help="replay fixtures; zero API cost (default)")
    cycle.add_argument("--live", action="store_true", help="call the Mistral API (needs MISTRAL_API_KEY)")
    cycle.add_argument("--fixtures", default=None, help="fixture directory for dry runs")
    cycle.add_argument("--brief", default=None, help="standing research brief override")
    cycle.add_argument(
        "--registry",
        default=None,
        help="fixture registry for dry runs only (synthetic demo claims)",
    )
    cycle.add_argument(
        "--out-dir",
        default=None,
        help="drafts directory for the run (defaults to content/dry-run for dry runs)",
    )

    review = sub.add_parser("review", help="Samuel's review session (interactive)")
    review.add_argument("--week", required=True)
    review.add_argument("--show", action="store_true", help="print the queue and lints, change nothing")
    review.add_argument("--drafts", default=None, help="drafts directory (default: content/drafts)")

    publish = sub.add_parser("mark-published", help="record a URL you posted manually")
    publish.add_argument("--id", required=True, dest="content_id")
    publish.add_argument("--platform", required=True)
    publish.add_argument("--url", required=True)
    publish.add_argument("--drafts", default=None, help="drafts directory (default: content/drafts)")

    ingest = sub.add_parser("ingest", help="ingest pasted platform stats for a week")
    ingest.add_argument("--week", required=True)
    ingest.add_argument("--raw", default=None, help="path to analytics/raw/<week>.yaml")
    ingest.add_argument("--no-agent", action="store_true", help="deterministic memo only (no API call)")

    loop = sub.add_parser("editloop", help="distil the week's edits/rejections into a voice PR proposal")
    loop.add_argument("--week", required=True)

    ev = sub.add_parser("evidence", help="Claims Registry operations (Evidence Keeper)")
    ev_sub = ev.add_subparsers(dest="evidence_command", required=True)
    ev_list = ev_sub.add_parser("list", help="list registry entries and their state")
    ev_list.add_argument("--as-of", default=None)
    ev_add = ev_sub.add_parser("add", help="register a claim with its receipt")
    ev_add.add_argument("--claim-id", default=None)
    ev_add.add_argument("--statement", required=True)
    ev_add.add_argument("--evidence-type", required=True, choices=list(evidence_keeper_types()))
    ev_add.add_argument("--evidence-ref", required=True)
    ev_add.add_argument("--expires", default=None)
    ev_add.add_argument("--note", default=None)
    ev_apply = ev_sub.add_parser("apply", help="apply a claims proposal")
    ev_apply.add_argument("--proposal", required=True)
    ev_apply.add_argument("--approve-personal", action="store_true")
    ev_quarantine = ev_sub.add_parser("quarantine", help="quarantine a claim whose evidence is stale")
    ev_quarantine.add_argument("--claim-id", required=True)
    ev_quarantine.add_argument("--reason", required=True)

    sub.add_parser("guardrail", help="prove the pipeline rejects a planted false claim")
    sub.add_parser("version", help="print engine version")
    return parser


def evidence_keeper_types() -> tuple[str, ...]:
    return (
        "repo_commit",
        "ci_run",
        "deployed_url",
        "artifact",
        "screenshot",
        "personal_statement",
    )


def _paths(args: argparse.Namespace) -> RepoPaths:
    return repo_paths(args.root)


def _confirm(question: str, expected: str) -> bool:
    if not sys.stdin.isatty():
        raise GateFailure(
            "this action needs Samuel's explicit confirmation and a real terminal (no TTY). "
            "Run it yourself, from your terminal."
        )
    print(question)
    return input(f"type {expected!r} to confirm: ").strip() == expected


def cmd_validate(args: argparse.Namespace) -> int:
    paths = _paths(args)
    as_of = _dt.date.fromisoformat(args.as_of) if args.as_of else None
    report = validate_repo(paths, as_of=as_of, extra_items=args.path)
    print(report.render())
    return 0 if report.ok else 1


def cmd_run_weekly(args: argparse.Namespace) -> int:
    paths = _paths(args)
    config = load_config(root=paths.root)
    week = args.week or current_week()
    if args.live and args.dry_run:
        raise GateFailure("choose either --live or --dry-run, not both")
    if args.live:
        client: Any = MistralClient(config=config, usage_path=paths.usage_log)
        LOGGER.warning("LIVE cycle: this will spend tokens. Budget caps are enforced by config.")
    else:
        fixtures = Path(args.fixtures) if args.fixtures else paths.fixtures / "dryrun"
        client = DryRunClient(fixtures, config=config, usage_path=paths.usage_log)
        print(f"dry run: replaying fixtures from {fixtures} (zero API cost)")
    registry_path = Path(args.registry) if args.registry else None
    drafts_dir = Path(args.out_dir) if args.out_dir else None
    if client.mode == "dry_run":
        if registry_path is None:
            registry_path = paths.fixtures / "demo" / "registry.json"
            print(
                "using the SYNTHETIC fixture registry (tests/fixtures/demo) — these are not "
                "real claims; pass --registry to override"
            )
        if drafts_dir is None:
            drafts_dir = paths.content / "dry-run"
    result = run_weekly(
        paths=paths,
        config=config,
        client=client,
        week=week,
        brief=args.brief,
        registry_path=registry_path,
        drafts_dir=drafts_dir,
    )
    print(f"week {week}: {'DEGRADED' if result.degraded else 'OK'}")
    for failure in result.failures:
        print(f"  FAILED {failure.step}: {failure.reason}")
    if result.digest_path:
        print(f"digest: {result.digest_path.relative_to(paths.root)}")
    if result.issue_path:
        print(f"issue text: {result.issue_path.relative_to(paths.root)}")
    print("nothing was published, scheduled or sent.")
    return result.exit_code


def cmd_review(args: argparse.Namespace) -> int:
    paths = _paths(args)
    registry = load_registry(paths)
    materials = load_brand(paths)
    week = args.week
    drafts = Path(args.drafts) if args.drafts else paths.drafts
    items = [i for i in content_mod.load_items(drafts, paths, week=week) if i.get("status") == "in_review"]
    if args.show:
        print(f"{len(items)} item(s) in review for {week}")
        for item in items:
            print(f"- {item['content_id']} [{item['format']}] {item.get('hook')}")
        decisions = load_decisions(paths, week)
        print(f"recorded decisions: {len(decisions['decisions'])}")
        return 0
    summary = run_interactive_review(
        paths=paths, week=week, registry=registry, materials=materials, drafts_dir=drafts
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_mark_published(args: argparse.Namespace) -> int:
    paths = _paths(args)
    item = record_publication(
        paths=paths,
        content_id=args.content_id,
        platform=args.platform,
        url=args.url,
        drafts_dir=Path(args.drafts) if args.drafts else None,
    )
    print(f"recorded publication of {item['content_id']} on {args.platform}: {args.url}")
    print("the engine did not post anything; this is a record of your manual action.")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    paths = _paths(args)
    config = load_config(root=paths.root)
    client = None
    if not args.no_agent:
        client = MistralClient(config=config, usage_path=paths.usage_log)
    update = ingest_week(
        paths=paths,
        config=config,
        week=args.week,
        raw_path=Path(args.raw) if args.raw else None,
        client=client,
    )
    print(update["memo"]["text"])
    print("\nartifacts: " + ", ".join(update.get("_artifacts") or []))
    return 0


def cmd_editloop(args: argparse.Namespace) -> int:
    paths = _paths(args)
    proposal = editloop.build_proposal(paths, args.week)
    json_path, md_path = editloop.write_proposal(paths, proposal)
    print(f"proposal: {json_path.relative_to(paths.root)}")
    print(f"summary:  {md_path.relative_to(paths.root)}")
    print("\nNo brand file was modified. To open the review PR:")
    for step in editloop.next_steps(paths, proposal):
        print(f"  {step}")
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    paths = _paths(args)
    config = load_config(root=paths.root)
    registry = load_registry(paths)
    command = args.evidence_command

    if command == "list":
        as_of = _dt.date.fromisoformat(args.as_of) if args.as_of else None
        print(registry_summary(registry, as_of))
        for row in evidence_keeper.registry_report(registry, as_of=as_of):
            flag = "EXPIRING" if row["expiring_soon"] and row["state"] == "valid" else row["state"].upper()
            print(f"{row['claim_id']}  {flag:<10} exp {row['expires']}  {row['statement'][:70]}")
        return 0

    if command == "add":
        claim_id = args.claim_id or registry.next_claim_id()
        founder_approved = False
        approved_date = None
        if args.evidence_type == "personal_statement":
            if not _confirm(
                "personal_statement claims are facts only Samuel can verify. "
                f"Approving {claim_id}: {args.statement}",
                f"APPROVE {claim_id}",
            ):
                print("not approved; registry unchanged.")
                return 1
            founder_approved = True
            approved_date = _dt.date.today().isoformat()
        operations = evidence_keeper.evidence_operations(
            claim_id=claim_id,
            statement=args.statement,
            evidence_type=args.evidence_type,
            evidence_ref=args.evidence_ref,
            expires=args.expires,
            founder_approved_date=approved_date,
            op_note=args.note,
        )
        proposal = evidence_keeper.build_proposal(
            paths,
            config,
            registry,
            week=_week_or_current(None),
            rationale=f"Founder registered {claim_id} from the command line.",
            operations=operations,
        )
        saved = evidence_keeper.save_proposal(paths, proposal, suffix=claim_id)
        summary = evidence_keeper.apply_proposal(
            paths, config, proposal, approved_by_founder=founder_approved
        )
        summary["proposal"] = str(saved.relative_to(paths.root))
        print(json.dumps(summary, indent=2))
        return 0

    if command == "apply":
        payload = evidence_keeper.load_proposal(Path(args.proposal), paths)
        personal = evidence_keeper.requires_founder_approval(payload)
        approved = False
        if personal:
            if not args.approve_personal:
                print("this proposal registers personal_statement claims: " + ", ".join(personal))
                return 1
            approved = _confirm(
                "Approve personal_statement claims " + ", ".join(personal) + "?",
                "APPROVE PERSONAL CLAIMS",
            )
            if not approved:
                print("not approved; registry unchanged.")
                return 1
        summary = evidence_keeper.apply_proposal(paths, config, payload, approved_by_founder=approved)
        print(json.dumps(summary, indent=2))
        return 0

    if command == "quarantine":
        existing = registry.get(args.claim_id)
        if existing is None:
            raise ClaimError([f"{args.claim_id}: not in the registry"])
        operations = evidence_keeper.evidence_operations(
            claim_id=args.claim_id,
            statement=existing["statement"],
            evidence_type=existing["evidence_type"],
            evidence_ref=existing["evidence_ref"],
            expires=existing.get("expires"),
            op="expire",
            op_note=args.reason,
            base_claim=existing,
        )
        proposal = evidence_keeper.build_proposal(
            paths,
            config,
            registry,
            week=_week_or_current(None),
            rationale=f"Quarantine {args.claim_id}: {args.reason}",
            operations=operations,
        )
        saved = evidence_keeper.save_proposal(paths, proposal, suffix=f"quarantine-{args.claim_id}")
        summary = evidence_keeper.apply_proposal(paths, config, proposal, approved_by_founder=False)
        summary["proposal"] = str(saved.relative_to(paths.root))
        print(json.dumps(summary, indent=2))
        return 0

    raise GateFailure(f"unknown evidence command {command!r}")


def _week_or_current(week: str | None) -> str:
    return week or current_week()


def cmd_guardrail(args: argparse.Namespace) -> int:
    paths = _paths(args)
    result = guardrail.assert_caught(paths)
    print(json.dumps(result, indent=2))
    print("\nGUARDRAIL OK: the planted false claim was rejected by the real validators.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    handlers = {
        "validate": cmd_validate,
        "run-weekly": cmd_run_weekly,
        "review": cmd_review,
        "mark-published": cmd_mark_published,
        "ingest": cmd_ingest,
        "editloop": cmd_editloop,
        "evidence": cmd_evidence,
        "guardrail": cmd_guardrail,
        "version": lambda _args: _version(),
    }
    handler = handlers.get(args.command)
    if handler is None:  # pragma: no cover - argparse enforces this
        parser.error(f"unknown command {args.command}")
    try:
        return int(handler(args))
    except (AmplifyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _version() -> int:
    from . import __version__

    print(f"amplify {__version__}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

# 07 — Implementation Notes, Decisions & Verification

This file records how the Blueprint v2.0 was implemented, the decisions taken where the
documents are silent, and what has **not** been verified. It does not replace
`docs/00`–`docs/06`; those remain authoritative.

## 1. What existed before this work

The repository contained only `docs/pdf/` (eight PDFs) and a `docs/pdf/README.md`, plus a single
commit. There was no code, no schemas, no CI, no tests, no Markdown copies of the
blueprint. Everything below was built in this change set.

## 2. Blueprint fidelity

| Requirement | Implementation |
|---|---|
| Path A only, plain Python under `amplify/` | `amplify/` CLI, no framework, no Path B code |
| Six agents as prompt file + strict output schema | `agents/*.md` + `schemas/*` + `amplify/agents.py` |
| Claims Registry is the single truth layer | `claims/registry.json`, `amplify/registry.py`, lint + CI |
| Evidence Keeper is the sole writer | `Registry.write(..., authorized_by="evidence-keeper")`; no other module can call it |
| `personal_statement` needs founder approval | schema requires `founder_approval`; `apply_operations` refuses without the founder flag; CLI requires typed confirmation |
| Producer and QA/Editor adversarial and separate | Producer may only emit `status: draft`; QA may reject but its schema has no rewrite field; the cycle refuses any status change other than the documented transition table |
| Content-as-code with YAML per item | `content/drafts/<content_id>.yaml`, validated against `schemas/content-item.schema.json` |
| Rubric + 70 auto-reject + reason codes | `schemas/rubric.json`, `amplify/scoring.py`, `schemas/qa-report.schema.json` |
| Digest + Issue text + DEGRADED policy | `amplify/digest.py`, `amplify/cycle.py` |
| Review digest keeps Samuel in control | `amplify/review.py`; only `decided_by: samuel` may approve or publish |
| Analytics from supplied data only | `amplify/ingest.py`; missing values stored `NULL` and listed as unknowns |
| Controlled voice/edit loop | `amplify/editloop.py`; proposal only, never edits `brand/` |
| GitHub Actions scheduling | `.github/workflows/{tests,content-ci,weekly}.yml` |
| Hard limits (no publish/schedule/reply/ads) | no platform credentials, no HTTP clients except the model API, workflows are read-only |

## 3. Decisions taken where the documents were silent

1. **`expires` is inclusive.** A claim is usable on its expiry date and dead the following
   day. Implemented in `Registry.status`.
2. **Status transition table.** `draft → in_review → approved | rejected`; `rejected →
   draft` for revisions; `approved → published` only when Samuel records a real URL;
   `approved → rejected` allowed so a human may withdraw an approval before publishing.
   Agents other than Samuel can never set `approved`/`published`.
3. **A rejected item may cite no claims.** Schema validation requires at least one claim
   only for `in_review`, `approved` and `published`. Otherwise a rejection *for* missing
   evidence would itself be unrepresentable.
4. **QA verdicts are recomputed, always.** In live mode the QA judge proposes subscores and
   may reject; the deterministic lints plus `apply_gates` produce the authoritative verdict.
   A generous model cannot pass a claim with no receipt, and a rejection is never overruled
   by a score.
5. **Score below 70 without a lint failure** maps the lowest dimension to a documented code
   (`WEAK_HOOK`, `TOO_GENERIC`, `OFF_BRAND`, `WRONG_AUDIENCE`). `clarity` has no dedicated
   code, so it maps to `TOO_GENERIC`, the documented catch-all. The mapping is table-driven
   in `amplify/scoring.py`.
6. **Scores schema.** `docs/03` shows `{truth, brand, voice, hook}` while the rubric defines
   five weighted dimensions. The schema stores the five rubric dimensions plus `composite`,
   because that is what the rubric, the 70-point gate and trend analysis require. The four
   illustrative keys in the doc are treated as a sketch, not a second rubric.
7. **Product-status words are split** into blocking (`production-ready`,
   `battle-tested`, `in production`, `GA`, `profitable`, …) and soft/warning (`launched`,
   `shipped`) because words like "live" and "launched" appear in ordinary sentences. A cited,
   valid registry claim whose statement contains the same term authorises the word either
   way. Documented in `brand/banned-and-required.md` and enforced in
   `amplify/lint.py`.
8. **Voice similarity is not faked.** Until `brand/voice-fingerprint.md` says
   `calibrated: true` **and** `brand/voice-library/` holds real samples, similarity cannot
   pass or fail an item: the lint reports `uncalibrated` and Samuel judges register himself.
   Hard checks (banned language, throat-clearing, sentence cap, emoji wall, tagline) still
   apply. This avoids inventing Samuel's style.
9. **Evidence Keeper does not run unattended.** It needs founder-supplied evidence, so the
   weekly cycle does not call it. Proposals come from `amplify evidence add|quarantine` or a
   founder-supplied evidence index (`run_evidence_keeper` exists for that path) and land in
   `content/review/<week>-claims-proposal.json`. Nothing changes until `evidence apply`.
10. **Dry runs use a clearly synthetic registry** from `tests/fixtures/demo/`, and write
    drafts to `content/dry-run/` (gitignored). A live cycle is refused if a fixture registry
    is supplied, so synthetic claims can never back real content.
11. **Weekly cadence is one cycle run.** The Monday plan comment can be produced with
    `run-weekly` (plan appears in `content/review/<week>-plan.md`) and Samuel reviews plan +
    drafts in the same Thursday session. Drafting from an unapproved plan is intentional:
    approval is about *publication*, and no content leaves review without Samuel.
12. **`weekly.yml` is inert until switched on.** It is gated on repository variable
    `ENGINE_SCHEDULE_ENABLED`, defaults to a dry run, and has read-only permissions. It
    cannot commit, open a PR, deploy or publish. Enabling it is a founder decision.
13. **`analytics/usage.jsonl` is committed; `analytics/marketing.sqlite` is gitignored.**
    Cost/token history belongs with content history; the SQLite file is a local index.
14. **Hook families are deterministic** (`receipt-first`, `question`, `personal-story`,
    `number-led`, `stated-claim`, `unknown`) so performance learning does not depend on model
    taste.
15. **No pricing is configured by default**, so cost metrics are `null` ("unknown") until
    Samuel enters real prices into `amplify/config.yaml`.

## 4. Environment constraint

The development sandbox has Python 3.11.2; the blueprint targets 3.12–3.15 and CI runs 3.12.
The code deliberately avoids 3.12-only syntax, so both work. Verified locally on 3.11.2;
CI matrix is 3.12 only.

## 5. Verification actually performed

| Check | Command | Result |
|---|---|---|
| Unit + integration tests | `.venv/bin/python -m pytest -q` | **215 passed** (4.1 s), no network, no API key |
| Repository gate | `python -m amplify validate` | valid (warnings: empty registry, uncalibrated voice, no pricing — all honest states); rubric weights checked |
| Guardrail proof | `python -m amplify guardrail` | planted `CLM-999` rejected with `UNVERIFIED_CLAIM` |
| Dry-run cycle | `python -m amplify run-weekly --week 2026-W43 --dry-run` | 6 items produced, 5 in review, 1 rejected, digest OK, zero API cost |
| Workflow syntax | YAML parsed by tests (`tests/test_workflows.py`) | all three workflows parse, are read-only, have no `continue-on-error`, and contain no publish/deploy steps |
| Static lint | `ruff check amplify tests --select E,F,W,B --ignore E501` | clean |
| Planted-claim CI path | `python -m amplify validate --path tests/fixtures/planted-false-claim.yaml` | exit 1, `CLM-999` reported |

**Not verified (and not claimable):** a live Mistral API call, real token accounting against
the provider, real platform statistics, and a green GitHub Actions run on GitHub's runners.
These need Samuel's key and repository access; the commands above are the verification steps.

## 6. Known limitations

* The heuristic scorer is a deterministic editorial proxy, not a taste model; live mode
  should use the QA judge for subscores, with the same gates.
* `voice-library` is empty, so voice similarity is inert until Samuel contributes samples.
* Rendered media (thumbnails, video) are briefs, not assets; the Producer writes briefs only.
* `content/approved` and `content/published` are archival folders; the engine keeps items in
  `content/drafts` and records status transitions in place (simpler diffs for a phone
  workflow).
* No dashboards, no notifications beyond Markdown digests and Issue text — per docs/06.

## 7. Repository layout change

The authoritative PDFs moved from `Docs/` to `docs/pdf/` (content unchanged, `git mv`
preserves history). `Docs/` and `docs/` differed only by case, which breaks checkouts on
macOS and Windows; the blueprint's own repo map uses lowercase `docs/`. All Markdown
references were updated.

## 8. Path B (Mistral Workflows) — deliberately deferred

Not built. Migration conditions remain: ≥8 weeks of pilot data, failures for durability (not
prompt) reasons, Path A cost above the quoted platform cost, public platform pricing. The
agent functions, prompts and schemas are already separable, so migration would wrap them as
activities without changing content contracts.

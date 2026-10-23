# MÖBIUS MUSE — The Inevitable Engine

**Making Ideas Inevitable** · Deep Muse Blue `#0A2463`

Möbius Muse's AI-operated marketing team. Six AI agents research, strategise, create, check
and learn. **Samuel Mungai Kariuki (founder) reviews, decides and publishes. Nothing
auto-posts. Ever.**

> Golden rule: AI researches, creates, checks and learns. Samuel decides what represents
> Möbius Muse and what gets published.

---

## What is implemented

This repository is a working implementation of the Blueprint v2.0 **Path A**: plain Python
orchestration under `amplify/`, versioned Git files as state, GitHub Actions for scheduling
and CI.

| Capability | Where | Status |
|---|---|---|
| Six agent contracts (system prompts) | `agents/*.md` | implemented |
| Strict JSON-schema validation of every output | `schemas/`, `amplify/schemas.py` | implemented |
| Claims Registry + expiry/quarantine policy | `claims/registry.json`, `amplify/registry.py` | implemented |
| Evidence Keeper as sole registry writer | `amplify/evidence_keeper.py` | implemented |
| Deterministic brand / voice / platform / atomization lints | `amplify/lint.py`, `brand/lint-rules.json` | implemented |
| Rubric scoring, 70-point auto-reject, reason codes | `amplify/scoring.py`, `schemas/rubric.json` | implemented |
| Weekly cycle with DEGRADED failure policy | `amplify/cycle.py` | implemented |
| Review digest + GitHub Issue text | `amplify/digest.py` | implemented |
| Human review, edit capture, approval ≠ publication | `amplify/review.py`, `amplify/cli.py` | implemented |
| Analytics ingest → SQLite → `scores.json` → weekly memo | `amplify/ingest.py` | implemented |
| Controlled learning loop (voice PR proposal) | `amplify/editloop.py` | implemented |
| CI + scheduled workflow | `.github/workflows/` | implemented |
| Guardrail proof (planted false claim) | `tests/fixtures/planted-false-claim.yaml`, `amplify/guardrail.py` | implemented |

**Not implemented on purpose:** Mistral Workflows (Path B, deferred — see
`docs/01-architecture.md`), the Phase-2 Community Triage agent, dashboards, platform
publishing, auto-scheduling, messaging integrations and paid services. No platform
credentials exist in this repo and none are needed.

## Install

Python 3.12+ (the engine also runs on 3.11; CI uses 3.12).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
# or: make install
```

Dependencies are pinned in `requirements.txt` (PyYAML, jsonschema) and
`requirements-dev.txt` (pytest). No framework, no database server, no background daemon.

## Configure

| Variable | Required | Purpose |
|---|---|---|
| `MISTRAL_API_KEY` | only for live cycles | the engine key (keep it separate from your Vibe coding key) |

* Local: copy `.env.example` to `.env` and fill it; run with the key in the environment.
  `.env` is gitignored and is never read by the code — export the variable yourself.
* GitHub Actions: add the repository secret `MISTRAL_API_KEY`.
* Budgets/models: `amplify/config.yaml` (monthly token cap, per-call cap, retry cap, models).
  The runner refuses to start a live cycle when the monthly cap is reached.
* Cost numbers appear only when real prices are configured in `amplify/config.yaml`;
  otherwise cost is reported as **unknown**, never estimated.

## Run

```bash
make lint                       # schemas, registry, brand, content, decisions
make test                       # 215 tests, zero API calls
make guardrail                  # prove the planted false claim is rejected
make dry-run W=2026-W43         # full cycle with canned outputs, zero cost
make review W=2026-W43          # your decision session (interactive, human-only)
```

The same commands without `make`:

```bash
python -m amplify validate
python -m amplify run-weekly --week 2026-W43 --dry-run
python -m amplify review --week 2026-W43            # add --show to just look
python -m amplify mark-published --id 2026-W43-FMT01-HERO \
    --platform youtube --url https://youtu.be/...
python -m amplify ingest --week 2026-W43 --no-agent
python -m amplify editloop --week 2026-W43
python -m amplify evidence list
```

A live cycle (`--live`) requires `MISTRAL_API_KEY` **and your explicit intent**. Never run
one without deciding to.

## The weekly cycle (what happens, in order)

```
research notes → weekly plan (1 hero + 2–3 supporting)
  → Producer drafts (hero + platform-native derivatives)
  → deterministic lints + QA scoring → in_review | rejected
  → content/review/<week>-digest.md  (DEGRADED on any failure)
  → make review: you approve / reject / edit
  → you publish manually, then record the URL
  → ingest pasted stats → scores.json + weekly memo
  → editloop: a voice-learning PR proposal you merge or ignore
```

**Failure policy:** any step failure stops that branch, is logged, marks the digest
`DEGRADED`, and writes `content/review/<week>-issue.md` (GitHub Issue text). Retries are
capped at `max_retries_per_task` (2, i.e. 3 attempts). Gates are never skipped to get a
green run.

## Adding evidence (the most important habit)

Nothing factual can be published without a registry entry:

```bash
python -m amplify evidence add \
  --statement "The Dexter bot has a recorded suite of 132 tests" \
  --evidence-type repo_commit \
  --evidence-ref "github.com/Sami-rixx/dexter @ 59a5a6d" \
  --expires 2027-04-21
```

* `verified_by` is always you; every entry needs a real `evidence_ref`.
* `personal_statement` claims (facts only you can verify) require a typed terminal
  confirmation and are recorded with `founder_approval`.
* Stale evidence is quarantined: `python -m amplify evidence quarantine --claim-id CLM-007
  --reason "repo history rewritten"`. Quarantined and expired claims are rejected by CI and
  by the runtime gate.

## Reviewing and approving content

`make review W=2026-W43` walks each `in_review` item, shows the blocking lints, and asks for
a decision. It refuses to run without a real terminal. Approving requires typing
`APPROVE <content_id>`.

* QA may reject; QA never rewrites. Rejections carry a documented reason code.
* If blocking lints remain, approval is refused unless you record an explicit
  `lint_override` with a note — the override is stored in the append-only decision log.
* `approved` **never** means published. Publishing is your manual act on each platform;
  `mark-published` only records the URL you already posted.
* Decisions, edits and reason codes are appended to
  `content/review/decisions-<week>.yaml`. That history feeds the learning loop and is never
  rewritten.

## Analytics

Paste platform numbers into `analytics/raw/<week>.yaml` (see
`analytics/raw/README.md`). Then `make ingest W=...`.

* Only supplied values are stored. Everything else is `null` and listed as unknown.
* `strategy/scores.json` is written **only** by the Growth Analyst and only from ingested
  data.
* The memo answers one question — *what should we do more of, with evidence?* — and every
  number in it is mechanically checked against the supplied data.

## Learning loop

`make editloop W=...` distils the week's edits and rejections into
`content/review/<week>-voice-proposal.{json,md}` and prints the exact `git`/`gh` commands to
open a PR. The Edit Loop **never** edits `brand/`; only you merge voice changes. Additions to
`brand/voice-library/` are your own words, verbatim, never generated.

## Tests and CI

```bash
python -m pytest -q          # 215 tests, no network, no API key
python -m amplify validate   # repository-wide gate
python -m amplify guardrail  # planted false claim must fail
```

Workflows:

| Workflow | Trigger | What it does |
|---|---|---|
| `tests.yml` | push to main, every PR | compile, validate, pytest, guardrail |
| `content-ci.yml` | PRs touching content/claims/brand/schemas/agents/engine | content gate + planted-claim refusal |
| `weekly.yml` | Thursday 03:00 UTC (06:00 EAT), manual | fallback cycle; dry-run unless enabled; read-only permissions |
| `analytics.yml` | manual only | Sunday-night analytics ingest + edit-loop proposal, when you have pasted stats |

`weekly.yml` is **disabled by default**: set repository variable
`ENGINE_SCHEDULE_ENABLED=true` to let the schedule run, and `ENGINE_LIVE=true` to allow live
calls. It has `contents: read` and cannot push, open PRs, deploy or publish.

## Human control and safety

* No publishing, scheduling, replying, messaging, ad spend or account connections — by
  design, at the architecture level.
* Secrets only from environment/GitHub Secrets; never in source, fixtures, prompts or logs.
* Claims only from verified evidence; `personal_statement` requires founder approval.
* No invented metrics, no estimated reach, no invented project status.
* No private learner, parent, customer or school data.
* No new platform, service or paid tool without a founder-approved Issue.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `MISTRAL_API_KEY is not set` | live run without the key: export it, or use `--dry-run`. |
| `monthly token budget exhausted` | usage cap hit in `analytics/usage.jsonl`; raise the cap deliberately or wait for the month to roll. |
| Digest says `DEGRADED` | read the failure list and `content/review/<week>-issue.md`; re-run after fixing. Nothing was published. |
| `dry-run fixture missing` | a fixture is absent for this week; dry runs replay `tests/fixtures/dryrun/<week>-*.json`. |
| `claims registry is empty` | expected on a fresh checkout: register evidence first (`evidence add`). |
| `voice similarity is not blocking yet` | the fingerprint is uncalibrated: add ≥3 real samples to `brand/voice-library/` and set `calibrated: true`. |
| `detail: 'expires' is a required property` | a proposal omitted a date; `evidence add` fills defaults, hand-written proposals must include it. |
| `refusing to overwrite existing draft` | the week's drafts already exist; the cycle preserves them on purpose. |

More detail: `docs/07-implementation-notes.md`. Worked examples of real engine output:
`docs/examples/`.

## Repository map

```
AGENTS.md              build-agent constitution (hard rules)
docs/                  00–07 Markdown blueprint, pdf/ (authoritative PDFs), examples/
brand/                 foundation, visual identity, banned language, voice fingerprint, library
claims/                registry.json (truth layer) + evidence/
strategy/              audiences, positioning, formats, scores.json, plans/, research/
agents/                six runtime system prompts
amplify/               the engine (CLI, cycle, agents, lints, ingest, review, edit loop)
schemas/               content, registry, per-agent outputs, rubric, analytics, decisions
content/               calendar, drafts, review digests, approved, published
analytics/             usage.jsonl (committed), raw/ (pasted stats), marketing.sqlite (ignored)
tests/                 unit + integration tests and fixtures
.github/workflows/     tests.yml, content-ci.yml, weekly.yml
```

## License / privacy

Private repository. Do not publish learner, parent, customer or school personal data.

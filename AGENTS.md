# AGENTS.md — Build-Agent Constitution

Read this file fully before writing any code in this repository. It is re-read every
session. It applies to every build agent (Codex CLI, Vibe, Arena AI, or human contributor).

> Source: `docs/pdf/AGENTS.pdf`. The Markdown copies of the blueprint live in `docs/`.

## What this repo is

The content engine for the Möbius Muse brand: a team of six “marketing agents”
(Strategist, Researcher, Evidence Keeper, Producer, QA/Editor, Growth Analyst) implemented
as Python functions calling the Mistral API with strict JSON-schema outputs. Context for all
design decisions lives in `docs/00-vision.md` through `docs/06-limits.md`. Read the relevant
docs before starting any task.

## Golden rule

AI researches, creates, checks and learns. Samuel decides what represents Möbius Muse and
what gets published.

## Hard rules — a PR violating any of these is rejected

1. **Secrets.** Never commit `.env`, API keys, tokens, or screenshots containing them.
   Never print secrets to logs. The engine reads `MISTRAL_API_KEY` from the environment
   only. `.env` is gitignored.
2. **Schemas.** Every marketing-agent output MUST validate against the schemas in
   `schemas/`. Use Mistral’s strict `json_schema` response_format so malformed output is
   impossible by construction.
3. **Claims.** Every factual statement in any content file MUST resolve to an existing,
   unexpired entry in `claims/registry.json` (see `docs/01-architecture.md`). No match → the
   item must not reach review.
4. **No publishing.** Nothing in this repo posts, schedules, replies, messages, or buys ads —
   now or ever. Output stops at review digests that Samuel reads. Publication is manual, by
   Samuel, on each platform.
5. **Path A only.** Orchestration is plain Python in `amplify/` (see
   `docs/01-architecture.md`). Do not introduce new platforms, services, databases, or paid
   subscriptions without an Issue approved by Samuel.
6. **Branches.** `main` is stable. All work on `feat/<issue>-<slug>` branches. PRs must have
   green CI and updated docs.
7. **Phone constraint.** This project is developed and operated from an Android phone. No
   persistent daemons or long-running servers. All schedules live in GitHub Actions cron;
   the phone is a console (pull → review → decide → push).

## Definition of done

Code + unit tests + docs updated in the same PR + `make lint` + `make test` green locally +
CI green. “The agent said it’s done” and “it worked once locally” do **not** count. Failures
must be reproducible and logged, not silently retried into oblivion.

## Verify locally (UserLAnd Kali/Ubuntu or Termux)

```bash
make lint      # content/schema/claims validators
make test      # unit tests, no live API calls (mocked fixtures)
make dry-run   # full weekly cycle with canned outputs, ZERO API cost
make guardrail # planted-false-claim proof
make review W=2026-W43   # founder decision session (human-driven)
```

**Never run a live cycle** (`python -m amplify run-weekly`) without Samuel’s explicit
instruction.

## Configuration & budgets

`amplify/config.yaml` holds per-agent model choices and hard budgets (monthly token cap,
per-item token cap, max retries per task = 2). Read budgets from config; never hardcode
numbers. Every API call’s usage is appended to `analytics/usage.jsonl`. The runner refuses
to start a cycle when the monthly budget is exhausted.

## When unsure

Stop and ask — comment on the Issue or PR. A halted agent is fine; a guessing agent is not.
Samuel reviews from a phone; keep PRs small and diffs readable.

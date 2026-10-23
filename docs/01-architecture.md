# 01 — Architecture

> Source: `docs/pdf/01-architecture.pdf` (authoritative).

## Decision: Path A (plain-Python orchestration)

The engine is a Python package `amplify/` run as a CLI:

```bash
python -m amplify run-weekly --week 2026-W43
```

- Each marketing agent = one Python function: system prompt (from `agents/<name>.md`) +
  structured input files + Mistral API call with strict `json_schema` output + schema
  validation.
- Orchestration is plain, readable Python. State lives in git-committed files, so a crash
  mid-cycle loses nothing.
- Execution environments:
  - Manual: UserLAnd (Kali/Ubuntu) or Termux on the founder’s phone.
  - Scheduled: GitHub Actions cron (`.github/workflows/weekly.yml`, Thursday 06:00 EAT).
    The phone is never required to be awake.
- **Path B (Mistral Workflows platform) is explicitly deferred.** Migrate only when ALL of
  these hold: ≥8 weeks of pilot data, cycles failing for durability (not prompt) reasons,
  Path A cost exceeds quoted platform cost, platform pricing public. Migration = wrap agent
  functions as activities; prompts/schemas/content unchanged. Do not build Path B pieces
  early.

## The Claims Registry — the truth layer

Single source of truth: `claims/registry.json`. Every factual statement in any content
item MUST cite registry entries that exist and are unexpired.

Entry schema:

```json
{
  "claim_id": "CLM-007",
  "statement": "The Dexter bot has a recorded suite of 132 tests",
  "evidence_type": "repo_commit",
  "evidence_ref": "github.com/Sami-rixx/dexter @ 59a5a6d",
  "verified_by": "samuel",
  "verified_date": "2026-10-21",
  "expires": "2027-04-21"
}
```

Evidence types: `repo_commit`, `ci_run`, `deployed_url`, `artifact`, `screenshot`,
`personal_statement`. `personal_statement` covers facts only Samuel can verify (e.g. “I
study Korean”, “I built this on a phone”). Samuel approves each once at registration; the
entry then becomes reusable until expiry.

Enforcement: content CI rejects any item whose `claims:` list references a
missing/expired entry. Unverifiable ideas are simply not said.

## Signature formats (the IP)

| ID | Format | Cadence | Primary platform | Purpose |
|---|---|---|---|---|
| FMT-01 | **Phone to Product** — a real build, idea→working product, documented on the founder’s itel RS4: brief, agent setup, failures, build log, artifact | Weekly | YouTube 8–12 min | Flagship proof; founder story + product demo + AI-build evidence in one asset |
| FMT-02 | **The Verification Files** — one unglamorous engineering truth per episode, each tied to a real repo example (“an import is not a workflow run”) | Biweekly, short-form | TikTok / Shorts | Anti-hype positioning; cheapest true asset we own |
| FMT-03 | **Blueprint in the Wild** — practical CBC/timetable/school-ops pain points for Kenyan school owners; product second | 2–3×/month | Facebook + IG | Revenue intent |

Supporting (unserialized) pillars: founder journal (Korean study / scholarship journey,
dated and real), build-in-public logs with receipts, Kenyan tech/AI commentary only when
there is a genuine angle.

**Atomization rule:** ONE hero asset per cycle, decomposed into platform-native
derivatives. Never four separate content efforts.

## Data flow (one weekly cycle)

```
claims/ + content/calendar + agents/ + strategy/scores.json
→ Researcher → Strategist → Producer (hero + derivatives)
→ QA/Editor (rubric + claims/brand/voice lint)
→ content/review/<week>-digest.md → Samuel: make review
→ decisions committed → Producer revises rejected items
→ Samuel publishes manually → stats pasted → Growth Analyst
→ strategy/scores.json + Edit Loop → next week
```

Any step failure: stop, preserve logs, mark digest **DEGRADED**, print GitHub Issue text.
Never silently skip a gate, never endless-retry.

## Stack (fixed unless Samuel approves otherwise)

| Layer | Choice |
|---|---|
| Language | Python 3.12–3.15 |
| AI | Mistral API, strict JSON-schema outputs |
| Orchestration | Plain Python (`amplify/`) |
| Scheduler | GitHub Actions cron |
| Source control | Git + GitHub (branches, PRs, CI) |
| Storage | Versioned files; `analytics/marketing.sqlite` (gitignored) |
| Secrets env | `MISTRAL_API_KEY`; GitHub Secret for CI; never committed |
| Notifications | Markdown review digests; no messaging APIs in v1 |

> Local note (2026-10-23): the development sandbox provides Python 3.11.2. The code avoids
> 3.12-only syntax and CI targets Python 3.12. This is recorded in
> `docs/07-implementation-notes.md`.

## Repo map

```
mobius-muse-marketing/
├── AGENTS.md              ← build-agent constitution (root)
├── README.md
├── docs/                  ← 00..06 (+ implementation notes)
├── brand/                 ← foundation, voice-fingerprint, library, visual, banned-and-required
├── claims/                ← registry.json + evidence/
├── strategy/              ← audience, positioning, formats, scores.json
├── agents/                ← runtime system-prompt files (six contracts)
├── amplify/               ← the engine (client, agents, cycle, lint, ingest, config.yaml)
├── workflows/             ← reserved for future Path B definitions
├── content/               ← calendar, drafts, review, approved, published
├── campaigns/ assets/
├── analytics/             ← marketing.sqlite (gitignored), usage.jsonl, raw/
├── schemas/               ← content-item, rubric, per-agent output schemas
├── tests/
└── .github/workflows/     ← content-ci.yml, weekly.yml, tests.yml
```

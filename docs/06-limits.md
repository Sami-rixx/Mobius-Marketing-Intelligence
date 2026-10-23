# 06 — Hard Limits, Budgets & Failure Policy

> Source: `docs/pdf/06-limits.pdf` (authoritative).

## What this system will NEVER do

1. Auto-publish, auto-schedule, auto-reply, or buy ads. Publication is the founder’s
   signature. (Architecture-level: no platform credentials exist in this repo.)
2. Engagement-bait, rage-bait, or trend-chasing outside the pillars in
   `docs/01-architecture.md`.
3. Make a claim without a registry receipt. If it can’t be evidenced, it doesn’t get said.
4. Generate a synthetic “founder voice”. `brand/` grows only from real Samuel material.
5. Acquire tools to fix process problems. Two subscriptions maximum (Mistral; one creative
   tool), reviewed monthly.
6. Report an invented metric. Performance numbers come from platforms or from Samuel.
   “Unknown” is a valid value.

## Secrets & keys

- Engine key: env `MISTRAL_API_KEY`, loaded by `amplify/client.py` only. GitHub Secret
  `MISTRAL_API_KEY` for Actions. `.env` gitignored.
- Keep the engine key separate from the founder’s Vibe CLI coding key. The engine runs
  unattended weekly cycles with budget caps; the Vibe key is for interactive build-agent
  work. A runaway cycle must not consume coding quota.
- If any key ever lands in git history: revoke and reissue immediately; history rewrite is
  acceptable for a private repo.
- Never print keys in logs, even partially.

## Budget configuration — `amplify/config.yaml`

```yaml
models:
  default: "mistral-medium-3.5"   # drafting; revisit quarterly
  qa_judge: "<flagship-model>"    # judging quality
budgets:
  monthly_max_tokens: 2000000
  per_item_max_tokens: 8000
  max_retries_per_task: 2
```

- The runner refuses to start a cycle if `analytics/usage.jsonl` shows the monthly cap
  reached. Hard stop, logged, digest DEGRADED.
- Every API call appends usage to `usage.jsonl` (model, tokens, cost estimate, task id).
  Cost per usable item is computed in the weekly memo from this file — it must be accurate.

## Failure policy

- Agent/task failure → stop that branch of the cycle, preserve logs, cap retries at 2, mark
  the week’s digest **DEGRADED** with the reason and the affected items listed. Never
  endless-retry, never silently skip.
- CI failure → PR cannot merge. The planted-false-claim guardrail test (docs/03) must remain
  green-blocking forever.
- Schema failure at runtime → the item cannot reach review; treat as agent failure above.

## Scope control

- Any new platform, service, database, paid tool, or Path B workflow engine requires a
  founder-approved Issue BEFORE code. AGENTS.md hard rule 5.
- No dashboards in the pilot. GitHub Issues + markdown digests + `make review` are the UI.
  Revisit after 8 weeks of data.
- Docs drift is a defect: any behaviour-changing PR must update the relevant `docs/` file in
  the same PR (PR template checklist enforces).

## Security posture

Private repo. Collaborators: Samuel + build agents via GitHub integration only. No
third-party OAuth apps beyond what GitHub Actions requires. `analytics/marketing.sqlite` and
`.env` never committed.

# 03 — Content Item Schema & Quality Gate

> Source: `docs/pdf/03-content-schema.pdf` (authoritative).

## The content record (one YAML file per item)

Stored at `content/drafts/<week>-<format>-<slug>.yaml`:

```yaml
content_id: 2026-W43-FMT01-EP03
format: FMT-01
campaign: w43-proof-of-work
platforms: [youtube, tiktok, instagram, facebook]
audience: [global-builders, kenya-educators]
objective: brand_trust
hook: "I built this app on a phone. Here's the receipt."
script: |
  ...
caption: ...
cta: ...
visual_brief: ...
claims: [CLM-041, CLM-042, CLM-007]
sources: ...
scores: {truth: 0, brand: 0, voice: 0, hook: 0}   # filled by QA
status: in_review   # draft | in_review | approved | rejected | published
rejection_reason: null
published_urls: {}
performance: {}
```

Rules:

- `claims` entries must exist and be unexpired in `claims/registry.json`.
- Status transitions only: `draft → in_review → (approved | rejected) → (published after
  manual posting)`. Agents may not set `approved`; only Samuel’s `make review` decisions do.
- `rejection_reason` uses the taxonomy below; it feeds the learning loop.

## Rejection taxonomy (reason codes)

| Code | Meaning |
|---|---|
| `VOICE` | Doesn’t sound like Samuel |
| `UNVERIFIED_CLAIM` | Claim lacks registry evidence |
| `OFF_BRAND` | Visual/tagline/tone violation |
| `WEAK_HOOK` | Fails hook strength |
| `WRONG_AUDIENCE` | Register or platform mismatch |
| `TOO_GENERIC` | Could be any AI brand; no receipts |
| `PERSONAL` | “I’ll rewrite it myself” — no system fix implied |

## Rubric (QA scores each 0–100)

| Dimension | Weight |
|---|---|
| Hook strength (first 1.5 s / first line) | 25 |
| Specificity & evidence (receipts shown) | 25 |
| Clarity | 20 |
| Brand fit | 15 |
| Platform fit | 15 |

**Auto-reject below 70.** Store subscores in `scores:` so trends are measurable over time.

## Content CI (runs on PRs touching `content/` or `claims/`)

1. YAML/schema validation — malformed items never reach review.
2. Claims lint — every `claims:` entry exists, unexpired.
3. Brand lint — banned phrases (“game-changer”, “revolutionary”, “unlock the power”),
   tagline misuse (“The Inevitable Form”), off-palette visual refs, unapproved
   product-status words (nothing is “production-ready” unless the registry says so).
4. Voice lint — similarity check vs `brand/voice-fingerprint.md`; below threshold → reject.
5. Rubric presence — QA subscores present and ≥ threshold for items marked `in_review`.

## The guardrail proof (M0 acceptance test)

**CI must demonstrably catch a lie.** The M0 PR includes a test draft citing non-existent
claim `CLM-999`; CI fails on it; the failing run is shown in the PR, then the test draft is
removed. A truth layer that has never been seen catching anything is assumed broken.

> Implementation: `tests/fixtures/planted-false-claim.yaml` is a **permanent negative
> fixture**. It is never removed; the guardrail test and `make guardrail` validate it
> against a fixture registry and assert rejection. `content-ci.yml` runs that test on every
> PR that touches content, claims, schemas, brand or the engine.

## North-star metric

First-pass approval rate = share of items Samuel approves with zero edits. Target ≥40% at
pilot end (week 4), ≥60% by week 12. It is the single best measure of whether the team has
learned the founder’s voice.

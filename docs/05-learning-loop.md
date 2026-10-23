# 05 — Authenticity Engine & Learning Loop

> Source: `docs/pdf/05-learning-loop.pdf` (authoritative).

The compounding moat: the system becomes more Samuel every week. Three assets, one loop.

## 1. Voice fingerprint — `brand/voice-fingerprint.md`

A living document describing HOW Samuel writes: typical sentence length, vocabulary,
humour/earnestness balance, what he refuses to say, Kenyan vs global register cues,
formatting habits. The Producer writes to it; the voice lint checks against it; the Edit
Loop updates it.

**Guardrail:** the fingerprint is never changed by an agent directly. The Edit Loop proposes
a patch as a PR; only Samuel merges it. Voice changes are founder-signed, always.

## 2. Voice library — `brand/voice-library/`

Real samples of Samuel’s writing (posts, paragraphs, messages), tagged by context
(`founder-note`, `technical-lesson`, `kenya-audience`, `global-audience`, `humorous`,
`earnest`). Used as few-shot examples by the Producer. Rule: **only real material enters;
synthetic “brand voice” samples are forbidden** (`TOO_GENERIC` reject at lint if detected as
the source style).

## 3. The Edit Loop — how the team learns

**Capture (automatic, at `make review`):**

- Every Samuel edit to an approved draft → store before/after diff.
- Every rejection → item id + reason code + Samuel’s note.

**Distill (Sunday night run, `amplify editloop`):**

- An agent reads the week’s diffs + rejections and proposes: new voice-library samples,
  fingerprint patch, and Producer instruction patches — as a single PR titled
  `voice: week W43 learnings`.
- Samuel reviews and merges (or not). **Merging IS the training signal.**

This history — weeks of corrections — is the moat competitors cannot clone. Protect it:
`brand/` and `content/review/decisions-*.yaml` are never deleted, only appended.

## 4. Performance learning — `analytics/marketing.sqlite`

Tables (minimal): `items` (content_id, format, theme, hook_text, platforms, week),
`performance` (content_id, platform, metric, value, recorded_at — pasted by Samuel or
ingest), `usage` (API call log).

Derived: `strategy/scores.json` — rolling scores per theme, format, hook family, audience.
Written only by Growth Analyst.

Weekly memo (one question): “What should we do more of — with evidence?” Posted as an Issue
comment. Decision rule (written down so agents don’t drift): a theme earns 3 more cycles if
its rolling score is above median; below-median themes are cut without sentiment. Formats
are never killed before 3 full cycles.

## 5. Guardrail metrics (recorded weekly in the memo)

| Metric | Why |
|---|---|
| First-pass approval rate | Voice learning (north star) |
| API cost per workflow run | Finds expensive steps |
| Cost per usable content item | True production efficiency |
| Human editing time (minutes/item) | Is automation reducing Samuel’s load? |
| Workflow failure rate | Reliability |
| Reach / engagement per published item | Distribution |
| Qualified inquiries (Blueprint) | Revenue connection — report honestly, including zeros |

No metric is ever estimated by an agent. **Unknown is a valid value.**

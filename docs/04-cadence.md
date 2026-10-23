# 04 — Weekly Cadence & Platform Playbooks

> Source: `docs/pdf/04-cadence.pdf` (authoritative).

## Weekly operating cycle

| Day | Machine | Samuel |
|---|---|---|
| Mon | Strategist posts weekly plan as a GitHub Issue comment; 5-line summary | Approve/adjust (≤2 min) |
| Mon–Tue | Researcher → Producer (hero + derivatives) → Evidence Keeper refresh | — |
| Wed | Content CI + QA scoring; failures file Issue text | — |
| Thu 06:00 EAT | Actions cron fallback run; digest at `content/review/<week>-digest.md` | Main session: `make review`, 30–60 min |
| Fri–Sun | Growth Analyst waits; Producer revises rejected items from Thursday decisions | Publish manually at own pace; paste stats when convenient |
| Sun night | Analytics ingest; Edit Loop distillation; next-week preview | Optional skim |

**Resilience rule:** if any step fails, that week’s digest is marked **DEGRADED** with the
failure logged — Samuel never receives silence and never receives garbage.

## Publishing is manual, always

The system has no credentials for any platform and never will in this architecture. Samuel
posts each approved item personally. Platform schedulers (native YouTube/TikTok/FB
scheduling) may be used by Samuel at his discretion; the engine never touches them.

## Platform playbooks

- **YouTube** — home of FMT-01. Deliverables per item: title options, thumbnail brief,
  outline, full script, description with receipts linked (repo, Actions run). Shorts =
  sliced FMT-01/FMT-02 moments with re-captioned hooks.
- **TikTok** — Verification Files + build moments. Hook lands inside 1.5 seconds; receipts
  on screen (terminal, CI badge, artifact); zero fluff; vertical 9:16.
- **Instagram** — Reels (TikTok derivatives, re-captioned, re-thumbnailed); carousels (“5
  things building a company on a phone taught me” — evidence-styled slides in Deep Muse
  Blue #0A2463).
- **Facebook** — Kenyan audience. FMT-03 (Blueprint) lives here; longer-form founder notes;
  school-owner language, not builder language. Community tone: answer comments personally.

## Language & register (reinforced)

Default English. Kenyan conversational register for Kenya-targeted campaigns. Sheng only
where Samuel would naturally use it. Format and register come from
`brand/voice-fingerprint.md`, not from agent taste.

## Atomization (the law)

One hero asset per cycle → derivatives per platform. Derivatives must reuse the hero’s
substance; platform-native re-expression is required (copy-paste across platforms is a
`VOICE`/`WRONG_AUDIENCE` reject).

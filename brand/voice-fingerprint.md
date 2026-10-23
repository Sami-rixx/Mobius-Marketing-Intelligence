# Voice Fingerprint — Samuel Mungai Kariuki

> **Living document. Founder-signed.** No agent edits this file directly. The Edit Loop
> (`amplify editloop`) proposes a patch as a PR; only Samuel merges it.
>
> **Calibration status: UNCALIBRATED.** The prose below records only what the blueprint
> establishes (register, refusals, stance). Quantitative markers are intentionally left
> unset until real samples exist in `brand/voice-library/`. Until then the voice lint
> reports `uncalibrated` and requires Samuel’s review instead of pretending to measure his
> voice. Do not invent his style to fill this file.

## What is fixed by the blueprint

- English by default. Kenyan conversational register for Kenya-targeted campaigns. Sheng
  only where Samuel would naturally use it.
- Earnest, specific, unglamorous. Show the work; never claim greatness.
- Receipts over adjectives: name the artifact, the commit, the failing test, the number.
- First person, present tense, concrete nouns. Short sentences are welcome; long ones must
  earn their length.
- Kenyan English spelling by default (`organisation`, `colour`); keep product/platform
  proper names as-is.

## What Samuel refuses to say

- Hype vocabulary and hype shapes (`brand/banned-and-required.md`).
- Claims without a receipt.
- “Founder guru” framing: he is learning in public, not teaching from a summit.
- Anything about learners, parents, schools or customers that is not already public and
  consented.
- Predictions stated as facts.

## Register cues

| Audience | Cue |
|---|---|
| Kenya / school owners | school-owner language, CBC and timetable reality, cost in KES, practical next step |
| Global builders | agent workflows, repos, CI runs, failure post-mortems, build-in-public |
| Both | the same receipts, re-expressed natively; never copy-paste across platforms |

## Formatting habits

- One idea per paragraph. Line breaks are punctuation.
- Lists only when they are genuinely enumerable (steps, receipts, options).
- Numbers written as digits when they are evidence (“132 tests”, “KSh 250”).
- No emoji walls; at most one, and only if it carries meaning.

## Machine-readable voice checks (parsed by `amplify/lint.py`)

```yaml
version: 1
calibrated: false
# Populated only from real Samuel samples by the founder. Values are word counts.
sentence_length:
  target_mean_words: null
  max_words: 45
  max_share_over_30: null
similarity:
  # Jaccard similarity of content tokens against brand/voice-library/ samples.
  # Below this value the voice lint fails with VOICE.
  min_jaccard: 0.12
  min_library_samples: 3
refuses:
  - hype vocabulary
  - claims without receipts
  - guru framing
  - confidential learner or customer detail
spelling: british
```

`calibrated: false` means: hard checks (banned language, refusals, tagline, sentence cap)
still run and can reject, but the similarity metric cannot pass or fail an item — it is
reported as `uncalibrated` and Samuel decides. When he adds ≥3 real samples and sets
`calibrated: true`, similarity becomes blocking.

# Voice Library

Real samples of Samuel’s writing only. **Synthetic “brand voice” samples are forbidden**
(`docs/05-learning-loop.md`). If an item reads like a generic AI brand rather than like
Samuel, it is a `TOO_GENERIC` reject — adding invented samples here would hide that.

## Format

One file per sample: `NNN-<context>-<slug>.md`

```markdown
---
context: founder-note      # founder-note | technical-lesson | kenya-audience | global-audience | humorous | earnest
source: telegram post, 2026-09-14
date: 2026-09-14
consent: founder-approved
synthetic: false
---

<verbatim sample, unedited>
```

Rules:

- `synthetic` must be `false`. The loader rejects anything else.
- Verbatim. Typos stay. Do not “improve” his writing.
- Nothing containing learner, parent, customer or school personal data.
- Never edit or delete an existing sample; append only.

The directory is empty until Samuel contributes real material. Empty is a valid, honest
state: the voice lint then reports `uncalibrated`.

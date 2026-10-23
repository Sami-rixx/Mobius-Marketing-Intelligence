# docs/ — the Blueprint

`docs/pdf/` holds the authoritative PDFs. This folder holds Markdown copies that the engine and
its prompts can read, plus implementation notes. If a Markdown copy and its PDF disagree, the
PDF wins and the Markdown file is a defect to fix.

| File | Source PDF | Purpose |
|---|---|---|
| `00-vision.md` | `docs/pdf/00-vision.pdf` | identity, tagline, stories, audiences, Proof-of-Work stance |
| `01-architecture.md` | `docs/pdf/01-architecture.pdf` | Path A, claims registry, formats, data flow, stack, repo map |
| `02-agent-contracts.md` | `docs/pdf/02-agent-contracts.pdf` | the six agents: mission, inputs, schema, limits, stop-conditions |
| `03-content-schema.md` | `docs/pdf/03-content-schema.pdf` | content item, status rules, rejection taxonomy, rubric, CI gates |
| `04-cadence.md` | `docs/pdf/04-cadence.pdf` | weekly cycle, resilience rule, platform playbooks, atomization |
| `05-learning-loop.md` | `docs/pdf/05-learning-loop.pdf` | voice fingerprint, voice library, edit loop, performance learning |
| `06-limits.md` | `docs/pdf/06-limits.pdf` | hard limits, secrets, budgets, failure policy, scope control |
| `07-implementation-notes.md` | (this implementation) | decisions, ambiguities, verification, limitations |

Build-agent constitution: `../AGENTS.md`.

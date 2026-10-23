# content/

| Folder | Purpose |
|---|---|
| `calendar/` | optional per-week intent, read by the Strategist |
| `drafts/` | the live working set: one YAML per content item, status in the file |
| `review/` | digests, QA reports, plans, decision logs, analytics memos, voice proposals |
| `approved/` | optional archive for approved snapshots |
| `published/` | optional archive for published snapshots |
| `dry-run/` | gitignored output of `make dry-run` — a rehearsal, never reviewed or published |

Items live in `drafts/` and change status in place (`draft → in_review → approved →
rejected/published`); copying to `approved/`/`published/` is optional housekeeping and never
required for correctness.

`review/decisions-*.yaml` and `brand/` are append-only history: never delete them.

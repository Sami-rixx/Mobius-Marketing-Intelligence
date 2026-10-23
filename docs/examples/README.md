# docs/examples/

Real artifacts produced by the engine during verification — kept so the behaviour can be
inspected without running anything.

| File | What it is |
|---|---|
| `dry-run-2026-W43-digest.md` | the review digest from `python -m amplify run-weekly --week 2026-W43 --dry-run` |
| `dry-run-2026-W43-qa.json` | the QA report from the same run (schema: `schemas/qa-report.schema.json`) |
| `dry-run-2026-W43-plan.json` | the weekly plan from the same run (schema: `schemas/weekly-plan.schema.json`) |

**Provenance:** these came from the committed dry-run fixtures and the *synthetic* demo
registry in `tests/fixtures/demo/`. Every claim in them starts with `SYNTHETIC FIXTURE` and
none of it is real project information, a real approval, or a published asset. They are
rehearsals.

Regenerate (zero API cost, overwrites nothing in `content/`):

```bash
python -m amplify run-weekly --week 2026-W43 --dry-run
# digest: content/review/2026-W43-digest.md
```

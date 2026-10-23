# tests/fixtures/

**Synthetic test data only.** Nothing here is a claim about Möbius Muse, and nothing here may
be copied into `claims/` or published.

| Path | Purpose |
|---|---|
| `demo/registry.json` | a clearly-labelled synthetic Claims Registry so dry runs and tests can exercise the real gates |
| `planted-false-claim.yaml` | the guardrail proof: a schema-valid draft citing `CLM-999`, which exists nowhere |
| `dryrun/<week>-<agent>.json` | canned agent outputs replayed by `DryRunClient` at zero API cost |

Every synthetic claim statement starts with `SYNTHETIC FIXTURE`. If you ever see that text
in public content, the gate that should have caught it is broken.

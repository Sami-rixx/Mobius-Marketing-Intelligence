# claims/evidence/

Raw receipts for registry entries: screenshots, CI run links, artifact notes, founder
statements. The registry entry stores a short `evidence_ref`; this directory stores the
longer-lived copy where a file makes sense.

Rules:

- Never commit secrets, tokens or screenshots containing them.
- Never commit learner, parent, customer or school personal data.
- Name files after the claim: `CLM-007-ci-run.png`, `CLM-012-founder-note.md`.
- Evidence for a `personal_statement` claim is Samuel's own statement plus the approval date
  recorded in the registry entry.

The Evidence Keeper is the only writer of `claims/registry.json`. Register or quarantine
claims with:

```bash
python -m amplify evidence list
python -m amplify evidence add --statement "..." --evidence-type repo_commit \
  --evidence-ref "github.com/Sami-rixx/<repo> @ <sha>"
python -m amplify evidence quarantine --claim-id CLM-007 --reason "repo history rewritten"
```

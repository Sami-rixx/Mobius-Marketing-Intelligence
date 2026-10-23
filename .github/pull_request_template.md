## What changed

<!-- one paragraph; what behaviour changed and why -->

## Checklist (AGENTS.md hard rules)

- [ ] No secrets, tokens, `.env` files or screenshots containing them
- [ ] New/changed agent output validates against a schema in `schemas/`
- [ ] Every factual statement cites an existing, unexpired claim in `claims/registry.json`
- [ ] Nothing publishes, schedules, replies, messages or buys ads
- [ ] Path A only: no new platform, service, database or paid tool (or a founder-approved Issue is linked)
- [ ] `make lint` green locally
- [ ] `make test` green locally
- [ ] `make guardrail` green (planted false claim still rejected)
- [ ] Docs updated in this PR (`docs/`, `README.md`, brand files) if behaviour changed
- [ ] If the Claims Registry changed: evidence is attached/referenced and `personal_statement` claims have founder approval

## Evidence (receipts, not adjectives)

<!-- commands run, links, screenshots of real output -->

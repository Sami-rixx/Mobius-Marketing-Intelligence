# Banned & Required Language

Enforced by `amplify/lint.py` on every content item, in `hook`, `script`, `caption`, `cta`
and `visual_brief`. A hit is an `OFF_BRAND` (or `TOO_GENERIC`) reject.

## Banned marketing filler (hard fail)

```text
game-changer, game changer, revolutionary, unlock the power, unleash,
disrupt, disruptor, 10x, synergy, cutting-edge, next-level, secret sauce,
skyrocket, supercharge, paradigm shift, thought leader
```

## Banned hype shapes (hard fail)

- “AI will replace …”, “the future of work is here”, “this changes everything”.
- “hustle”, “grind”, “crush it” — hustle-culture register.
- Fake urgency: “limited time”, “act now”, “only 3 spots”.
- Engagement bait: “comment X if …”, “tag a friend”, “double tap if …”, “who else …?”.

## Retired tagline (hard fail)

- “The Inevitable Form” — retired; only **Making Ideas Inevitable** is valid.
- Any tagline not exactly “Making Ideas Inevitable” when a tagline is asserted.

## Unapproved product-status claims (hard fail without a registry receipt)

```text
production-ready, production ready, enterprise-grade, battle-tested,
launched, live, shipped, in production, generally available, GA,
scaling, thousands of users, thousands of schools, profitable,
revenue-generating, funded, backed by
```

These words are allowed **only** if the item cites a registry claim whose `statement`
contains the same assertion and whose `evidence_type` is not `personal_statement` *unless*
Samuel approved it. (Implementation: `lint.product_status_terms` checks the item's cited
claims.)

## Required in every item

- A concrete artifact, number or named method mentioned in `script` or `visual_brief`
  (something a reader could go and look at) — otherwise `TOO_GENERIC`.
- The canonical tagline, if any tagline appears, written exactly as “Making Ideas
  Inevitable”.

## Never

- Confidential learner, parent, customer or school data. No names of minors. No school
  records. Replace with generic descriptions.
- Claims about outcomes (grades, placements, revenue) without a registry receipt.

# analytics/

| Path | Tracked? | Purpose |
|---|---|---|
| `usage.jsonl` | yes | one JSON line per model call: model, tokens, cost estimate (null when no prices), task id, mode |
| `raw/<week>.yaml` | yes | platform/founder-supplied stats, pasted by hand |
| `marketing.sqlite` | **no** (gitignored) | local index built from `raw/` for rolling scores |

Rules:

- A metric exists only if a platform or Samuel supplied it. Missing values are stored `NULL`
  and listed as unknown. The engine never estimates reach, conversions, revenue or inquiries.
- Cost is recorded only when real prices exist in `amplify/config.yaml`. Otherwise it is
  `null` — unknown is a valid value.
- `analytics/raw/` files are evidence of what you pasted; keep them.

## `raw/<week>.yaml` format

```yaml
week: 2026-W43
source: "TikTok Studio export, pasted 2026-10-26"
items:
  - content_id: 2026-W43-FMT01-HERO-TT
    platform: tiktok
    metrics: {views: 1200, likes: 40, comments: 5}
human_editing_minutes: 45
workflow_runs: 4
workflow_failures: 1
qualified_inquiries_blueprint: 0
```

Omit any metric you do not have. Do not fill gaps with guesses.

# content/calendar/

Optional per-week intent, written by Samuel before the Monday plan or by `make review`
afterwards. The engine reads `<week>.yaml` if it exists and treats it as *input*, never as
truth.

```yaml
week: 2026-W43
note: "Blueprint demo week; school term just ended"
planned_items:
  - format: FMT-01
    note: "finish the timetable importer"
    must_include_claims: [CLM-101]
```

Absent calendar files are fine: the Strategist then plans from research and scores alone.

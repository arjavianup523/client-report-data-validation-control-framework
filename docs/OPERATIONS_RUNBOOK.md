# Operations Runbook

## Normal run
```powershell
.\.venv\Scripts\python.exe -m src.run_controls
```

## Run with explicit paths
```powershell
.\.venv\Scripts\python.exe -m src.run_controls `
  --positions data/positions.csv `
  --controls data/control_totals.csv `
  --reference data/security_reference.csv `
  --config config.json `
  --output outputs `
  --db data/control_audit.db
```

## Interpret results
- `APPROVED`: no critical exceptions; the Excel workbook is written to `outputs/`.
- `BLOCKED`: at least one critical exception; no client-report workbook is written.
- Exit code `0`: approved.
- Exit code `2`: blocked by a control failure. This is an expected operational outcome, not a program crash.
- A JSON run summary is created for either decision. Run details, exceptions, and release decisions are persisted in SQLite.

## Investigate a blocked run
1. Open `outputs/run_summary_<run_id>.json`.
2. Review the exception details persisted in `data/control_audit.db`.
3. Correct the upstream source or control total; do not bypass the failed rule.
4. Rerun controls against the corrected source.
5. Confirm the new run is approved before distributing the workbook.

## Useful SQLite queries
```sql
SELECT run_id, started_at, status, position_count, exception_count, variance
FROM control_runs
ORDER BY started_at DESC;

SELECT run_id, rule_id, severity, record_id, field, observed_value, message
FROM control_exceptions
ORDER BY exception_id DESC;

SELECT run_id, event_time, decision, reason
FROM release_events
ORDER BY event_id DESC;
```

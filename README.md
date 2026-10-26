# Client Report Data Validation & Control Framework

A portfolio-reporting control workflow designed to demonstrate how investment operations teams can prevent inaccurate source data from reaching client reports.

## What it does
- Loads portfolio positions and a reference/control-total file.
- Validates required columns, missing values, duplicate position IDs, invalid quantities/prices, and unknown securities.
- Reconciles portfolio market value against supplied control totals using a configurable tolerance.
- Classifies exceptions by severity.
- Persists each run and its exceptions in SQLite.
- Records SHA-256 fingerprints and file sizes for the positions, control totals, security reference, and configuration used in each run.
- Includes a Source File Evidence worksheet in approved Excel reports and stores the same evidence in the audit database.
- Applies a release gate: a report is blocked if any critical exception exists.
- Exports an Excel workbook with a control summary, exceptions, and positions (only when release is approved).
- Includes automated tests for approval and blocking scenarios.

> This is a portfolio project using synthetic data, not a production-certified financial control system. It does not represent Franklin Templeton's internal systems or procedures.

## Requirements
- Python 3.10+
- Packages in `requirements.txt`

## Run on Windows (PowerShell)
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.run_controls --positions data/positions.csv --controls data/control_totals.csv --output outputs
```

If you already have a virtual environment, use its Python executable instead of creating another.

## Expected outputs
- `outputs/control_report_<run_id>.xlsx` when approved
- `outputs/run_summary_<run_id>.json` for every run
- `data/control_audit.db` containing run history and exceptions

If critical controls fail, the Excel client report is not created. The run summary and audit database still record the blocked decision.

## Demonstrate both release outcomes
Run the scenario demo below. It uses temporary copies of the sample data and does not overwrite your source CSVs, existing outputs, or audit database. It verifies that clean data is approved and a deliberately mismatched control total is blocked.
```powershell
.\.venv\Scripts\python.exe -m scripts.run_demo_scenarios
```

## Demonstrate both release outcomes
Run the scenario demo below. It uses temporary copies of the sample data and does not overwrite your source CSVs, existing outputs, or audit database. It verifies that clean data is approved and a deliberately mismatched control total is blocked.
```powershell
.\.venv\Scripts\python.exe -m scripts.run_demo_scenarios
```

## Test
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Control logic
- Critical: missing required fields, duplicate position IDs, invalid/non-positive quantities or prices, unknown security IDs, reconciliation variance above tolerance.
- Warning: missing optional descriptive values.
- Release rule: no critical exceptions.
- Reconciliation: compare the sum of `quantity * price` with the supplied control total, using absolute tolerance from `config.json`.

## Suggested next engineering increments
1. Add immutable source-file hashes and run metadata.
2. Add maker-checker approval and role-based permissions.
3. Add configurable control rules and versioned rule sets.
4. Add idempotency and safe re-runs.
5. Add structured logging and CI workflow.

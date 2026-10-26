# Control Matrix

| Control ID | Control objective | Test | Severity | Release impact | Evidence |
|---|---|---|---|---|---|
| SCHEMA-001 | Ensure required source fields exist | Required-column presence | Critical | Block | Run exception + JSON summary |
| DQ-001 | Ensure required fields are populated | Null checks on required fields | Critical | Block | Position ID, field, observed value |
| DQ-002 | Prevent double counting | Duplicate `position_id` detection | Critical | Block | Every row participating in duplicate |
| DQ-003 | Prevent invalid valuation inputs | Numeric, positive quantity and price | Critical | Block | Field-level exception |
| REF-001 | Ensure positions map to approved security reference data | `security_id` lookup | Critical | Block | Unmatched security ID |
| DQ-004 | Flag incomplete descriptive metadata | Missing currency | Warning | Does not block by itself | Warning exception |
| REC-001 | Ensure control total is available and unambiguous | Exactly one numeric portfolio control total | Critical | Block | Control-file exception |
| REC-002 | Ensure calculated value agrees to source control | Sum(quantity × price) compared with control total within tolerance | Critical | Block | Calculated, expected, and variance in run summary |

## Release policy
A run is `APPROVED` only when there are no configured release-blocking severities. Otherwise it is `BLOCKED`. A blocked run retains a JSON summary and SQLite audit record, but the client-report workbook is not generated.

## Known design boundary
This portfolio prototype demonstrates deterministic pre-release controls. It does not implement user authentication, independent maker-checker approval, signed audit records, market-price feeds, tax-lot accounting, or production access controls.

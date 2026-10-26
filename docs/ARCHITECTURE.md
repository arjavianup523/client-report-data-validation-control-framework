# Architecture

```text
Source positions CSV ─┐
Control totals CSV ───┼─> Input loading ─> Validation controls ─> Reconciliation
Security reference ───┘                                      │
                                                             v
                                                   Release decision
                                                    /            \
                                               APPROVED          BLOCKED
                                                  |                 |
                                      Excel control report      No report
                                                  \                 /
                                                   JSON run summary
                                                            |
                                                 SQLite audit history
```

## Components
- `src/control_engine.py`: validation, reconciliation, release decision, persistence, and Excel/JSON outputs.
- `src/run_controls.py`: command-line entry point and exit status.
- `data/`: synthetic positions, security reference, and expected control total.
- `tests/`: unit tests for individual control rules and end-to-end release behavior.
- `data/control_audit.db`: generated run, exception, and release-event history; excluded from version control.
- `outputs/`: generated run summaries and approved Excel reports; excluded from version control.

## Design choices
- Critical failures fail closed: no approved report is emitted.
- Warning exceptions are retained but do not independently block release.
- Run IDs link a control run, exceptions, and its release decision.
- The tolerance is configuration-driven rather than embedded in the reconciliation rule.

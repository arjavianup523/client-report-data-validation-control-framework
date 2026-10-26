
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.run_comparison import compare_runs, write_comparison_json
from src.exception_trends import (
    get_exception_trends,
    get_recurring_exceptions,
    get_run_history,
)
from src.remediation_tracker import (
    sync_remediation_cases,
    list_remediation_cases,
    get_remediation_summary,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE_DIR / "data" / "control_audit.db"
REPORT_DIR = BASE_DIR / "reports"


def _resolve_path(path: str | Path) -> Path:
    """Resolve relative paths against the project root."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return BASE_DIR / candidate


def _case_status(case: dict[str, Any]) -> str:
    """Return a normalized remediation status."""
    return str(case.get("status", "")).strip()


def build_remediation_section(
    db_path: str | Path,
) -> dict[str, Any]:
    """Synchronize exceptions and report every remediation lifecycle stage."""
    new_cases_registered = sync_remediation_cases(db_path)

    # Fetch the case list once, then classify the cases consistently.
    all_cases = list_remediation_cases(db_path, limit=10000)

    open_cases = [
        case for case in all_cases
        if _case_status(case) == "Open"
    ]

    in_progress_cases = [
        case for case in all_cases
        if _case_status(case) == "In Progress"
    ]

    resolved_cases = [
        case for case in all_cases
        if _case_status(case) == "Resolved"
    ]

    wont_fix_cases = [
        case for case in all_cases
        if _case_status(case) == "Won't Fix"
    ]

    active_cases = open_cases + in_progress_cases

    summary = get_remediation_summary(db_path)

    return {
        "new_cases_registered": new_cases_registered,
        "summary": summary,
        "active_cases": active_cases,
        "open_cases": open_cases,
        "in_progress_cases": in_progress_cases,
        "resolved_cases": resolved_cases,
        "wont_fix_cases": wont_fix_cases,
    }


def build_run_comparison(
    db_path: str | Path,
    report_dir: str | Path,
) -> dict[str, Any]:
    """Compare the two latest runs and save the comparison when possible."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    try:
        comparison = compare_runs(db_path=db_path)

        comparison_path = report_dir / "latest_run_comparison.json"
        write_comparison_json(comparison, comparison_path)

        return {
            "available": True,
            "result": comparison,
            "report_path": str(comparison_path),
        }

    except (ValueError, LookupError) as exc:
        return {
            "available": False,
            "reason": str(exc),
        }


def generate_operational_review(
    db_path: str | Path = DEFAULT_DB,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate an integrated operational control review."""
    db_path = _resolve_path(db_path)

    if report_path is None:
        report_path = REPORT_DIR / "operational_review.json"
    else:
        report_path = _resolve_path(report_path)

    report_path.parent.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        raise FileNotFoundError(
            f"Audit database was not found: {db_path}"
        )

    # Gather audit history and exception monitoring.
    run_history = get_run_history(db_path)
    exception_trends = get_exception_trends(db_path)
    recurring_exceptions = get_recurring_exceptions(db_path)

    # Synchronize remediation cases and report all lifecycle stages.
    remediation = build_remediation_section(db_path)

    # Compare the latest runs when at least two suitable runs exist.
    run_comparison = build_run_comparison(
        db_path=db_path,
        report_dir=report_path.parent,
    )

    report = {
        "report_name": "Client Report Operational Control Review",
        "generated_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "database": str(db_path),
        "run_history": run_history,
        "exception_trends": exception_trends,
        "recurring_exceptions": recurring_exceptions,
        "remediation": remediation,
        "run_comparison": run_comparison,
    }

    report_path.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )

    return report


def main() -> None:
    report_path = REPORT_DIR / "operational_review.json"

    report = generate_operational_review(
        db_path=DEFAULT_DB,
        report_path=report_path,
    )

    remediation = report["remediation"]
    summary = remediation["summary"]

    print("Operational review generated successfully.")
    print(f"Database: {DEFAULT_DB}")
    print(f"Report:   {report_path}")
    print(
        "New remediation cases registered: "
        f"{remediation['new_cases_registered']}"
    )
    print(
        "Recurring exceptions: "
        f"{len(report['recurring_exceptions'])}"
    )
    print(f"Open remediation cases: {summary['open_cases']}")
    print(
        "In-progress remediation cases: "
        f"{summary['in_progress_cases']}"
    )
    print(
        "Active remediation cases: "
        f"{len(remediation['active_cases'])}"
    )
    print(
        "Run comparison available: "
        f"{report['run_comparison']['available']}"
    )


if __name__ == "__main__":
    main()

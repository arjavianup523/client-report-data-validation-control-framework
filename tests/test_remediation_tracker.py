
import pytest

from src.control_engine import ExceptionRecord, persist_run
from src.remediation_tracker import (
    get_remediation_audit,
    get_remediation_summary,
    list_remediation_cases,
    sync_remediation_cases,
    update_remediation_case,
)


def make_exception(
    rule_id="DQ-003",
    record_id="P001",
    field="price",
    severity="CRITICAL",
):
    return ExceptionRecord(
        rule_id=rule_id,
        severity=severity,
        record_id=record_id,
        field=field,
        observed_value="invalid",
        message=f"Test failure: {field}",
    )


def save_run(db_path, run_id, exceptions):
    persist_run(
        db_path=db_path,
        run_id=run_id,
        started_at="2026-10-26T10:00:00+00:00",
        finished_at="2026-10-26T10:00:00+00:00",
        positions_file="test_positions.csv",
        status="BLOCKED" if exceptions else "APPROVED",
        position_count=1,
        exceptions=exceptions,
        metrics={
            "market_value": 100.0,
            "expected_market_value": 100.0,
            "variance": 0.0,
        },
        message="Test run",
    )


def seed_database(db_path):
    save_run(
        db_path,
        "RUN_001",
        [
            make_exception(),
            make_exception(
                rule_id="REF-001",
                record_id="P002",
                field="security_id",
            ),
            make_exception(
                rule_id="DQ-004",
                record_id="P003",
                field="account_id",
                severity="WARNING",
            ),
        ],
    )


def test_sync_registers_exceptions_once(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    assert sync_remediation_cases(db_path) == 3
    assert sync_remediation_cases(db_path) == 0

    cases = list_remediation_cases(db_path)
    assert len(cases) == 3
    assert all(case["status"] == "Open" for case in cases)


def test_case_can_be_assigned_and_updated(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    case = list_remediation_cases(
        db_path,
        severity="CRITICAL",
    )[0]

    updated = update_remediation_case(
        db_path,
        case["exception_key"],
        changed_by="reporting-analyst",
        owner="Operations Team",
        root_cause="Invalid source price",
        status="In Progress",
    )

    assert updated["owner"] == "Operations Team"
    assert updated["root_cause"] == "Invalid source price"
    assert updated["status"] == "In Progress"
    assert updated["resolved_at"] is None


def test_resolving_case_sets_resolution_timestamp(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    case = list_remediation_cases(db_path)[0]

    updated = update_remediation_case(
        db_path,
        case["exception_key"],
        changed_by="reviewer",
        status="Resolved",
        resolution_notes="Corrected the source record.",
    )

    assert updated["status"] == "Resolved"
    assert updated["resolved_at"] is not None
    assert updated["resolution_notes"] == (
        "Corrected the source record."
    )


def test_reopening_case_clears_resolution_timestamp(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    case = list_remediation_cases(db_path)[0]

    update_remediation_case(
        db_path,
        case["exception_key"],
        changed_by="reviewer",
        status="Resolved",
    )

    reopened = update_remediation_case(
        db_path,
        case["exception_key"],
        changed_by="reviewer",
        status="In Progress",
    )

    assert reopened["status"] == "In Progress"
    assert reopened["resolved_at"] is None


def test_each_change_is_audited(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    case = list_remediation_cases(db_path)[0]

    update_remediation_case(
        db_path,
        case["exception_key"],
        changed_by="analyst",
        owner="Team A",
        status="In Progress",
    )

    audit = get_remediation_audit(
        db_path,
        case["exception_key"],
    )

    assert audit[0]["field_name"] == "case_created"
    assert any(
        entry["field_name"] == "owner"
        and entry["new_value"] == "Team A"
        for entry in audit
    )
    assert any(
        entry["field_name"] == "status"
        and entry["new_value"] == "In Progress"
        for entry in audit
    )


def test_summary_counts_status_and_severity(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    cases = list_remediation_cases(db_path)
    critical_case = next(
        case for case in cases
        if case["severity"] == "CRITICAL"
    )

    update_remediation_case(
        db_path,
        critical_case["exception_key"],
        changed_by="reviewer",
        status="Resolved",
    )

    summary = get_remediation_summary(db_path)

    assert summary["total_cases"] == 3
    assert summary["resolved_cases"] == 1
    assert summary["open_cases"] == 2
    assert summary["by_severity"]["CRITICAL"] == 2
    assert summary["by_severity"]["WARNING"] == 1


def test_invalid_status_is_rejected(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    case = list_remediation_cases(db_path)[0]

    with pytest.raises(ValueError, match="Invalid status"):
        update_remediation_case(
            db_path,
            case["exception_key"],
            changed_by="reviewer",
            status="Closed",
        )


def test_missing_case_is_rejected(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    with pytest.raises(ValueError, match="not found"):
        update_remediation_case(
            db_path,
            "does-not-exist",
            changed_by="reviewer",
            status="Resolved",
        )


def test_blank_auditor_is_rejected(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    case = list_remediation_cases(db_path)[0]

    with pytest.raises(ValueError, match="changed_by cannot be blank"):
        update_remediation_case(
            db_path,
            case["exception_key"],
            changed_by=" ",
            status="Resolved",
        )


def test_original_control_exception_is_preserved(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_database(db_path)

    case = list_remediation_cases(db_path)[0]

    update_remediation_case(
        db_path,
        case["exception_key"],
        changed_by="reviewer",
        status="Resolved",
        resolution_notes="Fixed after review.",
    )

    import sqlite3

    with sqlite3.connect(db_path) as connection:
        original_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM control_exceptions
            WHERE run_id = ?
            """,
            ("RUN_001",),
        ).fetchone()[0]

    assert original_count == 3

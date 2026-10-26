
import json

import pytest

from src.control_engine import ExceptionRecord, persist_run
from src.run_comparison import compare_runs, write_comparison_json


def save_test_run(
    db_path,
    run_id,
    finished_at,
    status,
    exceptions,
    market_value,
    variance,
):
    persist_run(
        db_path=db_path,
        run_id=run_id,
        started_at=finished_at,
        finished_at=finished_at,
        positions_file="test_positions.csv",
        status=status,
        position_count=1,
        exceptions=exceptions,
        metrics={
            "market_value": market_value,
            "expected_market_value": market_value - variance,
            "variance": variance,
        },
        message=f"Test run {status.lower()}",
    )


def exception(rule_id, record_id, field, value="bad value"):
    return ExceptionRecord(
        rule_id=rule_id,
        severity="CRITICAL",
        record_id=record_id,
        field=field,
        observed_value=value,
        message=f"Test exception for {field}",
    )


def test_comparison_identifies_new_resolved_and_recurring(
    tmp_path,
):
    db_path = tmp_path / "audit.db"

    previous_exceptions = [
        exception("DQ-003", "P1", "price", "-1"),
        exception("REF-001", "P2", "security_id", "UNKNOWN"),
    ]

    current_exceptions = [
        exception("DQ-003", "P1", "price", "0"),
        exception("REC-002", "PORTFOLIO", "market_value_variance"),
    ]

    save_test_run(
        db_path,
        "RUN_OLD",
        "2026-10-25T10:00:00+00:00",
        "BLOCKED",
        previous_exceptions,
        100.0,
        5.0,
    )

    save_test_run(
        db_path,
        "RUN_NEW",
        "2026-10-26T10:00:00+00:00",
        "BLOCKED",
        current_exceptions,
        110.0,
        7.0,
    )

    result = compare_runs(db_path)

    assert result["comparison"]["previous_run_id"] == "RUN_OLD"
    assert result["comparison"]["current_run_id"] == "RUN_NEW"

    assert result["release"]["previous_status"] == "BLOCKED"
    assert result["release"]["current_status"] == "BLOCKED"
    assert result["release"]["status_changed"] is False

    assert result["financial_movement"]["market_value_change"] == 10.0
    assert result["financial_movement"]["variance_change"] == 2.0

    summary = result["exception_summary"]
    assert summary["new_count"] == 1
    assert summary["resolved_count"] == 1
    assert summary["recurring_count"] == 1

    assert summary["new"][0]["rule_id"] == "REC-002"
    assert summary["resolved"][0]["rule_id"] == "REF-001"
    assert summary["recurring"][0]["rule_id"] == "DQ-003"


def test_comparison_detects_release_status_change(tmp_path):
    db_path = tmp_path / "audit.db"

    save_test_run(
        db_path,
        "RUN_OLD",
        "2026-10-25T10:00:00+00:00",
        "BLOCKED",
        [exception("REC-002", "PORTFOLIO", "market_value_variance")],
        100.0,
        5.0,
    )

    save_test_run(
        db_path,
        "RUN_NEW",
        "2026-10-26T10:00:00+00:00",
        "APPROVED",
        [],
        100.0,
        0.0,
    )

    result = compare_runs(db_path)

    assert result["release"]["previous_status"] == "BLOCKED"
    assert result["release"]["current_status"] == "APPROVED"
    assert result["release"]["status_changed"] is True
    assert result["exception_summary"]["resolved_count"] == 1
    assert result["exception_summary"]["current_exception_count"] == 0


def test_comparison_requires_two_runs(tmp_path):
    db_path = tmp_path / "audit.db"

    save_test_run(
        db_path,
        "ONLY_RUN",
        "2026-10-26T10:00:00+00:00",
        "APPROVED",
        [],
        100.0,
        0.0,
    )

    with pytest.raises(ValueError, match="at least two"):
        compare_runs(db_path)


def test_comparison_requires_both_explicit_run_ids(tmp_path):
    with pytest.raises(ValueError, match="both current_run_id"):
        compare_runs(
            tmp_path / "audit.db",
            current_run_id="RUN_NEW",
        )


def test_comparison_json_is_written(tmp_path):
    db_path = tmp_path / "audit.db"

    save_test_run(
        db_path,
        "RUN_OLD",
        "2026-10-25T10:00:00+00:00",
        "APPROVED",
        [],
        100.0,
        0.0,
    )

    save_test_run(
        db_path,
        "RUN_NEW",
        "2026-10-26T10:00:00+00:00",
        "APPROVED",
        [],
        105.0,
        0.0,
    )

    result = compare_runs(db_path)
    output_path = write_comparison_json(
        result,
        tmp_path / "reports" / "run_comparison.json",
    )

    assert output_path.exists()
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["comparison"]["current_run_id"] == "RUN_NEW"

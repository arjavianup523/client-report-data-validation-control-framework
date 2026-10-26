
import pytest

from src.control_engine import ExceptionRecord, persist_run
from src.exception_trends import (
    get_exception_trends,
    get_recurring_exceptions,
    get_run_history,
)


def make_exception(
    rule_id,
    record_id,
    field,
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


def save_run(
    db_path,
    run_id,
    finished_at,
    status,
    exceptions,
    market_value=100.0,
    variance=0.0,
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


def seed_three_runs(db_path):
    save_run(
        db_path,
        "RUN_001",
        "2026-10-24T10:00:00+00:00",
        "BLOCKED",
        [
            make_exception("DQ-003", "P001", "price"),
            make_exception("REF-001", "P002", "security_id"),
        ],
        market_value=100.0,
        variance=5.0,
    )

    save_run(
        db_path,
        "RUN_002",
        "2026-10-25T10:00:00+00:00",
        "BLOCKED",
        [
            make_exception("DQ-003", "P001", "price"),
            make_exception("DQ-003", "P003", "quantity"),
        ],
        market_value=110.0,
        variance=3.0,
    )

    save_run(
        db_path,
        "RUN_003",
        "2026-10-26T10:00:00+00:00",
        "APPROVED",
        [
            make_exception("DQ-003", "P001", "price"),
        ],
        market_value=100.0,
        variance=0.0,
    )


def test_exception_trends_rank_rules_by_occurrences(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_three_runs(db_path)

    trends = get_exception_trends(db_path)

    assert trends[0]["rule_id"] == "DQ-003"
    assert trends[0]["total_occurrences"] == 4
    assert trends[0]["affected_runs"] == 3

    reference_trend = next(
        item for item in trends
        if item["rule_id"] == "REF-001"
    )
    assert reference_trend["total_occurrences"] == 1
    assert reference_trend["affected_runs"] == 1


def test_recurring_exceptions_find_same_record_and_field(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_three_runs(db_path)

    recurring = get_recurring_exceptions(db_path)

    assert len(recurring) == 1

    item = recurring[0]
    assert item["rule_id"] == "DQ-003"
    assert item["record_id"] == "P001"
    assert item["field"] == "price"
    assert item["affected_runs"] == 3
    assert item["total_occurrences"] == 3
    assert item["last_seen"] == "2026-10-26T10:00:00+00:00"


def test_recurring_exceptions_respect_minimum_runs(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_three_runs(db_path)

    recurring = get_recurring_exceptions(
        db_path,
        minimum_runs=4,
    )

    assert recurring == []


def test_run_history_returns_most_recent_first(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_three_runs(db_path)

    history = get_run_history(db_path)

    assert [run["run_id"] for run in history] == [
        "RUN_003",
        "RUN_002",
        "RUN_001",
    ]
    assert history[0]["status"] == "APPROVED"
    assert history[0]["variance"] == 0.0


def test_run_history_limit_is_respected(tmp_path):
    db_path = tmp_path / "audit.db"
    seed_three_runs(db_path)

    history = get_run_history(db_path, limit=2)

    assert len(history) == 2
    assert [run["run_id"] for run in history] == [
        "RUN_003",
        "RUN_002",
    ]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_limit_is_rejected(tmp_path, limit):
    db_path = tmp_path / "audit.db"
    seed_three_runs(db_path)

    with pytest.raises(ValueError, match="limit must be"):
        get_exception_trends(db_path, limit=limit)


@pytest.mark.parametrize("minimum_runs", [0, 1, -1, True, 2.5])
def test_invalid_minimum_runs_is_rejected(
    tmp_path,
    minimum_runs,
):
    db_path = tmp_path / "audit.db"
    seed_three_runs(db_path)

    with pytest.raises(ValueError, match="minimum_runs must"):
        get_recurring_exceptions(
            db_path,
            minimum_runs=minimum_runs,
        )


def test_missing_database_is_reported(tmp_path):
    db_path = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match="does not exist"):
        get_exception_trends(db_path)

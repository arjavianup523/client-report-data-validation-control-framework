
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


EXCEPTION_COLUMNS = (
    "rule_id",
    "severity",
    "record_id",
    "field",
    "observed_value",
    "message",
)

EXCEPTION_SIGNATURE = (
    "rule_id",
    "severity",
    "record_id",
    "field",
)


def _load_run(
    connection: sqlite3.Connection,
    run_id: str,
) -> dict[str, Any]:
    """Load one run and fail clearly if it does not exist."""
    row = connection.execute(
        """
        SELECT
            run_id,
            started_at,
            finished_at,
            status,
            position_count,
            exception_count,
            market_value,
            expected_market_value,
            variance,
            message
        FROM control_runs
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()

    if row is None:
        raise ValueError(
            f"Run ID not found in audit database: {run_id}"
        )

    columns = (
        "run_id",
        "started_at",
        "finished_at",
        "status",
        "position_count",
        "exception_count",
        "market_value",
        "expected_market_value",
        "variance",
        "message",
    )

    return dict(zip(columns, row))


def _load_exceptions(
    connection: sqlite3.Connection,
    run_id: str,
) -> list[dict[str, Any]]:
    """Load structured exceptions for a single run."""
    rows = connection.execute(
        """
        SELECT
            rule_id,
            severity,
            record_id,
            field,
            observed_value,
            message
        FROM control_exceptions
        WHERE run_id = ?
        ORDER BY rule_id, severity, record_id, field
        """,
        (run_id,),
    ).fetchall()

    return [
        dict(zip(EXCEPTION_COLUMNS, row))
        for row in rows
    ]


def _signature(
    exception: dict[str, Any],
) -> tuple[str, str, str, str]:
    """Create a stable key identifying an exception."""
    return tuple(
        str(exception[column])
        for column in EXCEPTION_SIGNATURE
    )


def _exception_counts(
    exceptions: list[dict[str, Any]],
) -> tuple[
    Counter[tuple[str, str, str, str]],
    dict[tuple[str, str, str, str], dict[str, Any]],
]:
    """Count exceptions and retain their latest available details."""
    counts: Counter[tuple[str, str, str, str]] = Counter()
    details: dict[
        tuple[str, str, str, str],
        dict[str, Any],
    ] = {}

    for exception in exceptions:
        key = _signature(exception)
        counts[key] += 1
        details[key] = exception

    return counts, details


def _exception_changes(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compare exceptions using rule, severity, record, and field.

    Changed observed values or message text do not by themselves create
    a new exception when the underlying signature remains the same.
    """
    previous_counts, previous_details = _exception_counts(previous)
    current_counts, current_details = _exception_counts(current)

    new: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    recurring: list[dict[str, Any]] = []

    all_keys = sorted(set(previous_counts) | set(current_counts))

    for key in all_keys:
        old_count = previous_counts[key]
        new_count = current_counts[key]

        if new_count > old_count:
            item = current_details[key].copy()
            item["occurrences"] = new_count - old_count
            new.append(item)

        if old_count > new_count:
            item = previous_details[key].copy()
            item["occurrences"] = old_count - new_count
            resolved.append(item)

        if old_count > 0 and new_count > 0:
            item = current_details[key].copy()
            item["occurrences"] = min(old_count, new_count)
            recurring.append(item)

    return {
        "new": new,
        "resolved": resolved,
        "recurring": recurring,
        "new_count": sum(item["occurrences"] for item in new),
        "resolved_count": sum(
            item["occurrences"] for item in resolved
        ),
        "recurring_count": sum(
            item["occurrences"] for item in recurring
        ),
    }


def compare_runs(
    db_path: str | Path,
    current_run_id: str | None = None,
    previous_run_id: str | None = None,
) -> dict[str, Any]:
    """
    Compare two audit runs in the existing SQLite database.

    If no IDs are supplied, compare the two most recent runs.
    If explicit IDs are supplied, both must be provided.
    """
    if (current_run_id is None) != (previous_run_id is None):
        raise ValueError(
            "Provide both current_run_id and previous_run_id, or neither."
        )

    database_path = Path(db_path)

    if not database_path.is_file():
        raise FileNotFoundError(
            f"Audit database does not exist: {database_path}"
        )

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row

        if current_run_id is None:
            rows = connection.execute(
                """
                SELECT run_id
                FROM control_runs
                ORDER BY finished_at DESC, run_id DESC
                LIMIT 2
                """
            ).fetchall()

            if len(rows) < 2:
                raise ValueError(
                    "at least two completed audit runs are required "
                    "for comparison."
                )

            current_run_id = rows[0]["run_id"]
            previous_run_id = rows[1]["run_id"]

        current = _load_run(connection, current_run_id)
        previous = _load_run(connection, previous_run_id)

        current_exceptions = _load_exceptions(
            connection,
            current_run_id,
        )
        previous_exceptions = _load_exceptions(
            connection,
            previous_run_id,
        )

    changes = _exception_changes(
        previous_exceptions,
        current_exceptions,
    )

    previous_market_value = previous["market_value"]
    current_market_value = current["market_value"]

    market_value_change = (
        current_market_value - previous_market_value
        if (
            current_market_value is not None
            and previous_market_value is not None
        )
        else None
    )

    previous_variance = previous["variance"]
    current_variance = current["variance"]

    variance_change = (
        current_variance - previous_variance
        if (
            current_variance is not None
            and previous_variance is not None
        )
        else None
    )

    return {
        "comparison": {
            "previous_run_id": previous["run_id"],
            "current_run_id": current["run_id"],
            "previous_finished_at": previous["finished_at"],
            "current_finished_at": current["finished_at"],
        },
        "release": {
            "previous_status": previous["status"],
            "current_status": current["status"],
            "status_changed": (
                previous["status"] != current["status"]
            ),
        },
        "financial_movement": {
            "previous_market_value": previous_market_value,
            "current_market_value": current_market_value,
            "market_value_change": market_value_change,
            "previous_variance": previous_variance,
            "current_variance": current_variance,
            "variance_change": variance_change,
        },
        "exception_summary": {
            "previous_exception_count": len(previous_exceptions),
            "current_exception_count": len(current_exceptions),
            "exception_count_change": (
                len(current_exceptions) - len(previous_exceptions)
            ),
            **changes,
        },
    }


def write_comparison_json(
    comparison: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Write comparison results to a JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(
            comparison,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    return path

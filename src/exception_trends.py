
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _validate_database(db_path: str | Path) -> Path:
    """Validate the audit database path before querying it."""
    path = Path(db_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Audit database does not exist: {path}"
        )

    return path


def _validate_limit(limit: int, name: str = "limit") -> None:
    """Require a positive integer limit."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"{name} must be a positive integer.")


def get_exception_trends(
    db_path: str | Path,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """
    Rank exception rules by total occurrences across audit runs.

    Each result includes the rule, severity, total occurrences,
    number of distinct affected runs, and latest occurrence time.
    """
    _validate_limit(limit)

    path = _validate_database(db_path)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute(
            """
            SELECT
                e.rule_id,
                e.severity,
                COUNT(*) AS total_occurrences,
                COUNT(DISTINCT e.run_id) AS affected_runs,
                MAX(r.finished_at) AS last_seen
            FROM control_exceptions AS e
            INNER JOIN control_runs AS r
                ON r.run_id = e.run_id
            GROUP BY
                e.rule_id,
                e.severity
            ORDER BY
                total_occurrences DESC,
                affected_runs DESC,
                e.rule_id ASC,
                e.severity ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_recurring_exceptions(
    db_path: str | Path,
    minimum_runs: int = 2,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Find exceptions present in at least minimum_runs distinct runs.

    Recurrence is identified by rule_id, severity, record_id, and field.
    A repeated exception in the same run does not count as multiple runs.
    """
    if (
        isinstance(minimum_runs, bool)
        or not isinstance(minimum_runs, int)
        or minimum_runs < 2
    ):
        raise ValueError(
            "minimum_runs must be an integer greater than or equal to 2."
        )

    _validate_limit(limit)
    path = _validate_database(db_path)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute(
            """
            SELECT
                e.rule_id,
                e.severity,
                e.record_id,
                e.field,
                COUNT(*) AS total_occurrences,
                COUNT(DISTINCT e.run_id) AS affected_runs,
                MAX(r.finished_at) AS last_seen
            FROM control_exceptions AS e
            INNER JOIN control_runs AS r
                ON r.run_id = e.run_id
            GROUP BY
                e.rule_id,
                e.severity,
                e.record_id,
                e.field
            HAVING COUNT(DISTINCT e.run_id) >= ?
            ORDER BY
                affected_runs DESC,
                total_occurrences DESC,
                e.rule_id ASC,
                e.record_id ASC,
                e.field ASC
            LIMIT ?
            """,
            (minimum_runs, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def get_run_history(
    db_path: str | Path,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the most recent audit runs with release and financial metrics."""
    _validate_limit(limit)
    path = _validate_database(db_path)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute(
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
            ORDER BY
                finished_at DESC,
                run_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_STATUSES = {
    "Open",
    "In Progress",
    "Resolved",
    "Won't Fix",
}

EXCEPTION_FIELDS = (
    "run_id",
    "rule_id",
    "severity",
    "record_id",
    "field",
    "observed_value",
    "message",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _database_path(db_path: str | Path) -> Path:
    path = Path(db_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Audit database does not exist: {path}"
        )

    return path


def _exception_key(exception: dict[str, Any]) -> str:
    """Create a deterministic key from the original exception evidence."""
    evidence = {
        field: exception.get(field)
        for field in EXCEPTION_FIELDS
    }

    serialized = json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create remediation tables without modifying existing audit tables."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS remediation_cases (
            exception_key TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            record_id TEXT,
            field TEXT,
            observed_value TEXT,
            exception_message TEXT,
            owner TEXT,
            root_cause TEXT,
            status TEXT NOT NULL DEFAULT 'Open'
                CHECK (
                    status IN (
                        'Open',
                        'In Progress',
                        'Resolved',
                        'Won''t Fix'
                    )
                ),
            resolution_notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS remediation_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            exception_key TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            FOREIGN KEY (exception_key)
                REFERENCES remediation_cases(exception_key)
        )
        """
    )


def _require_audit_tables(connection: sqlite3.Connection) -> None:
    """Ensure the existing control engine has created its audit tables."""
    required = {"control_runs", "control_exceptions"}

    existing = {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
    }

    missing = required - existing

    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(
            f"Required audit tables are missing: {names}. "
            "Run the control framework first."
        )


def sync_remediation_cases(
    db_path: str | Path,
) -> int:
    """
    Import previously unregistered exceptions into the remediation register.

    Returns the number of newly registered cases.
    Existing remediation details are preserved on subsequent syncs.
    """
    path = _database_path(db_path)
    created_count = 0
    now = _utc_now()

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _require_audit_tables(connection)
        _ensure_schema(connection)

        rows = connection.execute(
            """
            SELECT
                e.run_id,
                e.rule_id,
                e.severity,
                e.record_id,
                e.field,
                e.observed_value,
                e.message
            FROM control_exceptions AS e
            INNER JOIN control_runs AS r
                ON r.run_id = e.run_id
            ORDER BY
                e.run_id,
                e.rule_id,
                e.severity,
                e.record_id,
                e.field,
                e.observed_value,
                e.message
            """
        ).fetchall()

        for row in rows:
            exception = dict(zip(EXCEPTION_FIELDS, row))
            key = _exception_key(exception)

            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO remediation_cases (
                    exception_key,
                    run_id,
                    rule_id,
                    severity,
                    record_id,
                    field,
                    observed_value,
                    exception_message,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Open', ?, ?)
                """,
                (
                    key,
                    exception["run_id"],
                    exception["rule_id"],
                    exception["severity"],
                    exception["record_id"],
                    exception["field"],
                    (
                        None
                        if exception["observed_value"] is None
                        else str(exception["observed_value"])
                    ),
                    exception["message"],
                    now,
                    now,
                ),
            )

            if cursor.rowcount == 1:
                created_count += 1

                connection.execute(
                    """
                    INSERT INTO remediation_audit (
                        exception_key,
                        changed_at,
                        changed_by,
                        field_name,
                        old_value,
                        new_value
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        now,
                        "system",
                        "case_created",
                        None,
                        "Open",
                    ),
                )

    return created_count


def list_remediation_cases(
    db_path: str | Path,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List remediation cases with optional status and severity filters."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer.")

    if status is not None and status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status: {status}. "
            f"Allowed statuses: {', '.join(sorted(VALID_STATUSES))}"
        )

    path = _database_path(db_path)

    # Synchronize first so newly recorded control exceptions are included.
    sync_remediation_cases(path)

    query = """
        SELECT
            exception_key,
            run_id,
            rule_id,
            severity,
            record_id,
            field,
            observed_value,
            exception_message,
            owner,
            root_cause,
            status,
            resolution_notes,
            created_at,
            updated_at,
            resolved_at
        FROM remediation_cases
        WHERE 1 = 1
    """
    parameters: list[Any] = []

    if status is not None:
        query += " AND status = ?"
        parameters.append(status)

    if severity is not None:
        query += " AND severity = ?"
        parameters.append(severity)

    query += """
        ORDER BY
            CASE severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH' THEN 2
                WHEN 'WARNING' THEN 3
                ELSE 4
            END,
            created_at DESC,
            exception_key
        LIMIT ?
    """
    parameters.append(limit)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query, parameters).fetchall()

    return [dict(row) for row in rows]


def update_remediation_case(
    db_path: str | Path,
    exception_key: str,
    changed_by: str,
    *,
    owner: str | None = None,
    root_cause: str | None = None,
    status: str | None = None,
    resolution_notes: str | None = None,
) -> dict[str, Any]:
    """
    Update a case and record every changed field in the audit trail.

    Supply only fields to change. Passing None means leave that field
    unchanged. Use an empty string to clear an optional text field.
    """
    if not exception_key or not exception_key.strip():
        raise ValueError("exception_key cannot be blank.")

    if not changed_by or not changed_by.strip():
        raise ValueError("changed_by cannot be blank.")

    if status is not None and status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status: {status}. "
            f"Allowed statuses: {', '.join(sorted(VALID_STATUSES))}"
        )

    requested = {
        "owner": owner,
        "root_cause": root_cause,
        "status": status,
        "resolution_notes": resolution_notes,
    }
    changes = {
        field: value
        for field, value in requested.items()
        if value is not None
    }

    if not changes:
        raise ValueError("Provide at least one field to update.")

    path = _database_path(db_path)
    now = _utc_now()

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _require_audit_tables(connection)
        _ensure_schema(connection)

        existing = connection.execute(
            """
            SELECT *
            FROM remediation_cases
            WHERE exception_key = ?
            """,
            (exception_key,),
        ).fetchone()

        if existing is None:
            raise ValueError(
                f"Remediation case not found: {exception_key}"
            )

        columns = [
            column[1]
            for column in connection.execute(
                "PRAGMA table_info(remediation_cases)"
            ).fetchall()
        ]
        old_case = dict(zip(columns, existing))

        applied_changes: dict[str, Any] = {}

        for field, new_value in changes.items():
            old_value = old_case[field]

            if old_value != new_value:
                applied_changes[field] = new_value

        if not applied_changes:
            return old_case

        for field, new_value in applied_changes.items():
            connection.execute(
                f"""
                UPDATE remediation_cases
                SET {field} = ?
                WHERE exception_key = ?
                """,
                (new_value, exception_key),
            )

            connection.execute(
                """
                INSERT INTO remediation_audit (
                    exception_key,
                    changed_at,
                    changed_by,
                    field_name,
                    old_value,
                    new_value
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    exception_key,
                    now,
                    changed_by.strip(),
                    field,
                    (
                        None
                        if old_case[field] is None
                        else str(old_case[field])
                    ),
                    (
                        None
                        if new_value is None
                        else str(new_value)
                    ),
                ),
            )

        if "status" in applied_changes:
            new_status = applied_changes["status"]

            resolved_at = (
                now if new_status == "Resolved" else None
            )

            connection.execute(
                """
                UPDATE remediation_cases
                SET resolved_at = ?
                WHERE exception_key = ?
                """,
                (resolved_at, exception_key),
            )

        connection.execute(
            """
            UPDATE remediation_cases
            SET updated_at = ?
            WHERE exception_key = ?
            """,
            (now, exception_key),
        )

        result = connection.execute(
            """
            SELECT *
            FROM remediation_cases
            WHERE exception_key = ?
            """,
            (exception_key,),
        ).fetchone()

        result_columns = [
            column[1]
            for column in connection.execute(
                "PRAGMA table_info(remediation_cases)"
            ).fetchall()
        ]

    return dict(zip(result_columns, result))


def get_remediation_audit(
    db_path: str | Path,
    exception_key: str,
) -> list[dict[str, Any]]:
    """Return the change history for one remediation case."""
    path = _database_path(db_path)

    with sqlite3.connect(path) as connection:
        _require_audit_tables(connection)
        _ensure_schema(connection)
        connection.row_factory = sqlite3.Row

        rows = connection.execute(
            """
            SELECT
                audit_id,
                exception_key,
                changed_at,
                changed_by,
                field_name,
                old_value,
                new_value
            FROM remediation_audit
            WHERE exception_key = ?
            ORDER BY audit_id
            """,
            (exception_key,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_remediation_summary(
    db_path: str | Path,
) -> dict[str, Any]:
    """Summarize the current remediation workload by status and severity."""
    cases = list_remediation_cases(
        db_path,
        limit=2_147_483_647,
    )

    by_status: dict[str, int] = {
        status: 0 for status in sorted(VALID_STATUSES)
    }
    by_severity: dict[str, int] = {}

    for case in cases:
        by_status[case["status"]] += 1

        severity = case["severity"]
        by_severity[severity] = by_severity.get(severity, 0) + 1

    return {
        "total_cases": len(cases),
        "open_cases": by_status["Open"],
        "in_progress_cases": by_status["In Progress"],
        "resolved_cases": by_status["Resolved"],
        "wont_fix_cases": by_status["Won't Fix"],
        "by_status": by_status,
        "by_severity": by_severity,
    }

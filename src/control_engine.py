
from __future__ import annotations

import hashlib
import io
import json
import math
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class ExceptionRecord:
    rule_id: str
    severity: str
    record_id: str
    field: str
    observed_value: str
    message: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def file_evidence(path: str | Path, role: str) -> dict[str, Any]:
    """Fingerprint a source file using SHA-256 and record its size."""
    source_path = Path(path)
    content = source_path.read_bytes()

    return {
        "file_role": role,
        "file_path": str(source_path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def read_csv_with_evidence(
    path: str | Path,
    role: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse the same bytes that are fingerprinted for source evidence."""
    source_path = Path(path)
    content = source_path.read_bytes()

    evidence = {
        "file_role": role,
        "file_path": str(source_path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }

    return pd.read_csv(io.BytesIO(content)), evidence


def ensure_audit_schema(db_path: str | Path) -> None:
    """Create the audit tables if they do not already exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS control_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                positions_file TEXT NOT NULL,
                status TEXT NOT NULL,
                position_count INTEGER NOT NULL,
                exception_count INTEGER NOT NULL,
                market_value REAL,
                expected_market_value REAL,
                variance REAL,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS control_exceptions (
                exception_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                record_id TEXT,
                field TEXT,
                observed_value TEXT,
                message TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES control_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS release_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                event_time TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES control_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS source_file_evidence (
                evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                file_role TEXT NOT NULL,
                file_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                FOREIGN KEY(run_id) REFERENCES control_runs(run_id)
            );
            """
        )


def _add(
    exceptions: list[ExceptionRecord],
    rule: str,
    severity: str,
    record_id: Any,
    field: str,
    value: Any,
    message: str,
) -> None:
    """Add one structured control exception."""
    exceptions.append(
        ExceptionRecord(
            rule_id=rule,
            severity=severity,
            record_id="" if record_id is None else str(record_id),
            field=str(field),
            observed_value=str(value),
            message=message,
        )
    )


def validate_positions(
    positions: pd.DataFrame,
    reference: pd.DataFrame,
    controls: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, list[ExceptionRecord], dict[str, float | None]]:
    """
    Validate position data, reference integrity, and portfolio reconciliation.

    Returns:
        Validated copy of positions, structured exceptions, and reconciliation
        metrics. This function does not persist data or approve report release.
    """
    exceptions: list[ExceptionRecord] = []
    df = positions.copy()
    reference_df = reference.copy()

    required_columns = config.get(
        "required_position_columns",
        ["position_id", "account_id", "security_id", "quantity", "price"],
    )

    # ------------------------------------------------------------
    # 1. Position schema validation
    # ------------------------------------------------------------
    missing_columns = [
        column for column in required_columns
        if column not in df.columns
    ]

    for column in missing_columns:
        _add(
            exceptions,
            "SCHEMA-001",
            "CRITICAL",
            "POSITIONS_FILE",
            column,
            "MISSING",
            f"Required position column '{column}' is missing.",
        )

    required_schema_available = not missing_columns

    # ------------------------------------------------------------
    # 2. Required-field validation
    # ------------------------------------------------------------
    for column in required_columns:
        if column not in df.columns:
            continue

        blank_mask = (
            df[column].isna()
            | df[column].astype("string").str.strip().eq("").fillna(False)
        )

        for index in df.index[blank_mask]:
            record_id = (
                df.at[index, "position_id"]
                if "position_id" in df.columns
                else index
            )

            _add(
                exceptions,
                "DQ-001",
                "CRITICAL",
                record_id,
                column,
                df.at[index, column],
                f"Required field '{column}' is blank or missing.",
            )

    # ------------------------------------------------------------
    # 3. Duplicate position IDs
    # ------------------------------------------------------------
    if "position_id" in df.columns:
        position_ids = df["position_id"].astype("string").str.strip()

        valid_position_ids = (
            position_ids.notna()
            & position_ids.ne("").fillna(False)
        )

        duplicate_mask = (
            valid_position_ids
            & position_ids.duplicated(keep=False)
        )

        for index in df.index[duplicate_mask]:
            _add(
                exceptions,
                "DQ-002",
                "CRITICAL",
                df.at[index, "position_id"],
                "position_id",
                df.at[index, "position_id"],
                "Duplicate position_id detected.",
            )

    # ------------------------------------------------------------
    # 4. Numeric validation for quantity and price
    # ------------------------------------------------------------
    for column in ("quantity", "price"):
        if column not in df.columns:
            continue

        original_values = df[column].copy()
        converted = pd.to_numeric(original_values, errors="coerce")
        df[column] = converted

        for index in df.index:
            value = df.at[index, column]
            record_id = (
                df.at[index, "position_id"]
                if "position_id" in df.columns
                else index
            )

            is_finite_number = False

            if pd.notna(value):
                try:
                    is_finite_number = math.isfinite(float(value))
                except (TypeError, ValueError, OverflowError):
                    is_finite_number = False

            if not is_finite_number:
                _add(
                    exceptions,
                    "DQ-003",
                    "CRITICAL",
                    record_id,
                    column,
                    original_values.loc[index],
                    f"'{column}' must be a finite numeric value.",
                )
            elif float(value) <= 0:
                _add(
                    exceptions,
                    "DQ-003",
                    "CRITICAL",
                    record_id,
                    column,
                    value,
                    f"'{column}' must be greater than zero.",
                )

    # ------------------------------------------------------------
    # 5. Validate the security reference file itself
    # ------------------------------------------------------------
    reference_ids: set[str] = set()

    if "security_id" not in reference_df.columns:
        _add(
            exceptions,
            "REF-002",
            "CRITICAL",
            "REFERENCE_FILE",
            "security_id",
            "MISSING",
            "Security reference data must contain a security_id column.",
        )
    else:
        normalized_reference_ids = (
            reference_df["security_id"].astype("string").str.strip()
        )

        blank_reference_mask = (
            normalized_reference_ids.isna()
            | normalized_reference_ids.eq("").fillna(False)
        )

        for index in reference_df.index[blank_reference_mask]:
            _add(
                exceptions,
                "REF-003",
                "CRITICAL",
                f"REFERENCE_ROW_{index + 1}",
                "security_id",
                reference_df.at[index, "security_id"],
                "Reference record has a blank or missing security_id.",
            )

        nonblank_reference_ids = normalized_reference_ids[
            ~blank_reference_mask
        ]

        duplicate_reference_mask = nonblank_reference_ids.duplicated(
            keep=False
        )

        for index in nonblank_reference_ids.index[
            duplicate_reference_mask
        ]:
            _add(
                exceptions,
                "REF-004",
                "CRITICAL",
                f"REFERENCE_ROW_{index + 1}",
                "security_id",
                reference_df.at[index, "security_id"],
                "Duplicate security_id in reference data makes the lookup ambiguous.",
            )

        reference_ids = set(nonblank_reference_ids.tolist())

    # ------------------------------------------------------------
    # 6. Validate position-to-reference lookups
    # ------------------------------------------------------------
    if "security_id" in df.columns:
        normalized_position_ids = (
            df["security_id"].astype("string").str.strip()
        )

        for index in df.index:
            security_id = normalized_position_ids.loc[index]

            if pd.isna(security_id) or security_id == "":
                continue

            if security_id not in reference_ids:
                record_id = (
                    df.at[index, "position_id"]
                    if "position_id" in df.columns
                    else index
                )

                _add(
                    exceptions,
                    "REF-001",
                    "CRITICAL",
                    record_id,
                    "security_id",
                    df.at[index, "security_id"],
                    "Security ID not found in reference data.",
                )

    # ------------------------------------------------------------
    # 7. Optional descriptive-field warnings
    # ------------------------------------------------------------
    optional_columns = config.get(
        "optional_position_columns",
        ["as_of_date", "currency", "asset_class"],
    )

    for column in optional_columns:
        if column not in df.columns:
            continue

        blank_mask = (
            df[column].isna()
            | df[column].astype("string").str.strip().eq("").fillna(False)
        )

        for index in df.index[blank_mask]:
            record_id = (
                df.at[index, "position_id"]
                if "position_id" in df.columns
                else index
            )

            _add(
                exceptions,
                "DQ-004",
                "WARNING",
                record_id,
                column,
                df.at[index, column],
                f"Optional descriptive field '{column}' is blank.",
            )

    # ------------------------------------------------------------
    # 8. Calculate portfolio market value
    # ------------------------------------------------------------
    market_value: float | None = None

    if df.empty:
        _add(
            exceptions,
            "REC-003",
            "CRITICAL",
            "PORTFOLIO",
            "positions",
            0,
            "Cannot approve an empty portfolio; no positions were supplied.",
        )

    elif not {"quantity", "price"}.issubset(df.columns):
        # Missing-column exceptions have already been recorded.
        market_value = None

    else:
        values_are_valid = True

        for column in ("quantity", "price"):
            for value in df[column]:
                try:
                    valid_value = (
                        pd.notna(value)
                        and math.isfinite(float(value))
                        and float(value) > 0
                    )
                except (TypeError, ValueError, OverflowError):
                    valid_value = False

                if not valid_value:
                    values_are_valid = False
                    break

            if not values_are_valid:
                break

        if values_are_valid:
            try:
                calculated_value = float(
                    (df["quantity"] * df["price"]).sum()
                )

                if math.isfinite(calculated_value):
                    market_value = calculated_value
                else:
                    _add(
                        exceptions,
                        "REC-004",
                        "CRITICAL",
                        "PORTFOLIO",
                        "market_value",
                        calculated_value,
                        "Calculated portfolio market value is not finite.",
                    )
            except (TypeError, ValueError, OverflowError):
                _add(
                    exceptions,
                    "REC-004",
                    "CRITICAL",
                    "PORTFOLIO",
                    "market_value",
                    "INVALID",
                    "Portfolio market value could not be calculated safely.",
                )
        else:
            _add(
                exceptions,
                "REC-004",
                "CRITICAL",
                "PORTFOLIO",
                "quantity_or_price",
                "INVALID",
                "Market value cannot be calculated because quantity or price contains invalid values.",
            )

    # ------------------------------------------------------------
    # 9. Validate the expected portfolio control total
    # ------------------------------------------------------------
    expected: float | None = None

    if {"control_name", "expected_value"}.issubset(controls.columns):
        control_names = controls["control_name"].astype("string").str.strip()

        matched = controls.loc[
            control_names.eq("portfolio_market_value").fillna(False),
            "expected_value",
        ]
    else:
        matched = pd.Series(dtype="object")

    if len(matched) != 1:
        _add(
            exceptions,
            "REC-001",
            "CRITICAL",
            "CONTROL_TOTALS_FILE",
            "expected_value",
            len(matched),
            "Exactly one portfolio_market_value control total is required.",
        )
    else:
        raw_expected = matched.iloc[0]

        try:
            candidate = float(raw_expected)

            if not math.isfinite(candidate):
                raise ValueError("Expected value must be finite.")

            expected = candidate

        except (TypeError, ValueError, OverflowError):
            _add(
                exceptions,
                "REC-001",
                "CRITICAL",
                "CONTROL_TOTALS_FILE",
                "expected_value",
                raw_expected,
                "The portfolio_market_value control total must be a finite numeric value.",
            )

    # ------------------------------------------------------------
    # 10. Validate reconciliation tolerance
    # ------------------------------------------------------------
    tolerance: float | None = None

    try:
        tolerance = float(config["reconciliation_tolerance"])

        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError(
                "Reconciliation tolerance must be finite and non-negative."
            )

    except (KeyError, TypeError, ValueError, OverflowError):
        _add(
            exceptions,
            "REC-005",
            "CRITICAL",
            "CONFIG",
            "reconciliation_tolerance",
            config.get("reconciliation_tolerance", "MISSING"),
            "Reconciliation tolerance must be a finite, non-negative number.",
        )
        tolerance = None

    # ------------------------------------------------------------
    # 11. Reconcile actual and expected portfolio market value
    # ------------------------------------------------------------
    variance: float | None = None

    if market_value is not None and expected is not None:
        variance = market_value - expected

        if tolerance is not None:
            absolute_variance = abs(variance)

            exceeds_tolerance = (
                absolute_variance > tolerance
                and not math.isclose(
                    absolute_variance,
                    tolerance,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            )

            if exceeds_tolerance:
                _add(
                    exceptions,
                    "REC-002",
                    "CRITICAL",
                    "PORTFOLIO",
                    "market_value_variance",
                    round(variance, 6),
                    (
                        f"Portfolio market value differs from control total "
                        f"by {variance:.2f}; allowed tolerance is "
                        f"{tolerance:.2f}."
                    ),
                )

    metrics = {
        "market_value": market_value,
        "expected_market_value": expected,
        "variance": variance,
    }

    return df, exceptions, metrics


def persist_run(
    db_path: str | Path,
    run_id: str,
    started_at: str,
    finished_at: str,
    positions_file: str,
    status: str,
    position_count: int,
    exceptions: list[ExceptionRecord],
    metrics: dict[str, float | None],
    message: str,
    source_files: list[dict[str, Any]] | None = None,
) -> None:
    """Persist the run, exceptions, release decision, and source evidence."""
    ensure_audit_schema(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO control_runs
                (
                    run_id, started_at, finished_at, positions_file, status,
                    position_count, exception_count, market_value,
                    expected_market_value, variance, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started_at,
                    finished_at,
                    positions_file,
                    status,
                    position_count,
                    len(exceptions),
                    metrics["market_value"],
                    metrics["expected_market_value"],
                    metrics["variance"],
                    message,
                ),
            )

            connection.executemany(
                """
                INSERT INTO control_exceptions
                (
                    run_id, rule_id, severity, record_id, field,
                    observed_value, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        exception.rule_id,
                        exception.severity,
                        exception.record_id,
                        exception.field,
                        exception.observed_value,
                        exception.message,
                    )
                    for exception in exceptions
                ],
            )

            connection.execute(
                """
                INSERT INTO release_events
                (run_id, event_time, decision, reason)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, finished_at, status, message),
            )

            connection.executemany(
                """
                INSERT INTO source_file_evidence
                (run_id, file_role, file_path, sha256, size_bytes)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item["file_role"],
                        item["file_path"],
                        item["sha256"],
                        item["size_bytes"],
                    )
                    for item in (source_files or [])
                ],
            )


def write_outputs(
    output_dir: str | Path,
    run_id: str,
    positions: pd.DataFrame,
    exceptions: list[ExceptionRecord],
    metrics: dict[str, float | None],
    status: str,
    message: str,
    source_files: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path | None]:
    """Write the run summary and, only for approved runs, the Excel report."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    summary_path = output_path / f"run_summary_{run_id}.json"

    payload = {
        "run_id": run_id,
        "status": status,
        "message": message,
        "position_count": int(len(positions)),
        "exception_count": len(exceptions),
        "critical_exception_count": sum(
            exception.severity == "CRITICAL"
            for exception in exceptions
        ),
        "warning_count": sum(
            exception.severity == "WARNING"
            for exception in exceptions
        ),
        **metrics,
    }

    summary_path.write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    if status != "APPROVED":
        return summary_path, None

    report_path = output_path / f"control_report_{run_id}.xlsx"

    exceptions_df = pd.DataFrame(
        [asdict(exception) for exception in exceptions],
        columns=[
            "rule_id",
            "severity",
            "record_id",
            "field",
            "observed_value",
            "message",
        ],
    )

    summary_df = pd.DataFrame(
        [
            ("Run ID", run_id),
            ("Release decision", status),
            ("Decision reason", message),
            ("Position count", len(positions)),
            ("Exception count", len(exceptions)),
            ("Calculated market value", metrics["market_value"]),
            ("Expected market value", metrics["expected_market_value"]),
            ("Variance", metrics["variance"]),
        ],
        columns=["Control", "Result"],
    )

    evidence_df = pd.DataFrame(
        source_files or [],
        columns=["file_role", "file_path", "sha256", "size_bytes"],
    )

    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        summary_df.to_excel(
            writer,
            sheet_name="Control Summary",
            index=False,
        )
        exceptions_df.to_excel(
            writer,
            sheet_name="Exceptions",
            index=False,
        )
        positions.to_excel(
            writer,
            sheet_name="Positions",
            index=False,
        )
        evidence_df.to_excel(
            writer,
            sheet_name="Source File Evidence",
            index=False,
        )

    return summary_path, report_path


def run_controls(
    positions_path: str | Path,
    controls_path: str | Path,
    output_dir: str | Path,
    config_path: str | Path = "config.json",
    reference_path: str | Path = "data/security_reference.csv",
    db_path: str | Path = "data/control_audit.db",
) -> dict[str, Any]:
    """Run all controls, persist the audit trail, and enforce release rules."""
    started = utc_now()
    run_id = uuid.uuid4().hex[:12].upper()

    config = load_config(config_path)

    positions, positions_evidence = read_csv_with_evidence(
        positions_path, "positions"
    )
    controls, controls_evidence = read_csv_with_evidence(
        controls_path, "control_totals"
    )
    reference, reference_evidence = read_csv_with_evidence(
        reference_path, "security_reference"
    )

    source_files = [
        positions_evidence,
        controls_evidence,
        reference_evidence,
        file_evidence(config_path, "config"),
    ]

    checked, exceptions, metrics = validate_positions(
        positions,
        reference,
        controls,
        config,
    )

    blocking_severities = set(
        config.get("release_blocking_severities", ["CRITICAL"])
    )

    blocking_count = sum(
        exception.severity in blocking_severities
        for exception in exceptions
    )

    status = "BLOCKED" if blocking_count else "APPROVED"

    message = (
        "Release blocked because one or more release-blocking controls failed."
        if status == "BLOCKED"
        else "All release-blocking controls passed."
    )

    finished = utc_now()

    persist_run(
        db_path=db_path,
        run_id=run_id,
        started_at=started,
        finished_at=finished,
        positions_file=str(positions_path),
        status=status,
        position_count=len(checked),
        exceptions=exceptions,
        metrics=metrics,
        message=message,
        source_files=source_files,
    )

    summary_path, report_path = write_outputs(
        output_dir=output_dir,
        run_id=run_id,
        positions=checked,
        exceptions=exceptions,
        metrics=metrics,
        status=status,
        message=message,
        source_files=source_files,
    )

    return {
        "run_id": run_id,
        "status": status,
        "message": message,
        "position_count": len(checked),
        "exception_count": len(exceptions),
        "summary_path": str(summary_path),
        "report_path": str(report_path) if report_path else None,
        "metrics": metrics,
        "source_file_count": len(source_files),
    }

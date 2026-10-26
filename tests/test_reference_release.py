
import json
import sqlite3

import pandas as pd

from src.control_engine import run_controls


def create_project_inputs(tmp_path, reference_rows):
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()

    positions_path = data_dir / "positions.csv"
    controls_path = data_dir / "control_totals.csv"
    reference_path = data_dir / "security_reference.csv"
    config_path = tmp_path / "config.json"
    db_path = data_dir / "control_audit.db"

    pd.DataFrame(
        [
            {
                "position_id": "POS-001",
                "account_id": "ACC-001",
                "security_id": "SEC-001",
                "quantity": 2,
                "price": 10.0,
            }
        ]
    ).to_csv(positions_path, index=False)

    pd.DataFrame(
        [
            {
                "control_name": "portfolio_market_value",
                "expected_value": 20.0,
            }
        ]
    ).to_csv(controls_path, index=False)

    pd.DataFrame(reference_rows).to_csv(reference_path, index=False)

    config = {
        "required_position_columns": [
            "position_id",
            "account_id",
            "security_id",
            "quantity",
            "price",
        ],
        "reconciliation_tolerance": 0.01,
        "release_blocking_severities": ["CRITICAL"],
    }

    config_path.write_text(
        json.dumps(config),
        encoding="utf-8",
    )

    return {
        "positions_path": positions_path,
        "controls_path": controls_path,
        "reference_path": reference_path,
        "config_path": config_path,
        "output_dir": output_dir,
        "db_path": db_path,
    }


def execute_run(paths):
    return run_controls(
        positions_path=paths["positions_path"],
        controls_path=paths["controls_path"],
        output_dir=paths["output_dir"],
        config_path=paths["config_path"],
        reference_path=paths["reference_path"],
        db_path=paths["db_path"],
    )


def test_duplicate_reference_ids_block_report_release(tmp_path):
    paths = create_project_inputs(
        tmp_path,
        [
            {"security_id": "SEC-001"},
            {"security_id": "SEC-001"},
        ],
    )

    result = execute_run(paths)

    assert result["status"] == "BLOCKED"
    assert result["report_path"] is None
    assert result["exception_count"] >= 1

    assert paths["output_dir"].joinpath(
        f'run_summary_{result["run_id"]}.json'
    ).exists()


def test_blank_reference_id_blocks_report_release(tmp_path):
    paths = create_project_inputs(
        tmp_path,
        [
            {"security_id": "SEC-001"},
            {"security_id": ""},
        ],
    )

    result = execute_run(paths)

    assert result["status"] == "BLOCKED"
    assert result["report_path"] is None


def test_blocked_run_and_exceptions_are_audited(tmp_path):
    paths = create_project_inputs(
        tmp_path,
        [
            {"security_id": "SEC-001"},
            {"security_id": "SEC-001"},
        ],
    )

    result = execute_run(paths)

    with sqlite3.connect(paths["db_path"]) as connection:
        run = connection.execute(
            """
            SELECT status, exception_count
            FROM control_runs
            WHERE run_id = ?
            """,
            (result["run_id"],),
        ).fetchone()

        release_event = connection.execute(
            """
            SELECT decision
            FROM release_events
            WHERE run_id = ?
            """,
            (result["run_id"],),
        ).fetchone()

        exceptions = connection.execute(
            """
            SELECT COUNT(*)
            FROM control_exceptions
            WHERE run_id = ? AND rule_id = 'REF-004'
            """,
            (result["run_id"],),
        ).fetchone()[0]

    assert run is not None
    assert run[0] == "BLOCKED"
    assert run[1] >= 1
    assert release_event == ("BLOCKED",)
    assert exceptions == 2

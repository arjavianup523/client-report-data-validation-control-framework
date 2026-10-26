import hashlib
import json
import sqlite3

from src.control_engine import file_evidence, run_controls


def test_file_evidence_is_stable_for_identical_content(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("id,value\n1,10\n", encoding="utf-8")

    first = file_evidence(source, "positions")
    second = file_evidence(source, "positions")

    assert first["sha256"] == second["sha256"]
    assert first["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert first["size_bytes"] == source.stat().st_size


def test_file_evidence_changes_when_content_changes(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("id,value\n1,10\n", encoding="utf-8")
    original_hash = file_evidence(source, "positions")["sha256"]

    source.write_text("id,value\n1,11\n", encoding="utf-8")
    changed_hash = file_evidence(source, "positions")["sha256"]

    assert original_hash != changed_hash


def test_run_persists_all_four_source_fingerprints(tmp_path):
    data = tmp_path / "data"
    output = tmp_path / "outputs"
    data.mkdir()
    positions = data / "positions.csv"
    controls = data / "controls.csv"
    reference = data / "reference.csv"
    config_path = tmp_path / "config.json"
    db_path = data / "audit.db"

    positions.write_text(
        "position_id,account_id,security_id,quantity,price\nP1,A1,S1,2,10\n",
        encoding="utf-8",
    )
    controls.write_text(
        "control_name,expected_value\nportfolio_market_value,20\n",
        encoding="utf-8",
    )
    reference.write_text("security_id,security_name\nS1,Sample\n", encoding="utf-8")
    config_path.write_text(json.dumps({
        "required_position_columns": ["position_id", "account_id", "security_id", "quantity", "price"],
        "optional_position_columns": ["currency"],
        "reconciliation_tolerance": 0.01,
        "release_blocking_severities": ["CRITICAL"],
    }), encoding="utf-8")

    result = run_controls(positions, controls, output, config_path, reference, db_path)

    assert result["status"] == "APPROVED"
    assert result["source_file_count"] == 4
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT file_role, file_path, sha256, size_bytes "
            "FROM source_file_evidence WHERE run_id = ? ORDER BY file_role",
            (result["run_id"],),
        ).fetchall()

    assert {row[0] for row in rows} == {"positions", "control_totals", "security_reference", "config"}
    expected = {
        "positions": positions,
        "control_totals": controls,
        "security_reference": reference,
        "config": config_path,
    }
    for role, path, digest, size in rows:
        assert digest == hashlib.sha256(expected[role].read_bytes()).hexdigest()
        assert size == expected[role].stat().st_size

    report_path = result["report_path"]
    assert report_path is not None

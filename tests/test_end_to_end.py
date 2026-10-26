import json
import pandas as pd
from src.control_engine import run_controls

def test_approved_run_writes_excel_and_audit(tmp_path):
    data = tmp_path / "data"
    out = tmp_path / "outputs"
    data.mkdir()
    positions = pd.DataFrame([
        {"position_id": "P1", "account_id": "A1", "security_id": "S1",
         "quantity": 2, "price": 10, "currency": "USD"},
    ])
    controls = pd.DataFrame([{"control_name": "portfolio_market_value", "expected_value": 20}])
    reference = pd.DataFrame([{"security_id": "S1", "security_name": "Sample"}])
    positions.to_csv(data / "positions.csv", index=False)
    controls.to_csv(data / "controls.csv", index=False)
    reference.to_csv(data / "reference.csv", index=False)
    config = {
        "required_position_columns": ["position_id", "account_id", "security_id", "quantity", "price"],
        "optional_position_columns": ["currency"],
        "reconciliation_tolerance": 0.01,
        "release_blocking_severities": ["CRITICAL"],
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    result = run_controls(data / "positions.csv", data / "controls.csv", out,
                          tmp_path / "config.json", data / "reference.csv", data / "audit.db")
    assert result["status"] == "APPROVED"
    assert result["report_path"] is not None
    assert (out / f"control_report_{result['run_id']}.xlsx").exists()

def test_blocked_run_does_not_write_excel(tmp_path):
    data = tmp_path / "data"
    out = tmp_path / "outputs"
    data.mkdir()
    positions = pd.DataFrame([
        {"position_id": "P1", "account_id": "A1", "security_id": "S1",
         "quantity": 2, "price": 10, "currency": "USD"},
    ])
    controls = pd.DataFrame([{"control_name": "portfolio_market_value", "expected_value": 999}])
    reference = pd.DataFrame([{"security_id": "S1", "security_name": "Sample"}])
    positions.to_csv(data / "positions.csv", index=False)
    controls.to_csv(data / "controls.csv", index=False)
    reference.to_csv(data / "reference.csv", index=False)
    config = {
        "required_position_columns": ["position_id", "account_id", "security_id", "quantity", "price"],
        "optional_position_columns": ["currency"],
        "reconciliation_tolerance": 0.01,
        "release_blocking_severities": ["CRITICAL"],
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    result = run_controls(data / "positions.csv", data / "controls.csv", out,
                          tmp_path / "config.json", data / "reference.csv", data / "audit.db")
    assert result["status"] == "BLOCKED"
    assert result["report_path"] is None
    assert not list(out.glob("control_report_*.xlsx"))
    assert (out / f"run_summary_{result['run_id']}.json").exists()

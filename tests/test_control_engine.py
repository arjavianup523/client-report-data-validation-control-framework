import json
import pandas as pd

from src.control_engine import validate_positions


def fixtures():
    positions = pd.DataFrame([
        {"position_id": "P1", "account_id": "A1", "security_id": "S1",
         "quantity": 2, "price": 10.0, "currency": "USD"},
        {"position_id": "P2", "account_id": "A2", "security_id": "S2",
         "quantity": 3, "price": 20.0, "currency": "USD"},
    ])
    reference = pd.DataFrame([{"security_id": "S1"}, {"security_id": "S2"}])
    controls = pd.DataFrame([{"control_name": "portfolio_market_value", "expected_value": 80.0}])
    config = {
        "required_position_columns": ["position_id", "account_id", "security_id", "quantity", "price"],
        "reconciliation_tolerance": 0.01,
    }
    return positions, reference, controls, config


def test_clean_positions_pass_reconciliation():
    positions, reference, controls, config = fixtures()
    _, exceptions, metrics = validate_positions(positions, reference, controls, config)
    assert exceptions == []
    assert metrics["market_value"] == 80.0
    assert metrics["variance"] == 0.0


def test_duplicate_position_is_critical():
    positions, reference, controls, config = fixtures()
    positions = pd.concat([positions, positions.iloc[[0]]], ignore_index=True)
    _, exceptions, _ = validate_positions(positions, reference, controls, config)
    assert any(e.rule_id == "DQ-002" and e.severity == "CRITICAL" for e in exceptions)


def test_reconciliation_variance_is_critical():
    positions, reference, controls, config = fixtures()
    controls.loc[0, "expected_value"] = 999.0
    _, exceptions, metrics = validate_positions(positions, reference, controls, config)
    assert any(e.rule_id == "REC-002" for e in exceptions)
    assert metrics["variance"] == -919.0


def test_unknown_security_is_critical():
    positions, reference, controls, config = fixtures()
    positions.loc[0, "security_id"] = "UNKNOWN"
    _, exceptions, _ = validate_positions(positions, reference, controls, config)
    assert any(e.rule_id == "REF-001" for e in exceptions)


def test_missing_required_column_is_critical():
    positions, reference, controls, config = fixtures()
    positions = positions.drop(columns=["price"])
    _, exceptions, _ = validate_positions(positions, reference, controls, config)
    assert any(e.rule_id == "SCHEMA-001" and e.field == "price" for e in exceptions)


def test_invalid_price_is_critical():
    positions, reference, controls, config = fixtures()
    positions.loc[0, "price"] = -1
    _, exceptions, _ = validate_positions(positions, reference, controls, config)
    assert any(e.rule_id == "DQ-003" and e.field == "price" for e in exceptions)

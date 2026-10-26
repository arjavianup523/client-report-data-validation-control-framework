
import pandas as pd
import pytest

from src.control_engine import validate_positions


def make_data():
    positions = pd.DataFrame(
        [
            {
                "position_id": "POS-001",
                "account_id": "ACC-001",
                "security_id": "SEC-001",
                "quantity": 2.0,
                "price": 10.0,
            }
        ]
    )

    reference = pd.DataFrame(
        [{"security_id": "SEC-001"}]
    )

    controls = pd.DataFrame(
        [
            {
                "control_name": "portfolio_market_value",
                "expected_value": 20.0,
            }
        ]
    )

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

    return positions, reference, controls, config


@pytest.mark.parametrize("field", ["quantity", "price"])
@pytest.mark.parametrize("invalid_value", [0, -1])
def test_non_positive_financial_values_are_critical(field, invalid_value):
    positions, reference, controls, config = make_data()
    positions.loc[0, field] = invalid_value

    _, exceptions, _ = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "DQ-003"
        and exception.severity == "CRITICAL"
        and exception.field == field
        for exception in exceptions
    )


@pytest.mark.parametrize("field", ["quantity", "price"])
@pytest.mark.parametrize("invalid_value", ["not-a-number", float("inf"), float("-inf")])
def test_invalid_numeric_values_are_critical(field, invalid_value):
    positions, reference, controls, config = make_data()

    # Object dtype permits deliberately invalid text and numeric values.
    positions[field] = positions[field].astype(object)
    positions.loc[0, field] = invalid_value

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "DQ-003"
        and exception.severity == "CRITICAL"
        and exception.field == field
        for exception in exceptions
    )
    assert metrics["market_value"] is None


@pytest.mark.parametrize("field", ["quantity", "price"])
def test_missing_financial_values_are_critical(field):
    positions, reference, controls, config = make_data()
    positions.loc[0, field] = float("nan")

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "DQ-003"
        and exception.severity == "CRITICAL"
        and exception.field == field
        for exception in exceptions
    )
    assert metrics["market_value"] is None


def test_valid_financial_values_produce_expected_market_value():
    positions, reference, controls, config = make_data()

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert metrics["market_value"] == pytest.approx(20.0)
    assert metrics["expected_market_value"] == pytest.approx(20.0)
    assert metrics["variance"] == pytest.approx(0.0)
    assert not any(
        exception.rule_id == "DQ-003"
        for exception in exceptions
    )


def test_missing_price_column_is_reported_as_critical():
    positions, reference, controls, config = make_data()
    positions = positions.drop(columns=["price"])

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "SCHEMA-001"
        and exception.severity == "CRITICAL"
        and exception.field == "price"
        for exception in exceptions
    )
    assert metrics["market_value"] is None


def test_missing_quantity_column_is_reported_as_critical():
    positions, reference, controls, config = make_data()
    positions = positions.drop(columns=["quantity"])

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "SCHEMA-001"
        and exception.severity == "CRITICAL"
        and exception.field == "quantity"
        for exception in exceptions
    )
    assert metrics["market_value"] is None

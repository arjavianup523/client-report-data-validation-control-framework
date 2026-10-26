
import pandas as pd

from src.control_engine import validate_positions


def make_data():
    """Create a minimal valid portfolio for reconciliation tests."""
    positions = pd.DataFrame(
        [
            {
                "position_id": "POS-001",
                "account_id": "ACC-001",
                "security_id": "SEC-001",
                "quantity": 2,
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
    }

    return positions, reference, controls, config


def test_duplicate_control_totals_are_rejected():
    positions, reference, controls, config = make_data()
    controls = pd.concat([controls, controls], ignore_index=True)

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "REC-001"
        and exception.severity == "CRITICAL"
        for exception in exceptions
    )
    assert metrics["expected_market_value"] is None


def test_non_numeric_control_total_is_rejected():
    positions, reference, controls, config = make_data()

    # Use object dtype so pandas permits the deliberately invalid text value.
    controls["expected_value"] = controls["expected_value"].astype(object)
    controls.loc[0, "expected_value"] = "not-a-number"

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "REC-001"
        and exception.severity == "CRITICAL"
        for exception in exceptions
    )
    assert metrics["expected_market_value"] is None


def test_non_finite_control_total_is_rejected():
    positions, reference, controls, config = make_data()
    controls.loc[0, "expected_value"] = float("inf")

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "REC-001"
        and exception.severity == "CRITICAL"
        for exception in exceptions
    )
    assert metrics["expected_market_value"] is None


def test_empty_portfolio_is_critical():
    positions, reference, controls, config = make_data()
    positions = positions.iloc[0:0].copy()

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "REC-003"
        and exception.severity == "CRITICAL"
        for exception in exceptions
    )
    assert metrics["market_value"] is None


def test_variance_equal_to_tolerance_is_accepted():
    positions, reference, controls, config = make_data()

    # Market value becomes 20.01 against an expected value of 20.00.
    positions.loc[0, "price"] = 10.005
    config["reconciliation_tolerance"] = 0.01

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert abs(metrics["variance"]) <= 0.01 + 1e-12
    assert not any(
        exception.rule_id == "REC-002"
        for exception in exceptions
    )


def test_variance_above_tolerance_is_critical():
    positions, reference, controls, config = make_data()

    # Market value becomes 20.04, exceeding the 0.01 tolerance.
    positions.loc[0, "price"] = 10.02
    config["reconciliation_tolerance"] = 0.01

    _, exceptions, metrics = validate_positions(
        positions, reference, controls, config
    )

    assert metrics["variance"] > 0.01
    assert any(
        exception.rule_id == "REC-002"
        and exception.severity == "CRITICAL"
        for exception in exceptions
    )


def test_invalid_reconciliation_tolerance_is_critical():
    positions, reference, controls, config = make_data()
    config["reconciliation_tolerance"] = -0.01

    _, exceptions, _ = validate_positions(
        positions, reference, controls, config
    )

    assert any(
        exception.rule_id == "REC-005"
        and exception.severity == "CRITICAL"
        for exception in exceptions
    )


import pandas as pd

from src.control_engine import validate_positions


def make_test_data():
    """Create a small, valid portfolio for reference-data tests."""
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
        [
            {"security_id": "SEC-001"},
            {"security_id": "SEC-002"},
        ]
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


def test_duplicate_security_ids_create_critical_exception():
    positions, reference, controls, config = make_test_data()

    reference = pd.DataFrame(
        [
            {"security_id": "SEC-001"},
            {"security_id": "SEC-001"},
            {"security_id": "SEC-002"},
        ]
    )

    _, exceptions, _ = validate_positions(
        positions, reference, controls, config
    )

    duplicate_exceptions = [
        e for e in exceptions if e.rule_id == "REF-004"
    ]

    assert len(duplicate_exceptions) == 2
    assert all(e.severity == "CRITICAL" for e in duplicate_exceptions)


def test_security_ids_with_surrounding_whitespace_are_duplicates():
    positions, reference, controls, config = make_test_data()

    reference = pd.DataFrame(
        [
            {"security_id": "SEC-001"},
            {"security_id": " SEC-001 "},
        ]
    )

    _, exceptions, _ = validate_positions(
        positions, reference, controls, config
    )

    duplicate_exceptions = [
        e for e in exceptions if e.rule_id == "REF-004"
    ]

    assert len(duplicate_exceptions) == 2
    assert all(e.severity == "CRITICAL" for e in duplicate_exceptions)


def test_blank_security_ids_create_critical_exception():
    positions, reference, controls, config = make_test_data()

    reference = pd.DataFrame(
        [
            {"security_id": "SEC-001"},
            {"security_id": ""},
            {"security_id": None},
        ]
    )

    _, exceptions, _ = validate_positions(
        positions, reference, controls, config
    )

    missing_exceptions = [
        e for e in exceptions if e.rule_id == "REF-003"
    ]

    assert len(missing_exceptions) == 2
    assert all(e.severity == "CRITICAL" for e in missing_exceptions)


def test_missing_security_id_column_creates_critical_exception():
    positions, reference, controls, config = make_test_data()

    reference = pd.DataFrame(
        [{"ticker": "ABC"}, {"ticker": "XYZ"}]
    )

    _, exceptions, _ = validate_positions(
        positions, reference, controls, config
    )

    missing_column_exceptions = [
        e for e in exceptions if e.rule_id == "REF-002"
    ]

    assert len(missing_column_exceptions) == 1
    assert missing_column_exceptions[0].severity == "CRITICAL"


def test_reference_integrity_failures_do_not_hide_position_lookup_errors():
    positions, reference, controls, config = make_test_data()

    reference = pd.DataFrame(
        [
            {"security_id": "SEC-001"},
            {"security_id": "SEC-001"},
            {"security_id": ""},
        ]
    )

    _, exceptions, _ = validate_positions(
        positions, reference, controls, config
    )

    rule_ids = {e.rule_id for e in exceptions}

    assert "REF-004" in rule_ids
    assert "REF-003" in rule_ids

# Data Dictionary

## `positions.csv`
- `position_id`: unique source position identifier; required.
- `account_id`: account or portfolio identifier; required.
- `security_id`: key to security reference data; required.
- `quantity`: position quantity; must be numeric and greater than zero.
- `price`: unit price used for this demonstration; must be numeric and greater than zero.
- `as_of_date`: reporting date for the position.
- `currency`: currency code; missing values produce a warning in this prototype.
- `asset_class`: descriptive asset classification.

## `security_reference.csv`
- `security_id`: approved security identifier used to validate positions.
- `security_name`: readable security name.

## `control_totals.csv`
- `control_name`: must include exactly one `portfolio_market_value` row.
- `expected_value`: expected portfolio market value used for reconciliation.

## Derived measure
`market_value = Σ(quantity × price)`

`variance = calculated_market_value − expected_market_value`

A variance is acceptable only when its absolute value is less than or equal to `reconciliation_tolerance`.

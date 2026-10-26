from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd

from src.control_engine import run_controls


def main() -> None:
    # Use temporary copies so the demo cannot overwrite project data or outputs.
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="portfolio_control_demo_") as temp_name:
        temp = Path(temp_name)
        data = temp / "data"
        data.mkdir()
        output = temp / "outputs"
        positions = pd.read_csv(project / "data" / "positions.csv")
        controls = pd.read_csv(project / "data" / "control_totals.csv")
        reference = pd.read_csv(project / "data" / "security_reference.csv")
        config_path = temp / "config.json"
        shutil.copy2(project / "config.json", config_path)
        reference_path = data / "security_reference.csv"
        reference.to_csv(reference_path, index=False)

        # Scenario A: clean data should be approved and produce an Excel report.
        clean_positions = data / "positions_clean.csv"
        clean_controls = data / "controls_clean.csv"
        positions.to_csv(clean_positions, index=False)
        controls.to_csv(clean_controls, index=False)
        clean_result = run_controls(
            clean_positions, clean_controls, output / "clean",
            config_path, reference_path, temp / "audit.db"
        )
        clean_excel_created = bool(clean_result["report_path"] and Path(clean_result["report_path"]).exists())
        if clean_result["status"] != "APPROVED" or not clean_excel_created:
            raise SystemExit("FAIL: clean-data scenario did not approve and create an Excel report.")

        # Scenario B: add 100 to the expected total to deliberately force a mismatch.
        bad_controls = controls.copy()
        mask = bad_controls["control_name"].eq("portfolio_market_value")
        if int(mask.sum()) != 1:
            raise SystemExit("Cannot run demo: expected exactly one portfolio_market_value control total.")
        bad_controls.loc[mask, "expected_value"] = pd.to_numeric(
            bad_controls.loc[mask, "expected_value"], errors="raise"
        ) + 100.0
        bad_positions_path = data / "positions_bad_reconciliation.csv"
        bad_controls_path = data / "controls_bad_reconciliation.csv"
        positions.to_csv(bad_positions_path, index=False)
        bad_controls.to_csv(bad_controls_path, index=False)
        blocked_output = output / "blocked"
        blocked_result = run_controls(
            bad_positions_path, bad_controls_path, blocked_output,
            config_path, reference_path, temp / "audit.db"
        )
        summary_exists = bool(blocked_result["summary_path"] and Path(blocked_result["summary_path"]).exists())
        excel_exists = bool(list(blocked_output.glob("control_report_*.xlsx")))
        if blocked_result["status"] != "BLOCKED" or not summary_exists or excel_exists:
            raise SystemExit("FAIL: mismatched-total scenario did not block release as expected.")

        print("\nCONTROL FRAMEWORK DEMONSTRATION")
        print("=" * 62)
        print(f"Scenario A — clean data:              {clean_result['status']}")
        print(f"  Exceptions: {clean_result['exception_count']} | Approved Excel created: {clean_excel_created}")
        print(f"Scenario B — control total +100.00:  {blocked_result['status']}")
        print(f"  Exceptions: {blocked_result['exception_count']} | Blocked-run summary saved: {summary_exists}")
        print(f"  Approved Excel created for blocked run: {excel_exists}")
        print("\nPASS: clean data is approved; reconciliation mismatch is blocked.")
        print("Demo files were temporary; project source files and existing outputs were not changed.")


if __name__ == "__main__":
    main()

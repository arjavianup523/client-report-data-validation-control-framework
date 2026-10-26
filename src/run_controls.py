import argparse
import json
from pathlib import Path

from src.control_engine import run_controls


def main() -> None:
    parser = argparse.ArgumentParser(description="Run portfolio reporting data controls.")
    parser.add_argument("--positions", default="data/positions.csv")
    parser.add_argument("--controls", default="data/control_totals.csv")
    parser.add_argument("--reference", default="data/security_reference.csv")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="outputs")
    parser.add_argument("--db", default="data/control_audit.db")
    args = parser.parse_args()

    result = run_controls(args.positions, args.controls, args.output,
                          args.config, args.reference, args.db)
    print(json.dumps(result, indent=2))
    if result["status"] == "BLOCKED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

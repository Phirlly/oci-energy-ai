"""Run offline calculations from the repository root."""

import argparse
import csv
import json
from pathlib import Path

from .battery import Battery
from .billing import load_tariff
from .intervals import load_intervals
from .reporting import baseline_report, scenario_report

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "monthly-office"


def main():
    parser = argparse.ArgumentParser(description="Offline energy bill and battery calculations (illustrative tariff).")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("baseline", "scenario"):
        sub = commands.add_parser(command)
        sub.add_argument("--intervals", type=Path, default=SAMPLE / "intervals.csv")
        sub.add_argument("--tariff", type=Path, default=SAMPLE / "tariff.json")
        if command == "scenario":
            sub.add_argument("--power-kw", type=float, default=25)
            sub.add_argument("--capacity-kwh", type=float, default=100)
            sub.add_argument("--efficiency", type=float, default=.9)
            sub.add_argument("--target-kw", type=float, default=80)
    arguments = parser.parse_args()
    try:
        readings = load_intervals(arguments.intervals)
        tariff = load_tariff(arguments.tariff)
        if arguments.command == "baseline":
            result = baseline_report(readings, tariff)
        else:
            battery = Battery(arguments.power_kw, arguments.capacity_kwh, arguments.efficiency)
            result = scenario_report(readings, tariff, battery, arguments.target_kw)
        result["data_notice"] = ("Public ComStock modeled office profile; not a measured customer record."
                                 if arguments.intervals.resolve() == (SAMPLE / "intervals.csv").resolve()
                                 else "User-supplied interval readings; provenance is the operator's responsibility.")
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()

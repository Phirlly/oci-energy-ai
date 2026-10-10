"""Reproduce the prepared month from the verified, locally supplied ComStock file."""

import argparse
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from energy_ai.intervals import Interval, calendar_month

SOURCE_SHA256 = "4034a10c35cf02640b862b18098f74bd9ef6c9a908d4217dbb6d616903254c4a"
SOURCE_URL = (
    "https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/"
    "end-use-load-profiles-for-us-building-stock/2021/comstock_amy2018_release_1/"
    "timeseries_individual_buildings/by_county/upgrade=0/county=G3600610/2083-0.parquet"
)


def prepare(source: Path, output: Path):
    if output.exists():
        raise ValueError("Output directory exists; use a new directory for explicit regeneration and comparison.")
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SOURCE_SHA256:
            raise ValueError("Source SHA256 does not match the verified ComStock profile.")
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise ValueError("Source preparation requires pyarrow==24.0.0; normal demo use does not.") from exc
    table = parquet.read_table(source, columns=["timestamp", "out.electricity.total.energy_consumption", "bldg_id"])
    data = table.to_pydict()
    if len(data["timestamp"]) != 35040 or set(data["bldg_id"]) != {2083}:
        raise ValueError("Unexpected source building or annual row count.")
    readings = tuple(
        Interval(stamp, Decimal(str(value)))
        for stamp, value in zip(data["timestamp"], data["out.electricity.total.energy_consumption"])
        if datetime(2018, 6, 1) < stamp <= datetime(2018, 7, 1)
    )
    calendar_month(readings)
    if len(readings) != 2880:
        raise ValueError("Unexpected June row count.")
    output.mkdir(parents=True, exist_ok=False)
    with (output / "intervals.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["interval_end", "energy_kwh"])
        writer.writerows((row.end.isoformat(), str(row.energy_kwh)) for row in readings)
    metadata = {
        "name": "Modeled New York medium office — June 2018",
        "source": "DOE/NREL End-Use Load Profiles, ComStock AMY2018 release 1 (2021)",
        "publication_url": "https://data.openei.org/submissions/4520",
        "source_url": SOURCE_URL,
        "source_sha256": SOURCE_SHA256,
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "building_id": 2083, "building_type": "MediumOffice", "area_sqft": 37500,
        "state": "NY", "county_id": "G3600610",
        "interval_minutes": 15, "timestamp_convention": "interval ending",
        "clock": "Unzoned source simulation clock; no civil timezone or DST conversion applied.",
        "period_start": "2018-06-01", "period_end_exclusive": "2018-07-01", "interval_count": 2880,
        "transformation": "Selected June and total electricity kWh; renamed columns; retained source float values as decimal strings.",
        "notice": "Public modeled profile, not measured customer data. Tariff and bill are illustrative demo artifacts.",
    }
    tariff = {
        "kind": "illustrative_flat_monthly", "currency": "USD",
        "energy_usd_per_kwh": "0.18", "demand_usd_per_kw": "20.00", "fixed_usd_per_month": "75.00",
        "notice": "Invented demo tariff; flat energy, monthly maximum 15-minute demand and fixed charge. No tax, TOU or demand ratchets.",
    }
    # Independently checked from the source before implementing the domain tools.
    expected = {
        "period_start": "2018-06-01", "period_end_exclusive": "2018-07-01",
        "energy_kwh": "25924.3785746685796547", "peak_kw": "98.4702504786728",
        "energy_charge_usd": "4666.39", "demand_charge_usd": "1969.41",
        "fixed_charge_usd": "75.00", "total_usd": "6710.80",
    }
    for filename, content in (("metadata.json", metadata), ("tariff.json", tariff), ("expected-bill.json", expected)):
        with (output / filename).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(content, indent=2, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        prepare(arguments.source, arguments.output)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Prepared verified monthly sample in {arguments.output}")


if __name__ == "__main__":
    main()

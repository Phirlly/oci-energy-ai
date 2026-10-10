"""Validate quarter-hour, interval-ending readings on a source simulation clock."""

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

STEP = timedelta(minutes=15)
MAX_READINGS = 366 * 96
MAX_FILE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class Interval:
    end: datetime
    energy_kwh: Decimal


def validate_intervals(readings: Sequence[Interval]) -> None:
    if not readings or len(readings) > MAX_READINGS:
        raise ValueError("Provide between 1 and 35,136 quarter-hour readings.")
    previous = None
    for index, row in enumerate(readings, start=1):
        if row.end.tzinfo is not None:
            raise ValueError("Use the unzoned source simulation clock; timezone conversion is unsupported.")
        if row.end.minute % 15 or row.end.second or row.end.microsecond:
            raise ValueError(f"Reading {index}: timestamp must end on a quarter hour.")
        if previous is not None and row.end - previous != STEP:
            raise ValueError(f"Reading {index}: timestamps must be ordered, unique and gapless at 15 minutes.")
        energy = row.energy_kwh
        if not isinstance(energy, Decimal) or not energy.is_finite() or not 0 <= energy <= Decimal("1e9"):
            raise ValueError(f"Reading {index}: energy_kwh must be finite and between 0 and 1e9.")
        if len(energy.as_tuple().digits) > 24 or energy.as_tuple().exponent < -24:
            raise ValueError(f"Reading {index}: energy_kwh supports up to 24 decimal digits.")
        previous = row.end


def load_intervals(path: Path) -> tuple[Interval, ...]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Interval CSV exceeds the 10 MiB limit.")
    readings = []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["interval_end", "energy_kwh"]:
            raise ValueError("CSV columns must be interval_end,energy_kwh, in that order.")
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV line {line}: expected exactly two fields.")
            try:
                readings.append(Interval(datetime.fromisoformat(row["interval_end"]),
                                         Decimal(row["energy_kwh"])))
            except (ValueError, InvalidOperation) as exc:
                raise ValueError(f"CSV line {line}: invalid timestamp or energy value.") from exc
            if len(readings) > MAX_READINGS:
                raise ValueError("Interval CSV exceeds the 35,136 reading limit.")
    result = tuple(readings)
    validate_intervals(result)
    return result


def calendar_month(readings: Sequence[Interval]) -> tuple[datetime, datetime]:
    validate_intervals(readings)
    try:
        start = readings[0].end - STEP
    except OverflowError as exc:
        raise ValueError("Calendar month is outside the supported date range.") from exc
    if start.day != 1 or start.hour or start.minute:
        raise ValueError("This tariff requires one complete calendar month starting at midnight.")
    try:
        end = datetime(start.year + (start.month == 12), start.month % 12 + 1, 1)
    except ValueError as exc:
        raise ValueError("Calendar month is outside the supported date range.") from exc
    if readings[-1].end != end:
        raise ValueError("This tariff requires exactly one complete calendar month.")
    return start, end

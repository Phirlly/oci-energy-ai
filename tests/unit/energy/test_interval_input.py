import csv
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from energy_ai.intervals import Interval, load_intervals, validate_intervals


def quarter_hour_readings(count):
    start = datetime(2024, 1, 1)
    return tuple(Interval(start + timedelta(minutes=15 * (i + 1)), Decimal("1"))
                 for i in range(count))


class IntervalInputTests(unittest.TestCase):
    def write_csv(self, rows, header=("interval_end", "energy_kwh")):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "readings.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def write_csv_at_size(self, byte_count):
        path = self.write_csv([("2018-06-01T00:15:00", "1")])
        # Blank CSV lines preserve valid content while exercising the byte limit.
        with path.open("ab") as stream:
            stream.write(b"\n" * (byte_count - path.stat().st_size))
        self.assertEqual(path.stat().st_size, byte_count)
        return path

    def test_exact_decimal_and_interval_ending_clock(self):
        readings = load_intervals(self.write_csv([
            ("2018-06-01T00:15:00", "0.125"),
            ("2018-06-01T00:30:00", "1.2345678901234567"),
        ]))
        self.assertEqual(readings[0].end, datetime(2018, 6, 1, 0, 15))
        self.assertEqual(readings[0].energy_kwh, Decimal("0.125"))
        self.assertEqual(readings[1].energy_kwh, Decimal("1.2345678901234567"))

    def test_rejects_invalid_energy(self):
        for value in ("NaN", "Infinity", "-Infinity", "-0.1", "", "potato", "1e999"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_intervals(self.write_csv([("2018-06-01T00:15:00", value)]))

    def test_rejects_empty_bad_headers_and_extra_fields(self):
        for rows, header in (([], ("interval_end", "energy_kwh")),
                             ([("2018-06-01T00:15:00", "1")], ("time", "kwh")),
                             ([("2018-06-01T00:15:00", "1", "extra")],
                              ("interval_end", "energy_kwh"))):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                load_intervals(self.write_csv(rows, header))

    def test_rejects_gaps_duplicates_unsorted_and_misaligned_clock(self):
        for times in ((15, 15), (30, 15), (15, 45), (16, 31)):
            rows = [(datetime(2018, 6, 1) + timedelta(minutes=t), Decimal("1"))
                    for t in times]
            with self.subTest(times=times), self.assertRaises(ValueError):
                validate_intervals(tuple(Interval(*row) for row in rows))

    def test_rejects_timezone_qualified_timestamps(self):
        with self.assertRaisesRegex(ValueError, "clock|timezone"):
            load_intervals(self.write_csv([("2018-06-01T00:15:00Z", "1")]))

    def test_accepts_csv_at_file_size_limit(self):
        readings = load_intervals(self.write_csv_at_size(10 * 1024 * 1024))
        self.assertEqual(readings, (Interval(datetime(2018, 6, 1, 0, 15), Decimal("1")),))

    def test_rejects_csv_above_file_size_limit(self):
        path = self.write_csv_at_size(10 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, "10 MiB limit"):
            load_intervals(path)

    def test_accepts_maximum_reading_count(self):
        readings = quarter_hour_readings(35_136)
        with self.subTest(interface="validator"):
            self.assertIsNone(validate_intervals(readings))
        with self.subTest(interface="CSV loader"):
            path = self.write_csv((row.end.isoformat(), str(row.energy_kwh)) for row in readings)
            self.assertEqual(load_intervals(path), readings)

    def test_rejects_readings_above_count_limit(self):
        readings = quarter_hour_readings(35_137)
        with self.subTest(interface="validator"), self.assertRaisesRegex(ValueError, "between 1 and 35,136"):
            validate_intervals(readings)
        path = self.write_csv((row.end.isoformat(), str(row.energy_kwh)) for row in readings)
        with self.subTest(interface="CSV loader"), self.assertRaisesRegex(ValueError, "35,136 reading limit"):
            load_intervals(path)

    def test_accepts_energy_at_numeric_boundaries(self):
        cases = (("24 coefficient digits", "12345678.1234567890123456"),
                 ("minimum exponent", "1e-24"), ("maximum magnitude", "1000000000"))
        for boundary, value in cases:
            with self.subTest(boundary=boundary):
                readings = load_intervals(self.write_csv([("2018-06-01T00:15:00", value)]))
                self.assertEqual(readings[0].energy_kwh, Decimal(value))

    def test_rejects_energy_outside_numeric_boundaries(self):
        cases = (("25 coefficient digits", "123456789.1234567890123456", "24 decimal digits"),
                 ("exponent below limit", "1e-25", "24 decimal digits"),
                 ("magnitude above limit", "1000000001", "between 0 and 1e9"))
        for boundary, value, message in cases:
            with self.subTest(boundary=boundary), self.assertRaisesRegex(ValueError, message):
                load_intervals(self.write_csv([("2018-06-01T00:15:00", value)]))


if __name__ == "__main__":
    unittest.main()

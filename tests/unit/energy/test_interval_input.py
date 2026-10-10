import csv
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from energy_ai.intervals import Interval, load_intervals, validate_intervals


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


if __name__ == "__main__":
    unittest.main()

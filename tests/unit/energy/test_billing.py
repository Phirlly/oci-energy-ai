from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from energy_ai.billing import Tariff, calculate_bill, load_tariff
from energy_ai.intervals import Interval


def june(energies=None):
    values = energies if energies is not None else [Decimal("1")] * 2880
    start = datetime(2018, 6, 1)
    return tuple(Interval(start + timedelta(minutes=15 * (i + 1)), Decimal(value))
                 for i, value in enumerate(values))


class BillChargeTests(unittest.TestCase):
    def test_monthly_energy_demand_and_fixed_charges(self):
        bill = calculate_bill(june(), Tariff(Decimal("0.18"), Decimal("20"), Decimal("75")))
        self.assertEqual(bill.energy_kwh, Decimal("2880"))
        self.assertEqual(bill.peak_kw, Decimal("4"))
        self.assertEqual(bill.energy_charge_usd, Decimal("518.40"))
        self.assertEqual(bill.demand_charge_usd, Decimal("80.00"))
        self.assertEqual(bill.total_usd, Decimal("673.40"))

    def test_round_each_line_half_up_before_total(self):
        readings = june(["0.125"] + ["0"] * 2879)
        bill = calculate_bill(readings, Tariff(Decimal("0.04"), Decimal("0.01"), Decimal("0.005")))
        self.assertEqual(bill.energy_charge_usd, Decimal("0.01"))
        self.assertEqual(bill.demand_charge_usd, Decimal("0.01"))
        self.assertEqual(bill.fixed_charge_usd, Decimal("0.01"))
        self.assertEqual(bill.total_usd, Decimal("0.03"))


class BillingPeriodTests(unittest.TestCase):
    def test_rejects_partial_or_shifted_month(self):
        for readings in (june()[:-1], june()[1:], tuple(
            Interval(r.end + timedelta(days=1), r.energy_kwh) for r in june())):
            with self.subTest(first=readings[0].end), self.assertRaisesRegex(ValueError, "month"):
                calculate_bill(readings, Tariff(Decimal("1"), Decimal("1"), Decimal("1")))

    def test_leap_month_and_zero_usage(self):
        start = datetime(2024, 2, 1)
        readings = tuple(Interval(start + timedelta(minutes=15 * (i + 1)), Decimal(0))
                         for i in range(29 * 96))
        bill = calculate_bill(readings, Tariff(Decimal("0.18"), Decimal("20"), Decimal("75")))
        self.assertEqual(bill.period_end_exclusive, "2024-03-01")
        self.assertEqual(bill.total_usd, Decimal("75.00"))

    def test_minimum_timestamp_fails_with_validation_error(self):
        with self.assertRaises(ValueError):
            calculate_bill((Interval(datetime.min, Decimal(1)),),
                           Tariff(Decimal(0), Decimal(0), Decimal(0)))


class TariffValidationTests(unittest.TestCase):
    def test_tariff_rejects_negative_or_nonfinite(self):
        for value in ("-1", "NaN", "Infinity", "1e999"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Tariff(Decimal(value), Decimal("0"), Decimal("0"))

    def test_tariff_rejects_unsupported_currency_kind_notice_and_bad_value(self):
        original = json.loads(Path("examples/monthly-office/tariff.json").read_text())
        for changes in ({"currency": "GBP"}, {"kind": "time_of_use"}, {"notice": ""},
                        {"energy_usd_per_kwh": "NaN"}, {"energy_usd_per_kwh": True}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "tariff.json"
                path.write_text(json.dumps({**original, **changes}))
                with self.assertRaises(ValueError):
                    load_tariff(path)

    def test_tariff_rejects_missing_rate(self):
        original = json.loads(Path("examples/monthly-office/tariff.json").read_text())
        del original["energy_usd_per_kwh"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tariff.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_tariff(path)

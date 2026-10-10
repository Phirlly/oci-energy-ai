from decimal import Decimal
import json
from pathlib import Path
import unittest

from energy_ai.battery import Battery, simulate_battery
from energy_ai.billing import calculate_bill, load_tariff
from energy_ai.intervals import load_intervals
from energy_ai.reporting import bill_fields
from tests.assertions.battery_balance import assert_battery_balance


class SampleCalculationTests(unittest.TestCase):
    def test_prepared_sample_matches_independent_baseline(self):
        folder = Path("examples/monthly-office")
        readings = load_intervals(folder / "intervals.csv")
        bill = calculate_bill(readings, load_tariff(folder / "tariff.json"))
        self.assertEqual(len(readings), 2880)
        self.assertEqual(bill.energy_kwh, Decimal("25924.3785746685796547"))
        self.assertEqual(bill.peak_kw, Decimal("98.4702504786728"))
        self.assertEqual(bill.total_usd, Decimal("6710.80"))
        self.assertEqual(bill_fields(bill), json.loads((folder / "expected-bill.json").read_text()))

    def test_prepared_month_respects_physics_and_energy_balance(self):
        readings = load_intervals(Path("examples/monthly-office/intervals.csv"))
        battery = Battery(25, 100, .9)
        result = simulate_battery(readings, battery, target_kw=80)
        assert_battery_balance(self, result, battery)
        self.assertAlmostEqual(max(row.grid_kw for row in result.steps), 80)
        charge = sum(row.charge_kw * .25 for row in result.steps)
        discharge = sum(row.discharge_kw * .25 for row in result.steps)
        self.assertAlmostEqual(discharge / charge, .9)
        self.assertAlmostEqual(float(sum(row.energy_kwh for row in result.grid_intervals)
                                     - sum(row.energy_kwh for row in readings)), charge - discharge)

from decimal import Decimal
import unittest

from energy_ai.billing import Tariff, calculate_bill
from tests.fixtures.energy_profiles import june


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

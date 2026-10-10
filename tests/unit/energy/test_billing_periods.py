from datetime import datetime, timedelta
from decimal import Decimal
import unittest

from energy_ai.billing import Tariff, calculate_bill
from energy_ai.intervals import Interval
from tests.fixtures.energy_profiles import june


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

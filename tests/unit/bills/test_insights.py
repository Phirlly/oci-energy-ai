import unittest
from copy import deepcopy

from energy_ai.bills.insights import summarize
from energy_ai.bills.schema import Facts
from tests.fixtures.bills import FACTS


def facts(**changes):
    return Facts.model_validate(dict(deepcopy(FACTS), **changes))


class BillInsightsTests(unittest.TestCase):
    def test_actual_leap_period_and_included_fee_credit_reconcile(self):
        result = summarize([facts()])
        bill = result["bills"][0]
        self.assertEqual(bill["daily_kwh"], "20.00")
        self.assertEqual(bill["average_cost_per_kwh"], "0.1578")
        self.assertEqual(bill["charge_difference"], "0.00")
        self.assertEqual(result["aggregate"]["total_kwh"], "580.00")
        self.assertEqual(result["aggregate"]["days"], 29)

    def test_days_must_agree_with_dates_and_usage_must_be_consumption(self):
        for patch in ({"days": 28}, {"service": "water"}, {"usage_kind": "net"},
                      {"unit": "gallons"}, {"period_end": None}, {"consumption": None}):
            with self.subTest(patch=patch):
                self.assertIsNone(summarize([facts(**patch)])["bills"][0]["daily_kwh"])

    def test_zero_missing_and_unitemized_are_not_invented(self):
        zero = summarize([facts(consumption="0", charges=[])])["bills"][0]
        self.assertEqual(zero["daily_kwh"], "0.00")
        self.assertIsNone(zero["average_cost_per_kwh"])
        self.assertIsNone(zero["charge_difference"])
        self.assertIsNone(summarize([Facts()])["aggregate"])

    def test_weighted_totals_sort_periods_and_report_gaps(self):
        later = facts(period_start="2024-04-01", period_end="2024-05-01",
                      days=30, consumption="300", current_total="60")
        result = summarize([later, facts()])
        self.assertEqual(result["aggregate"]["days"], 59)
        self.assertEqual(result["aggregate"]["total_kwh"], "880.00")
        self.assertEqual(result["aggregate"]["daily_kwh"], "14.92")
        self.assertEqual(result["aggregate"]["gap_days"], 31)
        self.assertEqual(result["comparisons"][0]["daily_usage_change_percent"], "-50.00")
        self.assertIn("supplied", result["label"].lower())

    def test_inclusive_and_shared_reading_boundaries(self):
        shared = facts(period_start="2024-03-01", period_end="2024-03-31", days=30)
        self.assertEqual(summarize([facts(), shared])["aggregate"]["gap_days"], 0)
        inclusive = facts(period_end="2024-02-29", days=29)
        self.assertEqual(summarize([inclusive, shared])["aggregate"]["gap_days"], 0)
        self.assertIsNone(summarize([facts(period_end="2024-03-01", days=30), shared])["aggregate"])

    def test_aggregate_refuses_duplicate_unknown_and_incompatible_accounts(self):
        next_period = dict(period_start="2024-03-01", period_end="2024-04-01", days=31)
        for other in (facts(), facts(**next_period, account="DIFFERENT"),
                      facts(**next_period, account=None), facts(**next_period, currency="EUR"),
                      facts(**next_period, meter="OTHER")):
            with self.subTest(other=other):
                result = summarize([facts(), other])
                self.assertIsNone(result["aggregate"])
                self.assertTrue(result["warnings"])

    def test_twelve_periods_are_supplied_totals_not_invented_year(self):
        from datetime import date
        periods = []
        for month in range(1, 13):
            start = date(2024, month, 1)
            end = date(2025, 1, 1) if month == 12 else date(2024, month + 1, 1)
            periods.append(facts(period_start=start, period_end=end, days=(end-start).days))
        complete = summarize(periods)
        self.assertEqual(complete["aggregate"]["days"], 366)
        self.assertEqual(complete["aggregate"]["gap_days"], 0)
        missing = summarize(periods[:5] + periods[6:])
        self.assertEqual(missing["aggregate"]["gap_days"], 30)
        self.assertNotIn("annual", complete["label"].lower())

    def test_zero_previous_usage_percentage_unavailable(self):
        second = facts(period_start="2024-03-01", period_end="2024-04-01", days=31)
        result = summarize([facts(consumption="0"), second])
        self.assertIsNone(result["comparisons"][0]["daily_usage_change_percent"])

    def test_missing_charges_do_not_block_ready_consumption_metrics(self):
        second = facts(period_start="2024-03-01", period_end="2024-04-01", days=31,
                       consumption="620", current_total=None, currency=None)
        result = summarize([facts(current_total=None), second])
        self.assertEqual(result["aggregate"]["total_kwh"], "1200.00")
        self.assertEqual(result["aggregate"]["daily_kwh"], "20.00")
        self.assertIsNone(result["aggregate"]["current_total"])
        self.assertIsNone(result["aggregate"]["average_cost_per_kwh"])
        self.assertEqual(result["comparisons"][0]["daily_usage_change_percent"], "0.00")

    def test_out_of_range_coverage_is_reported_unavailable(self):
        result = summarize([facts(period_start="9999-12-31", period_end="9999-12-31", days=1)])
        self.assertIsNone(result["bills"][0]["daily_kwh"])

    def test_approved_amount_and_small_reconciliation_difference_retain_precision(self):
        result = summarize([facts(currency="KWD", current_total="91.234",
                                  consumption="580.1234", charges=[dict(label="Energy", amount="91.2339", role="additive")])])
        self.assertEqual(result["aggregate"]["current_total"], "91.234")
        self.assertEqual(result["aggregate"]["total_kwh"], "580.1234")
        self.assertEqual(result["bills"][0]["charge_difference"], "0.0001")

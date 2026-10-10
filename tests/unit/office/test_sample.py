from io import BytesIO
import unittest

from pypdf import PdfReader
from pypdf.generic import IndirectObject
from pydantic import ValidationError

from energy_ai.office.sample import Controls, office_profile, office_scenario
from energy_ai.office.bill_pdf import office_bill_pdf


class OfficeProfileTests(unittest.TestCase):
    def test_profile_reconciles_and_uses_source_interval_days(self):
        profile = office_profile()
        self.assertEqual(profile['bill']['total_usd'], '6710.80')
        self.assertEqual(profile['bill']['energy_charge_usd'], '4666.39')
        self.assertEqual(profile['bill']['demand_charge_usd'], '1969.41')
        self.assertEqual(profile['peak_interval_end'], '2018-06-18T10:45:00')
        self.assertEqual(profile['peak_interval_start'], '2018-06-18T10:30:00')
        self.assertEqual(len(profile['daily_peaks']), 30)
        self.assertEqual(profile['daily_peaks'][0]['day'], '2018-06-01')
        self.assertEqual(profile['daily_peaks'][-1]['day'], '2018-06-30')
        self.assertEqual(len(profile['peak_day']), 96)
        self.assertEqual(profile['peak_day'][0]['start'], '2018-06-18T00:00:00')
        self.assertAlmostEqual(max(row['load_kw'] for row in profile['peak_day']), 98.4702504786728)
        self.assertIn('modeled', profile['notice'])
        self.assertIn('Unzoned', profile['clock'])

    def test_scenario_has_independent_amounts_and_zero_battery_preserves_baseline(self):
        report = office_scenario(Controls())
        self.assertEqual(report['scenario_bill']['total_usd'], '6344.11')
        self.assertEqual(report['modeled_cost_difference_usd'], '366.69')
        self.assertTrue(report['battery']['target_achieved'])
        self.assertGreater(report['battery']['losses_kwh'], 0)
        self.assertAlmostEqual(report['battery']['final_soc_kwh'], 0)
        self.assertLessEqual(max(row['grid_kw'] for row in report['peak_day']), 80.000001)
        zero = office_scenario(Controls(power_kw=0, capacity_kwh=0))
        self.assertEqual(zero['scenario_bill']['total_usd'], '6710.80')
        self.assertEqual(zero['modeled_cost_difference_usd'], '0.00')
        self.assertFalse(zero['battery']['target_achieved'])

    def test_controls_reject_nonfinite_out_of_range_and_extra_inputs(self):
        for invalid in ({'power_kw': -1}, {'efficiency': 0}, {'capacity_kwh': 2001},
                        {'target_kw': float('nan')}, {'power_kw': '25'}, {'private': 'data'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                Controls(**invalid)

    def test_bill_pdf_is_readable_illustrative_and_reconciled(self):
        reader = PdfReader(BytesIO(office_bill_pdf()))
        self.assertIsInstance(reader.pages[0].raw_get('/Contents'), IndirectObject)
        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        for expected in ('ILLUSTRATIVE', '2018-06-01', '2018-07-01', '4666.39',
                         '1969.41', '75.00', '6710.80', '25924.3785746685796547',
                         '98.4702504786728', 'ComStock', 'not a utility-issued bill'):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

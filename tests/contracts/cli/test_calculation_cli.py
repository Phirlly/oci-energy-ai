from decimal import Decimal
import json
import subprocess
import sys
import unittest


class CalculationCommandTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "energy_ai", *arguments],
                              capture_output=True, text=True, timeout=15)

    def test_baseline_json(self):
        process = self.run_cli("baseline")
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["bill"]["total_usd"], "6710.80")
        self.assertEqual(report["interval_count"], 2880)
        self.assertIn("modeled", report["data_notice"])

    def test_scenario_json_includes_losses_and_costs(self):
        process = self.run_cli("scenario", "--power-kw", "25", "--capacity-kwh", "100", "--target-kw", "80")
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertGreater(float(report["scenario_bill"]["energy_kwh"]),
                           float(report["baseline_bill"]["energy_kwh"]))
        self.assertAlmostEqual(report["battery"]["final_soc_kwh"], 0, places=8)
        self.assertIn("hindsight", report["method"])
        # Documented sample regression values; hand calculations are in unit tests.
        self.assertEqual(report["baseline_bill"]["total_usd"], "6710.80")
        self.assertEqual(report["scenario_bill"]["total_usd"], "6344.11")
        self.assertEqual(report["modeled_cost_difference_usd"], "366.69")
        battery = report["battery"]
        self.assertGreater(battery["losses_kwh"], 0)
        self.assertAlmostEqual(battery["losses_kwh"],
                               battery["charge_energy_kwh"] - battery["discharge_energy_kwh"])
        added_energy = (Decimal(report["scenario_bill"]["energy_kwh"])
                        - Decimal(report["baseline_bill"]["energy_kwh"]))
        self.assertAlmostEqual(float(added_energy), battery["losses_kwh"])
        self.assertEqual(Decimal(report["scenario_bill"]["peak_kw"]), Decimal("80"))
        self.assertEqual(battery["target_kw"], 80)
        self.assertIs(battery["target_achieved"], True)

    def test_invalid_arguments_have_nonzero_exit_and_no_traceback(self):
        for args in (("scenario", "--target-kw", "NaN"), ("baseline", "--intervals", "missing.csv")):
            with self.subTest(args=args):
                process = self.run_cli(*args)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("error:", process.stderr)
                self.assertNotIn("Traceback", process.stderr)


if __name__ == "__main__":
    unittest.main()

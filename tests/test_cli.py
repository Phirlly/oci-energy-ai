import json
import subprocess
import sys
import unittest


class CommandTests(unittest.TestCase):
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

    def test_invalid_arguments_have_nonzero_exit_and_no_traceback(self):
        for args in (("scenario", "--target-kw", "NaN"), ("baseline", "--intervals", "missing.csv")):
            with self.subTest(args=args):
                process = self.run_cli(*args)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("error:", process.stderr)
                self.assertNotIn("Traceback", process.stderr)


if __name__ == "__main__":
    unittest.main()

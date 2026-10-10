from datetime import datetime, timedelta
from decimal import Decimal
import math
import unittest

from energy_ai.battery import Battery, simulate_battery
from energy_ai.intervals import Interval
from tests.assertions.battery_balance import assert_battery_balance


def profile(load_kw):
    return tuple(Interval(datetime(2018, 6, 1) + timedelta(minutes=15 * (i + 1)),
                          Decimal(str(kw)) / 4) for i, kw in enumerate(load_kw))


class BatteryDispatchTests(unittest.TestCase):
    def assert_physics(self, result, battery):
        assert_battery_balance(self, result, battery)

    def test_perfect_efficiency_hand_calculation(self):
        battery = Battery(power_kw=4, capacity_kwh=1, round_trip_efficiency=1)
        result = simulate_battery(profile([0, 8]), battery, target_kw=4)
        self.assertEqual([r.grid_kw for r in result.steps], [4, 4])
        self.assertEqual([r.soc_kwh for r in result.steps], [1, 0])
        self.assert_physics(result, battery)

    def test_losses_and_capacity_include_all_charge_energy(self):
        battery = Battery(power_kw=8, capacity_kwh=1, round_trip_efficiency=.81)
        result = simulate_battery(profile([0, 8]), battery, target_kw=4)
        self.assertAlmostEqual(result.steps[0].charge_kw, 4)
        self.assertAlmostEqual(result.steps[1].discharge_kw, 3.24)
        self.assertAlmostEqual(result.steps[1].grid_kw, 4.76)
        self.assert_physics(result, battery)

    def test_final_short_spike_does_not_leave_stranded_charge(self):
        battery = Battery(power_kw=2, capacity_kwh=100, round_trip_efficiency=.9)
        result = simulate_battery(profile([0] * 20 + [100]), battery, target_kw=5)
        self.assertAlmostEqual(sum(r.charge_kw * .25 for r in result.steps), .5 / .9)
        self.assertAlmostEqual(result.steps[-1].discharge_kw, 2)
        self.assert_physics(result, battery)

    def test_no_free_initial_charge_and_no_export(self):
        battery = Battery(power_kw=20, capacity_kwh=50, round_trip_efficiency=.9)
        result = simulate_battery(profile([100, 0, 0]), battery, target_kw=5)
        self.assertEqual([r.grid_kw for r in result.steps], [100, 0, 0])
        self.assert_physics(result, battery)

    def test_disabled_battery_preserves_load(self):
        for battery in (Battery(0, 10, .9), Battery(10, 0, .9)):
            result = simulate_battery(profile([0, 4, 10, 0]), battery, target_kw=2)
            self.assertEqual([r.grid_kw for r in result.steps], [0, 4, 10, 0])
            self.assert_physics(result, battery)

    def test_bad_battery_parameters_and_target_rejected(self):
        for power, capacity, efficiency in ((-1, 1, .9), (1, -1, .9), (1, 1, 0),
                                            (1, 1, 1.1), (math.inf, 1, .9),
                                            (1, math.nan, .9)):
            with self.subTest(power=power, capacity=capacity), self.assertRaises(ValueError):
                Battery(power, capacity, efficiency)
        for cap in (0, -1, math.nan, math.inf):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                simulate_battery(profile([1, 2]), Battery(1, 1, 1), target_kw=cap)

if __name__ == "__main__":
    unittest.main()

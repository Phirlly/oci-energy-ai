import math


def assert_battery_balance(case, result, battery):
    eta = math.sqrt(battery.round_trip_efficiency)
    previous = 0.0
    for row in result.steps:
        case.assertGreaterEqual(row.grid_kw, -1e-9)
        case.assertGreaterEqual(row.soc_kwh, -1e-9)
        case.assertLessEqual(row.soc_kwh, battery.capacity_kwh + 1e-9)
        case.assertLessEqual(row.charge_kw, battery.power_kw + 1e-9)
        case.assertLessEqual(row.discharge_kw, battery.power_kw + 1e-9)
        case.assertAlmostEqual(row.charge_kw * row.discharge_kw, 0)
        case.assertAlmostEqual(row.grid_kw, row.load_kw + row.charge_kw - row.discharge_kw)
        case.assertAlmostEqual(row.soc_kwh, previous + row.charge_kw * .25 * eta
                               - row.discharge_kw * .25 / eta)
        previous = row.soc_kwh
    case.assertAlmostEqual(previous, 0, places=8)

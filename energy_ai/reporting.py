"""JSON-ready calculation reports, shared by CLI and future agent tools."""

from dataclasses import asdict
from decimal import Decimal
from typing import Sequence

from .battery import Battery, simulate_battery
from .billing import Tariff, calculate_bill
from .intervals import Interval


def bill_fields(bill):
    return {key: str(value) if isinstance(value, Decimal) else value
            for key, value in asdict(bill).items()}


def baseline_report(readings: Sequence[Interval], tariff: Tariff) -> dict:
    return {"bill": bill_fields(calculate_bill(readings, tariff)),
            "interval_count": len(readings),
            "tariff_notice": "Illustrative flat USD tariff; excludes taxes, TOU, ratchets and other charges."}


def scenario_report(readings: Sequence[Interval], tariff: Tariff, battery: Battery, target_kw: float) -> dict:
    baseline = calculate_bill(readings, tariff)
    simulation = simulate_battery(readings, battery, target_kw)
    scenario = calculate_bill(simulation.grid_intervals, tariff)
    charge = sum(step.charge_kw * .25 for step in simulation.steps)
    discharge = sum(step.discharge_kw * .25 for step in simulation.steps)
    return {
        "method": "Greedy hindsight peak-limit scenario using the supplied period, not optimal dispatch.",
        "baseline_bill": bill_fields(baseline),
        "scenario_bill": bill_fields(scenario),
        "modeled_cost_difference_usd": str(baseline.total_usd - scenario.total_usd),
        "battery": {**asdict(battery), "target_kw": target_kw, "initial_soc_kwh": 0,
                    "final_soc_kwh": simulation.steps[-1].soc_kwh,
                    "charge_energy_kwh": charge, "discharge_energy_kwh": discharge,
                    "losses_kwh": charge - discharge,
                    "target_achieved": float(scenario.peak_kw) <= target_kw + 1e-8},
        "limitations": "Includes charging and conversion losses. Excludes capital cost, degradation, auxiliary loads and ROI.",
    }

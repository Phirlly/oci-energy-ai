"""Bounded hindsight peak-limit simulation; not an optimizer or controller."""

from dataclasses import dataclass
from decimal import Decimal
import math
from typing import Sequence

from .intervals import Interval, validate_intervals

HOURS = .25


@dataclass(frozen=True)
class Battery:
    power_kw: float
    capacity_kwh: float
    round_trip_efficiency: float = .9

    def __post_init__(self):
        for value in (self.power_kw, self.capacity_kwh):
            if not math.isfinite(value) or not 0 <= value <= 1e9:
                raise ValueError("Battery power and capacity must be finite and between 0 and 1e9.")
        if not math.isfinite(self.round_trip_efficiency) or not 0 < self.round_trip_efficiency <= 1:
            raise ValueError("Round-trip efficiency must be greater than 0 and at most 1.")


@dataclass(frozen=True)
class DispatchStep:
    load_kw: float
    grid_kw: float
    charge_kw: float
    discharge_kw: float
    soc_kwh: float


@dataclass(frozen=True)
class Simulation:
    steps: tuple[DispatchStep, ...]
    grid_intervals: tuple[Interval, ...]


def simulate_battery(readings: Sequence[Interval], battery: Battery, target_kw: float) -> Simulation:
    validate_intervals(readings)
    if not math.isfinite(target_kw) or not 0 < target_kw <= 1e9:
        raise ValueError("Target demand must be finite, greater than 0 and at most 1e9 kW.")
    eta = math.sqrt(battery.round_trip_efficiency)
    loads = [float(row.energy_kwh * 4) for row in readings]
    # Reverse sum of the *reachable* future stored-energy withdrawals.
    future = [0.0] * (len(loads) + 1)
    for i in range(len(loads) - 1, -1, -1):
        withdrawal = min(max(0.0, loads[i] - target_kw), battery.power_kw) * HOURS / eta
        future[i] = future[i + 1] + withdrawal
    steps = []
    grid_intervals = []
    soc = 0.0
    for i, (row, load) in enumerate(zip(readings, loads)):
        charge = discharge = 0.0
        if load > target_kw:
            discharge = min(load - target_kw, battery.power_kw, soc * eta / HOURS)
            soc = max(0.0, soc - discharge * HOURS / eta)
        elif load < target_kw:
            room = max(0.0, min(battery.capacity_kwh, future[i + 1]) - soc)
            charge = min(target_kw - load, battery.power_kw, room / (HOURS * eta))
            soc += charge * HOURS * eta
        grid = max(0.0, load + charge - discharge)
        steps.append(DispatchStep(load, grid, charge, discharge, soc))
        # Preserve exact original readings when the battery is inactive.
        energy = row.energy_kwh if charge == discharge == 0 else Decimal(str(grid * HOURS))
        grid_intervals.append(Interval(row.end, energy))
    return Simulation(tuple(steps), tuple(grid_intervals))

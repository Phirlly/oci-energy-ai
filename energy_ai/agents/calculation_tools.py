"""Deterministic calculations and execution evidence for the public sample."""

from dataclasses import dataclass, field
import json
from pathlib import Path

from agents import function_tool
from agents.tool_context import ToolContext

from energy_ai.battery import Battery
from energy_ai.billing import Tariff, load_tariff
from energy_ai.intervals import Interval, load_intervals
from energy_ai.reporting import scenario_report

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "monthly-office"


@dataclass(frozen=True)
class CalculationExecution:
    call_id: str
    parameters: dict
    report: dict


@dataclass
class AnalysisContext:
    readings: tuple[Interval, ...]
    tariff: Tariff
    executions: list[CalculationExecution] = field(default_factory=list)
    attempts: int = 0

    @classmethod
    def from_sample(cls):
        return cls(tuple(load_intervals(SAMPLE / "intervals.csv")), load_tariff(SAMPLE / "tariff.json"))


@function_tool(failure_error_function=None)
def analyze_energy(ctx: ToolContext[AnalysisContext], power_kw: float, capacity_kwh: float,
                   efficiency: float, target_kw: float) -> str:
    """Calculate the public sample's baseline bill and illustrative battery scenario.

    Args:
        power_kw: Battery charge/discharge power in kW.
        capacity_kwh: Battery energy capacity in kWh.
        efficiency: Round-trip efficiency, greater than zero and at most one.
        target_kw: Desired grid peak demand in kW.
    """
    context = ctx.context
    context.attempts += 1
    if context.attempts > 2:
        raise ValueError("Calculation tool call limit exceeded.")
    battery = Battery(power_kw, capacity_kwh, efficiency)
    report = scenario_report(context.readings, context.tariff, battery, target_kw)
    report["data_notice"] = "Public ComStock modeled office profile; invented flat USD tariff."
    parameters = dict(power_kw=power_kw, capacity_kwh=capacity_kwh,
                      efficiency=efficiency, target_kw=target_kw)
    context.executions.append(CalculationExecution(ctx.tool_call_id, parameters, report))
    return json.dumps(report, allow_nan=False)

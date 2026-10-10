"""Office tools bind calculations to presenter-selected controls."""

from dataclasses import dataclass, field
import json

from agents import function_tool
from agents.tool_context import ToolContext

from energy_ai.office.sample import Controls, inspection_report, office_scenario


@dataclass
class OfficeContext:
    controls: Controls
    executions: dict = field(default_factory=dict)

    def record(self, name, call_id, report):
        if name in self.executions:
            raise ValueError('Each office tool may execute once.')
        self.executions[name] = dict(call_id=call_id, report=report)
        return json.dumps(report, allow_nan=False)


@function_tool(failure_error_function=None)
def inspect_office(ctx: ToolContext[OfficeContext]) -> str:
    """Read the prepared office's bill, demand peak, source and illustrative tariff."""
    return ctx.context.record('inspect_office', ctx.tool_call_id, inspection_report())


@function_tool(failure_error_function=None)
def simulate_selected_battery(ctx: ToolContext[OfficeContext]) -> str:
    """Calculate the presenter's selected battery; controls cannot be changed by the model."""
    report = office_scenario(ctx.context.controls)
    # The chart remains available to the application; the model needs only its facts.
    report.pop('peak_day')
    return ctx.context.record('simulate_selected_battery', ctx.tool_call_id, report)

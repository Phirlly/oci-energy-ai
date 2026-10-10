import json
import unittest

from agents.tool_context import ToolContext

from energy_ai.agents.calculation_tools import AnalysisContext, analyze_energy
from tests.fixtures.agent_responses import PARAMETERS


class CalculationToolTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, context, call_id="call-1", **changes):
        arguments = json.dumps(PARAMETERS | changes)
        wrapped = ToolContext(context=context, tool_name="analyze_energy",
                              tool_call_id=call_id, tool_arguments=arguments)
        return json.loads(await analyze_energy.on_invoke_tool(wrapped, arguments))

    async def test_tool_uses_real_calculations_and_records_matching_execution(self):
        context = AnalysisContext.from_sample()
        report = await self.invoke(context)
        self.assertEqual(report["baseline_bill"]["total_usd"], "6710.80")
        self.assertEqual(report["scenario_bill"]["total_usd"], "6344.11")
        self.assertEqual(report["modeled_cost_difference_usd"], "366.69")
        self.assertTrue(report["battery"]["target_achieved"])
        self.assertIn("modeled", report["data_notice"])
        self.assertEqual(context.executions[0].call_id, "call-1")
        self.assertEqual(context.executions[0].report, report)

    async def test_bad_physical_parameters_cannot_generate_success(self):
        for changes in ({"power_kw": -1}, {"efficiency": 0}, {"target_kw": float("nan")}):
            with self.subTest(changes=changes):
                context = AnalysisContext.from_sample()
                with self.assertRaises(ValueError):
                    await self.invoke(context, **changes)
                self.assertEqual(context.executions, [])

    async def test_third_tool_call_is_rejected_before_calculation(self):
        context = AnalysisContext.from_sample()
        await self.invoke(context)
        await self.invoke(context, "call-2")
        with self.assertRaisesRegex(ValueError, "limit"):
            await self.invoke(context, "call-3")
        self.assertEqual(len(context.executions), 2)

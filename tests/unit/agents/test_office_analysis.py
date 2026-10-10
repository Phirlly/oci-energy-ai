import asyncio
import json
import unittest
from unittest.mock import patch

from agents import Runner

from energy_ai.agents.analysis import AnalysisError
from energy_ai.agents.office_analysis import analyze_office
from energy_ai.office.sample import Controls
from tests.fixtures.agent_responses import ANSWER, ScriptedModel, message
from tests.fixtures.office_responses import ENERGY_ANSWER, office_call, office_outputs


class OfficeAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_real_agents_use_tools_and_verified_facts_with_measured_events(self):
        events, model = [], ScriptedModel(office_outputs())
        result = await analyze_office(model, Controls(), 'evaluate_battery', events.append)
        self.assertEqual(result['energy'], ENERGY_ANSWER)
        self.assertEqual(result['savings'], ANSWER)
        self.assertEqual(result['usage'], dict(tool_calls=2, model_requests=4, input_tokens=40, output_tokens=80))
        self.assertEqual(result['scenario']['scenario_bill']['total_usd'], '6344.11')
        self.assertEqual([e['tool'] for e in events if e['kind'] == 'tool_started'],
                         ['inspect_office', 'simulate_selected_battery'])
        self.assertEqual([e['kind'] for e in events].count('analyst_verified'), 2)
        self.assertEqual([e['kind'] for e in events].count('workflow_transition'), 1)
        self.assertEqual([e['kind'] for e in events].count('model_finished'), 4)
        for request in model.requests:
            self.assertFalse(request['model_settings'].store)
            self.assertTrue(request['tracing'].is_disabled())
        self.assertIn(ENERGY_ANSWER['peak_kw'], str(model.requests[2]['input']))
        self.assertNotIn('explanation', json.dumps(events))

    async def test_zero_battery_uses_selected_controls_and_exact_tool_output(self):
        outputs = office_outputs()
        outputs[-1] = [message(ANSWER | dict(scenario_total_usd='6710.80', modeled_cost_difference_usd='0.00'))]
        result = await analyze_office(ScriptedModel(outputs), Controls(power_kw=0, capacity_kwh=0),
                                      'explain_bill', lambda event: None)
        self.assertEqual(result['scenario']['controls']['power_kw'], 0)
        self.assertEqual(result['savings']['modeled_cost_difference_usd'], '0.00')

    async def test_missing_tool_wrong_facts_or_repeated_tool_rejected(self):
        cases = [[message(ENERGY_ANSWER)],
                 [office_call('inspect_office', 'one')],
                 [office_call('inspect_office', 'one')]]
        sequences = [[cases[0]], [cases[1], [message(ENERGY_ANSWER | {'peak_kw': '1'})]],
                     [cases[2], [office_call('inspect_office', 'two')]]]
        for outputs in sequences:
            with self.subTest(outputs=outputs), self.assertRaises(AnalysisError):
                await analyze_office(ScriptedModel(outputs), Controls(), 'explain_bill', lambda event: None)

    async def test_correlated_tool_evidence_is_required(self):
        original = Runner.run
        async def corrupt(*args, **kwargs):
            result = await original(*args, **kwargs)
            next(i.raw_item for i in result.new_items if i.type == 'tool_call_output_item')['call_id'] = 'wrong'
            return result
        with patch('energy_ai.agents.office_analysis.Runner.run', side_effect=corrupt):
            with self.assertRaises(AnalysisError):
                await analyze_office(ScriptedModel(office_outputs()), Controls(), 'explain_bill', lambda event: None)

    async def test_timeout_and_provider_failure_are_safe_and_cancel_propagates(self):
        class Waiting(ScriptedModel):
            async def get_response(self, **request):
                await asyncio.Event().wait()
        with self.assertRaises(AnalysisError) as caught:
            await analyze_office(Waiting([]), Controls(), 'explain_bill', lambda event: None, timeout=.01)
        self.assertEqual(caught.exception.category, 'timeout')
        with self.assertRaises(AnalysisError) as caught:
            await analyze_office(ScriptedModel([RuntimeError('private-marker')]), Controls(),
                                 'explain_bill', lambda event: None)
        self.assertNotIn('private-marker', str(caught.exception))
        task = asyncio.create_task(analyze_office(Waiting([]), Controls(), 'explain_bill', lambda event: None))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

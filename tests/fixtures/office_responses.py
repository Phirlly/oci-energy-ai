"""Public office responses for actual offline Runner execution."""

from openai.types.responses import ResponseFunctionToolCall

from tests.fixtures.agent_responses import ANSWER, message

ENERGY_ANSWER = dict(baseline_total_usd='6710.80', peak_kw='98.4702504786728',
                     explanation='The modeled office peak occurs on June 18 at 10:30 in the source clock.')


def office_call(name, call_id):
    return ResponseFunctionToolCall(type='function_call', name=name,
                                    call_id=call_id, arguments='{}')


def office_outputs():
    return [[office_call('inspect_office', 'inspect-1')], [message(ENERGY_ANSWER)],
            [office_call('simulate_selected_battery', 'battery-1')], [message(ANSWER)]]

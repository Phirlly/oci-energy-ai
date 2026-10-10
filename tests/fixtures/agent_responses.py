"""Real Agents response objects with no network access."""

import json

from agents import Model, ModelResponse, Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

PARAMETERS = {"power_kw": 25, "capacity_kwh": 100, "efficiency": .9, "target_kw": 80}
ANSWER = {"baseline_total_usd": "6710.80", "scenario_total_usd": "6344.11",
          "modeled_cost_difference_usd": "366.69",
          "explanation": "The illustrative hindsight scenario reduces peak demand and includes charging losses."}


def tool_call(call_id="call-1", **changes):
    return ResponseFunctionToolCall(type="function_call", name="analyze_energy",
                                    call_id=call_id, arguments=json.dumps(PARAMETERS | changes))


def message(value=None):
    return ResponseOutputMessage(id="message-1", role="assistant", type="message", status="completed",
                                 content=[ResponseOutputText(type="output_text", annotations=[],
                                                             text=json.dumps(ANSWER if value is None else value))])


class ScriptedModel(Model):
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    async def get_response(self, **request):
        self.requests.append(request)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return ModelResponse(output=output, usage=Usage(requests=1, input_tokens=10,
                                                        output_tokens=20, total_tokens=30),
                             response_id=None)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError

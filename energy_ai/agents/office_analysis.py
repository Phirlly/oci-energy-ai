"""Sequential analyst runs with verified tools, bounded output and safe event metadata."""

import asyncio
from decimal import Decimal
import json
import time

from agents import Agent, ModelSettings, RunConfig, RunHooks, Runner
from agents.exceptions import ModelTimeoutError
from anthropic import APITimeoutError as AnthropicTimeout
from openai import APITimeoutError as OpenAITimeout

from energy_ai.agents.analysis import AnalysisError
from energy_ai.agents.office_tools import OfficeContext, inspect_office, simulate_selected_battery

QUESTIONS = {'explain_bill': 'Explain the office bill and its peak demand, then evaluate the selected battery.',
             'evaluate_battery': 'Evaluate how the selected battery changes peak demand and operating cost.'}
ENERGY = 'Energy Analyst'
SAVINGS = 'Tariff & Savings Analyst'


class OfficeEvents(RunHooks):
    def __init__(self, publish):
        self.publish = publish
        self.start = time.monotonic()

    def emit(self, kind, agent, **fields):
        self.publish(dict(kind=kind, agent=agent, elapsed_ms=round((time.monotonic() - self.start) * 1000), **fields))

    async def on_agent_start(self, context, agent):
        self.emit('analyst_started', agent.name)

    async def on_llm_start(self, context, agent, system_prompt, input_items):
        self.emit('model_started', agent.name)

    async def on_llm_end(self, context, agent, response):
        self.emit('model_finished', agent.name, input_tokens=response.usage.input_tokens,
                  output_tokens=response.usage.output_tokens)

    async def on_tool_start(self, context, agent, tool):
        self.emit('tool_started', agent.name, tool=tool.name)

    async def on_tool_end(self, context, agent, tool, result):
        self.emit('tool_finished', agent.name, tool=tool.name)


def verified_answer(result, context, tool_name, expected):
    """Accept an explanation only when actual tool evidence and every numeric field agree."""
    stage = 'tool_evidence'
    try:
        execution = context.executions[tool_name]
        calls = [i.raw_item for i in result.new_items if i.type == 'tool_call_item']
        outputs = [i.raw_item for i in result.new_items if i.type == 'tool_call_output_item']
        if (len(calls) != 1 or len(outputs) != 1 or calls[0].name != tool_name
                or calls[0].call_id != execution['call_id']
                or outputs[0].get('call_id') != execution['call_id']
                or json.loads(calls[0].arguments) != {}
                or json.loads(outputs[0]['output']) != execution['report']):
            raise ValueError('Missing tool evidence.')
        stage = 'answer_json'
        raw = result.final_output
        if not isinstance(raw, str) or len(raw) > 6000:
            raise ValueError('Answer too large.')
        raw = raw.strip()
        if raw.startswith('```json\n') and raw.endswith('\n```'):
            raw = raw[8:-4]
        answer = json.loads(raw)
        stage = 'answer_shape'
        if (not isinstance(answer, dict) or set(answer) != set(expected) | {'explanation'}
                or not isinstance(answer['explanation'], str)
                or not 1 <= len(answer['explanation'].strip()) <= 4000):
            raise ValueError('Answer fields differ.')
        stage = 'answer_facts'
        for key, value in expected.items():
            if (not isinstance(answer[key], str) or len(answer[key]) > 32
                    or not Decimal(answer[key]).is_finite() or Decimal(answer[key]) != Decimal(value)):
                raise ValueError('Numeric answer differs.')
        return answer
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise AnalysisError('verification', stage=stage) from None


async def analyze_office(model, controls, question, publish, *, timeout=180):
    context, hooks = OfficeContext(controls), OfficeEvents(publish)
    settings = ModelSettings(max_tokens=2048, timeout=60, store=False, tool_choice='required')
    config = RunConfig(tracing_disabled=True, trace_include_sensitive_data=False)
    usage = dict(tool_calls=0, model_requests=0, input_tokens=0, output_tokens=0)

    async def stage(name, tool, prompt, fields):
        agent = Agent(name=name, model=model, tools=[tool], model_settings=settings,
                      instructions=f'Use {tool.name} exactly once. Return only a JSON object with '
                      f'{fields} as decimal strings and explanation as a concise nonempty string. '
                      'Use exact tool numbers. Explain source and limits. This is a public modeled '
                      'office and invented tariff; battery simulation is hindsight, excludes equipment '
                      'cost and is not an investment recommendation. Never invent calculations.')
        result = await Runner.run(agent, prompt, context=context, max_turns=3, run_config=config, hooks=hooks)
        measured = result.context_wrapper.usage
        usage['model_requests'] += measured.requests
        usage['input_tokens'] += measured.input_tokens
        usage['output_tokens'] += measured.output_tokens
        usage['tool_calls'] += 1
        return result

    try:
        async with asyncio.timeout(min(timeout, 180)):
            prompt = QUESTIONS[question]
            first = await stage(ENERGY, inspect_office, prompt, 'baseline_total_usd, peak_kw')
            bill = context.executions.get('inspect_office', {}).get('report', {}).get('bill', {})
            energy = verified_answer(first, context, 'inspect_office',
                                     dict(baseline_total_usd=bill.get('total_usd'), peak_kw=bill.get('peak_kw')))
            hooks.emit('analyst_verified', ENERGY)
            hooks.emit('workflow_transition', SAVINGS)
            second = await stage(SAVINGS, simulate_selected_battery,
                                 prompt + '\nVerified energy findings: ' + json.dumps(energy),
                                 'baseline_total_usd, scenario_total_usd, modeled_cost_difference_usd')
            scenario = context.executions.get('simulate_selected_battery', {}).get('report', {})
            savings = verified_answer(second, context, 'simulate_selected_battery', dict(
                baseline_total_usd=scenario.get('baseline_bill', {}).get('total_usd'),
                scenario_total_usd=scenario.get('scenario_bill', {}).get('total_usd'),
                modeled_cost_difference_usd=scenario.get('modeled_cost_difference_usd')))
            hooks.emit('analyst_verified', SAVINGS)
            return dict(energy=energy, savings=savings, scenario=scenario, usage=usage)
    except (TimeoutError, ModelTimeoutError, OpenAITimeout, AnthropicTimeout):
        raise AnalysisError('timeout') from None
    except AnalysisError:
        raise
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise AnalysisError('verification', stage='runner') from None
    except Exception as error:
        category = {401: 'authentication', 403: 'access', 404: 'access', 429: 'rate_limit'}.get(
            getattr(error, 'status_code', None), 'provider_error')
        raise AnalysisError(category) from None

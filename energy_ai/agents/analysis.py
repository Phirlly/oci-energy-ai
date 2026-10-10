"""Prove a bounded public-sample model/tool round trip with independent amounts."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
import json

from agents import Agent, ModelSettings, RunConfig, Runner
from agents.exceptions import ModelTimeoutError
from anthropic import APITimeoutError as AnthropicTimeout
from openai import APITimeoutError as OpenAITimeout

from energy_ai.agents.calculation_tools import AnalysisContext, analyze_energy

PARAMETERS = dict(power_kw=25, capacity_kwh=100, efficiency=.9, target_kw=80)
EXPECTED = {"baseline_total_usd": "6710.80", "scenario_total_usd": "6344.11",
            "modeled_cost_difference_usd": "366.69"}
INSTRUCTIONS = """You are an energy analyst demonstrating a public modeled office month.
Use analyze_energy to calculate the requested scenario. Never invent calculations.
After the tool returns, answer with only one JSON object (no Markdown) containing
baseline_total_usd, scenario_total_usd, modeled_cost_difference_usd as decimal USD
strings, and explanation as a concise nonempty string. Explain the peak-demand
effect, charging losses, invented tariff and hindsight limitations. These are
illustrative operating costs, not equipment ROI. Use the tool's numeric results."""
PROMPT = "Analyze the sample month with a 25 kW, 100 kWh battery, 0.9 round-trip efficiency and 80 kW target."


class AnalysisError(Exception):
    """Fixed public categories; never include provider response bodies."""

    def __init__(self, category, *, stage=None, opening_fence=None):
        self.category = category
        self.diagnostics = {}
        if category == "verification" and stage in {
            "runner", "tool_evidence", "sample_calculation", "answer_json", "answer_shape", "answer_facts",
        }:
            self.diagnostics["stage"] = stage
            if stage == "answer_json" and isinstance(opening_fence, bool):
                self.diagnostics["opening_fence"] = opening_fence
        messages = {
            "verification": "Tool execution or numeric answer verification failed.",
            "timeout": "Model analysis exceeded its deadline.",
            "authentication": "Provider authentication failed; check its configured credential.",
            "access": "Provider model unavailable or access denied; check model access and region.",
            "rate_limit": "Provider quota or rate limit reached; retry later.",
            "provider_error": "Provider request failed; raw details suppressed.",
        }
        super().__init__(messages[category])


@dataclass(frozen=True)
class VerifiedAnalysis:
    answer: dict
    tool_calls: int
    model_requests: int
    input_tokens: int
    output_tokens: int


def _verify(result, context):
    stage = "tool_evidence"
    try:
        if not context.executions:
            raise ValueError("No execution.")
        calls = [item.raw_item for item in result.new_items if item.type == "tool_call_item"]
        outputs = [item.raw_item for item in result.new_items if item.type == "tool_call_output_item"]
        if len(calls) != len(context.executions) or len(outputs) != len(calls):
            raise ValueError("Missing execution evidence.")
        for execution in context.executions:
            stage = "tool_evidence"
            call = [item for item in calls if item.call_id == execution.call_id]
            output = [item for item in outputs if item.get("call_id") == execution.call_id]
            if (len(call) != 1 or len(output) != 1 or call[0].name != "analyze_energy"
                    or execution.parameters != PARAMETERS
                    or json.loads(call[0].arguments) != PARAMETERS
                    or json.loads(output[0]["output"]) != execution.report):
                raise ValueError("Execution evidence differs.")
            stage = "sample_calculation"
            report = execution.report
            actual = {"baseline_total_usd": report["baseline_bill"]["total_usd"],
                      "scenario_total_usd": report["scenario_bill"]["total_usd"],
                      "modeled_cost_difference_usd": report["modeled_cost_difference_usd"]}
            if actual != EXPECTED:
                raise ValueError("Independent sample regression.")
        stage = "answer_json"
        answer = json.loads(result.final_output)
        stage = "answer_shape"
        if not isinstance(answer, dict) or set(answer) != set(EXPECTED) | {"explanation"}:
            raise ValueError("Answer fields differ.")
        if not isinstance(answer["explanation"], str) or not 1 <= len(answer["explanation"].strip()) <= 4000:
            raise ValueError("Explanation missing.")
        stage = "answer_facts"
        for name, expected in EXPECTED.items():
            value = answer[name]
            if not isinstance(value, str) or len(value) > 32 or Decimal(value) != Decimal(expected):
                raise ValueError("Answer amount differs.")
    except (ValueError, KeyError, TypeError, ArithmeticError):
        fenced = isinstance(result.final_output, str) and result.final_output.lstrip().startswith("```")
        raise AnalysisError("verification", stage=stage, opening_fence=fenced) from None
    usage = result.context_wrapper.usage
    return VerifiedAnalysis(answer, len(calls), usage.requests, usage.input_tokens, usage.output_tokens)


async def analyze_sample(model, *, timeout=120):
    """Use real Runner execution; return only after tool and final-answer validation."""
    context = AnalysisContext.from_sample()
    agent = Agent(
        name="Energy Analyst", instructions=INSTRUCTIONS, model=model, tools=[analyze_energy],
        model_settings=ModelSettings(max_tokens=2048, timeout=60, store=False, tool_choice="required"),
    )
    try:
        async with asyncio.timeout(min(timeout, 120)):
            result = await Runner.run(agent, PROMPT, context=context, max_turns=4,
                                      run_config=RunConfig(tracing_disabled=True,
                                                           trace_include_sensitive_data=False))
            return _verify(result, context)
    except (TimeoutError, ModelTimeoutError, OpenAITimeout, AnthropicTimeout):
        raise AnalysisError("timeout") from None
    except AnalysisError:
        raise
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise AnalysisError("verification", stage="runner") from None
    except Exception as error:
        category = {401: "authentication", 403: "access", 404: "access", 429: "rate_limit"}.get(
            getattr(error, "status_code", None), "provider_error")
        raise AnalysisError(category) from None

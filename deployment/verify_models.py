"""Opt-in public-sample model/tool verification using GitHub environment secrets."""

import argparse
import asyncio
import json
import logging
import os
import time

from deployment.configuration import DeploymentError
from deployment.model_context import load_oci_model_context
from energy_ai.agents.analysis import AnalysisError, EXPECTED, analyze_sample
from energy_ai.agents.provider_clients import DEFAULT_MODELS, open_model

GUIDANCE = {
    "configuration": "Check the selected provider's environment settings and model identifier.",
    "foundation": "Check OCI identity and the owned foundation's latest APPLY and ACTIVE project.",
    "unexpected": "Model check failed; raw details suppressed.",
}


def provider_options(provider, environment):
    options = {"model_id": environment.get(f"{provider.upper()}_MODEL") or None}
    if provider == "oci":
        options.update(load_oci_model_context(environment))
    else:
        options["api_key"] = environment.get(f"{provider.upper()}_API_KEY")
        if not isinstance(options["api_key"], str) or not options["api_key"].strip():
            raise ValueError("Provider key is required.")
    return options


async def verify_provider(provider, environment):
    started = time.monotonic()
    diagnostics = {}
    try:
        options = provider_options(provider, environment)
        async with open_model(provider, **options) as model:
            result = await analyze_sample(model)
        return {
            "provider": provider, "status": "passed",
            "model": options["model_id"] or DEFAULT_MODELS[provider],
            "tool_calls": result.tool_calls, "model_requests": result.model_requests,
            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "amounts": {name: result.answer[name] for name in EXPECTED},
        }
    except AnalysisError as error:
        category, guidance = error.category, str(error)
        diagnostics = error.diagnostics
    except DeploymentError:
        category, guidance = "foundation", GUIDANCE["foundation"]
    except ValueError:
        category, guidance = "configuration", GUIDANCE["configuration"]
    except Exception:
        category, guidance = "unexpected", GUIDANCE["unexpected"]
    report = {"provider": provider, "status": "failed", "category": category, "guidance": guidance}
    if diagnostics:
        report["diagnostics"] = diagnostics
    return report


async def verify_selected(selection, environment, *, check=None):
    check = check or verify_provider
    results = []
    for provider in DEFAULT_MODELS if selection == "configured" else [selection]:
        key = environment.get(f"{provider.upper()}_API_KEY")
        if selection == "configured" and provider != "oci" and (key is None or isinstance(key, str) and not key.strip()):
            results.append({"provider": provider, "status": "skipped", "reason": "API key not configured."})
        else:
            results.append(await check(provider, environment))
    return results


def _write_summary(path, results):
    with open(path, "a", encoding="utf-8") as summary:
        summary.write("## Public-sample model/tool verification\n\n")
        summary.write("| Provider | Status | Tool calls | Model requests |\n| --- | --- | ---: | ---: |\n")
        for result in results:
            summary.write(f"| {result['provider']} | {result['status']} | "
                          f"{result.get('tool_calls', '-')} | {result.get('model_requests', '-')} |\n")
        summary.write("\nPassed means real tool execution and agreement with the independent sample amounts. "
                      "Skipped providers were not tested. No application was deployed.\n")


def main(arguments=None, *, environment=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("configured", *DEFAULT_MODELS), default="configured")
    args = parser.parse_args(arguments)
    environment = os.environ if environment is None else environment
    # SDK debug/error logs can contain response bodies. This CLI emits only its safe report.
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        results = asyncio.run(verify_selected(args.provider, environment))
    finally:
        logging.disable(previous_logging)
    print(json.dumps({"sample": "monthly-office", "providers": results}, allow_nan=False))
    if environment.get("GITHUB_STEP_SUMMARY"):
        try:
            _write_summary(environment["GITHUB_STEP_SUMMARY"], results)
        except OSError:
            print("Could not write the GitHub summary; inspect the safe JSON report.")
            return 1
    return 1 if any(result["status"] == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Opt-in real-model extraction checks; only invented public bill text is sent."""

import argparse
import asyncio
from datetime import date
from decimal import Decimal
import json
import logging
import os
import time

from deployment.verify_models import provider_options, verify_selected
from energy_ai.agents.provider_clients import DEFAULT_MODELS, open_model
from energy_ai.bills.examples import EXAMPLES
from energy_ai.bills.extraction import ExtractionError, extract_bill
from energy_ai.bills.insights import summarize


class ExpectedFactsError(ValueError):
    def __init__(self, fields, diagnostics=None):
        self.fields = sorted(fields)
        self.diagnostics = dict(fields=self.fields, **(diagnostics or {}))
        super().__init__("Independent fixture comparison failed.")


def check_facts(facts, index):
    if index == 2:
        if facts.service != "water" or summarize([facts])["bills"][0]["daily_kwh"] is not None:
            raise ExpectedFactsError(["non_electric_classification"])
        return
    expected = (
        dict(start="2024-02-01", end="2024-03-01", days=29, kwh=580, total="91.50", daily="20.00",
             supplier="Juniper Power", account="DEMO-A71", meter="MTR-EXAMPLE"),
        dict(start="2024-04-10", end="2024-05-10", days=30, kwh=900, total="129.15", daily="30.00",
             supplier="Cedar Municipal Utilities", account="SAMPLE-B82", meter="LAB-001"),
    )[index]
    expected_fields = dict(service="electricity", usage_kind="consumption", unit="kWh", currency="USD",
                           period_start=date.fromisoformat(expected["start"]),
                           period_end=date.fromisoformat(expected["end"]), days=expected["days"],
                           consumption=expected["kwh"], current_total=Decimal(expected["total"]),
                           **{name: expected[name] for name in ("supplier", "account", "meter")})
    different = [name for name, value in expected_fields.items() if getattr(facts, name) != value]
    if different:
        diagnostics = {}
        if "supplier" in different:
            actual = " ".join((facts.supplier or "").casefold().split())
            wanted = expected["supplier"].casefold()
            diagnostics = dict(supplier_absent=facts.supplier is None,
                               supplier_normalized_match=actual == wanted,
                               supplier_contains_expected=wanted in actual)
        raise ExpectedFactsError(different, diagnostics)
    insight = summarize([facts])["bills"][0]
    different = [name for name, value in dict(daily_kwh=expected["daily"], charge_difference="0.00").items()
                 if insight[name] != value]
    if different:
        raise ExpectedFactsError(different)
    if index == 0 and not any(charge.role == "included" and charge.amount == 12 for charge in facts.charges):
        raise ExpectedFactsError(["included_fee"])


async def verify_bill_provider(provider, environment):
    started = time.monotonic()
    checks = []
    stage = "provider_or_configuration"
    try:
        async with open_model(provider, **provider_options(provider, environment)) as model:
            for index, text in enumerate(EXAMPLES):
                stage = "extraction"
                result = await extract_bill(model, [text])
                stage = "expected_facts"
                check_facts(result.candidate.facts, index)
                checks.append(dict(fixture=("electric-summary", "electric-table", "water-only")[index],
                                   model_requests=result.requests, input_tokens=result.input_tokens,
                                   output_tokens=result.output_tokens))
        return dict(provider=provider, status="passed", checks=checks,
                    elapsed_seconds=round(time.monotonic() - started, 2))
    except Exception as error:
        diagnostics = None
        if isinstance(error, ExtractionError):
            diagnostics = error.diagnostics
        elif isinstance(error, ExpectedFactsError):
            diagnostics = error.diagnostics
        return dict(provider=provider, status="failed", completed_checks=len(checks),
                    stage="extraction_" + error.category if isinstance(error, ExtractionError) else stage,
                    diagnostics=diagnostics,
                    guidance="Public bill extraction or expected-fact check failed; raw details suppressed.")


def main(arguments=None, *, environment=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("configured", *DEFAULT_MODELS), default="configured")
    args = parser.parse_args(arguments)
    environment = os.environ if environment is None else environment
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        results = asyncio.run(verify_selected(args.provider, environment, check=verify_bill_provider))
    finally:
        logging.disable(previous)
    print(json.dumps({"fixtures": "invented-public-bills", "providers": results}, allow_nan=False))
    if environment.get("GITHUB_STEP_SUMMARY"):
        with open(environment["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("\n## Invented bill extraction\n\n| Provider | Status | Verified layouts |\n| --- | --- | ---: |\n")
            for result in results:
                summary.write(f"| {result['provider']} | {result['status']} | {len(result.get('checks', []))} |\n")
            summary.write("\nPublic text only. Checks prove exact-source evidence, expected facts and deterministic arithmetic; users must still review their own bills.\n")
    return int(any(item["status"] == "failed" for item in results))


if __name__ == "__main__":
    raise SystemExit(main())

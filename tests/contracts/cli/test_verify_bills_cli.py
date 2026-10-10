from contextlib import asynccontextmanager, redirect_stdout, redirect_stderr
import io
import json
import unittest
from unittest.mock import patch

from deployment.verify_bills import main, check_facts
from energy_ai.bills.schema import Facts
from tests.fixtures.bills import FACTS


class PublicBillVerificationTests(unittest.TestCase):
    def test_independent_expected_facts_reject_account_balance_and_wrong_period(self):
        check_facts(Facts.model_validate(FACTS), 0)
        for changes in ({"current_total": "131.50"}, {"days": 30}, {"consumption": "590"},
                        {"charges": []}, {"service": "mixed"}, {"supplier": "Wrong Utility"},
                        {"account": "WRONG"}, {"meter": "WRONG"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                check_facts(Facts.model_validate(dict(FACTS, **changes)), 0)

    def test_water_is_not_mistaken_for_electricity_from_outage_notice(self):
        check_facts(Facts(service="water", unit="gallons", consumption="4200"), 2)
        with self.assertRaises(ValueError):
            check_facts(Facts(service="electricity", usage_kind="consumption", unit="kWh", consumption="4200"), 2)

    @patch("deployment.verify_bills.open_model")
    def test_provider_failure_is_safe_and_is_not_skipped(self, factory):
        @asynccontextmanager
        async def opened(*args, **kwargs):
            raise RuntimeError("private-marker")
            yield
        factory.side_effect = opened
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(["--provider", "openai"], environment={"OPENAI_API_KEY": "secret-marker"})
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(report["providers"][0]["status"], "failed")
        self.assertNotIn("private-marker", output.getvalue() + errors.getvalue())
        self.assertNotIn("secret-marker", output.getvalue() + errors.getvalue())

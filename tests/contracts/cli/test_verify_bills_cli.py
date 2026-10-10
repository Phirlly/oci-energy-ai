from contextlib import asynccontextmanager, redirect_stdout, redirect_stderr
import io
import json
import unittest
from unittest.mock import patch

from deployment.verify_bills import main, check_facts
from energy_ai.bills.schema import Facts
from tests.fixtures.bills import FACTS
from tests.fixtures.agent_responses import ScriptedModel, message
from tests.fixtures.bills import proposal


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

    def test_mismatch_diagnostics_keep_comparisons_independent_and_values_private(self):
        variants = [(dict(account="private-marker", current_total="987.65"), ["account", "current_total"]),
                    (dict(charges=[]), ["charge_difference"]),
                    (dict(charges=[row for row in FACTS["charges"] if row["role"] != "included"]), ["included_fee"])]
        for changes, fields in variants:
            with self.subTest(fields=fields), self.assertRaises(ValueError) as caught:
                check_facts(Facts.model_validate(dict(FACTS, **changes)), 0)
            self.assertEqual(caught.exception.fields, fields)
            self.assertNotIn("private-marker", str(caught.exception))

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

    @patch("deployment.verify_bills.open_model")
    def test_supplier_mismatch_reports_only_boolean_shape_and_still_fails(self, factory):
        from energy_ai.bills.examples import EXAMPLES
        for supplier, absent, normalized, contains in (
            (None, True, False, False),
            (" JUNIPER   power ", False, True, True),
            ("private-marker Juniper Power", False, False, True),
            ("private-marker", False, False, False),
        ):
            data = proposal(text=EXAMPLES[0])
            if supplier is None:
                data["supplier"] = None
            else:
                data["supplier"]["value"] = supplier
            @asynccontextmanager
            async def opened(*args, **kwargs):
                yield ScriptedModel([[message(data)]])
            factory.side_effect = opened
            output = io.StringIO()
            with self.subTest(supplier=supplier), redirect_stdout(output):
                code = main(["--provider", "openai"], environment={"OPENAI_API_KEY": "key-marker"})
            report = json.loads(output.getvalue())["providers"][0]
            self.assertEqual(code, 1)
            self.assertEqual(report["stage"], "expected_facts")
            self.assertEqual(report["diagnostics"], dict(fields=["supplier"], supplier_absent=absent,
                             supplier_normalized_match=normalized, supplier_contains_expected=contains))
            self.assertNotIn("marker", output.getvalue())
            self.assertNotIn("Juniper", output.getvalue())

    @patch("deployment.verify_bills.open_model")
    def test_report_excludes_arbitrary_evidence_keys_and_quotes(self, factory):
        data = proposal()
        data["account"]["evidence"]["private-marker"] = "secret-marker"
        @asynccontextmanager
        async def opened(*args, **kwargs):
            yield ScriptedModel([[message(data)], [message(data)]])
        factory.side_effect = opened
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--provider", "openai"], environment={"OPENAI_API_KEY": "key-marker"})
        report = json.loads(output.getvalue())["providers"][0]
        self.assertEqual(code, 1)
        self.assertEqual(report["stage"], "extraction_schema")
        self.assertIsNone(report["diagnostics"])
        self.assertNotIn("marker", output.getvalue())

    @patch("deployment.verify_bills.open_model")
    def test_expected_fact_report_does_not_publish_model_values(self, factory):
        # The original source quote may match while the extracted meaning is wrong.
        from energy_ai.bills.examples import EXAMPLES
        data = proposal(text=EXAMPLES[0])
        data["account"]["value"] = "private-marker"
        @asynccontextmanager
        async def opened(*args, **kwargs):
            yield ScriptedModel([[message(data)]])
        factory.side_effect = opened
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--provider", "openai"], environment={"OPENAI_API_KEY": "key-marker"})
        report = json.loads(output.getvalue())["providers"][0]
        self.assertEqual(code, 1)
        self.assertEqual(report["stage"], "expected_facts")
        self.assertEqual(report["diagnostics"], {"fields": ["account"]})
        self.assertNotIn("marker", output.getvalue())

import unittest

from energy_ai.bills.proposal import BillProposal
from energy_ai.bills.schema import Candidate
from tests.fixtures.bills import TEXT, candidate, proposal


class SourcedProposalTests(unittest.TestCase):
    def test_paired_values_preserve_domain_facts_and_locally_generated_evidence_keys(self):
        actual = BillProposal.model_validate(proposal()).to_candidate().verify([TEXT])
        expected = Candidate.model_validate(candidate()).verify([TEXT])
        self.assertEqual(actual, expected)
        self.assertEqual(actual.evidence["charges.3"].offset, 0)

    def test_nulls_remain_absent_without_invented_facts_or_evidence(self):
        data = {name: [] if name == "charges" else None for name in proposal()}
        result = BillProposal.model_validate(data).to_candidate().verify([TEXT])
        self.assertIsNone(result.facts.consumption)
        self.assertEqual(result.facts.service, "unknown")
        self.assertEqual(result.facts.usage_kind, "unknown")
        self.assertEqual(result.evidence, {})
        self.assertEqual(set(BillProposal.model_json_schema()["required"]), set(data))

    def test_each_nonnull_value_requires_its_evidence_and_all_fields_are_required(self):
        for change in ("missing_field", "missing_evidence", "null_evidence", "extra_evidence",
                       "unknown_field", "missing_charge_evidence", "missing_value"):
            data = proposal()
            if change == "missing_field":
                del data["unit"]
            elif change == "missing_evidence":
                del data["unit"]["evidence"]
            elif change == "null_evidence":
                data["unit"]["evidence"] = None
            elif change == "extra_evidence":
                data["unit"]["evidence"]["other"] = "kWh"
            elif change == "unknown_field":
                data["other"] = data["unit"]
            elif change == "missing_charge_evidence":
                del data["charges"][0]["evidence"]
            else:
                del data["unit"]["value"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                BillProposal.model_validate(data)

    def test_typed_pairs_retain_numeric_classification_and_calendar_constraints(self):
        variants = [("days", True), ("days", "29"), ("days", 367), ("days", 0),
                    ("consumption", "-1"), ("consumption", "NaN"),
                    ("consumption", "1000000001"), ("current_total", "1.00001"),
                    ("current_total", "Infinity"), ("currency", "usd"),
                    ("service", "unknown"), ("usage_kind", "unknown"),
                    ("period_start", "2024-02-30"), ("period_start", "2024-02-01T00:00:00")]
        for field, value in variants:
            data = proposal()
            data[field]["value"] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                BillProposal.model_validate(data).to_candidate()

    def test_charge_role_count_and_amount_bounds_are_preserved(self):
        for change in ("role", "amount", "count"):
            data = proposal()
            if change == "count":
                data["charges"] *= 9
            else:
                data["charges"][0]["value"][change] = "total" if change == "role" else "1000000001"
            with self.subTest(change=change), self.assertRaises(ValueError):
                BillProposal.model_validate(data)

    def test_source_verification_remains_mandatory_after_conversion(self):
        for evidence in (dict(page=1, quote="invented"), dict(page=2, quote=TEXT)):
            data = proposal()
            data["consumption"]["evidence"] = evidence
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, "evidence"):
                BillProposal.model_validate(data).to_candidate().verify([TEXT])

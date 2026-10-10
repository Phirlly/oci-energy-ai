import unittest
from copy import deepcopy

from energy_ai.bills.review import BillReview, ReviewError
from energy_ai.bills.schema import Candidate, Facts
from tests.fixtures.bills import FACTS, TEXT, candidate


class EvidenceAndRevisionTests(unittest.TestCase):
    def test_proposal_requires_real_page_quote_for_every_fact_and_charge(self):
        for change in ("wrong_quote", "wrong_page", "missing"):
            data = candidate()
            if change == "wrong_quote":
                data["evidence"]["consumption"]["quote"] = "9999 kWh"
            elif change == "wrong_page":
                data["evidence"]["consumption"]["page"] = 2
            else:
                del data["evidence"]["consumption"]
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "evidence"):
                Candidate.model_validate(data).verify([TEXT])

    def test_approval_is_revision_specific_and_preserves_proposal(self):
        review = BillReview([TEXT])
        proposal = Candidate.model_validate(candidate())
        review.propose(proposal)
        self.assertEqual(review.revision, 1)
        review.approve(1)
        self.assertEqual(review.approved_facts(1).consumption, 580)
        edited = deepcopy(FACTS)
        edited["consumption"] = "600"
        review.edit(Facts.model_validate(edited), 1)
        self.assertEqual(review.proposal.facts.consumption, 580)
        self.assertEqual(review.revision, 2)
        self.assertIn("consumption", review.corrections)
        with self.assertRaisesRegex(ReviewError, "approve"):
            review.approved_facts(2)
        with self.assertRaisesRegex(ReviewError, "changed"):
            review.approve(1)
        review.approve(2)
        self.assertEqual(review.approved_facts(2).consumption, 600)

    def test_missing_values_remain_missing_and_invalid_values_rejected(self):
        self.assertIsNone(Facts().consumption)
        for patch in ({"consumption": "-1"}, {"days": 0}, {"consumption": "NaN"},
                      {"currency": "dollars"}, {"period_start": "yesterday"},
                      {"charges": [{"label": "Fee", "amount": "1", "role": "total"}]}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                Facts.model_validate(patch)

    def test_matching_quote_does_not_approve_semantics(self):
        data = candidate()
        data["facts"]["current_total"] = "131.50"
        review = BillReview([TEXT])
        review.propose(Candidate.model_validate(data))
        with self.assertRaisesRegex(ReviewError, "approve"):
            review.approved_facts(review.revision)

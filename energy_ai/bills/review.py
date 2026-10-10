"""Revision-specific approval, with proposal and correction provenance retained."""

from energy_ai.bills.schema import Candidate, Facts


class ReviewError(ValueError):
    pass


class BillReview:
    def __init__(self, pages):
        self.pages = list(pages)
        self.proposal: Candidate | None = None
        self.facts = Facts()
        self.revision = 0
        self.approved_revision = None
        self.corrections = []

    def check_revision(self, revision):
        if revision != self.revision:
            raise ReviewError("This bill changed. Refresh before saving or approving.")

    def propose(self, candidate):
        candidate.verify(self.pages)
        self.proposal = candidate.model_copy(deep=True)
        self.facts = candidate.facts.model_copy(deep=True)
        self.corrections = []
        self.revision += 1
        self.approved_revision = None

    def edit(self, facts, revision):
        self.check_revision(revision)
        before, after = self.facts.model_dump(), facts.model_dump()
        changed = {name for name in before if before[name] != after[name]}
        self.corrections = sorted(set(self.corrections) | changed)
        self.facts = facts.model_copy(deep=True)
        self.revision += 1
        self.approved_revision = None

    def approve(self, revision):
        self.check_revision(revision)
        self.approved_revision = revision

    def approved_facts(self, revision):
        self.check_revision(revision)
        if self.approved_revision != revision:
            raise ReviewError("Review and approve this revision before calculating insights.")
        return self.facts.model_copy(deep=True)

    def public(self):
        return dict(pages=self.pages, facts=self.facts.model_dump(mode="json"),
                    proposal=self.proposal.model_dump(mode="json") if self.proposal else None,
                    revision=self.revision, approved_revision=self.approved_revision,
                    corrections=self.corrections)

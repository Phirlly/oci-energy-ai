"""Model-facing proposal: every present value structurally carries its source."""

from typing import Generic, Literal, TypeVar

from pydantic import Field

from energy_ai.bills.schema import (
    Candidate, Charge, Currency, Days, Energy, Evidence, Facts, Money, SourceQuote, StrictModel, Text,
)

T = TypeVar("T")


class Sourced(StrictModel, Generic[T]):
    value: T
    evidence: SourceQuote


class BillProposal(StrictModel):
    supplier: Sourced[Text] | None = Field(description=(
        "Name of the issuing utility or organization as printed, excluding surrounding "
        "statement headings, labels or notices. The exact evidence quote may include "
        "that surrounding text; the value contains only the issuer name."
    ))
    account: Sourced[Text] | None
    meter: Sourced[Text] | None
    service: Sourced[Literal["electricity", "water", "gas", "mixed"]] | None
    usage_kind: Sourced[Literal["consumption", "net", "export"]] | None
    unit: Sourced[Text] | None
    period_start: Sourced[Text] | None
    period_end: Sourced[Text] | None
    days: Sourced[Days] | None
    currency: Sourced[Currency] | None
    consumption: Sourced[Energy] | None
    current_total: Sourced[Money] | None
    charges: list[Sourced[Charge]] = Field(max_length=40)

    def to_candidate(self):
        values, evidence = {}, {}
        for name in type(self).model_fields:
            if name == "charges":
                continue
            sourced = getattr(self, name)
            if sourced is not None:
                values[name] = sourced.value
                evidence[name] = Evidence(**sourced.evidence.model_dump())
        values["charges"] = [row.value for row in self.charges]
        evidence.update({f"charges.{index}": Evidence(**row.evidence.model_dump())
                         for index, row in enumerate(self.charges)})
        return Candidate(facts=Facts.model_validate(values), evidence=evidence)

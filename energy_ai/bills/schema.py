"""Bounded, provider-neutral bill facts; evidence is checked against original text."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Text = Annotated[str, Field(min_length=1, max_length=160)]
Money = Annotated[Decimal, Field(ge=-1000000000, le=1000000000, max_digits=15, decimal_places=4)]
Energy = Annotated[Decimal, Field(ge=0, le=1000000000, max_digits=15, decimal_places=4)]
Days = Annotated[int, Field(strict=True, ge=1, le=366)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, str_strip_whitespace=True)


class Charge(StrictModel):
    label: Text
    amount: Money
    role: Literal["additive", "included", "excluded"]


class Facts(StrictModel):
    supplier: Text | None = None
    account: Text | None = None
    meter: Text | None = None
    service: Literal["electricity", "water", "gas", "mixed", "unknown"] = "unknown"
    usage_kind: Literal["consumption", "net", "export", "unknown"] = "unknown"
    unit: Text | None = None
    period_start: date | None = None
    period_end: date | None = None
    days: Days | None = None
    currency: Currency | None = None
    consumption: Energy | None = None
    current_total: Money | None = None
    charges: list[Charge] = Field(default_factory=list, max_length=40)

    @field_validator("period_start", "period_end", mode="before")
    @classmethod
    def calendar_dates_only(cls, value):
        if value is not None and not isinstance(value, date):
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError("Use an ISO calendar date.")
        return value


class SourceQuote(StrictModel):
    page: int = Field(strict=True, ge=1, le=20)
    quote: str = Field(min_length=1, max_length=600)


class Evidence(SourceQuote):
    offset: int | None = Field(default=None, ge=0)


class EvidenceError(ValueError):
    """Only application-owned field names and counts may cross this boundary."""

    def __init__(self, category, fields, unexpected_keys=0):
        self.category, self.fields, self.unexpected_keys = category, fields, unexpected_keys
        super().__init__("Bill evidence verification failed.")


class Candidate(StrictModel):
    facts: Facts
    evidence: dict[str, Evidence] = Field(max_length=55)

    def verify(self, pages):
        required = {name for name, value in self.facts.model_dump().items()
                    if name != "charges" and value is not None and value != "unknown"}
        required.update(f"charges.{index}" for index in range(len(self.facts.charges)))
        if set(self.evidence) != required:
            raise EvidenceError("keys", sorted(required - set(self.evidence)),
                                len(set(self.evidence) - required))
        unmatched = [name for name, item in self.evidence.items()
                     if item.page > len(pages) or item.quote not in pages[item.page - 1]]
        if unmatched:
            raise EvidenceError("quote", sorted(unmatched))
        for item in self.evidence.values():
            item.offset = pages[item.page - 1].index(item.quote)
        return self

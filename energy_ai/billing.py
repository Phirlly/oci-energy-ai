"""A deliberately explicit, illustrative flat monthly electricity tariff."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import json
from pathlib import Path
from typing import Sequence

from .intervals import Interval, calendar_month


@dataclass(frozen=True)
class Tariff:
    energy_usd_per_kwh: Decimal
    demand_usd_per_kw: Decimal
    fixed_usd_per_month: Decimal

    def __post_init__(self):
        for value in (self.energy_usd_per_kwh, self.demand_usd_per_kw, self.fixed_usd_per_month):
            if not isinstance(value, Decimal) or not value.is_finite() or not 0 <= value <= Decimal("1e9"):
                raise ValueError("Tariff rates must be finite Decimal values between 0 and 1e9.")
            if len(value.as_tuple().digits) > 24 or value.as_tuple().exponent < -24:
                raise ValueError("Tariff rates support up to 24 decimal digits.")


@dataclass(frozen=True)
class Bill:
    period_start: str
    period_end_exclusive: str
    energy_kwh: Decimal
    peak_kw: Decimal
    energy_charge_usd: Decimal
    demand_charge_usd: Decimal
    fixed_charge_usd: Decimal
    total_usd: Decimal


def load_tariff(path: Path) -> Tariff:
    if path.stat().st_size > 50_000:
        raise ValueError("Tariff JSON exceeds the 50 KB limit.")
    data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    fields = ("energy_usd_per_kwh", "demand_usd_per_kw", "fixed_usd_per_month")
    if not isinstance(data, dict) or set(data) != {*fields, "currency", "kind", "notice"}:
        raise ValueError("Tariff JSON must contain the three rates, currency, kind and notice.")
    if data["currency"] != "USD" or data["kind"] != "illustrative_flat_monthly":
        raise ValueError("Only USD illustrative_flat_monthly tariffs are supported.")
    if not isinstance(data["notice"], str) or not data["notice"].strip():
        raise ValueError("Tariff notice must explain the illustrative assumptions.")
    try:
        return Tariff(*(Decimal(str(data[field])) for field in fields))
    except InvalidOperation as exc:
        raise ValueError("Tariff rates must be numeric.") from exc


def calculate_bill(readings: Sequence[Interval], tariff: Tariff) -> Bill:
    start, end = calendar_month(readings)
    # Enough precision for validated input bounds, sums and products.
    with localcontext() as context:
        context.prec = 64
        energy = sum((row.energy_kwh for row in readings), Decimal(0))
        peak = max(row.energy_kwh for row in readings) * 4
        def cents(value):
            return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        energy_charge = cents(energy * tariff.energy_usd_per_kwh)
        demand_charge = cents(peak * tariff.demand_usd_per_kw)
        fixed_charge = cents(tariff.fixed_usd_per_month)
        return Bill(start.date().isoformat(), end.date().isoformat(), energy, peak,
                    energy_charge, demand_charge, fixed_charge,
                    energy_charge + demand_charge + fixed_charge)

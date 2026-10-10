"""Decimal arithmetic on approved facts; no tariff or interval inference."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP


def rounded(value, places="0.01"):
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def exact(value):
    return format(value, ".2f") if value == value.quantize(Decimal("0.01")) else format(value, "f")


def coverage(facts):
    if not facts.period_start or not facts.period_end or not facts.days:
        return None
    difference = (facts.period_end - facts.period_start).days
    if difference < 0 or facts.days not in (difference, difference + 1):
        return None
    try:
        return facts.period_start, facts.period_start + timedelta(days=facts.days)
    except OverflowError:
        return None


def _bill(facts):
    warnings = []
    electricity = facts.service == "electricity"
    usage = electricity and facts.usage_kind == "consumption" and facts.unit == "kWh"
    period = coverage(facts)
    if not electricity:
        warnings.append("Select an electricity-only service before electricity analysis.")
    if not usage:
        warnings.append("Confirm consumption in kWh; net, exported or unknown usage is unsupported.")
    if period is None:
        warnings.append("Confirm dates and billed days; days must match exclusive or inclusive dates.")
    if facts.consumption is None:
        warnings.append("Consumption is missing.")
    if facts.current_total is None or facts.currency is None:
        warnings.append("Current electricity charges or currency are missing.")
    daily = facts.consumption / facts.days if usage and period and facts.consumption is not None else None
    average = (facts.current_total / facts.consumption
               if usage and facts.consumption and facts.current_total is not None and facts.currency else None)
    additive = [charge.amount for charge in facts.charges if charge.role == "additive"]
    difference = (facts.current_total - sum(additive, Decimal(0))
                  if electricity and additive and facts.current_total is not None else None)
    if difference is not None and difference != 0:
        warnings.append("Additive charges do not reconcile with the current electricity total.")
    return dict(daily_kwh=rounded(daily) if daily is not None else None,
                average_cost_per_kwh=rounded(average, "0.0001") if average is not None else None,
                charge_difference=exact(difference) if difference is not None else None,
                warnings=warnings)


def summarize(facts):
    result = dict(label="Supplied-period insights", bills=[_bill(f) for f in facts],
                  aggregate=None, comparisons=[], warnings=[])
    if not facts:
        result["warnings"].append("Approve at least one bill.")
        return result
    ready = all(coverage(f) and f.service == "electricity" and f.usage_kind == "consumption"
                and f.unit == "kWh" and f.consumption is not None for f in facts)
    if not ready:
        result["warnings"].append("Combined totals require complete, compatible electricity facts.")
        return result
    if len(facts) > 1:
        first = facts[0]
        # Full identity is compared only inside this session and never reported in insights.
        identity = lambda f: (f.supplier, f.account, f.meter)
        if not first.supplier or not first.account or not first.meter or any(identity(f) != identity(first) for f in facts):
            result["warnings"].append("Confirm matching supplier, full account, meter and currency before combining.")
            return result
    currencies = {f.currency for f in facts if f.currency}
    if len(currencies) > 1:
        result["warnings"].append("Different currencies cannot be combined.")
        return result
    ordered = sorted(facts, key=lambda f: f.period_start)
    gap = 0
    for earlier, later in zip(ordered, ordered[1:]):
        distance = (coverage(later)[0] - coverage(earlier)[1]).days
        if distance < 0:
            result["warnings"].append("Duplicate or overlapping periods cannot be combined.")
            return result
        gap += distance
    days = sum(f.days for f in facts)
    energy = sum((f.consumption for f in facts), Decimal(0))
    cost_ready = all(f.current_total is not None and f.currency for f in facts)
    total = sum((f.current_total for f in facts), Decimal(0)) if cost_ready else None
    if not cost_ready:
        result["warnings"].append("Combined costs are unavailable until each bill has current charges and currency.")
    result["aggregate"] = dict(days=days, total_kwh=exact(energy), current_total=exact(total) if total is not None else None,
                               currency=next(iter(currencies), None), daily_kwh=rounded(energy / days),
                               average_cost_per_kwh=rounded(total / energy, "0.0001") if energy and total is not None else None,
                               gap_days=gap, periods=len(facts))
    for earlier, later in zip(ordered, ordered[1:]):
        previous = earlier.consumption / earlier.days
        current = later.consumption / later.days
        result["comparisons"].append(dict(
            earlier_start=earlier.period_start.isoformat(), later_start=later.period_start.isoformat(),
            daily_usage_change_percent=rounded((current / previous - 1) * 100) if previous else None))
    if gap:
        result["warnings"].append(f"{gap} days are not covered between supplied periods.")
    return result

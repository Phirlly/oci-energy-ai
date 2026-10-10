"""Presentation of the prepared source month through existing calculation tools."""

from datetime import timedelta
from functools import lru_cache
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from energy_ai.battery import Battery, simulate_battery
from energy_ai.billing import load_tariff
from energy_ai.intervals import load_intervals
from energy_ai.reporting import baseline_report, scenario_report

SAMPLE = Path(__file__).resolve().parents[2] / 'examples' / 'monthly-office'


class Controls(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    power_kw: float = Field(default=25, ge=0, le=500)
    capacity_kwh: float = Field(default=100, ge=0, le=2000)
    efficiency: float = Field(default=.9, gt=0, le=1)
    target_kw: float = Field(default=80, gt=0, le=500)


@lru_cache(maxsize=1)
def source():
    return tuple(load_intervals(SAMPLE / 'intervals.csv')), load_tariff(SAMPLE / 'tariff.json')


def office_profile():
    readings, tariff = source()
    metadata = json.loads((SAMPLE / 'metadata.json').read_text())
    peak = max(readings, key=lambda row: row.energy_kwh)
    peak_start = peak.end - timedelta(minutes=15)
    daily, peak_day = {}, []
    for row in readings:
        start = row.end - timedelta(minutes=15)
        day, kw = start.date().isoformat(), float(row.energy_kwh * 4)
        daily[day] = max(daily.get(day, 0), kw)
        if start.date() == peak_start.date():
            peak_day.append(dict(start=start.isoformat(), load_kw=kw))
    return dict(**baseline_report(readings, tariff), name=metadata['name'],
                notice=metadata['notice'], source=metadata['source'],
                source_url=metadata['publication_url'], license=metadata['license'],
                clock=metadata['clock'], peak_interval_start=peak_start.isoformat(),
                peak_interval_end=peak.end.isoformat(), peak_day=peak_day,
                daily_peaks=[dict(day=day, peak_kw=kw) for day, kw in daily.items()],
                tariff=dict(energy_usd_per_kwh=str(tariff.energy_usd_per_kwh),
                            demand_usd_per_kw=str(tariff.demand_usd_per_kw),
                            fixed_usd_per_month=str(tariff.fixed_usd_per_month)))


def office_scenario(controls: Controls):
    readings, tariff = source()
    battery = Battery(controls.power_kw, controls.capacity_kwh, controls.efficiency)
    report = scenario_report(readings, tariff, battery, controls.target_kw)
    steps = simulate_battery(readings, battery, controls.target_kw).steps
    peak = max(readings, key=lambda row: row.energy_kwh)
    day = (peak.end - timedelta(minutes=15)).date()
    report['peak_day'] = [dict(start=(row.end - timedelta(minutes=15)).isoformat(),
                              load_kw=step.load_kw, grid_kw=step.grid_kw, soc_kwh=step.soc_kwh)
                          for row, step in zip(readings, steps)
                          if (row.end - timedelta(minutes=15)).date() == day]
    report['controls'] = controls.model_dump()
    report['data_notice'] = 'Public ComStock modeled office profile; invented flat USD tariff.'
    return report


def inspection_report():
    profile = office_profile()
    return {key: value for key, value in profile.items() if key not in {'daily_peaks', 'peak_day'}}

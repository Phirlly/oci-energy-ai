from datetime import datetime, timedelta
from decimal import Decimal

from energy_ai.intervals import Interval


def june(energies=None):
    values = energies if energies is not None else [Decimal("1")] * 2880
    start = datetime(2018, 6, 1)
    return tuple(Interval(start + timedelta(minutes=15 * (i + 1)), Decimal(value))
                 for i, value in enumerate(values))

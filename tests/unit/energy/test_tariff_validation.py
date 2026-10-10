from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from energy_ai.billing import Tariff, load_tariff


class TariffValidationTests(unittest.TestCase):
    def test_tariff_rejects_negative_or_nonfinite(self):
        for value in ("-1", "NaN", "Infinity", "1e999"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Tariff(Decimal(value), Decimal("0"), Decimal("0"))

    def test_tariff_rejects_unsupported_currency_kind_notice_and_bad_value(self):
        original = json.loads(Path("examples/monthly-office/tariff.json").read_text())
        for changes in ({"currency": "GBP"}, {"kind": "time_of_use"}, {"notice": ""},
                        {"energy_usd_per_kwh": "NaN"}, {"energy_usd_per_kwh": True}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "tariff.json"
                path.write_text(json.dumps({**original, **changes}))
                with self.assertRaises(ValueError):
                    load_tariff(path)

    def test_tariff_rejects_missing_rate(self):
        original = json.loads(Path("examples/monthly-office/tariff.json").read_text())
        del original["energy_usd_per_kwh"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tariff.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_tariff(path)

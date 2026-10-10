from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class SamplePreparationCommandTests(unittest.TestCase):
    def test_unverified_source_is_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "wrong.parquet"
            source.write_bytes(b"not the verified public source")
            output = root / "output"
            process = subprocess.run([sys.executable, "-m", "tools.prepare_sample", str(source),
                                      "--output", str(output)], capture_output=True, text=True, timeout=15)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("SHA256", process.stderr)
            self.assertFalse(output.exists())

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            marker = root / "intervals.csv"
            marker.write_text("preserve me", encoding="utf-8")
            process = subprocess.run([sys.executable, "-m", "tools.prepare_sample", "unused.parquet",
                                      "--output", str(root)], capture_output=True, text=True, timeout=15)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("exists", process.stderr)
            self.assertEqual(marker.read_text(), "preserve me")


if __name__ == "__main__":
    unittest.main()

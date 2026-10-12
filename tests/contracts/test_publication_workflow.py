from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PublicationWorkflowTests(unittest.TestCase):
    def test_download_guard_rejects_missing_multiple_or_mixed_ids(self):
        workflow = (ROOT/'.github/workflows/publish-console.yml').read_text()
        guard = re.search(r"run: '(\[\[ .*? \]\])'", workflow).group(1)
        for value, expected in [('', 1), ('12,13', 1), ('123abc', 1), ('0', 1), ('123', 0)]:
            with self.subTest(value=value):
                result = subprocess.run(['bash', '-c', guard], env={'RUNTIME_ARTIFACT_ID': value},
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, expected)

    def test_publication_consumes_checked_id_without_build_or_runtime_credentials(self):
        workflow = (ROOT/'.github/workflows/publish-console.yml').read_text()
        self.assertIn('uses: ./.github/workflows/validate.yml', workflow)
        self.assertIn('export_runtime: true', workflow)
        self.assertIn('needs: validate', workflow)
        self.assertIn('artifact-ids: ${{ needs.validate.outputs.artifact_id }}', workflow)
        self.assertIn('digest-mismatch: error', workflow)
        self.assertIn('3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c', workflow)
        self.assertNotRegex(workflow, r'OPENAI_API_KEY|ANTHROPIC_API_KEY|DEMO_PASSWORD|docker build|secrets: inherit')

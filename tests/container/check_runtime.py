"""Opt-in checks inside the actual restricted image; no network or credentials."""

import asyncio
import errno
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, '/app')
sys.path.insert(0, '/checks')


class ImageContentsTests(unittest.TestCase):
    def test_release_platform_and_public_only_application_contents(self):
        self.assertEqual(sys.platform, 'linux')
        self.assertEqual(platform.machine(), EXPECTED_MACHINE)
        self.assertEqual(sys.version_info[:2], (3, 12))
        self.assertEqual(Path('/app/release.txt').read_text(), EXPECTED_RELEASE + '\n')
        self.assertEqual({p.name for p in Path('/app').iterdir()},
                         {'.venv', 'energy_ai', 'frontend', 'examples', 'release.txt'})
        self.assertEqual({p.name for p in Path('/app/examples/monthly-office').iterdir()},
                         {'README.md', 'intervals.csv', 'tariff.json', 'metadata.json', 'expected-bill.json'})
        self.assertEqual({p.name for p in Path('/app/frontend').iterdir()}, {'dist'})
        for path in Path('/app/energy_ai').rglob('*'):
            if path.is_file():
                self.assertEqual(path.suffix, '.py', str(path))
        for executable in ('node', 'npm', 'uv', 'gcc', 'pip', 'pip3'):
            self.assertIsNone(shutil.which(executable), executable)
        self.assertFalse(Path('/usr/local/lib/python3.12/ensurepip').exists())
        self.assertFalse(Path('/etc/energy-ai/runtime.json').exists())

    def test_nonroot_readonly_process_and_writable_data(self):
        self.assertEqual((os.getuid(), os.getgid()), (10001, 10001))
        status = Path('/proc/self/status').read_text()
        self.assertRegex(status, r'CapEff:\s+0+\n')
        self.assertRegex(status, r'NoNewPrivs:\s+1\n')
        root = next(row.split() for row in Path('/proc/mounts').read_text().splitlines()
                    if row.split()[1] == '/')
        self.assertIn('ro', root[3].split(','))
        with self.assertRaises(OSError) as error:
            Path('/app/release.txt').write_text('unexpected')
        self.assertIn(error.exception.errno, (errno.EROFS, errno.EACCES))
        with tempfile.TemporaryDirectory(dir='/data') as directory:
            path = Path(directory) / 'write-check'
            path.write_text('public fixture')
            self.assertEqual(path.read_text(), 'public fixture')

    def test_entrypoint_rejects_missing_configuration_without_credentials_or_network(self):
        result = subprocess.run([sys.executable, '-B', '-m', 'energy_ai.web.serve'],
                                cwd='/app', env={}, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr.strip(),
                         'Hosted startup or serving failed. Check runtime configuration, OCI identity and Vault access.')


class PackagedApplicationTests(unittest.TestCase):
    def test_browser_login_calculations_and_linux_pdf_worker(self):
        from fastapi.testclient import TestClient
        from energy_ai.web.app import create_app
        from energy_ai.office.sample import Controls
        from energy_ai.bills.pdf import extract_pdf, PdfError

        origin, backend = 'https://demo.example', '10.40.1.8:8080'
        password = 'admin'
        app = create_app(access_code=password, origin=origin, backend_host=backend,
                         release=EXPECTED_RELEASE)
        with TestClient(app, base_url=origin, headers={'host': backend}) as client:
            self.assertEqual(client.get('/healthz').json(),
                             dict(status='ready', release=EXPECTED_RELEASE, schema=1))
            html = client.get('/')
            self.assertEqual(html.status_code, 200)
            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html.text)
            self.assertGreaterEqual(len(assets), 2)
            for asset in assets:
                response = client.get(asset)
                self.assertEqual(response.status_code, 200)
                self.assertGreater(len(response.content), 100)
            self.assertEqual(client.get('/api/office').status_code, 401)
            headers = {'origin': origin, 'x-energy-action': '1'}
            login = client.post('/api/session', json={'code': password}, headers=headers)
            self.assertEqual(login.status_code, 200)
            self.assertIn('; secure', login.headers['set-cookie'].lower())
            self.assertEqual(client.get('/api/office').json()['bill']['total_usd'], '6710.80')
            scenario = client.post('/api/office/scenario', json=Controls().model_dump(), headers=headers)
            self.assertEqual(scenario.json()['scenario_bill']['total_usd'], '6344.11')
            self.assertEqual(scenario.json()['modeled_cost_difference_usd'], '366.69')
            pdf = client.get('/api/office/bill.pdf')
            self.assertEqual(pdf.headers['content-type'], 'application/pdf')
            pages = asyncio.run(extract_pdf(pdf.content))
            self.assertEqual(len(pages), 1)
            self.assertIn('TOTAL CURRENT CHARGES: USD 6710.80', pages[0])
            with self.assertRaises(PdfError):
                asyncio.run(extract_pdf(b'%PDF-1.7\nmalformed fixture'))

    def test_sqlite_reopen_preserves_completed_history_and_interrupts_active_run(self):
        from energy_ai.office.runs import RunRepository

        with tempfile.TemporaryDirectory(dir='/data') as directory:
            path = Path(directory) / 'office.sqlite3'
            repository = RunRepository(path)
            try:
                complete = repository.create('complete', {'provider': 'oci'})
                repository.finish(complete['id'], 'complete', result={'total_usd': '6710.80'})
                active = repository.create('active', {'provider': 'oci'})
            finally:
                repository.close()
            reopened = RunRepository(path)
            try:
                self.assertEqual(reopened.get(complete['id'])['status'], 'complete')
                self.assertEqual(reopened.get(complete['id'])['result'], {'total_usd': '6710.80'})
                self.assertEqual(reopened.get(active['id'])['status'], 'interrupted')
                self.assertEqual(reopened.db.execute('PRAGMA user_version').fetchone()[0], 1)
            finally:
                reopened.close()


if __name__ == '__main__':
    EXPECTED_RELEASE, EXPECTED_MACHINE = sys.argv[1:]
    if not re.fullmatch('[a-f0-9]{40}', EXPECTED_RELEASE) or EXPECTED_MACHINE not in {'aarch64', 'x86_64'}:
        raise SystemExit('Expected a commit SHA and native machine architecture.')
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    suite.addTests(unittest.defaultTestLoader.loadTestsFromNames([
        'tests.contracts.agents.test_instance_auth',
        'tests.contracts.agents.test_provider_requests',
        'tests.contracts.agents.test_anthropic_messages',
        'tests.contracts.web.test_hosted_runtime',
    ]))
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())

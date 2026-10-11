import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  workers: 1,
  retries: 0,
  use: { baseURL: 'http://127.0.0.1:8765', browserName: 'chromium', trace: 'off' },
  webServer: [{
    command: '.venv/bin/python -m energy_ai.web --port 8765',
    cwd: '..',
    url: 'http://127.0.0.1:8765',
    reuseExistingServer: false,
    env: { DEMO_PASSWORD: 'admin', OPENAI_API_KEY: '',
           ANTHROPIC_API_KEY: '', OCI_PROFILE: '' }
  }, {
    command: '.venv/bin/python -m tests.fixtures.office_server',
    cwd: '..', url: 'http://127.0.0.1:8767', reuseExistingServer: false,
    env: { DEMO_PASSWORD: 'admin' }
  }, {
    command: '.venv/bin/python -m tests.fixtures.setup_server',
    cwd: '..', url: 'http://127.0.0.1:8768', reuseExistingServer: false
  }, {
    command: '.venv/bin/python -m tests.fixtures.web_server',
    cwd: '..', url: 'http://127.0.0.1:8766', reuseExistingServer: false,
    env: { DEMO_PASSWORD: 'admin' }
  }]
});

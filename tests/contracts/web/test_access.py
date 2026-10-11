import unittest
from fastapi.testclient import TestClient

from energy_ai.web.app import create_app

ORIGIN = "http://127.0.0.1:8765"
HEADERS = {"origin": ORIGIN, "x-energy-action": "1"}
CODE = "test-launch-code"


class SessionAccessTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.app = create_app(access_code=CODE, origin=ORIGIN, clock=lambda: self.now[0])
        self.client = self.enterContext(TestClient(self.app, base_url=ORIGIN))

    def login(self):
        return self.client.post("/api/session", json={"code": CODE}, headers=HEADERS)

    def test_requires_code_and_same_origin_mutation_headers(self):
        self.assertEqual(self.client.get("/api/documents").status_code, 401)
        self.assertEqual(self.client.post("/api/session", json={"code": CODE}).status_code, 403)
        self.assertEqual(self.client.post("/api/session", json={"code": "wrong"}, headers=HEADERS).status_code, 401)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertNotIn(CODE, cookie)
        self.assertEqual(self.client.get("/api/documents", headers={"host": "attacker.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/example", headers=dict(HEADERS, origin="http://evil.example")).status_code, 403)

    def test_logout_and_fixed_expiry_remove_documents_and_session(self):
        self.login()
        self.client.post("/api/example", headers=HEADERS)
        self.now[0] += 1801
        self.assertEqual(self.client.get("/api/documents").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/documents").json(), [])
        self.client.delete("/api/session", headers=HEADERS)
        self.assertEqual(self.client.get("/api/documents").status_code, 401)

    def test_provider_status_and_private_response_headers(self):
        self.login()
        response = self.client.get("/api/session")
        self.assertEqual(response.json()["providers"], [])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])
        self.assertIn("nosniff", response.headers["x-content-type-options"])

    def test_login_rate_and_session_count_are_bounded(self):
        for _ in range(10):
            self.client.post("/api/session", json={"code": "wrong"}, headers=HEADERS)
        self.assertEqual(self.login().status_code, 429)

    def test_error_does_not_echo_submitted_private_data(self):
        self.login()
        response = self.client.post("/api/session", content='{"code": "PRIVATE", "extra": 2}', headers=HEADERS)
        self.assertNotIn("PRIVATE", response.text)


class HostedAccessTests(unittest.TestCase):
    def test_https_login_secure_cookie_health_and_forwarded_header_boundaries(self):
        origin, backend, release = 'https://demo.example', '10.40.1.8:8080', 'a' * 40
        password = 'public-fixture-password-123'
        app = create_app(access_code=password, origin=origin, backend_host=backend, release=release)
        with TestClient(app, base_url=origin, headers={'host': backend}) as client:
            health = client.get('/healthz')
            self.assertEqual(health.json(), {'status': 'ready', 'release': release, 'schema': 1})
            headers = {'origin': origin, 'x-energy-action': '1'}
            response = client.post('/api/session', json={'code': password}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertIn('; secure', response.headers['set-cookie'].lower())
            self.assertEqual(response.headers['strict-transport-security'], 'max-age=31536000')
            self.assertEqual(client.get('/api/session').status_code, 200)
            self.assertEqual(client.get('/healthz', headers={'host': 'wrong.example',
                'x-forwarded-host': backend, 'x-forwarded-proto': 'https'}).status_code, 403)
            self.assertEqual(client.post('/api/session', json={'code': password}, headers={
                **headers, 'origin': 'https://wrong.example', 'x-forwarded-host': 'demo.example'}).status_code, 403)
            response = client.delete('/api/session', headers=headers)
            self.assertIn('; secure', response.headers['set-cookie'].lower())
            self.assertEqual(client.get('/api/session').status_code, 401)

    def test_public_mode_rejects_unsafe_or_incomplete_configuration(self):
        valid = dict(access_code='public-fixture-password-123', origin='https://demo.example',
                     backend_host='10.40.1.8:8080', release='a' * 40)
        for changed in ({'origin': 'http://demo.example'}, {'origin': 'https://demo.example/'},
                        {'origin': 'https://user@demo.example'}, {'origin': 'https://demo.example:443'},
                        {'backend_host': '203.0.113.1:8080'}, {'backend_host': '10.40.1.8:80'},
                        {'release': '../private'}, {'access_code': CODE}, {'release': None}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                create_app(**(valid | changed))

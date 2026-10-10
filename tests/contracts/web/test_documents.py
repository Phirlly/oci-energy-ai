import asyncio
from copy import deepcopy
import threading
import time
import unittest

from fastapi.testclient import TestClient
from energy_ai.bills.extraction import ExtractionResult
from energy_ai.bills.schema import Candidate
from energy_ai.web.app import create_app
from tests.contracts.web.test_access import ORIGIN, HEADERS, CODE
from tests.fixtures.bills import FACTS, TEXT, candidate, pdf_bytes


class DocumentJourneyTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(access_code=CODE, origin=ORIGIN)
        self.client = self.enterContext(TestClient(self.app, base_url=ORIGIN))
        self.client.post("/api/session", json={"code": CODE}, headers=HEADERS)

    def upload(self, content=None):
        return self.client.post("/api/documents", content=pdf_bytes() if content is None else content,
                                headers=dict(HEADERS, **{"content-type": "application/pdf"}))

    def test_real_pdf_review_approval_and_edit_invalidates_insights(self):
        uploaded = self.upload()
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        doc = uploaded.json()
        path = "/api/documents/" + doc["id"]
        self.assertIn("580 kWh", doc["pages"][0])
        self.assertEqual(self.client.post("/api/insights", json={"revisions": {doc["id"]: 0}}, headers=HEADERS).status_code, 409)
        edited = self.client.put(path, json={"revision": 0, "facts": FACTS}, headers=HEADERS)
        self.assertEqual(edited.json()["revision"], 1)
        self.assertEqual(self.client.post(path + "/approve", json={"revision": 0}, headers=HEADERS).status_code, 409)
        self.client.post(path + "/approve", json={"revision": 1}, headers=HEADERS)
        result = self.client.post("/api/insights", json={"revisions": {doc["id"]: 1}}, headers=HEADERS)
        self.assertEqual(result.json()["aggregate"]["daily_kwh"], "20.00")
        self.client.put(path, json={"revision": 1, "facts": dict(FACTS, consumption="600")}, headers=HEADERS)
        self.assertEqual(self.client.post("/api/insights", json={"revisions": {doc["id"]: 1}}, headers=HEADERS).status_code, 409)

    def test_duplicate_invalid_and_oversize_uploads_are_rejected(self):
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.upload(b"not pdf").status_code, 422)
        self.assertEqual(self.upload(b"%PDF-" + b"x" * (4 * 1024 * 1024)).status_code, 413)

    def test_other_session_cannot_read_edit_delete_or_analyze_document(self):
        doc = self.client.post("/api/example", headers=HEADERS).json()
        stranger = TestClient(self.app, base_url=ORIGIN)
        try:
            stranger.post("/api/session", json={"code": CODE}, headers=HEADERS)
            path = "/api/documents/" + doc["id"]
            self.assertEqual(stranger.get(path).status_code, 404)
            self.assertEqual(stranger.delete(path, headers=HEADERS).status_code, 404)
            self.assertEqual(stranger.put(path, json={"revision": 0, "facts": FACTS}, headers=HEADERS).status_code, 404)
            self.assertEqual(stranger.post("/api/insights", json={"revisions": {doc["id"]: 0}}, headers=HEADERS).status_code, 404)
        finally:
            stranger.close()
        self.assertEqual(self.client.delete("/api/documents/" + doc["id"], headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.get("/api/documents").json(), [])

    def test_extraction_requires_explicit_consent_and_configured_provider(self):
        doc = self.client.post("/api/example", headers=HEADERS).json()
        path = "/api/documents/" + doc["id"] + "/extract"
        self.assertEqual(self.client.post(path, json={"provider": "openai", "consent": True}, headers=HEADERS).status_code, 422)


class ExtractionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.started, self.finish = threading.Event(), threading.Event()
        self.cancelled = threading.Event()
        self.now = [0]
        async def extractor(provider, pages):
            self.started.set()
            try:
                while not self.finish.is_set():
                    await asyncio.sleep(.005)
            except asyncio.CancelledError:
                self.cancelled.set()
                # Deliberately complete despite cancellation: stale-result guard must still hold.
            return ExtractionResult(Candidate.model_validate(candidate()).verify([TEXT]), 1, 20, 30)
        self.app = create_app(access_code=CODE, origin=ORIGIN, extractor=extractor,
                              providers=["openai"], clock=lambda: self.now[0])
        self.client = self.enterContext(TestClient(self.app, base_url=ORIGIN))
        self.client.post("/api/session", json={"code": CODE}, headers=HEADERS)
        # Source text matches the independently invented extraction fixture.
        doc = self.client.post("/api/documents", content=pdf_bytes(), headers=HEADERS).json()
        self.path = "/api/documents/" + doc["id"]

    def start(self):
        response = self.client.post(self.path + "/extract", json={"provider": "openai", "consent": True}, headers=HEADERS)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertTrue(self.started.wait(1))

    def test_edit_cancels_and_late_result_cannot_overwrite_correction(self):
        self.start()
        self.assertEqual(self.client.post(self.path + "/approve", json={"revision": 0}, headers=HEADERS).status_code, 409)
        self.assertEqual(self.client.post(self.path + "/extract", json={"provider": "openai", "consent": True}, headers=HEADERS).status_code, 409)
        self.client.put(self.path, json={"revision": 0, "facts": dict(FACTS, consumption="700")}, headers=HEADERS)
        self.assertTrue(self.cancelled.wait(1))
        result = self.client.get(self.path).json()
        self.assertEqual(result["facts"]["consumption"], "700")
        self.assertIsNone(result["proposal"])
        self.assertEqual(result["revision"], 1)

    def test_delete_and_expiry_cancel_job_and_discard_late_output(self):
        self.start()
        self.assertEqual(self.client.delete(self.path, headers=HEADERS).status_code, 200)
        self.assertTrue(self.cancelled.wait(1))
        self.assertEqual(self.client.get(self.path).status_code, 404)
        self.now[0] += 1801
        self.assertEqual(self.client.get("/api/documents").status_code, 401)

    def test_completed_job_installs_proposal_without_approval(self):
        self.start()
        self.finish.set()
        for _ in range(100):
            result = self.client.get(self.path).json()
            if result["job"]["status"] != "running":
                break
            time.sleep(.01)
        self.assertEqual(result["job"]["status"], "complete")
        self.assertEqual(result["revision"], 1)
        self.assertIsNone(result["approved_revision"])
        self.assertEqual(result["job"]["usage"]["requests"], 1)

    def test_expiry_during_extraction_cancels_and_removes_state(self):
        self.start()
        self.now[0] += 1801
        self.assertEqual(self.client.get(self.path).status_code, 401)
        self.assertTrue(self.cancelled.wait(1))
        self.client.post("/api/session", json={"code": CODE}, headers=HEADERS)
        self.assertEqual(self.client.get("/api/documents").json(), [])

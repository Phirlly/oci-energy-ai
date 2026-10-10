"""Bounded, transient, session-owned work and cancellation-safe extraction jobs."""

import asyncio
from dataclasses import dataclass, field
import secrets
import time

from fastapi import HTTPException

from energy_ai.bills.review import BillReview

TTL = 1800


@dataclass
class Document:
    digest: str
    review: BillReview
    id: str = field(default_factory=lambda: secrets.token_urlsafe(18))
    job: dict | None = None
    task: asyncio.Task | None = None

    def cancel(self):
        # Invalidate before signalling cancellation, including cancellation-resistant clients.
        if self.job and self.job["status"] == "running":
            self.job = dict(id=self.job["id"], status="cancelled")
        if self.task and not self.task.done():
            self.task.cancel()

    def public(self):
        return dict(id=self.id, job=self.job, **self.review.public())


@dataclass
class Session:
    expires: float
    documents: dict = field(default_factory=dict)
    uploading: bool = False
    upload_task: asyncio.Task | None = None


class Sessions:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.items = {}
        self.tasks = set()
        self.parsers = 0
        self.attempts = []

    def close(self, token):
        session = self.items.pop(token, None)
        if session:
            for doc in session.documents.values():
                doc.cancel()
            if session.upload_task and not session.upload_task.done():
                session.upload_task.cancel()
            session.documents.clear()

    def prune(self):
        for token, session in list(self.items.items()):
            if session.expires <= self.clock():
                self.close(token)

    def login_attempt(self):
        now = self.clock()
        self.attempts = [stamp for stamp in self.attempts if now - stamp < 60]
        if len(self.attempts) >= 10:
            raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.")
        self.attempts.append(now)

    def create(self):
        self.prune()
        if len(self.items) >= 8:
            raise HTTPException(429, "Local session limit reached. Sign out of an existing session.")
        token = secrets.token_urlsafe(32)
        self.items[token] = Session(self.clock() + TTL)
        return token

    def get(self, token):
        self.prune()
        if token not in self.items:
            raise HTTPException(401, "Session ended. Sign in again; unsaved work is no longer available.")
        return self.items[token]

    def document(self, session, document_id):
        if document_id not in session.documents:
            raise HTTPException(404, "Bill not found in this session.")
        return session.documents[document_id]

    def live(self, token, session):
        self.prune()
        return self.items.get(token) is session

    def start(self, token, session, doc, provider, extractor):
        if doc.job and doc.job["status"] == "running":
            raise HTTPException(409, "Extraction is already running.")
        if len(self.tasks) >= 2:
            raise HTTPException(429, "Two extractions are running. Try again shortly.")
        job_id, revision = secrets.token_urlsafe(12), doc.review.revision
        doc.job = dict(id=job_id, status="running")
        async def run():
            try:
                async with asyncio.timeout(105):
                    result = await extractor(provider, list(doc.review.pages))
                if (self.live(token, session) and session.documents.get(doc.id) is doc
                        and doc.job == dict(id=job_id, status="running") and doc.review.revision == revision):
                    doc.review.propose(result.candidate)
                    doc.job = dict(id=job_id, status="complete", usage=dict(
                        requests=result.requests, input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens))
            except asyncio.CancelledError:
                pass
            except Exception:
                if (self.live(token, session) and session.documents.get(doc.id) is doc
                        and doc.job == dict(id=job_id, status="running")):
                    doc.job = dict(id=job_id, status="failed",
                                   error="Extraction failed. Retry or enter the bill facts manually.")
        task = asyncio.create_task(run())
        doc.task = task
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

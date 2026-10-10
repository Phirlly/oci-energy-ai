"""Session-scoped upload/review routes; all computation uses current approved facts."""

import asyncio
import hashlib

from fastapi import APIRouter, HTTPException, Request

from energy_ai.bills.examples import EXAMPLES, EXAMPLE_FACTS
from energy_ai.bills.insights import summarize
from energy_ai.bills.pdf import MAX_BYTES, PdfError, extract_pdf
from energy_ai.bills.review import BillReview
from energy_ai.bills.schema import Facts
from energy_ai.web.requests import Edit, Extraction, Revision, Selection, read_bytes, read_contract
from energy_ai.web.sessions import Document


def document_routes(store, providers, extractor):
    router = APIRouter(prefix="/api")

    def context(request):
        token = request.cookies.get("energy_session")
        return token, store.get(token)

    def find(request, document_id):
        token, session = context(request)
        return token, session, store.document(session, document_id)

    def add(session, pages, digest):
        if len(session.documents) >= 12:
            raise HTTPException(409, "Limit: 12 bills per session. Delete a bill before adding another.")
        if any(doc.digest == digest for doc in session.documents.values()):
            raise HTTPException(409, "This document is already in your session.")
        doc = Document(digest, BillReview(pages))
        session.documents[doc.id] = doc
        return doc

    @router.get("/documents")
    async def list_documents(request: Request):
        _, session = context(request)
        return [doc.public() for doc in session.documents.values()]

    @router.post("/documents", status_code=201)
    async def upload(request: Request):
        token, session = context(request)
        if len(session.documents) >= 12:
            raise HTTPException(409, "Limit: 12 bills per session.")
        if store.parsers >= 2 or session.uploading:
            raise HTTPException(429, "An upload is running. Try again shortly.")
        session.uploading, session.upload_task = True, asyncio.current_task()
        store.parsers += 1
        try:
            async with asyncio.timeout(20):
                raw = await read_bytes(request, MAX_BYTES)
                digest = hashlib.sha256(raw).hexdigest()
                if any(doc.digest == digest for doc in session.documents.values()):
                    raise HTTPException(409, "This document is already in your session.")
                pages = await extract_pdf(raw)
                del raw
                if not store.live(token, session):
                    raise HTTPException(401, "Session ended during upload.")
                return add(session, pages, digest).public()
        except PdfError as error:
            raise HTTPException(422, str(error)) from None
        except TimeoutError:
            raise HTTPException(408, "Upload exceeded its deadline.") from None
        finally:
            store.parsers -= 1
            session.uploading, session.upload_task = False, None

    @router.post("/example", status_code=201)
    async def example(request: Request):
        _, session = context(request)
        doc = add(session, [EXAMPLES[0]], "invented-public-example")
        doc.review.edit(Facts.model_validate(EXAMPLE_FACTS), 0)
        return doc.public()

    @router.get("/documents/{document_id}")
    async def get_document(document_id: str, request: Request):
        return find(request, document_id)[2].public()

    @router.delete("/documents/{document_id}")
    async def delete_document(document_id: str, request: Request):
        _, session, doc = find(request, document_id)
        doc.cancel()
        del session.documents[doc.id]
        return {"deleted": True}

    @router.put("/documents/{document_id}")
    async def edit(document_id: str, request: Request):
        _, _, doc = find(request, document_id)
        body = await read_contract(request, Edit)
        _, _, doc = find(request, document_id)
        doc.review.check_revision(body.revision)
        doc.cancel()
        doc.review.edit(body.facts, body.revision)
        return doc.public()

    @router.post("/documents/{document_id}/approve")
    async def approve(document_id: str, request: Request):
        _, _, doc = find(request, document_id)
        body = await read_contract(request, Revision)
        _, _, doc = find(request, document_id)
        if doc.job and doc.job["status"] == "running":
            raise HTTPException(409, "Wait for extraction or save corrections to cancel it before approving.")
        doc.review.approve(body.revision)
        return doc.public()

    @router.post("/documents/{document_id}/extract", status_code=202)
    async def extract(document_id: str, request: Request):
        token, session, doc = find(request, document_id)
        body = await read_contract(request, Extraction)
        token, session, doc = find(request, document_id)
        if body.provider not in providers or extractor is None:
            raise HTTPException(422, "This provider is not configured on the server.")
        store.start(token, session, doc, body.provider, extractor)
        return doc.public()

    @router.delete("/documents/{document_id}/extract")
    async def cancel(document_id: str, request: Request):
        _, _, doc = find(request, document_id)
        doc.cancel()
        return doc.public()

    @router.post("/insights")
    async def insights(request: Request):
        _, session = context(request)
        body = await read_contract(request, Selection)
        _, session = context(request)
        facts = []
        for document_id, revision in body.revisions.items():
            doc = store.document(session, document_id)
            if doc.job and doc.job["status"] == "running":
                raise HTTPException(409, "Wait for extraction before calculating insights.")
            facts.append(doc.review.approved_facts(revision))
        return dict(summarize(facts), document_ids=list(body.revisions))

    return router

"""Same-origin authenticated local presenter; transient state, no raw document logs."""

import asyncio
from contextlib import asynccontextmanager
import hmac
from pathlib import Path
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from energy_ai.bills.review import ReviewError
from energy_ai.agents.provider_clients import DEFAULT_MODELS
from energy_ai.web.documents import document_routes
from energy_ai.web.office import office_routes
from energy_ai.office.runs import RunRepository
from energy_ai.office.run_service import RunService
from energy_ai.web.requests import Login, read_contract
from energy_ai.web.sessions import Sessions, TTL


def create_app(*, access_code, origin, providers=(), extractor=None, model_ids=None, clock=time.monotonic,
               office_analyzer=None, office_database=':memory:'):
    parsed = urlsplit(origin)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
            or parsed.path or parsed.query or parsed.fragment or parsed.username):
        raise ValueError("The local presenter requires an exact http://127.0.0.1:PORT origin.")
    if not isinstance(access_code, str) or len(access_code) < 12:
        raise ValueError("Use a launch code of at least 12 characters.")
    store = Sessions(clock)
    models = {p: (model_ids or {}).get(p) or DEFAULT_MODELS[p] for p in providers}

    @asynccontextmanager
    async def lifespan(app):
        repository = RunRepository(office_database)
        app.state.office = RunService(repository, office_analyzer)
        async def cleanup():
            while True:
                await asyncio.sleep(5)
                store.prune()
        cleanup_task = asyncio.create_task(cleanup())
        try:
            yield
        finally:
            cleanup_task.cancel()
            for token in list(store.items):
                store.close(token)
            await asyncio.gather(cleanup_task, *store.tasks, return_exceptions=True)
            await app.state.office.close()
            repository.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.sessions = store

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        if (request.headers.get("host") != parsed.netloc
                or request.headers.get("origin", origin) != origin
                or request.method not in {"GET", "HEAD"} and (
                    request.headers.get("origin") != origin
                    or request.headers.get("x-energy-action") != "1")):
            response = JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
        else:
            response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                      "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                                      "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })
        return response

    @app.exception_handler(ReviewError)
    async def review_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.post("/api/session")
    async def login(request: Request):
        store.login_attempt()
        body = await read_contract(request, Login)
        if not hmac.compare_digest(body.code.encode(), access_code.encode()):
            raise HTTPException(401, "Incorrect launch code.")
        old = request.cookies.get("energy_session")
        if old:
            store.close(old)
        token = store.create()
        response = JSONResponse({"signed_in": True})
        response.set_cookie("energy_session", token, httponly=True, samesite="strict",
                            max_age=TTL, path="/api")
        return response

    @app.get("/api/session")
    async def session(request: Request):
        current = store.get(request.cookies.get("energy_session"))
        return dict(providers=list(providers), models=models,
                    expires_in=max(0, int(current.expires - clock())))

    @app.delete("/api/session")
    async def logout(request: Request):
        store.close(request.cookies.get("energy_session"))
        response = JSONResponse({"signed_out": True})
        response.delete_cookie("energy_session", path="/api")
        return response

    app.include_router(document_routes(store, providers, extractor))
    app.include_router(office_routes(store, models, office_analyzer))
    assets = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if assets.is_dir():
        app.mount("/", StaticFiles(directory=assets, html=True), name="frontend")
    return app

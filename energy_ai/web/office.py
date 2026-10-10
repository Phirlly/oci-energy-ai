"""Authenticated public-office calculations and bounded asynchronous runs."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import ConfigDict, BaseModel

from energy_ai.office.bill_pdf import office_bill_pdf
from energy_ai.office.runs import RunError
from energy_ai.office.sample import Controls, office_profile, office_scenario
from energy_ai.web.requests import read_contract


class StartOfficeRun(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    request_key: UUID
    provider: Literal['oci', 'openai', 'anthropic']
    consent: Literal[True]
    controls: Controls
    question: Literal['explain_bill', 'evaluate_battery']


def office_routes(sessions, models, analyzer):
    router = APIRouter(prefix='/api/office')

    def service(request):
        sessions.get(request.cookies.get('energy_session'))
        return request.app.state.office

    @router.get('')
    async def profile(request: Request):
        service(request)
        return office_profile()

    @router.get('/bill.pdf')
    async def bill(request: Request):
        service(request)
        return Response(office_bill_pdf(), media_type='application/pdf',
                        headers={'Content-Disposition': 'attachment; filename="illustrative-office-bill.pdf"'})

    @router.post('/scenario')
    async def scenario(request: Request):
        service(request)
        controls = await read_contract(request, Controls)
        service(request)
        return office_scenario(controls)

    @router.get('/runs')
    async def history(request: Request):
        return service(request).repository.history()

    @router.post('/runs', status_code=202)
    async def start(request: Request):
        current = service(request)
        body = await read_contract(request, StartOfficeRun)
        current = service(request)
        if body.provider not in models or analyzer is None:
            raise HTTPException(409, 'This provider is not configured for office analysis.')
        payload = dict(provider=body.provider, model=models[body.provider],
                       controls=body.controls.model_dump(), question=body.question)
        try:
            return current.start(str(body.request_key), payload)
        except RunError as error:
            raise HTTPException(409, str(error)) from None

    @router.get('/runs/{run_id}')
    async def get(request: Request, run_id: str):
        try:
            return service(request).repository.get(run_id)
        except KeyError:
            raise HTTPException(404, 'Office run not found.') from None

    @router.delete('/runs/{run_id}')
    async def cancel(request: Request, run_id: str):
        try:
            return service(request).cancel(run_id)
        except KeyError:
            raise HTTPException(404, 'Office run not found.') from None

    return router

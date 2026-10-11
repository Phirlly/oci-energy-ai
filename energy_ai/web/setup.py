"""Small first-run HTTP boundary; the hosted setup runtime owns credentials and writes."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import ConfigDict, Field

from energy_ai.bills.schema import StrictModel
from energy_ai.web.requests import read_contract
from energy_ai.web.setup_secrets import SetupError


class SetupRequest(StrictModel):
    model_config = ConfigDict(str_strip_whitespace=False)
    setup_code: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    openai_key: str = Field(default='', max_length=4096)
    anthropic_key: str = Field(default='', max_length=4096)


def setup_routes(sessions, setup):
    router = APIRouter(prefix='/api/setup')

    @router.get('')
    async def status():
        return {'required': setup is not None and setup.required}

    @router.post('')
    async def complete(request: Request):
        sessions.login_attempt()
        if setup is None:
            raise HTTPException(409, 'Setup is already complete. Sign in with the demo password.')
        body = await read_contract(request, SetupRequest)
        keys = {name: key for name, key in (('openai', body.openai_key), ('anthropic', body.anthropic_key)) if key}
        try:
            await setup.complete(body.setup_code, body.password, keys)
        except SetupError as error:
            raise HTTPException(error.status, str(error)) from None
        return {'required': False}

    return router

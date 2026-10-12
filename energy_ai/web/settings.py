"""Owner-authorized provider maintenance; never returns persisted credentials."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import ConfigDict, Field

from energy_ai.bills.schema import StrictModel
from energy_ai.web.requests import read_contract
from energy_ai.web.setup_secrets import SetupError


class ProviderSettingsRequest(StrictModel):
    model_config = ConfigDict(str_strip_whitespace=False)
    owner_code: str = Field(min_length=1, max_length=200)
    changes: dict[Literal['openai', 'anthropic'], Annotated[str, Field(min_length=1, max_length=4096)] | None] = Field(min_length=1, max_length=2)


def settings_routes(sessions, setup):
    router = APIRouter(prefix='/api/settings')

    @router.post('')
    async def update(request: Request):
        token = request.cookies.get('energy_session')
        sessions.get(token)
        sessions.login_attempt()
        body = await read_contract(request, ProviderSettingsRequest)
        sessions.get(token)
        if setup is None:
            raise HTTPException(409, 'Owner settings are unavailable for this installation.')
        try:
            await setup.update_keys(body.owner_code, body.changes)
        except SetupError as error:
            raise HTTPException(error.status, str(error)) from None
        return {'saved': True}

    return router

"""Browser-only public workflow fixture; real SDK Runner, no external services."""

import asyncio
import os

import uvicorn

from energy_ai.agents.analysis import AnalysisError
from energy_ai.agents.office_analysis import analyze_office
from energy_ai.web.app import create_app
from tests.fixtures.agent_responses import ScriptedModel
from tests.fixtures.office_responses import office_outputs


async def scripted(provider, controls, question, publish):
    class DelayedModel(ScriptedModel):
        async def get_response(self, **request):
            await asyncio.sleep(.5)
            return await super().get_response(**request)
    if provider == 'anthropic':
        await asyncio.sleep(.5)
        raise AnalysisError('rate_limit')
    return await analyze_office(DelayedModel(office_outputs()), controls, question, publish)


if __name__ == '__main__':
    uvicorn.run(create_app(access_code=os.environ['ENERGY_ACCESS_CODE'], origin='http://127.0.0.1:8767',
                           providers=['openai', 'anthropic'], office_analyzer=scripted),
                host='127.0.0.1', port=8767, access_log=False)

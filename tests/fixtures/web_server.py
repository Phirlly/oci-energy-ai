"""Playwright-only scripted provider; never imported by the production launcher."""

import asyncio
import os

import uvicorn

from energy_ai.bills.extraction import ExtractionResult
from energy_ai.bills.schema import Candidate
from energy_ai.web.app import create_app
from tests.fixtures.bills import candidate


async def scripted(provider, pages):
    await asyncio.sleep(1.5)
    proposal = candidate()
    for evidence in proposal["evidence"].values():
        evidence["quote"] = pages[0]
    return ExtractionResult(Candidate.model_validate(proposal).verify(pages), 1, 20, 30)


if __name__ == "__main__":
    uvicorn.run(create_app(access_code=os.environ["ENERGY_ACCESS_CODE"], origin="http://127.0.0.1:8766",
                           providers=["openai", "anthropic"], extractor=scripted),
                host="127.0.0.1", port=8766, access_log=False)

"""Small request contracts; never echo submitted values in validation errors."""

import json
import asyncio
from typing import Annotated, Literal

from fastapi import HTTPException, Request
from pydantic import Field

from energy_ai.bills.schema import Facts, StrictModel


class Login(StrictModel):
    code: str = Field(min_length=1, max_length=200)


class Revision(StrictModel):
    revision: int = Field(strict=True, ge=0)


class Edit(Revision):
    facts: Facts


class Extraction(StrictModel):
    provider: Literal["oci", "openai", "anthropic"]
    consent: Literal[True]


class Selection(StrictModel):
    revisions: dict[str, Annotated[int, Field(strict=True, ge=0)]] = Field(min_length=1, max_length=12)


async def read_bytes(request: Request, maximum):
    output = bytearray()
    async for chunk in request.stream():
        if len(output) + len(chunk) > maximum:
            raise HTTPException(413, "Request is too large.")
        output.extend(chunk)
    return bytes(output)


async def read_contract(request, contract):
    try:
        async with asyncio.timeout(10):
            return contract.model_validate_json(await read_bytes(request, 100000))
    except TimeoutError:
        raise HTTPException(408, "Request exceeded its deadline.") from None
    except (ValueError, TypeError):
        raise HTTPException(422, "Check the submitted fields and their formats.") from None

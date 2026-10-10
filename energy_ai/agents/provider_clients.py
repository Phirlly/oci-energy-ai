"""Explicit provider endpoints and bounded clients; credentials stay in memory."""

from contextlib import asynccontextmanager
import re

from agents import OpenAIResponsesModel
from anthropic import AsyncAnthropic
import httpx
import httpx2
from oci_genai_auth import HttpxOciAuth
from openai import AsyncOpenAI

from energy_ai.agents.anthropic_model import AnthropicMessagesModel

DEFAULT_MODELS = {"oci": "google.gemini-2.5-flash",
                  "openai": "gpt-4.1-mini-2025-04-14", "anthropic": "claude-haiku-5-5"}


class FixedSignerAuth(HttpxOciAuth):
    """User API signing keys have no refresh operation or profile dependency."""

    def _refresh_signer(self):
        pass


@asynccontextmanager
async def open_model(provider, *, api_key=None, model_id=None, oci_region=None,
                     oci_project=None, oci_signer=None, transport=None):
    if provider not in DEFAULT_MODELS:
        raise ValueError("Unknown provider.")
    model_id = DEFAULT_MODELS[provider] if model_id is None else model_id
    if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", model_id):
        raise ValueError("Invalid model identifier.")
    auth = None
    project = ""
    if provider == "oci":
        if (not isinstance(oci_region, str) or not re.fullmatch(r"[a-z]{2,3}-[a-z0-9-]+-[1-9][0-9]?", oci_region)
                or not isinstance(oci_project, str)
                or not re.fullmatch(r"ocid1\.generativeaiproject\.oc1\.[a-z0-9-]+\.[a-z0-9.]{20,255}", oci_project)
                or oci_signer is None):
            raise ValueError("OCI region, project and signing identity are required.")
        auth, project, api_key = FixedSignerAuth(oci_signer), oci_project, "not-used"
        endpoint = f"https://inference.generativeai.{oci_region}.oci.oraclecloud.com/openai/v1"
    else:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Provider API key is required.")
        endpoint = "https://api.openai.com/v1"
    if provider == "anthropic":
        async with httpx2.AsyncClient(timeout=httpx2.Timeout(60, connect=10), transport=transport,
                                      follow_redirects=False, trust_env=False) as http:
            async with AsyncAnthropic(api_key=api_key, base_url="https://api.anthropic.com",
                                      max_retries=0, timeout=60, http_client=http) as client:
                yield AnthropicMessagesModel(client, model_id)
    else:
        async with httpx.AsyncClient(auth=auth, timeout=httpx.Timeout(60, connect=10),
                                     transport=transport, follow_redirects=False, trust_env=False) as http:
            async with AsyncOpenAI(api_key=api_key, organization="", project=project, base_url=endpoint,
                                   max_retries=0, timeout=60, http_client=http) as client:
                yield OpenAIResponsesModel(model_id, client)

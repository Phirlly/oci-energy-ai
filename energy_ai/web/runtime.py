"""Explicit local provider configuration; runtime never discovers deployment state."""

import os
from contextlib import asynccontextmanager

from energy_ai.agents.provider_clients import open_model
from energy_ai.bills.extraction import extract_bill
from energy_ai.agents.office_analysis import analyze_office


def configured_providers(environment):
    configured = [provider for provider in ("openai", "anthropic")
                  if environment.get(f"{provider.upper()}_API_KEY", "").strip()]
    if all(environment.get(name, "").strip() for name in ("OCI_PROFILE", "OCI_REGION", "OCI_GENAI_PROJECT")):
        configured.insert(0, "oci")
    return configured


@asynccontextmanager
async def configured_model(provider):
    options = {"model_id": os.environ.get(f"{provider.upper()}_MODEL") or None}
    if provider == "oci":
        from oci.config import from_file, validate_config
        from oci.signer import Signer
        # Explicitly selected local profile only; no Resource Manager permissions or discovery.
        config = from_file(profile_name=os.environ["OCI_PROFILE"])
        validate_config(config)
        options.update(oci_region=os.environ["OCI_REGION"], oci_project=os.environ["OCI_GENAI_PROJECT"],
                       oci_signer=Signer(config["tenancy"], config["user"], config["fingerprint"],
                                         config["key_file"], config.get("pass_phrase")))
    else:
        options["api_key"] = os.environ.get(f"{provider.upper()}_API_KEY")
    async with open_model(provider, **options) as model:
        yield model


async def extract_configured(provider, pages):
    async with configured_model(provider) as model:
        return await extract_bill(model, pages)


async def analyze_configured(provider, controls, question, publish):
    async with configured_model(provider) as model:
        return await analyze_office(model, controls, question, publish)

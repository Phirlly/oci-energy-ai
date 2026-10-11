"""Instance identity and startup-only Vault reads; no deployment identity or profile."""

import base64
from contextlib import asynccontextmanager

from oci.auth.signers import InstancePrincipalsSecurityTokenSigner
from oci.retry import NoneRetryStrategy
from oci.secrets import SecretsClient
from oci.vault import VaultsClient

from energy_ai.agents.instance_auth import InstanceAuth
from energy_ai.agents.office_analysis import analyze_office
from energy_ai.agents.provider_clients import open_model
from energy_ai.bills.extraction import extract_bill
from energy_ai.web.hosted_configuration import RuntimeConfigurationError
from energy_ai.web.passwords import valid_password


def _close_identity(signer):
    for owner in ('federation_client', 'leaf_certificate_retriever', 'intermediate_certificate_retriever'):
        try:
            getattr(signer, owner).requests_session.close()
        except Exception:
            pass  # Cleanup must not expose SDK state or skip the other owned sessions.


def _secret(client, secret_id, name):
    bundle = client.get_secret_bundle(secret_id, stage='CURRENT').data
    if bundle.secret_id != secret_id or 'CURRENT' not in (bundle.stages or []):
        raise ValueError()
    content = bundle.secret_bundle_content
    if (content.content_type != 'BASE64' or not isinstance(content.content, str)
            or len(content.content) > 32768):
        raise ValueError()
    value = base64.b64decode(content.content, validate=True).decode('utf-8')
    if name == 'demo_password':
        if not valid_password(value):
            raise ValueError()
    elif not 1 <= len(value) <= 4096 or any(not 33 <= ord(char) <= 126 for char in value):
        raise ValueError()
    return value


class HostedRuntime:
    def __init__(self, config, signer, values):
        self.config = config
        self.providers = config.providers
        self.password = values.pop('demo_password')
        self.keys = values
        self.auth = InstanceAuth(signer, cleanup=lambda: _close_identity(signer))

    @asynccontextmanager
    async def model(self, provider):
        if provider not in self.providers:
            raise RuntimeConfigurationError('Provider is not configured.')
        options = dict(model_id=self.config.models()[provider])
        if provider == 'oci':
            options.update(oci_region=self.config.region, oci_project=self.config.project, oci_auth=self.auth)
        else:
            options['api_key'] = self.keys[provider]
        async with open_model(provider, **options) as model:
            yield model

    async def extract(self, provider, pages):
        async with self.model(provider) as model:
            return await extract_bill(model, pages)

    async def analyze(self, provider, controls, question, publish):
        async with self.model(provider) as model:
            return await analyze_office(model, controls, question, publish)

    def close(self):
        self.auth.close()
        self.keys.clear()
        self.password = ''


def load_runtime(config):
    signer = None
    setup_clients = []
    try:
        signer = InstancePrincipalsSecurityTokenSigner(
            retry_strategy=NoneRetryStrategy(), federation_client_retry_strategy=NoneRetryStrategy())
        if signer.region != config.region:
            raise ValueError()
        client = SecretsClient({'region': config.region}, signer=signer, timeout=(10, 30),
                               service_endpoint=f'https://secrets.vaults.{config.region}.oci.oraclecloud.com',
                               retry_strategy=NoneRetryStrategy())
        if config.version == 2:
            from energy_ai.web.hosted_setup import HostedSetup
            from energy_ai.web.setup_secrets import SetupSecrets
            setup_clients.append(client)
            vault = VaultsClient({'region': config.region}, signer=signer, timeout=(10, 30),
                                service_endpoint=f'https://vaults.{config.region}.oci.oraclecloud.com',
                                retry_strategy=NoneRetryStrategy())
            setup_clients.append(vault)
            return HostedSetup(config, signer, SetupSecrets(vault, client, config.secret_ids['settings']))
        try:
            values = {name: _secret(client, secret_id, name) for name, secret_id in config.secret_ids.items()}
        finally:
            client.base_client.session.close()
        return HostedRuntime(config, signer, values)
    except Exception:
        for owner in setup_clients:
            try:
                owner.base_client.session.close()
            except Exception:
                pass
        if signer is not None:
            _close_identity(signer)
        raise RuntimeConfigurationError('Hosted OCI identity or Vault credentials are unavailable.') from None

"""Nonsecret hosted configuration. Credentials belong only in OCI Vault."""

from dataclasses import dataclass
import json
from pathlib import Path
import re

from oci.regions_definitions import REGION_REALMS, REGIONS_SHORT_NAMES

from energy_ai.agents.provider_clients import DEFAULT_MODELS
from energy_ai.web.origin import OriginPolicy


class RuntimeConfigurationError(ValueError):
    """Fixed operator messages; never include supplied values or SDK exceptions."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


@dataclass(frozen=True)
class HostedConfiguration:
    region: str
    project: str
    origin: str
    backend_host: str
    secret_ids: dict
    model_ids: dict

    @property
    def providers(self):
        return ('oci',) + tuple(name for name in ('openai', 'anthropic') if name in self.secret_ids)

    @classmethod
    def from_bytes(cls, content):
        try:
            if not isinstance(content, bytes) or len(content) > 16384:
                raise ValueError()
            data = json.loads(content, object_pairs_hook=_unique_object)
            if (not isinstance(data, dict) or set(data) != {
                    'version', 'region', 'project', 'origin', 'backend_host', 'secret_ids', 'model_ids'}
                    or type(data['version']) is not int or data['version'] != 1):
                raise ValueError()
            data.pop('version')
            config = cls(**data)
            if REGION_REALMS.get(config.region) != 'oc1':
                raise ValueError()
            regions = {config.region} | {short for short, full in REGIONS_SHORT_NAMES.items() if full == config.region}
            def valid_id(value, kind):
                if not isinstance(value, str):
                    return False
                match = re.fullmatch(r'ocid1\.' + kind + r'\.oc1\.([a-z0-9-]+)\.([a-z0-9.]{20,255})', value)
                return bool(match and match[1] in regions)
            if not valid_id(config.project, 'generativeaiproject'):
                raise ValueError()
            if not OriginPolicy.validate(config.origin, config.backend_host).secure:
                raise ValueError()
            if (not isinstance(config.secret_ids, dict) or 'demo_password' not in config.secret_ids
                    or set(config.secret_ids) - {'demo_password', 'openai', 'anthropic'}
                    or not all(valid_id(value, 'vaultsecret') for value in config.secret_ids.values())
                    or len(set(config.secret_ids.values())) != len(config.secret_ids)):
                raise ValueError()
            if (not isinstance(config.model_ids, dict) or set(config.model_ids) - set(config.providers)
                    or not all(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value)
                               for value in config.model_ids.values())):
                raise ValueError()
            return config
        except (TypeError, ValueError, KeyError):
            raise RuntimeConfigurationError('Invalid hosted runtime configuration.') from None

    @classmethod
    def load(cls, path):
        try:
            with Path(path).open('rb') as source:
                return cls.from_bytes(source.read(16385))
        except OSError:
            raise RuntimeConfigurationError('Hosted runtime configuration cannot be read.') from None

    def models(self):
        return {provider: self.model_ids.get(provider, DEFAULT_MODELS[provider]) for provider in self.providers}

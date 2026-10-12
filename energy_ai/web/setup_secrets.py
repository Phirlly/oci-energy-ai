"""Conditional first-run claim of one Vault secret; credentials never leave memory."""

import base64
from dataclasses import dataclass
import hmac
import json
import time

from oci.retry import NoneRetryStrategy
from oci.vault.models import Base64SecretContentDetails, UpdateSecretDetails

from energy_ai.web.hosted_configuration import _unique_object
from energy_ai.web.passwords import valid_password

COMPLETION_TAG = 'energy_ai_setup'


class SetupError(Exception):
    def __init__(self, status=503, message='Setup could not be verified. Wait a moment and try again.'):
        self.status = status
        super().__init__(message)


class AlreadyConfigured(SetupError):
    def __init__(self, value):
        self.value = value
        super().__init__(409, 'Setup is already complete. Sign in with the demo password.')


class SettingsChanged(SetupError):
    def __init__(self, value):
        self.value = value
        super().__init__(409, 'Settings changed while saving. Review the configured providers and try again.')


@dataclass(frozen=True, repr=False)
class SettingsSnapshot:
    value: dict
    etag: str
    tags: dict


def valid_keys(keys):
    return (isinstance(keys, dict) and not set(keys) - {'openai', 'anthropic'}
            and all(isinstance(value, str) and 1 <= len(value) <= 4096
                    and all(33 <= ord(char) <= 126 for char in value) for value in keys.values()))


def _payload(raw, marker):
    if len(raw) > 16384:
        raise ValueError()
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] not in (1, 2):
        raise ValueError()
    if set(value) == {'version', 'setup_code'}:
        if value['version'] != 1 or marker is not None or not valid_password(value['setup_code']):
            raise ValueError()
    elif set(value) == ({'version', 'password', 'keys'} if value['version'] == 1 else
                        {'version', 'owner_code', 'password', 'keys'}):
        if marker != 'complete' or not valid_password(value['password']) or not valid_keys(value['keys']):
            raise ValueError()
        if value['version'] == 2 and not valid_password(value['owner_code']):
            raise ValueError()
    else:
        raise ValueError()
    return value


class SetupSecrets:
    def __init__(self, vault, bundles, secret_id, *, monotonic=time.monotonic, sleep=time.sleep):
        self.vault, self.bundles, self.secret_id = vault, bundles, secret_id
        self.monotonic, self.sleep = monotonic, sleep

    def read(self):
        try:
            metadata = self.vault.get_secret(self.secret_id, retry_strategy=NoneRetryStrategy())
            secret, etag = metadata.data, metadata.headers.get('etag')
            if (secret.id != self.secret_id or secret.lifecycle_state != 'ACTIVE'
                    or type(secret.current_version_number) is not int or secret.current_version_number < 1
                    or not isinstance(etag, str) or not etag or len(etag) > 1024
                    or not isinstance(secret.freeform_tags, dict)):
                raise ValueError()
            bundle = self.bundles.get_secret_bundle(self.secret_id,
                version_number=secret.current_version_number, retry_strategy=NoneRetryStrategy()).data
            content = bundle.secret_bundle_content
            if (bundle.secret_id != self.secret_id or type(bundle.version_number) is not int
                    or bundle.version_number != secret.current_version_number
                    or 'CURRENT' not in (bundle.stages or []) or content.content_type != 'BASE64'
                    or not isinstance(content.content, str) or len(content.content) > 24576):
                raise ValueError()
            raw = base64.b64decode(content.content, validate=True)
            value = _payload(raw, secret.freeform_tags.get(COMPLETION_TAG))
            return SettingsSnapshot(value, etag, dict(secret.freeform_tags))
        except Exception:
            raise SetupError() from None

    def complete(self, code, password, keys):
        if not valid_password(code) or not valid_password(password) or not valid_keys(keys):
            raise SetupError(422, 'Check the setup code, password and optional API keys.')
        snapshot = self.read()
        if 'password' in snapshot.value:
            raise AlreadyConfigured(snapshot.value)
        if not hmac.compare_digest(code.encode(), snapshot.value['setup_code'].encode()):
            raise SetupError(403, 'Incorrect setup code.')
        value = {'version': 2, 'owner_code': snapshot.value['setup_code'], 'password': password, 'keys': dict(keys)}
        encoded = self._write(snapshot, value)
        current = self._confirm_completion()
        actual = json.dumps(current, sort_keys=True, separators=(',', ':')).encode()
        if not hmac.compare_digest(actual, encoded):
            raise AlreadyConfigured(current)
        return current

    def update_keys(self, code, changes):
        if (not valid_password(code) or not isinstance(changes, dict) or not changes
                or not valid_keys({name: key for name, key in changes.items() if key is not None})
                or set(changes) - {'openai', 'anthropic'}):
            raise SetupError(422, 'Check the owner code and provider key changes.')
        snapshot = self.read()
        if snapshot.value.get('version') != 2 or 'password' not in snapshot.value:
            raise SetupError(409, 'Owner settings are unavailable for this installation.')
        if not hmac.compare_digest(code.encode(), snapshot.value['owner_code'].encode()):
            raise SetupError(403, 'Incorrect owner code.')
        keys = dict(snapshot.value['keys'])
        for name, key in changes.items():
            if key is None:
                keys.pop(name, None)
            else:
                keys[name] = key
        value = dict(snapshot.value, keys=keys)
        if value == snapshot.value:
            return value
        encoded = self._write(snapshot, value)
        for current in self._confirmations():
            actual = json.dumps(current, sort_keys=True, separators=(',', ':')).encode()
            if hmac.compare_digest(actual, encoded):
                return current
            if current != snapshot.value:
                raise SettingsChanged(current)
        raise SetupError()

    def _write(self, snapshot, value):
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        if len(encoded) > 16384:
            raise SetupError(422, 'Combined settings are too large. Check the password and API keys.')
        details = UpdateSecretDetails(
            secret_content=Base64SecretContentDetails(content=base64.b64encode(encoded).decode(), stage='CURRENT'),
            freeform_tags=snapshot.tags | {COMPLETION_TAG: 'complete'}, enable_auto_generation=False)
        try:
            self.vault.update_secret(self.secret_id, details, if_match=snapshot.etag,
                                     retry_strategy=NoneRetryStrategy())
        except Exception:
            pass  # A lost response can mean committed; inspect, never replay the write.
        return encoded

    def _confirm_completion(self):
        for current in self._confirmations():
            return current
        raise SetupError()

    def _confirmations(self):
        deadline = self.monotonic() + 30
        for attempt in range(16):
            if attempt and self.monotonic() >= deadline:
                break
            try:
                current = self.read().value
                if 'password' in current:
                    yield current
            except SetupError:
                pass  # Accepted writes can precede readable, coherent CURRENT content.
            remaining = deadline - self.monotonic()
            if attempt == 15 or remaining <= 0:
                break
            self.sleep(min(2, remaining))

    def close(self):
        for client in (self.vault, self.bundles):
            try:
                client.base_client.session.close()
            except Exception:
                pass

"""Owned Vault credentials: compare CURRENT in memory, guard changes, never log values."""

import base64
from datetime import datetime, timedelta, timezone

from oci.vault import models

from deployment.application_configuration import regional_identifier
from deployment.configuration import DeploymentError
from deployment.resource_jobs import retry_token
from energy_ai.web.passwords import valid_password


ROLES = {'demo_password': 'demo-password', 'openai': 'openai', 'anthropic': 'anthropic'}
_PENDING = {'PENDING_DELETION', 'SCHEDULING_DELETION'}


class RuntimeSecrets:
    def __init__(self, client, reader, config, repository, vault_id, key_id, deadline):
        self.client, self.reader, self.config = client, reader, config
        self.vault_id, self.key_id, self.deadline = vault_id, key_id, deadline
        self.names = {role: f'oci-energy-ai-{config.deployment_id}-{suffix}' for role, suffix in ROLES.items()}
        self.tags = {'application': 'oci-energy-ai', 'deployment_id': config.deployment_id,
                     'repository': repository, 'managed_by': 'github-actions'}
        self.repository = repository

    def _verify(self, secret, role):
        if (not regional_identifier(secret.id, 'vaultsecret', self.config.region)
                or secret.compartment_id != self.config.compartment_ocid
                or secret.vault_id != self.vault_id or secret.key_id != self.key_id
                or secret.secret_name != self.names[role]
                or any((secret.freeform_tags or {}).get(k) != v for k, v in self.tags.items())):
            raise DeploymentError('Vault credential ownership does not match; refusing adoption.')

    def _get(self, secret_id, role, *, pending=False):
        while True:
            result = self.deadline.call(self.client.get_secret, secret_id)
            self._verify(result.data, role)
            if result.data.id != secret_id:
                raise DeploymentError('Vault credential identity changed.')
            state = result.data.lifecycle_state
            if state == 'ACTIVE' or pending and state in _PENDING:
                if not isinstance(result.headers.get('etag'), str) or not result.headers['etag']:
                    raise DeploymentError('Vault credential ETag missing.')
                return result
            if state not in {'CREATING', 'UPDATING'}:
                raise DeploymentError('Vault credential is not active; inspect its lifecycle.')
            self.deadline.pause()

    def inventory(self):
        """All returned children, not just expected names; used before parent deletion."""
        result = {}
        reverse = {name: role for role, name in self.names.items()}
        for secret in self.deadline.pages(self.client.list_secrets, self.config.compartment_ocid,
                                          vault_id=self.vault_id):
            role = reverse.get(secret.secret_name)
            if role is None or role in result:
                raise DeploymentError('Vault contains unknown or duplicate credentials; cleanup refused.')
            result[role] = self._get(secret.id, role, pending=True)
        return result

    def _current(self, secret_id):
        try:
            bundle = self.deadline.call(self.reader.get_secret_bundle, secret_id, stage='CURRENT').data
            content = bundle.secret_bundle_content
            if (bundle.secret_id != secret_id or 'CURRENT' not in (bundle.stages or [])
                    or content.content_type != 'BASE64' or not isinstance(content.content, str)
                    or len(content.content) > 32768):
                raise ValueError()
            return base64.b64decode(content.content, validate=True).decode('utf-8')
        except Exception:
            raise DeploymentError('Vault CURRENT credential could not be verified.') from None

    def synchronize(self, values):
        if (not isinstance(values, dict) or 'demo_password' not in values or set(values) - set(ROLES)
                or not valid_password(values['demo_password'])
                or any(not isinstance(v, str) or not 1 <= len(v) <= 4096
                       or any(not 33 <= ord(c) <= 126 for c in v)
                       for k, v in values.items() if k != 'demo_password')):
            raise DeploymentError('Invalid runtime credential inputs.')
        existing = self.inventory()
        result = {}
        for role, value in values.items():
            content = models.Base64SecretContentDetails(
                content=base64.b64encode(value.encode('utf-8')).decode('ascii'), stage='CURRENT')
            if role not in existing:
                created = self.deadline.call(self.client.create_secret, models.CreateSecretDetails(
                    compartment_id=self.config.compartment_ocid, vault_id=self.vault_id,
                    key_id=self.key_id, secret_name=self.names[role], freeform_tags=self.tags,
                    secret_content=content),
                    opc_retry_token=retry_token(self.repository, self.vault_id, self.names[role]))
                current = self._get(created.data.id, role)
            else:
                current = self._get(existing[role].data.id, role)
                if self._current(current.data.id) != value:
                    try:
                        self.deadline.call(self.client.update_secret, current.data.id,
                            models.UpdateSecretDetails(secret_content=content), if_match=current.headers['etag'])
                    except DeploymentError:
                        # An ambiguous response may follow a committed write. Never resubmit here.
                        self._get(current.data.id, role)
                        if self._current(current.data.id) != value:
                            raise DeploymentError('Vault credential update was not verified; inspect before retrying.') from None
                        result[role] = current.data.id
                        continue
                    current = self._get(current.data.id, role)
            if self._current(current.data.id) != value:
                raise DeploymentError('Vault CURRENT credential does not match; activation stopped.')
            result[role] = current.data.id
        return result

    def schedule_deletion(self, inventory):
        for role, earlier in inventory.items():
            current = self._get(earlier.data.id, role, pending=True)
            if current.data.lifecycle_state in _PENDING:
                continue
            self.deadline.call(self.client.schedule_secret_deletion, current.data.id,
                models.ScheduleSecretDeletionDetails(time_of_deletion=datetime.now(timezone.utc) + timedelta(days=2)),
                if_match=current.headers['etag'])

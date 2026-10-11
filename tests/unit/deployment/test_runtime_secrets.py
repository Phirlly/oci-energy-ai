import base64
from datetime import datetime, timezone
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from oci.exceptions import ServiceError
from oci.secrets import models as bundles
from oci.vault import models

from deployment.configuration import DeploymentError
from deployment.resource_jobs import OperationDeadline
from deployment.runtime_secrets import RuntimeSecrets
from tests.fixtures.resource_manager import CONFIG, REPOSITORY, response


VAULT = 'ocid1.vault.oc1.iad.' + 'v' * 32
KEY = 'ocid1.key.oc1.iad.' + 'k' * 32
SECRET = 'ocid1.vaultsecret.oc1.iad.' + 's' * 32


class RuntimeSecretTests(unittest.TestCase):
    def setUp(self):
        self.client, self.reader = Mock(), Mock()
        self.clock = 0
        self.deadline = OperationDeadline(60, lambda: self.clock, self.advance)
        self.store = RuntimeSecrets(self.client, self.reader, CONFIG, REPOSITORY, VAULT, KEY, self.deadline)
        self.secret = models.Secret(id=SECRET, compartment_id=CONFIG.compartment_ocid,
            vault_id=VAULT, key_id=KEY, secret_name='oci-energy-ai-energy-demo-demo-password',
            freeform_tags=self.store.tags, lifecycle_state='ACTIVE')
        self.client.list_secrets.return_value = response([self.secret])
        self.client.get_secret.return_value = NS(data=self.secret, headers={'etag': 'guard'})
        self.client.create_secret.return_value = response(self.secret)
        self.reader.get_secret_bundle.return_value = self.bundle('admin')

    def advance(self, seconds):
        self.clock += seconds

    def bundle(self, value):
        return response(bundles.SecretBundle(secret_id=SECRET, stages=['CURRENT'],
            secret_bundle_content=bundles.Base64SecretBundleContentDetails(
                content=base64.b64encode(value.encode()).decode())))

    def test_repeat_skips_versions_and_changed_password_uses_etag(self):
        self.assertEqual(self.store.synchronize({'demo_password': 'admin'}), {'demo_password': SECRET})
        self.client.update_secret.assert_not_called()
        self.reader.get_secret_bundle.side_effect = [self.bundle('admin'), self.bundle('changed')]
        self.store.synchronize({'demo_password': 'changed'})
        args, options = self.client.update_secret.call_args
        self.assertEqual(args[0], SECRET)
        self.assertEqual(base64.b64decode(args[1].secret_content.content), b'changed')
        self.assertEqual(args[1].secret_content.stage, 'CURRENT')
        self.assertEqual(options['if_match'], 'guard')
        self.assertNotIn('opc_retry_token', options)

    def test_create_uses_owned_metadata_and_stable_retry_identity(self):
        self.client.list_secrets.return_value = response([])
        self.store.synchronize({'demo_password': 'admin'})
        details = self.client.create_secret.call_args.args[0]
        self.assertEqual((details.vault_id, details.key_id, details.compartment_id),
                         (VAULT, KEY, CONFIG.compartment_ocid))
        self.assertEqual(details.freeform_tags, self.store.tags)
        token = self.client.create_secret.call_args.kwargs['opc_retry_token']
        self.store.synchronize({'demo_password': 'admin'})
        self.assertEqual(self.client.create_secret.call_args.kwargs['opc_retry_token'], token)

    def test_ambiguous_update_is_resolved_by_current_value_without_resubmission(self):
        self.reader.get_secret_bundle.side_effect = [self.bundle('old'), self.bundle('admin')]
        self.client.update_secret.side_effect = ServiceError(500, 'Internal', {}, 'private-detail')
        self.store.synchronize({'demo_password': 'admin'})
        self.assertEqual(self.client.update_secret.call_count, 1)
        self.reader.get_secret_bundle.side_effect = [self.bundle('old'), self.bundle('old')]
        with self.assertRaisesRegex(DeploymentError, 'credential') as raised:
            self.store.synchronize({'demo_password': 'admin'})
        self.assertNotIn('private-detail', str(raised.exception))

    def test_foreign_pending_duplicate_or_wrong_bundle_cannot_be_adopted(self):
        for field, value in [('key_id', KEY + 'foreign'), ('freeform_tags', {}),
                             ('lifecycle_state', 'PENDING_DELETION')]:
            with self.subTest(field=field):
                original = getattr(self.secret, field)
                setattr(self.secret, field, value)
                with self.assertRaises(DeploymentError):
                    self.store.synchronize({'demo_password': 'admin'})
                setattr(self.secret, field, original)
        self.client.list_secrets.return_value = response([self.secret, self.secret])
        with self.assertRaises(DeploymentError):
            self.store.synchronize({'demo_password': 'admin'})
        self.client.list_secrets.return_value = response([self.secret])
        self.reader.get_secret_bundle.return_value.data.secret_id = SECRET + 'foreign'
        with self.assertRaises(DeploymentError):
            self.store.synchronize({'demo_password': 'admin'})
        self.client.create_secret.assert_not_called()
        self.client.update_secret.assert_not_called()

    def test_inventory_is_paginated_unfiltered_and_rejects_unknown_before_cleanup(self):
        unknown = NS(secret_name='someone-else', id=SECRET + 'other')
        self.client.list_secrets.side_effect = [NS(data=[self.secret], headers={'opc-next-page': 'next'}),
                                                response([unknown])]
        with self.assertRaisesRegex(DeploymentError, 'unknown'):
            self.store.inventory()
        self.assertEqual(self.client.list_secrets.call_args.kwargs,
                         {'vault_id': VAULT, 'page': 'next'})
        self.client.schedule_secret_deletion.assert_not_called()

    def test_cleanup_preserves_pending_schedule_and_guards_new_schedule(self):
        self.secret.lifecycle_state = 'PENDING_DELETION'
        self.secret.time_of_deletion = datetime(2026, 10, 20, tzinfo=timezone.utc)
        inventory = self.store.inventory()
        self.store.schedule_deletion(inventory)
        self.client.schedule_secret_deletion.assert_not_called()
        self.secret.lifecycle_state = 'ACTIVE'
        self.store.schedule_deletion(self.store.inventory())
        self.assertEqual(self.client.schedule_secret_deletion.call_args.kwargs['if_match'], 'guard')

    def test_bad_input_is_rejected_before_any_cloud_operation(self):
        for values in ({}, {'demo_password': ' '}, {'demo_password': 'admin', 'openai': 'a b'}):
            with self.subTest(values=tuple(values)), self.assertRaises(DeploymentError):
                self.store.synchronize(values)
        self.client.list_secrets.assert_not_called()

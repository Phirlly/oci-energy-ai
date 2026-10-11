import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from oci.response import Response
from oci.retry import NoneRetryStrategy

from deployment.configuration import DeploymentConfiguration, DeploymentError
from deployment.oci_identity import resource_manager_client, DeliveryClients
from deployment.resource_manager import ResourceManager
from tests.fixtures.deployment_environment import configured_environment


class DeploymentIdentityTests(unittest.TestCase):
    @patch("deployment.oci_identity.ResourceManagerClient")
    @patch("deployment.oci_identity.Signer")
    def test_identity_is_in_memory_with_bounded_requests_and_no_sdk_retries(self, signer, client):
        environment = configured_environment() | {"OCI_PRIVATE_KEY_PASSPHRASE": "fake-passphrase"}
        result = resource_manager_client(environment)
        self.assertIs(result, client.return_value)
        self.assertIsNone(signer.call_args.kwargs["private_key_file_location"])
        self.assertEqual(signer.call_args.kwargs["private_key_content"], environment["OCI_PRIVATE_KEY"])
        self.assertEqual(signer.call_args.kwargs["pass_phrase"], "fake-passphrase")
        options = client.call_args.kwargs
        self.assertEqual(options["timeout"], (10, 30))
        self.assertIsInstance(options["retry_strategy"], NoneRetryStrategy)
        config = client.call_args.args[0]
        self.assertEqual(config["region"], "us-ashburn-1")
        self.assertEqual(config["key_content"], environment["OCI_PRIVATE_KEY"])
        self.assertNotIn("key_file", config)

    @patch("oci.config.from_file")
    @patch("oci.signer.load_private_key_from_file")
    def test_real_sdk_client_accepts_generated_in_memory_identity_without_files(self, key_file, profile):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        environment = configured_environment() | {"OCI_PRIVATE_KEY": pem}
        client = resource_manager_client(environment)
        self.assertEqual(client.base_client.endpoint, "https://resourcemanager.us-ashburn-1.oraclecloud.com/20180917")
        config = DeploymentConfiguration("fixture-demo", environment["OCI_REGION"], environment["OCI_COMPARTMENT_OCID"])
        with patch.object(client.base_client, "call_api", return_value=Response(200, {}, [], None)) as transport:
            manager = ResourceManager(client, config, "example/oci-energy-ai", "123-1")
            self.assertFalse(manager.destroy("fixture-demo"))
        transport.assert_called_once()
        self.assertEqual(transport.call_args.kwargs["method"], "GET")
        self.assertEqual(transport.call_args.kwargs["query_params"], {"compartmentId": config.compartment_ocid})
        key_file.assert_not_called()
        profile.assert_not_called()

    @patch("deployment.oci_identity.ResourceManagerClient")
    @patch("deployment.oci_identity.Signer")
    def test_incomplete_configuration_fails_before_key_parse_or_client_creation(self, signer, client):
        with self.assertRaisesRegex(DeploymentError, "configuration"):
            resource_manager_client({})
        signer.assert_not_called()
        client.assert_not_called()

    def test_invalid_private_key_returns_fixed_error_without_secret_or_traceback(self):
        with self.assertRaisesRegex(DeploymentError, "signing key") as raised:
            resource_manager_client(configured_environment())
        self.assertNotIn("fake-private-key", str(raised.exception))

    @patch('deployment.oci_identity.deployment_identity')
    def test_delivery_clients_close_every_session_including_per_vault_clients(self, identity):
        from unittest.mock import Mock
        identity.return_value = ({'region': 'us-ashburn-1'}, object())
        constructors = {name: Mock() for name in DeliveryClients.SERVICES}
        key_factory = Mock()
        with patch.dict(DeliveryClients.SERVICES, constructors), patch('deployment.oci_identity.KmsManagementClient', key_factory):
            with self.assertRaisesRegex(RuntimeError, 'fixture'):
                with DeliveryClients(configured_environment()) as clients:
                    self.assertIs(clients.keys('https://fixture.oraclecloud.com'), key_factory.return_value)
                    self.assertIs(clients.keys('https://fixture.oraclecloud.com'), key_factory.return_value)
                    raise RuntimeError('fixture')
        key_factory.assert_called_once()
        for constructor in [*constructors.values(), key_factory]:
            self.assertEqual(constructor.call_args.kwargs['timeout'], (10, 30))
            self.assertIsInstance(constructor.call_args.kwargs['retry_strategy'], NoneRetryStrategy)
            constructor.return_value.base_client.session.close.assert_called_once()

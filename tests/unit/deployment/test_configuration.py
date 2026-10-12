import unittest

from deployment.configuration import DeploymentConfiguration


class DeploymentConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.valid = {
            "deployment_id": "energy-demo",
            "region": "us-ashburn-1",
            "compartment_ocid": "ocid1.compartment.oc1.." + "a" * 32,
        }

    def test_valid_configuration_emits_only_terraform_inputs(self):
        config = DeploymentConfiguration.from_mapping(self.valid)
        self.assertEqual(config.terraform_variables(), self.valid)
        self.assertEqual(config.deployment_id, "energy-demo")

    def test_rejects_missing_unknown_and_credential_fields(self):
        for value in ({}, {**self.valid, "private_key": "private-marker"},
                      {**self.valid, "profile": "DEFAULT"}, [], None):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                DeploymentConfiguration.from_mapping(value)
            self.assertNotIn("private-marker", str(error.exception))

    def test_root_compartment_emits_the_same_three_terraform_inputs(self):
        values = self.valid | {"compartment_ocid": "ocid1.tenancy.oc1.." + "a" * 32}
        self.assertEqual(DeploymentConfiguration.from_mapping(values).terraform_variables(), values)

    def test_rejects_unsafe_or_ambiguous_identifiers(self):
        invalid = {
            "deployment_id": ("ab", "A-demo", "-demo", "demo-", "a" * 33, "x\ny", True),
            "region": ("", "US-ASHBURN-1", "us-ashburn-0", "../region", None),
            "compartment_ocid": ("ocid1.tenancy.oc2.." + "a" * 32,
                                 "ocid1.user.oc1.." + "a" * 32,
                                 "ocid1.tenancy.oc1.." + "a" * 32 + "\n",
                                 "ocid1.compartment.oc2.." + "a" * 32, "fake", 42),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    DeploymentConfiguration.from_mapping({**self.valid, field: value})

    def test_direct_construction_cannot_bypass_validation(self):
        with self.assertRaises(ValueError):
            DeploymentConfiguration(**{**self.valid, "deployment_id": "../../demo"})

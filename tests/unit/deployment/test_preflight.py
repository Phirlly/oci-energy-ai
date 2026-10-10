import unittest

from deployment.preflight import check_deployment_setup, format_setup_report
from tests.fixtures.deployment_environment import configured_environment


class DeploymentSetupTests(unittest.TestCase):
    def setUp(self):
        self.environment = configured_environment()

    def statuses(self, report):
        return {check.setting: check.status for check in report.checks}

    def test_oci_only_passes_configuration_without_claiming_live_access(self):
        report = check_deployment_setup(self.environment)
        self.assertTrue(report.complete)
        statuses = self.statuses(report)
        self.assertEqual(statuses["OCI_REGION"], "format_accepted")
        self.assertEqual(statuses["OCI_PRIVATE_KEY"], "supplied_unverified")
        self.assertEqual(statuses["OPENAI_API_KEY"], "not_configured")
        self.assertEqual(statuses["ANTHROPIC_API_KEY"], "not_configured")
        self.assertIn("Live authentication, permissions and model calls were not checked",
                      format_setup_report(report))

    def test_optional_keys_are_independent_and_remain_unverified(self):
        for names in (("OPENAI_API_KEY",), ("ANTHROPIC_API_KEY",),
                      ("OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                       "OCI_PRIVATE_KEY_PASSPHRASE")):
            with self.subTest(names=names):
                environment = {**self.environment, **dict.fromkeys(names, "fake-marker")}
                report = check_deployment_setup(environment)
                self.assertTrue(report.complete)
                for name in names:
                    self.assertEqual(self.statuses(report)[name], "supplied_unverified")

    def test_all_missing_required_settings_are_reported_together(self):
        report = check_deployment_setup({})
        self.assertFalse(report.complete)
        missing = {check.setting for check in report.checks if check.status == "missing"}
        self.assertEqual(missing, set(self.environment))

    def test_missing_private_key_cannot_pass(self):
        del self.environment["OCI_PRIVATE_KEY"]
        report = check_deployment_setup(self.environment)
        self.assertFalse(report.complete)
        self.assertEqual(self.statuses(report)["OCI_PRIVATE_KEY"], "missing")

    def test_empty_or_whitespace_required_values_are_missing(self):
        for name in self.environment:
            for value in ("", " \n\t"):
                with self.subTest(name=name, value=value):
                    report = check_deployment_setup({**self.environment, name: value})
                    self.assertFalse(report.complete)
                    self.assertEqual(self.statuses(report)[name], "missing")

    def test_invalid_required_formats_are_rejected_without_echoing_values(self):
        invalid = {
            "DEPLOYMENT_ID": ("../private-marker", "ab", "UPPER"),
            "OCI_REGION": (" ../private-marker ", "us-ashburn-0"),
            "OCI_COMPARTMENT_OCID": ("private-marker", self.environment["OCI_USER_OCID"]),
            "OCI_TENANCY_OCID": ("private-marker", self.environment["OCI_USER_OCID"]),
            "OCI_USER_OCID": ("private-marker", self.environment["OCI_TENANCY_OCID"]),
            "OCI_FINGERPRINT": ("private-marker", "ab:" * 15, "ab" * 16),
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    report = check_deployment_setup({**self.environment, name: value})
                    self.assertFalse(report.complete)
                    self.assertEqual(self.statuses(report)[name], "invalid")
                    self.assertNotIn("private-marker", format_setup_report(report))

    def test_padded_identifiers_are_rejected_and_mixed_case_fingerprint_is_valid(self):
        for name, value in self.environment.items():
            if name == "OCI_PRIVATE_KEY":
                continue
            with self.subTest(name=name):
                report = check_deployment_setup({**self.environment, name: value + "\n"})
                self.assertEqual(self.statuses(report)[name], "invalid")
        self.environment["OCI_FINGERPRINT"] = ":".join(["aB"] * 16)
        self.assertTrue(check_deployment_setup(self.environment).complete)


class SetupReportPrivacyTests(unittest.TestCase):
    def test_report_contains_no_input_values_or_unrelated_settings(self):
        environment = {
            **configured_environment(),
            "OPENAI_API_KEY": "fake-openai-marker\n::error::do-not-print",
            "ANTHROPIC_API_KEY": "fake-anthropic-marker",
            "OCI_PRIVATE_KEY_PASSPHRASE": "fake-passphrase-marker",
            "UNRELATED_SECRET": "unrelated-secret-marker",
        }
        original = dict(environment)
        report = check_deployment_setup(environment)
        rendered = format_setup_report(report)
        self.assertEqual(environment, original)
        self.assertEqual(report, check_deployment_setup(environment))
        for value in environment.values():
            self.assertNotIn(value, rendered)
            self.assertNotIn(value, repr(report))
        self.assertNotIn("UNRELATED_SECRET", rendered)
        self.assertNotIn("::error::", rendered)

    def test_whitespace_optional_keys_stay_unconfigured(self):
        report = check_deployment_setup({**configured_environment(), "OPENAI_API_KEY": " \n"})
        self.assertTrue(report.complete)
        optional = {check.setting: check.status for check in report.checks}
        self.assertEqual(optional["OPENAI_API_KEY"], "not_configured")

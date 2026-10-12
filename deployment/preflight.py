"""Check GitHub deployment configuration without authenticating or printing values."""

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
import os
import re

from deployment.configuration import validate_compartment_tenancy, validate_deployment_value
from energy_ai.web.passwords import PASSWORD_GUIDANCE, valid_password


_TERRAFORM_FIELDS = {
    "DEPLOYMENT_ID": "deployment_id",
    "OCI_REGION": "region",
    "OCI_COMPARTMENT_OCID": "compartment_ocid",
}
_IDENTITY_PATTERNS = {
    "OCI_TENANCY_OCID": r"ocid1\.tenancy\.oc1\.\.[a-z0-9]{20,255}",
    "OCI_USER_OCID": r"ocid1\.user\.oc1\.\.[a-z0-9]{20,255}",
    "OCI_FINGERPRINT": r"(?:[a-fA-F0-9]{2}:){15}[a-fA-F0-9]{2}",
}
_VARIABLE_GUIDANCE = {
    "DEPLOYMENT_ID": "3-32 lowercase letters, digits or hyphens; start with a letter, end alphanumeric.",
    "OCI_REGION": "OCI commercial region name; availability is not checked.",
    "OCI_COMPARTMENT_OCID": "OC1 child compartment OCID or the root OCID matching OCI_TENANCY_OCID.",
    "OCI_TENANCY_OCID": "OC1 tenancy OCID for the deployment identity.",
    "OCI_USER_OCID": "OC1 user OCID for the deployment identity.",
    "OCI_FINGERPRINT": "16 colon-separated hexadecimal byte pairs.",
}
_OPTIONAL_SECRETS = (
    "OCI_PRIVATE_KEY_PASSPHRASE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
)
_PROVIDER_KEY_BOUNDS = {
    "OPENAI_API_KEY": (1, 4096), "ANTHROPIC_API_KEY": (1, 4096),
}


@dataclass(frozen=True)
class SetupCheck:
    setting: str
    status: str
    detail: str


@dataclass(frozen=True)
class SetupReport:
    """Contains statuses and fixed guidance only, never supplied configuration."""

    checks: tuple[SetupCheck, ...]

    @property
    def complete(self):
        return all(check.status not in {"missing", "invalid"} for check in self.checks)


def _absent(value):
    return value is None or isinstance(value, str) and not value.strip()


def check_deployment_setup(environment: Mapping[str, str], *, application=False) -> SetupReport:
    checks = []
    for setting, guidance in _VARIABLE_GUIDANCE.items():
        value = environment.get(setting)
        status = "format_accepted"
        if _absent(value):
            status = "missing"
        elif not isinstance(value, str):
            status = "invalid"
        elif setting in _TERRAFORM_FIELDS:
            try:
                validate_deployment_value(_TERRAFORM_FIELDS[setting], value)
                if setting == "OCI_COMPARTMENT_OCID":
                    validate_compartment_tenancy(value, environment.get("OCI_TENANCY_OCID"))
            except ValueError:
                status = "invalid"
        elif not re.fullmatch(_IDENTITY_PATTERNS[setting], value):
            status = "invalid"
        checks.append(SetupCheck(setting, status, guidance))

    settings = ("OCI_PRIVATE_KEY", *_OPTIONAL_SECRETS) + (("DEMO_PASSWORD",) if application else ())
    for setting in settings:
        value = environment.get(setting)
        if application and setting == "DEMO_PASSWORD":
            if value is None or value == "":
                status = "missing"
            else:
                status = "format_accepted" if valid_password(value) else "invalid"
            checks.append(SetupCheck(setting, status, PASSWORD_GUIDANCE))
            continue
        if application and setting in _PROVIDER_KEY_BOUNDS:
            minimum, maximum = _PROVIDER_KEY_BOUNDS[setting]
            if value is None or value == "":
                status = "not_configured"
            elif (not isinstance(value, str) or not minimum <= len(value) <= maximum
                  or any(not 33 <= ord(char) <= 126 for char in value)):
                status = "invalid"
            else:
                status = "format_accepted"
            guidance = (f"{minimum}-{maximum} printable ASCII characters without spaces; "
                        "format only, authentication unverified.")
            checks.append(SetupCheck(setting, status, guidance))
            continue
        if _absent(value):
            status = "missing" if setting == "OCI_PRIVATE_KEY" else "not_configured"
        else:
            status = "supplied_unverified" if isinstance(value, str) else "invalid"
        guidance = "Secret presence only; content and credentials are not validated."
        if setting == "OCI_PRIVATE_KEY_PASSPHRASE":
            guidance = "Needed only for an encrypted private key; not validated."
        checks.append(SetupCheck(setting, status, guidance))
    return SetupReport(tuple(checks))


def format_setup_report(report: SetupReport) -> str:
    result = "Configuration checks passed" if report.complete else "Configuration needs attention"
    lines = [
        "## Deployment configuration check", "", result + ".", "",
        "Live authentication, permissions and model calls were not checked.",
        "No OCI resources were created and no secrets were written to Vault.", "",
        "| Setting | Status | Guidance |", "| --- | --- | --- |",
    ]
    lines.extend(f"| {check.setting} | {check.status} | {check.detail} |" for check in report.checks)
    lines.extend([
        "", "Configure these settings in GitHub Settings > Environments > demo.",
        "Absent external provider keys allow OCI-only setup. Supplied keys do not prove provider support.",
        "Deployment and real model/tool verification remain separate pending steps.",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", action="store_true",
                        help="Also require the browser password and validate runtime credential formats.")
    arguments = parser.parse_args()
    report = check_deployment_setup(os.environ, application=arguments.application)
    print(format_setup_report(report))
    return 0 if report.complete else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Syntactic input validation; live OCI availability is checked separately."""

from dataclasses import asdict, dataclass
import re


class DeploymentError(Exception):
    """Fixed operator guidance safe for deployment logs."""


_PATTERNS = {
    "deployment_id": r"[a-z][a-z0-9-]{1,30}[a-z0-9]",
    "region": r"[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?",
    "compartment_ocid": r"ocid1\.compartment\.oc1\.\.[a-z0-9]{20,255}",
}


def validate_deployment_value(name, value):
    """Validate one Terraform input without including its value in errors."""
    if name not in _PATTERNS:
        raise ValueError("Unknown deployment input.")
    if not isinstance(value, str) or not re.fullmatch(_PATTERNS[name], value):
        raise ValueError(f"Invalid {name}; see deployment input requirements.")


@dataclass(frozen=True)
class DeploymentConfiguration:
    deployment_id: str
    region: str
    compartment_ocid: str

    def __post_init__(self):
        for name in _PATTERNS:
            validate_deployment_value(name, getattr(self, name))

    @classmethod
    def from_mapping(cls, values):
        if not isinstance(values, dict) or set(values) != set(_PATTERNS):
            raise ValueError("Provide exactly deployment_id, region and compartment_ocid.")
        return cls(**values)

    def terraform_variables(self):
        return asdict(self)

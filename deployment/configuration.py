"""Syntactic input validation; live OCI availability is checked separately."""

from dataclasses import asdict, dataclass
import re


_PATTERNS = {
    "deployment_id": r"[a-z][a-z0-9-]{1,30}[a-z0-9]",
    "region": r"[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?",
    "compartment_ocid": r"ocid1\.compartment\.oc1\.\.[a-z0-9]{20,255}",
}


@dataclass(frozen=True)
class DeploymentConfiguration:
    deployment_id: str
    region: str
    compartment_ocid: str

    def __post_init__(self):
        for name, pattern in _PATTERNS.items():
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                raise ValueError(f"Invalid {name}; see deployment input requirements.")

    @classmethod
    def from_mapping(cls, values):
        if not isinstance(values, dict) or set(values) != set(_PATTERNS):
            raise ValueError("Provide exactly deployment_id, region and compartment_ocid.")
        return cls(**values)

    def terraform_variables(self):
        return asdict(self)

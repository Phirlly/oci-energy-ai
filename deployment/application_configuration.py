"""Pinned, nonsecret hosting topology stored in the owned Resource Manager stack."""

from dataclasses import asdict, dataclass
import json
import re

from oci.regions_definitions import REGION_REALMS, REGIONS_SHORT_NAMES

from deployment.configuration import validate_compartment_tenancy


def regional_identifier(value, kind, region):
    """Accept the selected OC1 region's long or short identifier only."""
    aliases = {region} | {short for short, full in REGIONS_SHORT_NAMES.items() if full == region}
    match = re.fullmatch(r"ocid1\." + kind + r"\.oc1\.([a-z0-9-]+)\.[a-z0-9.]{20,255}", value) if isinstance(value, str) else None
    return bool(REGION_REALMS.get(region) == "oc1" and match and match[1] in aliases)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


@dataclass(frozen=True)
class ApplicationConfiguration:
    version: int
    tenancy_ocid: str
    home_region: str
    availability_domain: str
    image_ocid: str

    def __post_init__(self):
        if (type(self.version) is not int or self.version != 1
                or not isinstance(self.tenancy_ocid, str)
                or not re.fullmatch(r"ocid1\.tenancy\.oc1\.\.[a-z0-9]{20,255}", self.tenancy_ocid)
                or not isinstance(self.home_region, str) or REGION_REALMS.get(self.home_region) != "oc1"
                or not isinstance(self.availability_domain, str)
                or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", self.availability_domain)
                or not isinstance(self.image_ocid, str)
                or not re.fullmatch(r"ocid1\.image\.oc1\.[a-z0-9-]+\.[a-z0-9.]{20,255}", self.image_ocid)):
            raise ValueError("Invalid application topology configuration.")

    def validate_region(self, region):
        if not regional_identifier(self.image_ocid, "image", region):
            raise ValueError("Application image does not match the deployment region.")

    def to_json(self):
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value):
        try:
            if not isinstance(value, str) or len(value.encode("utf-8")) + len("application") > 8192:
                raise ValueError()
            data = json.loads(value, object_pairs_hook=_unique_object)
            if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
                raise ValueError()
            return cls(**data)
        except (TypeError, ValueError, RecursionError):
            raise ValueError("Invalid application topology configuration.") from None


def stack_application(variables, config):
    """Validate every stack variable; return its optional hosting topology."""
    base = config.terraform_variables()
    if (not isinstance(variables, dict) or set(variables) not in (set(base), set(base) | {"application"})
            or any(variables.get(key) != value for key, value in base.items())):
        raise ValueError("Stack variables do not match the deployment.")
    if "application" not in variables:
        return None
    application = ApplicationConfiguration.from_json(variables["application"])
    application.validate_region(config.region)
    validate_compartment_tenancy(config.compartment_ocid, application.tenancy_ocid)
    return application

locals {
  application_count = local.application == null ? 0 : 1
  resource_prefix   = "oci-energy-ai-${var.deployment_id}"
  root_compartment  = startswith(var.compartment_ocid, "ocid1.tenancy.")
  ownership_tags = {
    application   = "oci-energy-ai"
    deployment_id = var.deployment_id
    managed_by    = "terraform"
  }
}

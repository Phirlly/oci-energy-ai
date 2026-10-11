locals {
  application_count = var.application == null ? 0 : 1
  resource_prefix   = "oci-energy-ai-${var.deployment_id}"
  ownership_tags = {
    application   = "oci-energy-ai"
    deployment_id = var.deployment_id
    managed_by    = "terraform"
  }
}

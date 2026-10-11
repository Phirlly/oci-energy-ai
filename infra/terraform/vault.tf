resource "oci_kms_vault" "app" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  display_name   = local.resource_prefix
  vault_type     = "DEFAULT"
  freeform_tags  = local.ownership_tags
}

resource "oci_kms_key" "app" {
  count               = local.application_count
  compartment_id      = var.compartment_ocid
  display_name        = "${local.resource_prefix}-secrets"
  management_endpoint = oci_kms_vault.app[0].management_endpoint
  protection_mode     = "SOFTWARE"
  freeform_tags       = local.ownership_tags
  key_shape {
    algorithm = "AES"
    length    = 32
  }
}

# Secret values are synchronized by the deployment SDK, never Terraform state.

resource "oci_vault_secret" "settings" {
  count                  = var.console_install ? 1 : 0
  compartment_id         = var.compartment_ocid
  vault_id               = oci_kms_vault.app[0].id
  key_id                 = oci_kms_key.app[0].id
  secret_name            = "${local.resource_prefix}-settings"
  freeform_tags          = local.ownership_tags
  enable_auto_generation = true
  secret_generation_context {
    generation_type     = "PASSPHRASE"
    generation_template = "SECRETS_DEFAULT_PASSWORD"
    passphrase_length   = 32
    secret_template     = jsonencode({ version = 1, setup_code = "%GENERATED_PASSPHRASE%" })
  }
  lifecycle {
    ignore_changes = all
    postcondition {
      condition     = self.compartment_id == var.compartment_ocid && self.vault_id == oci_kms_vault.app[0].id && self.key_id == oci_kms_key.app[0].id && self.secret_name == "${local.resource_prefix}-settings" && alltrue([for key, value in local.ownership_tags : lookup(self.freeform_tags, key, "") == value])
      error_message = "Settings ownership changed; stop and inspect the existing installation."
    }
  }
}

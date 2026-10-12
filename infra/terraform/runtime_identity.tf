resource "oci_identity_dynamic_group" "app" {
  provider       = oci.home
  count          = local.application_count
  compartment_id = local.application.tenancy_ocid
  name           = "${local.resource_prefix}-runtime"
  description    = "Exact OCI Energy AI application instance"
  matching_rule  = "instance.id = '${oci_core_instance.app[0].id}'"
  freeform_tags  = local.ownership_tags
}

resource "oci_identity_policy" "app" {
  provider       = oci.home
  count          = local.application_count
  compartment_id = local.application.tenancy_ocid
  name           = "${local.resource_prefix}-runtime"
  description    = "Read demo artifacts and secrets, run own commands and invoke Responses"
  freeform_tags  = local.ownership_tags
  statements = concat(var.console_install ? [
    "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to use secrets in compartment id ${var.compartment_ocid} where all {target.secret.id = '${oci_vault_secret.settings[0].id}', any {request.permission = 'SECRET_READ', request.permission = 'SECRET_UPDATE'}}",
    "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to read secret-bundles in compartment id ${var.compartment_ocid} where all {target.secret.id = '${oci_vault_secret.settings[0].id}', request.permission = 'SECRET_BUNDLE_READ'}",
    ] : [
    "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to read objects in compartment id ${var.compartment_ocid} where target.bucket.name = '${oci_objectstorage_bucket.artifacts.name}'",
    "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to read secret-bundles in compartment id ${var.compartment_ocid} where any {target.secret.name = '${local.resource_prefix}-demo-password', target.secret.name = '${local.resource_prefix}-openai', target.secret.name = '${local.resource_prefix}-anthropic'}",
    ], [
    "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to use instance-agent-command-execution-family in compartment id ${var.compartment_ocid} where request.instance.id = target.instance.id",
    "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to manage generative-ai-response in compartment id ${var.compartment_ocid}",
  ])
}

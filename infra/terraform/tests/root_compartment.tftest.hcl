mock_provider "oci" {
  source = "./tests/fixtures"
  mock_resource "oci_generative_ai_project" {
    defaults = { id = "ocid1.generativeaiproject.oc1.iad.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  }
  mock_resource "oci_apigateway_gateway" {
    defaults = { hostname = "example.apigateway.us-ashburn-1.oci.customer-oci.com" }
  }
  mock_resource "oci_vault_secret" {
    defaults = { id = "ocid1.vaultsecret.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
  }
  mock_resource "oci_core_instance" {
    defaults = { private_ip = "10.40.1.10" }
  }
}
mock_provider "oci" {
  alias  = "home"
  source = "./tests/fixtures"
}

variables {
  deployment_id       = "root-demo"
  region              = "us-ashburn-1"
  compartment_ocid    = "ocid1.tenancy.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  console_install     = true
  tenancy_ocid        = "ocid1.tenancy.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  availability_domain = "EXAMPLE:US-ASHBURN-AD-1"
  image_ocid          = "ocid1.image.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  console_release = {
    artifact_base = "https://objectstorage.us-ashburn-1.oraclecloud.com/n/example/b/public/o/"
    release       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    host_digest   = sha256(join("", [for name in ["__init__.py", "activation.py", "artifacts.py", "bootstrap.sh", "console_contract.py", "console_install.py", "console_sources.py", "contracts.py", "control.py", "entrypoint.py", "install_entry.py", "oci-energy-ai-install.service", "oci-energy-ai-install.timer", "oci-energy-ai.service", "process.py", "service.py", "service_entry.py", "state.py"] : filesha256("host/${name}")]))
    image_id      = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    image_sha256  = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    image_bytes   = 123456
  }
}

run "foreign_root_console_is_rejected" {
  command = plan
  variables { tenancy_ocid = "ocid1.tenancy.oc1..ffffffffffffffffffffffffffffffff" }
  expect_failures = [terraform_data.installation]
}

run "foreign_root_github_is_rejected" {
  command = plan
  variables {
    console_install = false
    application = {
      version             = 1
      tenancy_ocid        = "ocid1.tenancy.oc1..ffffffffffffffffffffffffffffffff"
      home_region         = "us-phoenix-1"
      availability_domain = "EXAMPLE:US-ASHBURN-AD-1"
      image_ocid          = "ocid1.image.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  }
  expect_failures = [terraform_data.installation]
}

run "github_root_keeps_bucket_and_secret_access_scoped" {
  command   = apply
  state_key = "github"
  variables {
    console_install = false
    application = {
      version             = 1
      tenancy_ocid        = "ocid1.tenancy.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      home_region         = "us-phoenix-1"
      availability_domain = "EXAMPLE:US-ASHBURN-AD-1"
      image_ocid          = "ocid1.image.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  }
  assert {
    condition = toset(oci_identity_policy.app[0].statements) == toset([
      "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to read objects in tenancy where target.bucket.name = '${oci_objectstorage_bucket.artifacts.name}'",
      "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to read secret-bundles in tenancy where all {target.compartment.id = '${var.compartment_ocid}', any {target.secret.name = '${local.resource_prefix}-demo-password', target.secret.name = '${local.resource_prefix}-openai', target.secret.name = '${local.resource_prefix}-anthropic'}}",
      "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to use instance-agent-command-execution-family in tenancy where request.instance.id = target.instance.id",
      "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to manage generative-ai-response in tenancy where target.compartment.id = '${var.compartment_ocid}'",
    ])
    error_message = "Root GitHub policies must retain exact bucket, root secret names, own-instance and root Responses limits."
  }
}

run "console_root_creates_scoped_runtime_in_selected_root" {
  command = apply
  assert {
    condition = alltrue([
      for compartment in [oci_objectstorage_bucket.artifacts.compartment_id, oci_generative_ai_project.energy.compartment_id, oci_core_instance.app[0].compartment_id, oci_core_vcn.app[0].compartment_id, oci_kms_vault.app[0].compartment_id, oci_kms_key.app[0].compartment_id, oci_vault_secret.settings[0].compartment_id, oci_apigateway_gateway.app[0].compartment_id, oci_identity_policy.app[0].compartment_id, oci_identity_dynamic_group.app[0].compartment_id] : compartment == var.compartment_ocid
    ]) && oci_identity_dynamic_group.app[0].matching_rule == "instance.id = '${oci_core_instance.app[0].id}'"
    error_message = "The root install must target its selected root and exact runtime instance."
  }
  assert {
    condition = toset(oci_identity_policy.app[0].statements) == toset([
      "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to use secrets in tenancy where all {target.secret.id = '${oci_vault_secret.settings[0].id}', any {request.permission = 'SECRET_READ', request.permission = 'SECRET_UPDATE'}}",
      "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to read secret-bundles in tenancy where all {target.secret.id = '${oci_vault_secret.settings[0].id}', request.permission = 'SECRET_BUNDLE_READ'}",
      "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to use instance-agent-command-execution-family in tenancy where request.instance.id = target.instance.id",
      "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to manage generative-ai-response in tenancy where target.compartment.id = '${var.compartment_ocid}'",
    ])
    error_message = "Root Console policies must retain exact settings permissions, own-instance and root Responses limits."
  }
}

run "unchanged_root_reapply_preserves_host_and_settings" {
  command = apply
  assert {
    condition     = output.instance_ocid == run.console_root_creates_scoped_runtime_in_selected_root.instance_ocid && output.settings_secret_ocid == run.console_root_creates_scoped_runtime_in_selected_root.settings_secret_ocid && terraform_data.installation.output == terraform_data.installation.input
    error_message = "Unchanged root install must preserve the host, settings and saved topology."
  }
}

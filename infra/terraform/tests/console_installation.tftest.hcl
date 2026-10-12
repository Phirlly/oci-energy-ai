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
  deployment_id       = "console-demo"
  region              = "us-ashburn-1"
  compartment_ocid    = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
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

run "first_install_has_private_runtime_and_exact_settings_permissions" {
  command = apply
  assert {
    condition     = local.application.home_region == "us-phoenix-1" && length(oci_core_instance.app) == 1
    error_message = "Console resolves home-region identity and creates the application."
  }
  assert {
    condition     = toset(keys(oci_core_instance.app[0].metadata)) == toset(["user_data", "energy_ai_install"]) && length(jsonencode(oci_core_instance.app[0].metadata)) < 32000
    error_message = "Combined metadata must fit and include the desired install."
  }
  assert {
    condition     = jsondecode(oci_core_instance.app[0].metadata.energy_ai_install).manifest.runtime.version == 2 && !contains(keys(jsondecode(oci_core_instance.app[0].metadata.energy_ai_install).manifest.runtime), "backend_host")
    error_message = "Host derives its backend from IMDS, not its own Terraform IP."
  }
  assert {
    condition     = jsondecode(oci_core_instance.app[0].metadata.energy_ai_install).manifest.runtime.secret_ids.settings == oci_vault_secret.settings[0].id && jsondecode(oci_core_instance.app[0].metadata.energy_ai_install).manifest.runtime.model_ids.openai == "gpt-4.1-2025-04-14"
    error_message = "Setup runtime must select its generated secret and verified model."
  }
  assert {
    condition     = oci_vault_secret.settings[0].enable_auto_generation && length(oci_vault_secret.settings[0].secret_content) == 0 && jsondecode(oci_vault_secret.settings[0].secret_generation_context[0].secret_template).setup_code == "%GENERATED_PASSPHRASE%"
    error_message = "OCI must generate the claim; Terraform cannot contain its value."
  }
  assert {
    condition     = length(oci_identity_policy.app[0].statements) == 4 && contains(oci_identity_policy.app[0].statements, "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to use secrets in compartment id ${var.compartment_ocid} where all {target.secret.id = '${oci_vault_secret.settings[0].id}', any {request.permission = 'SECRET_READ', request.permission = 'SECRET_UPDATE'}}") && contains(oci_identity_policy.app[0].statements, "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to read secret-bundles in compartment id ${var.compartment_ocid} where all {target.secret.id = '${oci_vault_secret.settings[0].id}', request.permission = 'SECRET_BUNDLE_READ'}")
    error_message = "Runtime must have only exact-secret read/update/bundle permissions."
  }
  assert {
    condition     = jsonencode(local.cloud_config.runcmd) == jsonencode([["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", "oci-energy-ai-install.timer"]]) && contains([for item in local.cloud_config.write_files : item.path], "/etc/systemd/system/oci-energy-ai-install.service")
    error_message = "Install timer must start before any package bootstrap."
  }
  assert {
    condition     = output.settings_secret_ocid == oci_vault_secret.settings[0].id && jsondecode(file("schema.yaml")).primaryOutputButton == "$${application_origin}"
    error_message = "Console must expose application link and settings identity only."
  }
}

run "unchanged_reapply_retains_installation_and_settings" {
  command = apply
  assert {
    condition     = oci_core_instance.app[0].id == run.first_install_has_private_runtime_and_exact_settings_permissions.instance_ocid && terraform_data.installation.output == terraform_data.installation.input
    error_message = "Unchanged application must retain its saved topology."
  }
  assert {
    condition     = output.settings_secret_ocid == run.first_install_has_private_runtime_and_exact_settings_permissions.settings_secret_ocid
    error_message = "Reapply must preserve the owned settings secret."
  }
}

run "reject_image_replacement" {
  command = plan
  variables { image_ocid = "ocid1.image.oc1.iad.dddddddddddddddddddddddddddddddd" }
  expect_failures = [oci_core_instance.app]
}
run "reject_ad_replacement" {
  command = plan
  variables { availability_domain = "EXAMPLE:US-ASHBURN-AD-2" }
  expect_failures = [oci_core_instance.app]
}
run "reject_location_change" {
  command = plan
  variables { deployment_id = "renamed-demo" }
  expect_failures = [oci_vault_secret.settings]
}
run "reject_conversion_to_foundation" {
  command = plan
  variables { console_install = false }
  expect_failures = [oci_generative_ai_project.energy]
}
run "explicit_retry_generation_preserves_topology" {
  command = apply
  variables { install_generation = 1 }
  assert {
    condition     = oci_core_instance.app[0].id == run.first_install_has_private_runtime_and_exact_settings_permissions.instance_ocid && jsondecode(oci_core_instance.app[0].metadata.energy_ai_install).generation == 1
    error_message = "A higher attempt budget must not replace the host."
  }
}

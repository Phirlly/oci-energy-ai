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
  console_release = {
    artifact_base = "https://objectstorage.us-ashburn-1.oraclecloud.com/n/example/b/public/o/"
    release       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    host_digest   = sha256(join("", [for name in ["__init__.py", "activation.py", "artifacts.py", "bootstrap.sh", "console_contract.py", "console_install.py", "console_sources.py", "contracts.py", "control.py", "entrypoint.py", "install_entry.py", "oci-energy-ai-install.service", "oci-energy-ai-install.timer", "oci-energy-ai.service", "process.py", "service.py", "service_entry.py", "state.py"] : filesha256("host/${name}")]))
    image_id      = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    image_sha256  = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    image_bytes   = 123456
  }
}

run "automatic_selection_skips_custom_and_wrong_version_images" {
  command = apply
  assert {
    condition     = oci_core_instance.app[0].source_details[0].source_id == "ocid1.image.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    error_message = "Select the newest eligible OL9 platform image without a user image input."
  }
}
run "new_catalog_preserves_initial_image_host_and_settings" {
  command = apply
  override_data {
    target = data.oci_core_images.console[0]
    values = { images = [{ id = "ocid1.image.oc1.iad.cccccccccccccccccccccccccccccccc", operating_system = "Oracle Linux", operating_system_version = "9.9", state = "AVAILABLE", compartment_id = "" }] }
  }
  assert {
    condition     = oci_core_instance.app[0].source_details[0].source_id == "ocid1.image.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" && oci_core_instance.app[0].id == run.automatic_selection_skips_custom_and_wrong_version_images.instance_ocid && output.settings_secret_ocid == run.automatic_selection_skips_custom_and_wrong_version_images.settings_secret_ocid && terraform_data.installation.input == terraform_data.installation.output
    error_message = "A refreshed catalog must not change the image, instance, settings or topology."
  }
}
run "empty_later_catalog_preserves_selected_image" {
  command = apply
  override_data {
    target = data.oci_core_images.console[0]
    values = { images = [] }
  }
  assert {
    condition     = oci_core_instance.app[0].source_details[0].source_id == "ocid1.image.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" && oci_core_instance.app[0].id == run.automatic_selection_skips_custom_and_wrong_version_images.instance_ocid && output.settings_secret_ocid == run.automatic_selection_skips_custom_and_wrong_version_images.settings_secret_ocid
    error_message = "An older image need not remain in the recent catalog to preserve the host."
  }
}
run "changed_explicit_override_is_rejected" {
  command = plan
  variables { image_ocid = "ocid1.image.oc1.iad.dddddddddddddddddddddddddddddddd" }
  expect_failures = [terraform_data.console_image]
}

mock_provider "oci" { source = "./tests/fixtures" }
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

run "reject_mixed_deployment_modes" {
  command = plan
  variables {
    application = { version = 1, tenancy_ocid = "ocid1.tenancy.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", home_region = "us-phoenix-1", availability_domain = "EXAMPLE:US-ASHBURN-AD-1", image_ocid = "ocid1.image.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
  }
  expect_failures = [terraform_data.installation]
}
run "reject_missing_release" {
  command = plan
  variables { console_release = null }
  expect_failures = [terraform_data.installation]
}
run "reject_mismatched_host_release" {
  command = plan
  variables { console_release = merge(var.console_release, { host_digest = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" }) }
  expect_failures = [oci_core_instance.app]
}
run "reject_nonpublic_release_source" {
  command = plan
  variables { console_release = merge(var.console_release, { artifact_base = "https://example.com/private?secret=hidden" }) }
  expect_failures = [var.console_release]
}
run "reject_fractional_generation" {
  command = plan
  variables { install_generation = 0.5 }
  expect_failures = [var.install_generation]
}
run "reject_wrong_operating_system" {
  command = plan
  override_data {
    target = data.oci_core_image.console[0]
    values = { operating_system = "Other Linux", operating_system_version = "9.8", state = "AVAILABLE" }
  }
  expect_failures = [oci_core_instance.app]
}
run "reject_wrong_major_version" {
  command = plan
  override_data {
    target = data.oci_core_image.console[0]
    values = { operating_system = "Oracle Linux", operating_system_version = "8.10", state = "AVAILABLE" }
  }
  expect_failures = [oci_core_instance.app]
}
run "reject_unavailable_image" {
  command = plan
  override_data {
    target = data.oci_core_image.console[0]
    values = { operating_system = "Oracle Linux", operating_system_version = "9.8", state = "DISABLED" }
  }
  expect_failures = [oci_core_instance.app]
}
run "reject_incompatible_shape" {
  command = plan
  override_data {
    target = data.oci_core_shapes.console[0]
    values = { shapes = [] }
  }
  expect_failures = [oci_core_instance.app]
}
run "reject_unready_home_region" {
  command = plan
  override_data {
    target = data.oci_identity_region_subscriptions.console[0]
    values = { region_subscriptions = [{ is_home_region = true, region_name = "us-phoenix-1", state = "IN_PROGRESS" }] }
  }
  expect_failures = [data.oci_identity_region_subscriptions.console]
}

run "reject_custom_image_with_matching_os" {
  command = plan
  override_data {
    target = data.oci_core_image.console[0]
    values = { operating_system = "Oracle Linux", operating_system_version = "9.8", state = "AVAILABLE", compartment_id = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  }
  expect_failures = [oci_core_instance.app]
}

run "reject_empty_initial_catalog" {
  command = plan
  variables { image_ocid = null }
  override_data {
    target = data.oci_core_images.console[0]
    values = { images = [] }
  }
  expect_failures = [terraform_data.console_image]
}
run "reject_catalog_with_only_ineligible_images" {
  command = plan
  variables { image_ocid = null }
  override_data {
    target = data.oci_core_images.console[0]
    values = { images = [
      { id = "ocid1.image.oc1.iad.dddddddddddddddddddddddddddddddd", operating_system = "Oracle Linux", operating_system_version = "9", state = "AVAILABLE", compartment_id = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" },
      { id = "ocid1.image.oc1.iad.eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", operating_system = "Oracle Linux", operating_system_version = "8.10", state = "AVAILABLE", compartment_id = "" }
    ] }
  }
  expect_failures = [terraform_data.console_image]
}
run "accept_manual_platform_image_with_null_compartment" {
  command = plan
  override_data {
    target = data.oci_core_image.console[0]
    values = { operating_system = "Oracle Linux", operating_system_version = "9", state = "AVAILABLE", compartment_id = null }
  }
  assert {
    condition     = oci_core_instance.app[0].source_details[0].source_id == var.image_ocid && length(data.oci_core_images.console) == 0
    error_message = "An explicit platform image need not be present in the recent-image catalog."
  }
}

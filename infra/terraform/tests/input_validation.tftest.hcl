mock_provider "oci" {
  source          = "./tests/fixtures"
  override_during = plan
}

mock_provider "oci" {
  alias           = "home"
  source          = "./tests/fixtures"
  override_during = plan
}

variables {
  deployment_id    = "energy-demo"
  region           = "us-ashburn-1"
  compartment_ocid = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "reject_unsafe_deployment_name" {
  command = plan
  variables { deployment_id = "../../energy" }
  expect_failures = [var.deployment_id]
}

run "root_foundation_targets_selected_root_without_hosting" {
  command = plan
  variables { compartment_ocid = "ocid1.tenancy.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  assert {
    condition     = oci_objectstorage_bucket.artifacts[0].compartment_id == var.compartment_ocid && oci_generative_ai_project.energy.compartment_id == var.compartment_ocid && length(oci_core_instance.app) == 0
    error_message = "Root foundation must use the selected root and remain foundation-only."
  }
}

run "reject_invalid_region" {
  command = plan
  variables { region = "us-ashburn-0" }
  expect_failures = [var.region]
}

run "reject_noncommercial_realm" {
  command = plan
  variables { compartment_ocid = "ocid1.compartment.oc2..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  expect_failures = [var.compartment_ocid]
}

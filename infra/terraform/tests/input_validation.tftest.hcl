mock_provider "oci" {
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

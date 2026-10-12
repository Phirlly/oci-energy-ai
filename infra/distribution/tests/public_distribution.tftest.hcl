mock_provider "oci" {
  mock_data "oci_objectstorage_namespace" {
    defaults = { namespace = "fixture" }
  }
}

variables {
  deployment_id    = "releases-abcdef012345"
  region           = "us-ashburn-1"
  compartment_ocid = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "public_assets_without_listing_or_demo_resources" {
  command = plan
  assert {
    condition     = oci_objectstorage_bucket.distribution.access_type == "ObjectReadWithoutList" && oci_objectstorage_bucket.distribution.storage_tier == "Standard" && oci_objectstorage_bucket.distribution.versioning == "Disabled"
    error_message = "Public assets require anonymous reads without listing and Standard immutable objects."
  }
  assert {
    condition     = oci_objectstorage_bucket.distribution.freeform_tags.purpose == "console-distribution" && output.artifact_bucket_name == "oci-energy-ai-releases-abcdef012345-artifacts" && output.object_storage_namespace == "fixture"
    error_message = "Distribution ownership and output identity must remain separate from demo installations."
  }
}

run "reject_demo_identity" {
  command = plan
  variables { deployment_id = "energy-demo" }
  expect_failures = [var.deployment_id]
}

run "reject_noncommercial_region" {
  command = plan
  variables { region = "invalid" }
  expect_failures = [var.region]
}

run "reject_noncompartment" {
  command = plan
  variables { compartment_ocid = "invalid" }
  expect_failures = [var.compartment_ocid]
}

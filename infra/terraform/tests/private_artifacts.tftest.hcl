mock_provider "oci" {
  source          = "./tests/fixtures"
  override_during = plan
}

variables {
  deployment_id    = "energy-demo"
  region           = "us-ashburn-1"
  compartment_ocid = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "private_artifact_storage" {
  command = plan

  assert {
    condition     = oci_objectstorage_bucket.artifacts.access_type == "NoPublicAccess"
    error_message = "Deployment artifacts must require OCI authentication."
  }
  assert {
    condition     = oci_objectstorage_bucket.artifacts.storage_tier == "Standard" && oci_objectstorage_bucket.artifacts.versioning == "Disabled"
    error_message = "Immutable artifact names use Standard storage without hidden object versions."
  }
  assert {
    condition     = output.artifact_bucket_name == "oci-energy-ai-energy-demo-artifacts" && output.object_storage_namespace == "example-namespace"
    error_message = "Artifact outputs must identify the deployment's private bucket."
  }
  assert {
    condition     = oci_objectstorage_bucket.artifacts.compartment_id == var.compartment_ocid && oci_objectstorage_bucket.artifacts.freeform_tags["deployment_id"] == var.deployment_id
    error_message = "Storage must belong to the selected deployment and compartment."
  }
}

provider "oci" {
  region = var.region
}

data "oci_objectstorage_namespace" "current" {}

resource "oci_objectstorage_bucket" "distribution" {
  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.current.namespace
  name           = "oci-energy-ai-${var.deployment_id}-artifacts"
  access_type    = "ObjectReadWithoutList"
  storage_tier   = "Standard"
  versioning     = "Disabled"
  freeform_tags = {
    application   = "oci-energy-ai"
    deployment_id = var.deployment_id
    managed_by    = "terraform"
    purpose       = "console-distribution"
  }
}

output "artifact_bucket_name" {
  value = oci_objectstorage_bucket.distribution.name
}

output "object_storage_namespace" {
  value = data.oci_objectstorage_namespace.current.namespace
}

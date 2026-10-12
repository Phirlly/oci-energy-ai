data "oci_objectstorage_namespace" "current" {
  count = var.console_install ? 0 : 1
}

moved {
  from = oci_objectstorage_bucket.artifacts
  to   = oci_objectstorage_bucket.artifacts[0]
}

resource "oci_objectstorage_bucket" "artifacts" {
  count          = var.console_install ? 0 : 1
  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.current[0].namespace
  name           = "${local.resource_prefix}-artifacts"
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
  versioning     = "Disabled"
  freeform_tags  = local.ownership_tags
}

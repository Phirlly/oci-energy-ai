mock_data "oci_objectstorage_namespace" {
  defaults = { namespace = "example-namespace" }
}

mock_resource "oci_generative_ai_project" {
  defaults = { id = "ocid1.generativeaiproject.oc1.iad.exampleproject" }
}

mock_data "oci_identity_region_subscriptions" {
  defaults = { region_subscriptions = [{ is_home_region = true, region_name = "us-phoenix-1", state = "READY" }] }
}
mock_data "oci_core_image" {
  defaults = { operating_system = "Oracle Linux", operating_system_version = "9.8", state = "AVAILABLE" }
}
mock_data "oci_core_shapes" {
  defaults = { shapes = [{ name = "VM.Standard.E5.Flex", is_flexible = true }] }
}

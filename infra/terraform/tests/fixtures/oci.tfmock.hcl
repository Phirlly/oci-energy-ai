mock_data "oci_objectstorage_namespace" {
  defaults = { namespace = "example-namespace" }
}

mock_resource "oci_generative_ai_project" {
  defaults = { id = "ocid1.generativeaiproject.oc1.iad.exampleproject" }
}

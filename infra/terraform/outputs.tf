output "artifact_bucket_name" {
  description = "Private bucket for immutable application artifacts."
  value       = oci_objectstorage_bucket.artifacts.name
}

output "object_storage_namespace" {
  description = "Namespace containing the artifact bucket."
  value       = data.oci_objectstorage_namespace.current.namespace
}

output "generative_ai_project_ocid" {
  description = "Project for the future Responses API integration."
  value       = oci_generative_ai_project.energy.id
}

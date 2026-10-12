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

output "instance_ocid" {
  value = try(oci_core_instance.app[0].id, null)
}

output "application_origin" {
  value = try("https://${oci_apigateway_gateway.app[0].hostname}", null)
}

output "backend_host" {
  value = try("${oci_core_instance.app[0].private_ip}:8080", null)
}

output "vault_ocid" {
  value = try(oci_kms_vault.app[0].id, null)
}

output "key_ocid" {
  value = try(oci_kms_key.app[0].id, null)
}

output "settings_secret_ocid" {
  description = "Open this secret in OCI Vault and reveal CURRENT content to retrieve setup_code. No password or key belongs in Terraform."
  value       = try(oci_vault_secret.settings[0].id, null)
}

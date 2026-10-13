output "artifact_bucket_name" {
  description = "Private bucket for immutable application artifacts."
  value       = var.console_install ? null : oci_objectstorage_bucket.artifacts[0].name
}

output "object_storage_namespace" {
  description = "Namespace containing the artifact bucket."
  value       = var.console_install ? null : data.oci_objectstorage_namespace.current[0].namespace
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
  description = "In the deployment region, open Identity & Security > Secret Management, select the deployment compartment and this secret's OCID. Under Versions, open CURRENT actions > View Secret Contents, enable decoded Base64 and copy only setup_code into Owner code in the demo. Keep credentials out of Terraform."
  value       = try(oci_vault_secret.settings[0].id, null)
}

output "settings_secret_url" {
  description = "Open the owner setup secret in OCI Console. Under Versions, view CURRENT contents with decoded Base64 and copy only setup_code into the demo's Owner code field."
  value       = var.console_install ? "https://cloud.oracle.com/security/kms/${oci_kms_vault.app[0].id}/secrets/${oci_vault_secret.settings[0].id}?region=${var.region}" : null
}

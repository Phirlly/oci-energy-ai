data "oci_identity_region_subscriptions" "console" {
  count      = var.console_install ? 1 : 0
  tenancy_id = var.tenancy_ocid
  lifecycle {
    precondition {
      condition     = var.tenancy_ocid != null
      error_message = "Console installation requires the selected tenancy."
    }
    postcondition {
      condition     = length([for item in self.region_subscriptions : item.region_name if item.is_home_region && item.state == "READY"]) == 1
      error_message = "The tenancy must have exactly one ready home region."
    }
  }
}
locals {
  console_home_region = var.console_install ? try(one([for item in data.oci_identity_region_subscriptions.console[0].region_subscriptions : item.region_name if item.is_home_region && item.state == "READY"]), var.region) : var.region
  application = var.console_install ? {
    version             = 1
    tenancy_ocid        = var.tenancy_ocid
    home_region         = local.console_home_region
    availability_domain = var.availability_domain
    image_ocid          = local.console_selected_image
  } : var.application
  console_topology = var.console_install ? {
    deployment_id    = var.deployment_id
    compartment_ocid = var.compartment_ocid
    region           = var.region
    application      = local.application
    host_digest      = local.host_digest
  } : null
  console_manifest = var.console_install ? {
    version      = 1
    host_digest  = try(var.console_release.host_digest, "")
    release      = try(var.console_release.release, "")
    image_id     = try(var.console_release.image_id, "")
    image_sha256 = try(var.console_release.image_sha256, "")
    image_bytes  = try(var.console_release.image_bytes, 0)
    runtime = {
      version    = 2
      region     = var.region
      project    = oci_generative_ai_project.energy.id
      origin     = "https://${oci_apigateway_gateway.app[0].hostname}"
      secret_ids = { settings = oci_vault_secret.settings[0].id }
      model_ids  = { oci = var.oci_model, openai = var.openai_model, anthropic = var.anthropic_model }
    }
  } : null
  instance_metadata = merge({
    user_data = base64gzip("#cloud-config\n${yamlencode(local.cloud_config)}")
    }, var.console_install ? {
    energy_ai_install = jsonencode({
      version       = 1
      generation    = var.install_generation
      artifact_base = try(var.console_release.artifact_base, "")
      manifest      = local.console_manifest
    })
  } : {})
}
# First records intent for new stacks; it cannot reconstruct unrecorded legacy state.
resource "terraform_data" "installation" {
  input = { console_install = var.console_install, topology = local.console_topology }
  lifecycle {
    ignore_changes = [input]
    precondition {
      condition     = !var.console_install || var.application == null
      error_message = "Console and GitHub application modes cannot be combined."
    }
    precondition {
      condition     = !var.console_install || var.console_release != null
      error_message = "Use a checked Console ZIP with its pinned release."
    }
    precondition {
      condition     = local.application == null ? true : (!local.root_compartment || var.compartment_ocid == local.application.tenancy_ocid)
      error_message = "The root compartment must match the selected deployment tenancy."
    }
  }
}

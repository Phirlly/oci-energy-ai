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
data "oci_core_image" "console" {
  count    = var.console_install ? 1 : 0
  image_id = var.image_ocid
  lifecycle {
    precondition {
      condition     = var.image_ocid != null
      error_message = "Select an Oracle Linux 9 image."
    }
    postcondition {
      condition     = self.operating_system == "Oracle Linux" && can(regex("^9(\\.|$)", self.operating_system_version)) && self.state == "AVAILABLE"
      error_message = "The selected image must be an available Oracle Linux 9 image."
    }
  }
}
data "oci_core_shapes" "console" {
  count               = var.console_install ? 1 : 0
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  image_id            = var.image_ocid
  shape               = "VM.Standard.E5.Flex"
  lifecycle {
    precondition {
      condition     = var.availability_domain != null && var.image_ocid != null
      error_message = "Select the host availability domain and image."
    }
    postcondition {
      condition     = anytrue([for item in self.shapes : item.name == "VM.Standard.E5.Flex" && item.is_flexible])
      error_message = "The selected image/domain must support VM.Standard.E5.Flex."
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
    image_ocid          = var.image_ocid
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
      model_ids  = { oci = "google.gemini-2.5-flash", openai = "gpt-4.1-2025-04-14", anthropic = "claude-haiku-5-5" }
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
  }
}

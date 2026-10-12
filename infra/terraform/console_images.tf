# Discover only for automatic Console installs; GitHub has its own pinned topology.
data "oci_core_images" "console" {
  count            = var.console_install && var.image_ocid == null ? 1 : 0
  compartment_id   = var.compartment_ocid
  operating_system = "Oracle Linux"
  shape            = "VM.Standard.E5.Flex"
  state            = "AVAILABLE"
  sort_by          = "TIMECREATED"
  sort_order       = "DESC"
}

locals {
  console_candidates = var.console_install && var.image_ocid == null ? [
    for item in data.oci_core_images.console[0].images : item.id
    if item.operating_system == "Oracle Linux" && can(regex("^9(\\.|$)", item.operating_system_version)) &&
    item.state == "AVAILABLE" && (item.compartment_id == null || item.compartment_id == "")
  ] : []
  # Local indirection and input (not computed output) keep image reads in plan.
  # Adding custom conditions to those data sources would defer first-install reads.
  console_selected_image = var.console_install ? terraform_data.console_image[0].input : null
}

resource "terraform_data" "console_image" {
  count = var.console_install ? 1 : 0
  input = var.image_ocid != null ? var.image_ocid : try(local.console_candidates[0], null)
  lifecycle {
    ignore_changes = [input]
    precondition {
      condition     = var.availability_domain != null
      error_message = "Select the availability domain for the demo host."
    }
    postcondition {
      condition     = self.input != null && self.input != ""
      error_message = "No available Oracle Linux 9 platform image supports VM.Standard.E5.Flex in this region. Choose a supported region or provide a compatible platform image override."
    }
    postcondition {
      condition     = var.image_ocid == null ? true : self.input == var.image_ocid
      error_message = "The host image is fixed after initial selection. Keep the saved image or use a fresh stack."
    }
  }
}

data "oci_core_image" "console" {
  count    = var.console_install ? 1 : 0
  image_id = local.console_selected_image
}

data "oci_core_shapes" "console" {
  count               = var.console_install ? 1 : 0
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  image_id            = local.console_selected_image
  shape               = "VM.Standard.E5.Flex"
}

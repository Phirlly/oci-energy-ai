resource "oci_generative_ai_project" "energy" {
  compartment_id = var.compartment_ocid
  display_name   = local.resource_prefix
  description    = "OCI Energy AI demonstration"
  freeform_tags  = local.ownership_tags

  lifecycle {
    precondition {
      condition     = terraform_data.installation.output.console_install == var.console_install
      error_message = "Installation mode is fixed after recording it. Create a fresh stack to change modes."
    }
  }

  long_term_memory_config {
    standard_long_term_memory_strategy {
      is_enabled = false
    }
  }

  short_term_memory_optimization_config {
    is_enabled = false
  }
}

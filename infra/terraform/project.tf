resource "oci_generative_ai_project" "energy" {
  compartment_id = var.compartment_ocid
  display_name   = local.resource_prefix
  description    = "OCI Energy AI demonstration"
  freeform_tags  = local.ownership_tags

  long_term_memory_config {
    standard_long_term_memory_strategy {
      is_enabled = false
    }
  }

  short_term_memory_optimization_config {
    is_enabled = false
  }
}

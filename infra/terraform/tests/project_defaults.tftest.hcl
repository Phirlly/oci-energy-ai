mock_provider "oci" {
  source          = "./tests/fixtures"
  override_during = plan
}

variables {
  deployment_id    = "energy-demo"
  region           = "us-ashburn-1"
  compartment_ocid = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "project_without_optional_memory" {
  command = plan

  assert {
    condition     = !oci_generative_ai_project.energy.long_term_memory_config[0].standard_long_term_memory_strategy[0].is_enabled && !oci_generative_ai_project.energy.short_term_memory_optimization_config[0].is_enabled
    error_message = "Optional memory services must be disabled."
  }
  assert {
    condition     = oci_generative_ai_project.energy.compartment_id == var.compartment_ocid && oci_generative_ai_project.energy.freeform_tags["deployment_id"] == var.deployment_id
    error_message = "The GenAI project must belong to the selected deployment."
  }
  assert {
    condition     = output.generative_ai_project_ocid == "ocid1.generativeaiproject.oc1.iad.exampleproject"
    error_message = "The project output must identify the managed project."
  }
}

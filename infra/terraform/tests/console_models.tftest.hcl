mock_provider "oci" {
  source = "./tests/fixtures"
  mock_resource "oci_generative_ai_project" {
    defaults = { id = "ocid1.generativeaiproject.oc1.iad.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  }
  mock_resource "oci_apigateway_gateway" {
    defaults = { hostname = "example.apigateway.us-ashburn-1.oci.customer-oci.com" }
  }
  mock_resource "oci_vault_secret" {
    defaults = { id = "ocid1.vaultsecret.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
  }
  mock_resource "oci_core_instance" {
    defaults = { private_ip = "10.40.1.10" }
  }
}
mock_provider "oci" {
  alias  = "home"
  source = "./tests/fixtures"
}
variables {
  deployment_id       = "console-demo"
  region              = "us-ashburn-1"
  compartment_ocid    = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  console_install     = true
  tenancy_ocid        = "ocid1.tenancy.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  availability_domain = "EXAMPLE:US-ASHBURN-AD-1"
  image_ocid          = "ocid1.image.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  console_release = {
    artifact_base = "https://objectstorage.us-ashburn-1.oraclecloud.com/n/example/b/public/o/"
    release       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    host_digest   = sha256(join("", [for name in ["__init__.py", "activation.py", "artifacts.py", "bootstrap.sh", "console_contract.py", "console_install.py", "console_sources.py", "contracts.py", "control.py", "entrypoint.py", "install_entry.py", "oci-energy-ai-install.service", "oci-energy-ai-install.timer", "oci-energy-ai.service", "process.py", "service.py", "service_entry.py", "state.py"] : filesha256("host/${name}")]))
    image_id      = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    image_sha256  = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    image_bytes   = 123456
  }
}


run "default_models" {
  command = apply
  assert {
    condition     = local.console_manifest.runtime.model_ids == { oci = "google.gemini-2.5-flash", openai = "gpt-4.1-2025-04-14", anthropic = "claude-haiku-5-5" }
    error_message = "Console defaults must preserve all three verified model IDs."
  }
}

run "configured_models" {
  command = apply
  variables {
    oci_model       = "oci.fixture:2"
    openai_model    = "openai_fixture-2"
    anthropic_model = "anthropic-fixture-2"
  }
  assert {
    condition     = jsondecode(oci_core_instance.app[0].metadata.energy_ai_install).manifest.runtime.model_ids == { oci = "oci.fixture:2", openai = "openai_fixture-2", anthropic = "anthropic-fixture-2" }
    error_message = "Every model override must reach instance metadata even when advanced controls are hidden."
  }
  assert {
    condition     = output.instance_ocid == run.default_models.instance_ocid && output.settings_secret_ocid == run.default_models.settings_secret_ocid && terraform_data.installation.output.topology == local.console_topology
    error_message = "Model updates must retain the host, settings and topology."
  }
  assert {
    condition     = !strcontains(jsonencode(local.cloud_config), "openai_fixture-2")
    error_message = "Mutable models must not enter first-boot user_data."
  }
}

run "configured_models_repeat" {
  command = apply
  variables {
    show_advanced_options = true
    oci_model             = "oci.fixture:2"
    openai_model          = "openai_fixture-2"
    anthropic_model       = "anthropic-fixture-2"
  }
  assert {
    condition     = output.instance_ocid == run.configured_models.instance_ocid && output.settings_secret_ocid == run.configured_models.settings_secret_ocid && local.console_manifest.runtime.model_ids == { oci = "oci.fixture:2", openai = "openai_fixture-2", anthropic = "anthropic-fixture-2" }
    error_message = "Repeated overrides and form visibility changes must preserve configuration and identities."
  }
}

run "reject_empty_oci_model" {
  command = plan
  variables { oci_model = "" }
  expect_failures = [var.oci_model]
}
run "reject_path_openai_model" {
  command = plan
  variables { openai_model = "../bad" }
  expect_failures = [var.openai_model]
}
run "reject_padded_anthropic_model" {
  command = plan
  variables { anthropic_model = " bad " }
  expect_failures = [var.anthropic_model]
}
run "reject_oversize_model" {
  command = plan
  variables { oci_model = join("", [for n in range(129) : "x"]) }
  expect_failures = [var.oci_model]
}

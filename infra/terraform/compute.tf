locals {
  host_assets = [
    "__init__.py", "activation.py", "artifacts.py", "bootstrap.sh",
    "console_contract.py", "console_install.py", "console_sources.py", "contracts.py",
    "control.py", "entrypoint.py", "install_entry.py", "oci-energy-ai-install.service",
    "oci-energy-ai-install.timer", "oci-energy-ai.service", "process.py",
    "service.py", "service_entry.py", "state.py",
  ]
  host_digest = sha256(join("", [for name in local.host_assets : filesha256("${path.module}/host/${name}")]))
  host_configuration = merge({
    version     = var.console_install ? 2 : 1
    host_digest = local.host_digest
    region      = var.region
    }, var.console_install ? {} : {
    namespace = data.oci_objectstorage_namespace.current[0].namespace
    bucket    = oci_objectstorage_bucket.artifacts[0].name
  })
  cloud_config = {
    write_files = concat([
      for name in local.host_assets : {
        path        = "/opt/oci-energy-ai/host/${name}"
        owner       = "root:root"
        permissions = "0600"
        content     = file("${path.module}/host/${name}")
      }
      ], [
      { path = "/etc/oci-energy-ai/host.json", owner = "root:root", permissions = "0600", content = jsonencode(local.host_configuration) },
      { path = "/usr/local/sbin/oci-energy-ai", owner = "root:root", permissions = "0755", content = file("${path.module}/host/entrypoint.py") },
      { path = "/etc/systemd/system/oci-energy-ai.service", owner = "root:root", permissions = "0644", content = file("${path.module}/host/oci-energy-ai.service") },
      { path = "/etc/sudoers.d/oci-energy-ai", owner = "root:root", permissions = "0440", content = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/oci-energy-ai\n" },
      ], var.console_install ? [
      for name in ["oci-energy-ai-install.service", "oci-energy-ai-install.timer"] : {
        path = "/etc/systemd/system/${name}", owner = "root:root", permissions = "0644", content = file("${path.module}/host/${name}")
      }
    ] : [])
    runcmd = var.console_install ? [["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", "oci-energy-ai-install.timer"]] : [["/bin/bash", "/opt/oci-energy-ai/host/bootstrap.sh"]]
  }
}

resource "oci_core_instance" "app" {
  count                = local.application_count
  compartment_id       = var.compartment_ocid
  availability_domain  = local.application.availability_domain
  display_name         = local.resource_prefix
  shape                = "VM.Standard.E5.Flex"
  freeform_tags        = local.ownership_tags
  preserve_boot_volume = false
  shape_config {
    ocpus         = 1
    memory_in_gbs = 8
  }
  source_details {
    source_type             = "image"
    source_id               = local.application.image_ocid
    boot_volume_size_in_gbs = 50
  }
  create_vnic_details {
    subnet_id        = oci_core_subnet.app[0].id
    assign_public_ip = false
    nsg_ids          = [oci_core_network_security_group.app[0].id]
  }
  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }
  agent_config {
    are_all_plugins_disabled = false
    plugins_config {
      name          = "Compute Instance Run Command"
      desired_state = "ENABLED"
    }
  }
  metadata = local.instance_metadata
  lifecycle {
    precondition {
      condition = var.console_install ? (
        data.oci_core_image.console[0].operating_system == "Oracle Linux" &&
        can(regex("^9(\\.|$)", data.oci_core_image.console[0].operating_system_version)) &&
        data.oci_core_image.console[0].state == "AVAILABLE" &&
        (data.oci_core_image.console[0].compartment_id == null || data.oci_core_image.console[0].compartment_id == "")
      ) : true
      error_message = "The host image must be an available Oracle Linux 9 platform image; custom images are not supported."
    }
    precondition {
      condition     = var.console_install ? anytrue([for item in data.oci_core_shapes.console[0].shapes : item.name == "VM.Standard.E5.Flex" && item.is_flexible]) : true
      error_message = "The selected image and availability domain must support VM.Standard.E5.Flex."
    }
    precondition {
      condition     = length(jsonencode(local.instance_metadata)) < 32000
      error_message = "Host metadata exceeds OCI's combined 32,000-byte limit."
    }
    precondition {
      condition     = !var.console_install || terraform_data.installation.output.topology == local.console_topology
      error_message = "Console host identity is fixed. Preserve the saved image, domain, location and helpers; use a fresh stack for a different host."
    }
    precondition {
      condition     = !var.console_install || try(var.console_release.host_digest == local.host_digest, false)
      error_message = "The checked release must match the packaged host helpers."
    }
  }
  depends_on = [oci_core_network_security_group_security_rule.app_https, data.oci_core_image.console, data.oci_core_shapes.console]
}

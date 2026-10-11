locals {
  host_assets = [
    "__init__.py", "activation.py", "artifacts.py", "bootstrap.sh", "contracts.py",
    "control.py", "entrypoint.py", "oci-energy-ai.service", "process.py",
    "service.py", "service_entry.py", "state.py",
  ]
  host_digest = sha256(join("", [for name in local.host_assets : filesha256("${path.module}/host/${name}")]))
  host_configuration = {
    version     = 1
    host_digest = local.host_digest
    region      = var.region
    namespace   = data.oci_objectstorage_namespace.current.namespace
    bucket      = oci_objectstorage_bucket.artifacts.name
  }
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
    ])
    runcmd = [["/bin/bash", "/opt/oci-energy-ai/host/bootstrap.sh"]]
  }
}

resource "oci_core_instance" "app" {
  count                = local.application_count
  compartment_id       = var.compartment_ocid
  availability_domain  = var.application.availability_domain
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
    source_id               = var.application.image_ocid
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
  metadata = {
    user_data = base64gzip("#cloud-config\n${yamlencode(local.cloud_config)}")
  }
  lifecycle {
    precondition {
      condition     = length(jsonencode({ user_data = base64gzip("#cloud-config\n${yamlencode(local.cloud_config)}") })) < 32000
      error_message = "Host metadata exceeds OCI's combined 32,000-byte limit."
    }
  }
  depends_on = [oci_core_network_security_group_security_rule.app_https]
}

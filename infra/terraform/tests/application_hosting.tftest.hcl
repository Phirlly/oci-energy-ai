mock_provider "oci" {
  source = "./tests/fixtures"
}

mock_provider "oci" {
  alias  = "home"
  source = "./tests/fixtures"
}

variables {
  deployment_id    = "energy-demo"
  region           = "us-ashburn-1"
  compartment_ocid = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "foundation_has_no_application_resources" {
  command = plan
  assert {
    condition     = length(terraform_data.console_image) == 0 && length(data.oci_core_images.console) == 0 && length(data.oci_core_image.console) == 0
    error_message = "Foundation deployment must not select or read a Console image."
  }
  assert {
    condition     = length(oci_core_instance.app) == 0 && length(oci_core_vcn.app) == 0 && length(oci_kms_vault.app) == 0 && length(oci_apigateway_gateway.app) == 0 && length(oci_identity_dynamic_group.app) == 0
    error_message = "Foundation operation must not create hosting resources."
  }
}

run "private_host_with_https_gateway_and_instance_identity" {
  command = apply
  assert {
    condition     = length(oci_objectstorage_bucket.artifacts) == 1 && length(data.oci_objectstorage_namespace.current) == 1 && local.host_configuration == { version = 1, host_digest = local.host_digest, region = var.region, namespace = "example-namespace", bucket = "oci-energy-ai-energy-demo-artifacts" }
    error_message = "GitHub hosting must retain its exact private storage and version-1 host configuration."
  }
  assert {
    condition     = length(terraform_data.console_image) == 0 && length(data.oci_core_images.console) == 0 && length(data.oci_core_image.console) == 0 && oci_core_instance.app[0].source_details[0].source_id == var.application.image_ocid
    error_message = "GitHub topology remains independently pinned and must not query Console images."
  }
  variables {
    application = {
      version             = 1
      tenancy_ocid        = "ocid1.tenancy.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      home_region         = "us-phoenix-1"
      availability_domain = "EXAMPLE:US-ASHBURN-AD-1"
      image_ocid          = "ocid1.image.oc1.iad.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  }
  assert {
    condition     = !oci_core_instance.app[0].create_vnic_details[0].assign_public_ip && oci_core_subnet.app[0].prohibit_public_ip_on_vnic && oci_core_instance.app[0].instance_options[0].are_legacy_imds_endpoints_disabled
    error_message = "The host must be private and require IMDSv2."
  }
  assert {
    condition     = oci_core_instance.app[0].shape == "VM.Standard.E5.Flex" && oci_core_instance.app[0].shape_config[0].ocpus == 1 && oci_core_instance.app[0].shape_config[0].memory_in_gbs == 8 && tonumber(oci_core_instance.app[0].source_details[0].boot_volume_size_in_gbs) == 50
    error_message = "The reviewed demo sizing must be explicit."
  }
  assert {
    condition     = length(oci_core_security_list.empty[0].ingress_security_rules) == 0 && length(oci_core_security_list.empty[0].egress_security_rules) == 0 && oci_core_subnet.app[0].security_list_ids == toset([oci_core_security_list.empty[0].id]) && oci_core_subnet.gateway[0].security_list_ids == toset([oci_core_security_list.empty[0].id])
    error_message = "Default security-list rules must not broaden NSG access."
  }
  assert {
    condition     = oci_core_network_security_group_security_rule.app_http[0].source == oci_core_network_security_group.gateway[0].id && oci_core_network_security_group_security_rule.app_http[0].source_type == "NETWORK_SECURITY_GROUP" && oci_core_network_security_group_security_rule.app_http[0].tcp_options[0].destination_port_range[0].min == 8080 && !oci_core_network_security_group_security_rule.app_http[0].stateless
    error_message = "Only the gateway NSG may initiate application traffic."
  }
  assert {
    condition     = oci_core_network_security_group_security_rule.gateway_https[0].tcp_options[0].destination_port_range[0].min == 443 && oci_core_network_security_group_security_rule.app_https[0].tcp_options[0].destination_port_range[0].min == 443
    error_message = "Public ingress and application outbound access use HTTPS."
  }
  assert {
    condition     = oci_apigateway_gateway.app[0].endpoint_type == "PUBLIC" && oci_apigateway_deployment.app[0].path_prefix == "/" && oci_apigateway_deployment.app[0].specification[0].routes[0].path == "/{path*}" && !oci_apigateway_deployment.app[0].specification[0].logging_policies[0].access_log[0].is_enabled
    error_message = "The demo needs one TLS gateway and private-data-safe route logging."
  }
  assert {
    condition     = oci_identity_dynamic_group.app[0].matching_rule == "instance.id = '${oci_core_instance.app[0].id}'" && oci_kms_vault.app[0].vault_type == "DEFAULT" && oci_kms_key.app[0].protection_mode == "SOFTWARE" && oci_kms_key.app[0].key_shape[0].length == 32
    error_message = "Identity must target this instance; secrets use the reviewed Vault/key configuration."
  }
  assert {
    condition     = length(jsonencode(oci_core_instance.app[0].metadata)) < 32000 && toset(keys(oci_core_instance.app[0].metadata)) == toset(["user_data"]) && length(local.host_digest) == 64
    error_message = "Cloud-init metadata must fit OCI's limit and carry no SSH key or secret variable."
  }
  assert {
    condition     = oci_apigateway_deployment.app[0].specification[0].routes[0].backend[0].url == "http://${oci_core_instance.app[0].private_ip}:8080/$${request.path[path]}" && !oci_apigateway_deployment.app[0].specification[0].logging_policies[0].execution_log[0].is_enabled
    error_message = "Wildcard routes must retain the path without exposing requests in gateway logs."
  }
  assert {
    condition     = length(oci_identity_policy.app[0].statements) == 4 && contains(oci_identity_policy.app[0].statements, "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to read objects in compartment id ${var.compartment_ocid} where target.bucket.name = '${oci_objectstorage_bucket.artifacts[0].name}'") && contains(oci_identity_policy.app[0].statements, "Allow dynamic-group id ${oci_identity_dynamic_group.app[0].id} to read secret-bundles in compartment id ${var.compartment_ocid} where any {target.secret.name = '${local.resource_prefix}-demo-password', target.secret.name = '${local.resource_prefix}-openai', target.secret.name = '${local.resource_prefix}-anthropic'}")
    error_message = "Runtime reads must be scoped to this deployment's bucket and three secrets."
  }
  assert {
    condition     = toset(local.host_assets) == toset([for name in fileset(path.module, "host/*") : trimprefix(name, "host/")])
    error_message = "Every installed host asset must participate in the helper digest."
  }
}

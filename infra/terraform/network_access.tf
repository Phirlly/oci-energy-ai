resource "oci_core_network_security_group" "gateway" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.app[0].id
  display_name   = "${local.resource_prefix}-gateway"
  freeform_tags  = local.ownership_tags
}

resource "oci_core_network_security_group" "app" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.app[0].id
  display_name   = "${local.resource_prefix}-app"
  freeform_tags  = local.ownership_tags
}

resource "oci_core_network_security_group_security_rule" "gateway_https" {
  count                     = local.application_count
  network_security_group_id = oci_core_network_security_group.gateway[0].id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "0.0.0.0/0"
  source_type               = "CIDR_BLOCK"
  stateless                 = false
  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "gateway_backend" {
  count                     = local.application_count
  network_security_group_id = oci_core_network_security_group.gateway[0].id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = oci_core_network_security_group.app[0].id
  destination_type          = "NETWORK_SECURITY_GROUP"
  stateless                 = false
  tcp_options {
    destination_port_range {
      min = 8080
      max = 8080
    }
  }
}

resource "oci_core_network_security_group_security_rule" "app_http" {
  count                     = local.application_count
  network_security_group_id = oci_core_network_security_group.app[0].id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = oci_core_network_security_group.gateway[0].id
  source_type               = "NETWORK_SECURITY_GROUP"
  stateless                 = false
  tcp_options {
    destination_port_range {
      min = 8080
      max = 8080
    }
  }
}

resource "oci_core_network_security_group_security_rule" "app_https" {
  count                     = local.application_count
  network_security_group_id = oci_core_network_security_group.app[0].id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  stateless                 = false
  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

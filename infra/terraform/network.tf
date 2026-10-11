resource "oci_core_vcn" "app" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  display_name   = local.resource_prefix
  cidr_blocks    = ["10.40.0.0/16"]
  dns_label      = "energy"
  freeform_tags  = local.ownership_tags
}

resource "oci_core_internet_gateway" "app" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.app[0].id
  display_name   = "${local.resource_prefix}-public"
  enabled        = true
  freeform_tags  = local.ownership_tags
}

resource "oci_core_nat_gateway" "app" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.app[0].id
  display_name   = "${local.resource_prefix}-outbound"
  block_traffic  = false
  freeform_tags  = local.ownership_tags
}

resource "oci_core_route_table" "gateway" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.app[0].id
  display_name   = "${local.resource_prefix}-gateway"
  freeform_tags  = local.ownership_tags
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.app[0].id
  }
}

resource "oci_core_route_table" "app" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.app[0].id
  display_name   = "${local.resource_prefix}-app"
  freeform_tags  = local.ownership_tags
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_nat_gateway.app[0].id
  }
}

# Security lists and NSGs are additive. Never inherit the VCN default list.
resource "oci_core_security_list" "empty" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.app[0].id
  display_name   = "${local.resource_prefix}-nsg-only"
  # Omitted rule blocks produce empty lists with the pinned OCI provider.
  freeform_tags = local.ownership_tags
}

resource "oci_core_subnet" "gateway" {
  count                      = local.application_count
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.app[0].id
  display_name               = "${local.resource_prefix}-gateway"
  cidr_block                 = "10.40.0.0/24"
  dns_label                  = "gateway"
  route_table_id             = oci_core_route_table.gateway[0].id
  security_list_ids          = [oci_core_security_list.empty[0].id]
  prohibit_public_ip_on_vnic = false
  freeform_tags              = local.ownership_tags
}

resource "oci_core_subnet" "app" {
  count                      = local.application_count
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.app[0].id
  display_name               = "${local.resource_prefix}-app"
  cidr_block                 = "10.40.1.0/24"
  dns_label                  = "app"
  route_table_id             = oci_core_route_table.app[0].id
  security_list_ids          = [oci_core_security_list.empty[0].id]
  prohibit_public_ip_on_vnic = true
  freeform_tags              = local.ownership_tags
}

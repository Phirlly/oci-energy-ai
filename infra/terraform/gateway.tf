resource "oci_apigateway_gateway" "app" {
  count                      = local.application_count
  compartment_id             = var.compartment_ocid
  display_name               = local.resource_prefix
  endpoint_type              = "PUBLIC"
  subnet_id                  = oci_core_subnet.gateway[0].id
  network_security_group_ids = [oci_core_network_security_group.gateway[0].id]
  freeform_tags              = local.ownership_tags
}

resource "oci_apigateway_deployment" "app" {
  count          = local.application_count
  compartment_id = var.compartment_ocid
  display_name   = local.resource_prefix
  gateway_id     = oci_apigateway_gateway.app[0].id
  path_prefix    = "/"
  freeform_tags  = local.ownership_tags
  specification {
    logging_policies {
      access_log {
        is_enabled = false
      }
      execution_log {
        is_enabled = false
      }
    }
    request_policies {
      rate_limiting {
        rate_in_requests_per_second = 30
        rate_key                    = "TOTAL"
      }
    }
    routes {
      path    = "/{path*}"
      methods = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
      backend {
        type                       = "HTTP_BACKEND"
        url                        = "http://${oci_core_instance.app[0].private_ip}:8080/$${request.path[path]}"
        connect_timeout_in_seconds = 10
        read_timeout_in_seconds    = 120
        send_timeout_in_seconds    = 30
      }
    }
  }
}

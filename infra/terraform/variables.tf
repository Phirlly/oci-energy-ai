variable "deployment_id" {
  description = "Unique nonconfidential deployment name, 3-32 lowercase letters, digits or hyphens."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.deployment_id))
    error_message = "deployment_id must start with a letter and end with a letter or digit."
  }
}

variable "region" {
  description = "OCI commercial region; service availability must be checked before deployment."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?$", var.region))
    error_message = "region must be an OCI region name such as us-ashburn-1."
  }
}

variable "compartment_ocid" {
  description = "Target compartment OCID in the OC1 commercial realm."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^ocid1\\.compartment\\.oc1\\.\\.[a-z0-9]{20,255}$", var.compartment_ocid))
    error_message = "compartment_ocid must identify an OC1 compartment."
  }
}

variable "application" {
  description = "Pinned nonsecret host topology; null retains foundation-only operation. Managed by the deployment workflow."
  type = object({
    version             = number
    tenancy_ocid        = string
    home_region         = string
    availability_domain = string
    image_ocid          = string
  })
  default = null
  validation {
    condition = var.application == null ? true : (
      var.application.version == 1 &&
      can(regex("^ocid1\\.tenancy\\.oc1\\.\\.[a-z0-9]{20,255}$", var.application.tenancy_ocid)) &&
      can(regex("^[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?$", var.application.home_region)) &&
      can(regex("^[A-Za-z0-9:_-]{1,128}$", var.application.availability_domain)) &&
      can(regex("^ocid1\\.image\\.oc1\\.[a-z0-9-]+\\.[a-z0-9.]{20,255}$", var.application.image_ocid))
    )
    error_message = "application must contain valid version-1 OC1 hosting topology."
  }
}

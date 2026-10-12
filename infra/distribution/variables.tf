variable "deployment_id" {
  description = "Repository-derived distribution identity; never a demo deployment ID."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^releases-[a-f0-9]{12}$", var.deployment_id))
    error_message = "deployment_id must be the repository-derived releases identity."
  }
}

variable "region" {
  description = "Maintainer's OCI commercial distribution region."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?$", var.region))
    error_message = "region must be an OCI commercial region name."
  }
}

variable "compartment_ocid" {
  description = "Maintainer's OC1 root or child compartment for public build distribution."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^ocid1\\.(compartment|tenancy)\\.oc1\\.\\.[a-z0-9]{20,255}$", var.compartment_ocid))
    error_message = "compartment_ocid must identify an OC1 root or child compartment."
  }
}

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

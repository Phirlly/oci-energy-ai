variable "show_advanced_options" {
  description = "Display optional advanced settings in the Console form; no runtime effect."
  type        = bool
  default     = false
  nullable    = false
}
variable "oci_model" {
  description = "OCI model ID for Console installs. Access and tool/output compatibility must be verified."
  type        = string
  default     = "google.gemini-2.5-flash"
  nullable    = false
  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$", var.oci_model))
    error_message = "OCI model ID must use 1–128 letters, digits, dots, underscores, colons or hyphens, starting with a letter or digit."
  }
}
variable "openai_model" {
  description = "OpenAI model ID for Console installs. Access and tool/output compatibility must be verified."
  type        = string
  default     = "gpt-4.1-2025-04-14"
  nullable    = false
  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$", var.openai_model))
    error_message = "OpenAI model ID must use 1–128 letters, digits, dots, underscores, colons or hyphens, starting with a letter or digit."
  }
}
variable "anthropic_model" {
  description = "Anthropic model ID for Console installs. Access and tool/output compatibility must be verified."
  type        = string
  default     = "claude-haiku-5-5"
  nullable    = false
  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$", var.anthropic_model))
    error_message = "Anthropic model ID must use 1–128 letters, digits, dots, underscores, colons or hyphens, starting with a letter or digit."
  }
}
variable "console_install" {
  description = "Native Console mode. Use the checked Console ZIP for a fresh stack."
  type        = bool
  default     = false
  nullable    = false
}
variable "tenancy_ocid" {
  description = "Tenancy selected by OCI Console; used for exact-instance identity."
  type        = string
  default     = null
  validation {
    condition     = var.tenancy_ocid == null ? true : can(regex("^ocid1\\.tenancy\\.oc1\\.\\.[a-z0-9]{20,255}$", var.tenancy_ocid))
    error_message = "Select an OC1 tenancy."
  }
}
variable "availability_domain" {
  description = "Saved availability domain for the private application host."
  type        = string
  default     = null
  validation {
    condition     = var.availability_domain == null ? true : can(regex("^[A-Za-z0-9:_-]{1,128}$", var.availability_domain))
    error_message = "Select an availability domain."
  }
}
variable "image_ocid" {
  description = "Optional platform image override for a fresh stack; normally selected automatically and retained."
  type        = string
  default     = null
  validation {
    condition     = var.image_ocid == null ? true : can(regex("^ocid1\\.image\\.oc1\\.[a-z0-9-]+\\.[a-z0-9.]{20,255}$", var.image_ocid))
    error_message = "Select an Oracle Linux 9 image."
  }
}
variable "install_generation" {
  description = "Increase only to retry an exhausted installer; preserves the host."
  type        = number
  default     = 0
  nullable    = false
  validation {
    condition     = var.install_generation >= 0 && var.install_generation <= 1000000 && floor(var.install_generation) == var.install_generation
    error_message = "Installer generation must be an integer from 0 to 1000000."
  }
}
variable "console_release" {
  description = "Checked public build identity supplied by the Console ZIP; no credentials."
  type = object({
    artifact_base = string
    release       = string
    host_digest   = string
    image_id      = string
    image_sha256  = string
    image_bytes   = number
  })
  default = null
  validation {
    condition = var.console_release == null ? true : (
      can(regex("^https://objectstorage\\.[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?\\.oraclecloud\\.com/n/[A-Za-z0-9_-]{1,255}/b/[A-Za-z0-9_-]{1,255}/o/$", var.console_release.artifact_base)) &&
      can(regex("^[a-f0-9]{40}$", var.console_release.release)) &&
      can(regex("^[a-f0-9]{64}$", var.console_release.host_digest)) &&
      can(regex("^sha256:[a-f0-9]{64}$", var.console_release.image_id)) &&
      can(regex("^[a-f0-9]{64}$", var.console_release.image_sha256)) &&
      var.console_release.image_bytes > 0 && var.console_release.image_bytes <= 2147483648 &&
      floor(var.console_release.image_bytes) == var.console_release.image_bytes
    )
    error_message = "Console release must contain an exact checked public image and host identity."
  }
}
variable "instance_shape" {
  description = "Fixed reviewed demo size; used by the Console image filter."
  type        = string
  default     = "VM.Standard.E5.Flex"
  nullable    = false
  validation {
    condition     = var.instance_shape == "VM.Standard.E5.Flex"
    error_message = "This demo uses VM.Standard.E5.Flex."
  }
}
variable "image_operating_system" {
  description = "Console image filter; Terraform also checks major version 9."
  type        = string
  default     = "Oracle Linux"
  nullable    = false
  validation {
    condition     = var.image_operating_system == "Oracle Linux"
    error_message = "This demo uses Oracle Linux."
  }
}

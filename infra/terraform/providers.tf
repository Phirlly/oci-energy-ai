provider "oci" {
  region = var.region
}

provider "oci" {
  alias  = "home"
  region = local.application == null ? var.region : local.application.home_region
}

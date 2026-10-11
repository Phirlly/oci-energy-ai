provider "oci" {
  region = var.region
}

provider "oci" {
  alias  = "home"
  region = var.application == null ? var.region : var.application.home_region
}

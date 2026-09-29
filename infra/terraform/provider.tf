provider "oci" {
  auth                = var.oci_auth
  config_file_profile = var.oci_profile
  region              = var.region
}

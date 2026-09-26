output "app_compartment_ocid" {
  value = oci_identity_compartment.app.id
}

output "terraform_state_bucket" {
  value = oci_objectstorage_bucket.terraform_state.name
}

output "instance_ocid" {
  value = oci_core_instance.app_host.id
}

output "reserved_public_ip" {
  value = oci_core_public_ip.reserved.ip_address
}

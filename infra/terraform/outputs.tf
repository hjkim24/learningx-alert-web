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

output "backup_bucket" {
  value = oci_objectstorage_bucket.backups.name
}

output "vault_ocid" {
  value = oci_kms_vault.secrets.id
}

output "vault_management_endpoint" {
  value = oci_kms_vault.secrets.management_endpoint
}

output "vault_key_ocid" {
  value = oci_kms_key.secrets.id
}

output "web_nsg_ocid" {
  value = oci_core_network_security_group.web.id
}

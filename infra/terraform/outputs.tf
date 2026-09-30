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

output "django_secret_key_ocid" {
  value = one(data.oci_vault_secrets.django_secret_key.secrets).id
}

output "google_client_secret_ocid" {
  value = one(data.oci_vault_secrets.google_client_secret.secrets).id
}

output "credential_encryption_keys_ocid" {
  value = one(data.oci_vault_secrets.credential_encryption_keys.secrets).id
}

output "object_storage_namespace" {
  value = var.object_storage_namespace
}

output "app_private_ip" {
  value = oci_core_instance.app_host.private_ip
}

output "app_domain" {
  value = var.app_domain
}

output "google_client_id" {
  value = var.google_client_id
}

output "signup_open" {
  value = var.signup_open
}

output "privacy_contact_email" {
  value = var.privacy_contact_email
}

output "admin_emails" {
  value = var.admin_emails
}

output "pilot_allowed_emails" {
  value = var.pilot_allowed_emails
}

output "canvas_base_url" {
  value = var.canvas_base_url
}

output "learningx_allowed_hosts" {
  value = var.learningx_allowed_hosts
}

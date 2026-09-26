resource "oci_kms_vault" "secrets" {
  compartment_id = oci_identity_compartment.app.id
  display_name   = "learningx-alert-vault"
  vault_type     = "DEFAULT"

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [defined_tags, freeform_tags]
  }
}

resource "oci_kms_key" "secrets" {
  compartment_id      = oci_identity_compartment.app.id
  display_name        = "learningx-alert-secrets-key"
  management_endpoint = oci_kms_vault.secrets.management_endpoint
  protection_mode     = "SOFTWARE"

  key_shape {
    algorithm = "AES"
    length    = 32
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [defined_tags, freeform_tags]
  }
}

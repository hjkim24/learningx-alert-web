data "oci_vault_secrets" "django_secret_key" {
  compartment_id = oci_identity_compartment.app.id
  name           = "django-secret-key"
  state          = "ACTIVE"
  vault_id       = oci_kms_vault.secrets.id
}

data "oci_vault_secrets" "google_client_secret" {
  compartment_id = oci_identity_compartment.app.id
  name           = "google-client-secret"
  state          = "ACTIVE"
  vault_id       = oci_kms_vault.secrets.id
}

data "oci_vault_secrets" "credential_encryption_keys" {
  compartment_id = oci_identity_compartment.app.id
  name           = "credential-encryption-keys"
  state          = "ACTIVE"
  vault_id       = oci_kms_vault.secrets.id
}

check "one_django_secret_key" {
  assert {
    condition     = length(data.oci_vault_secrets.django_secret_key.secrets) == 1
    error_message = "expected exactly one active django-secret-key in the application Vault"
  }
}

check "one_google_client_secret" {
  assert {
    condition     = length(data.oci_vault_secrets.google_client_secret.secrets) == 1
    error_message = "expected exactly one active google-client-secret in the application Vault"
  }
}

check "one_credential_encryption_keys" {
  assert {
    condition     = length(data.oci_vault_secrets.credential_encryption_keys.secrets) == 1
    error_message = "expected exactly one active credential-encryption-keys in the application Vault"
  }
}

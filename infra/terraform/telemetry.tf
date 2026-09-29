# Grafana Cloud OTLP export. Empty endpoint = telemetry profile off.
# The token itself is created by hand in the Vault as "grafana-otlp-token";
# Terraform only looks it up, so it never lands in state.

variable "grafana_otlp_endpoint" {
  description = "Grafana Cloud OTLP gateway, e.g. https://otlp-gateway-prod-<region>.grafana.net/otlp. Empty disables export."
  type        = string
  default     = ""
}

variable "grafana_instance_id" {
  description = "Grafana Cloud OTLP instance ID (basic-auth username)."
  type        = string
  default     = ""
}

data "oci_vault_secrets" "grafana_otlp_token" {
  count          = var.grafana_otlp_endpoint == "" ? 0 : 1
  compartment_id = oci_identity_compartment.app.id
  name           = "grafana-otlp-token"
  state          = "ACTIVE"
  vault_id       = oci_kms_vault.secrets.id
}

output "grafana_otlp_endpoint" {
  value = var.grafana_otlp_endpoint
}

output "grafana_instance_id" {
  value = var.grafana_instance_id
}

output "grafana_otlp_token_ocid" {
  value = var.grafana_otlp_endpoint == "" ? "" : one(data.oci_vault_secrets.grafana_otlp_token[0].secrets[*].id)
}

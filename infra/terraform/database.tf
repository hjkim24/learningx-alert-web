# MySQL HeatWave Always Free (MySQL.Free) lives in the app subnet with a private
# IP only. The DB system itself is created outside Terraform so the admin
# password never lands in Terraform state; Terraform owns the network rule that
# lets only the app host reach it, and the Vault secret lookups.

resource "oci_core_network_security_group" "db" {
  compartment_id = oci_identity_compartment.app.id
  display_name   = "learningx-alert-db-nsg"
  vcn_id         = oci_core_vcn.existing.id
}

resource "oci_core_network_security_group_security_rule" "mysql_from_web" {
  network_security_group_id = oci_core_network_security_group.db.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = oci_core_network_security_group.web.id
  source_type               = "NETWORK_SECURITY_GROUP"
  stateless                 = false
  description               = "MySQL from the LearningX Alert host only"

  tcp_options {
    destination_port_range {
      min = 3306
      max = 3306
    }
  }
}

resource "oci_core_network_security_group_security_rule" "mysql_to_web" {
  # Egress from the web NSG to the DB NSG (NSG rules are stateful, so the reply
  # path needs nothing more).
  network_security_group_id = oci_core_network_security_group.web.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = oci_core_network_security_group.db.id
  destination_type          = "NETWORK_SECURITY_GROUP"
  stateless                 = false
  description               = "LearningX Alert host to MySQL"

  tcp_options {
    destination_port_range {
      min = 3306
      max = 3306
    }
  }
}

variable "database_host" {
  description = "Private IP of the MySQL DB system. Empty keeps the app on SQLite."
  type        = string
  default     = ""
}

data "oci_vault_secrets" "database_password" {
  compartment_id = oci_identity_compartment.app.id
  name           = "database-password"
  state          = "ACTIVE"
  vault_id       = oci_kms_vault.secrets.id
}

check "one_database_password" {
  assert {
    condition     = length(data.oci_vault_secrets.database_password.secrets) == 1
    error_message = "expected exactly one active database-password in the application Vault"
  }
}

output "db_nsg_ocid" {
  value = oci_core_network_security_group.db.id
}

output "database_host" {
  value = var.database_host
}

output "database_password_ocid" {
  value = one(data.oci_vault_secrets.database_password.secrets[*].id)
}

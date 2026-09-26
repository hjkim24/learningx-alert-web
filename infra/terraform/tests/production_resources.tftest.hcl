mock_provider "oci" {}

variables {
  tenancy_ocid                       = "ocid1.tenancy.oc1..test"
  existing_compartment_ocid          = "ocid1.tenancy.oc1..test"
  app_compartment_ocid               = "ocid1.compartment.oc1..test"
  object_storage_namespace           = "testnamespace"
  instance_ocid                      = "ocid1.instance.oc1.ap-chuncheon-1.test"
  instance_availability_domain       = "test:AP-CHUNCHEON-1-AD-1"
  instance_image_ocid                = "ocid1.image.oc1.ap-chuncheon-1.test"
  instance_boot_volume_size_in_gbs   = 47
  instance_boot_volume_vpus_per_gb   = 10
  instance_assign_public_ip          = true
  instance_assign_private_dns_record = false
  instance_vnic_display_name         = "tossterm"
  instance_skip_source_dest_check    = false
  instance_existing_nsg_ids          = []
  vcn_ocid                           = "ocid1.vcn.oc1.ap-chuncheon-1.test"
  vcn_dns_label                      = "tossterm"
  vcn_is_ipv6enabled                 = false
  subnet_ocid                        = "ocid1.subnet.oc1.ap-chuncheon-1.test"
  subnet_dns_label                   = "sub"
  subnet_dhcp_options_ocid           = "ocid1.dhcpoptions.oc1.ap-chuncheon-1.test"
  subnet_route_table_ocid            = "ocid1.routetable.oc1.ap-chuncheon-1.test"
  subnet_security_list_ocids         = ["ocid1.securitylist.oc1.ap-chuncheon-1.test"]
  subnet_prohibit_public_ip_on_vnic  = false
  subnet_prohibit_internet_ingress   = false
  reserved_public_ip_ocid            = "ocid1.publicip.oc1.ap-chuncheon-1.test"
  reserved_public_ip_display_name    = "tossterm-reserved-ip"
  primary_private_ip_ocid            = "ocid1.privateip.oc1.ap-chuncheon-1.test"
  google_client_id                   = "test.apps.googleusercontent.com"
  pilot_allowed_emails               = "pilot@example.com"
}

run "approved_production_resources" {
  command = plan

  assert {
    condition = (
      oci_objectstorage_bucket.backups.name == "learningx-alert-backups" &&
      oci_objectstorage_bucket.backups.access_type == "NoPublicAccess"
    )
    error_message = "backup bucket must be private and use the approved name"
  }

  assert {
    condition = (
      one(oci_objectstorage_object_lifecycle_policy.backups.rules).action == "DELETE" &&
      one(oci_objectstorage_object_lifecycle_policy.backups.rules).target == "objects" &&
      one(oci_objectstorage_object_lifecycle_policy.backups.rules).time_amount == "14" &&
      one(oci_objectstorage_object_lifecycle_policy.backups.rules).time_unit == "DAYS"
    )
    error_message = "backup objects must expire after 14 days"
  }

  assert {
    condition = (
      oci_kms_vault.secrets.vault_type == "DEFAULT" &&
      oci_kms_key.secrets.key_shape[0].algorithm == "AES" &&
      oci_kms_key.secrets.key_shape[0].length == 32 &&
      oci_kms_key.secrets.protection_mode == "SOFTWARE"
    )
    error_message = "Vault must use the approved default vault and AES-256 software key"
  }

  assert {
    condition     = oci_identity_dynamic_group.app_instance.matching_rule == "instance.id = '${var.instance_ocid}'"
    error_message = "dynamic group must match only the existing app instance"
  }

  assert {
    condition = (
      contains(oci_identity_policy.app_instance.statements, "Allow dynamic-group learningx-alert-instance to read secret-bundles in compartment id ${var.app_compartment_ocid} where any {target.secret.name = 'django-secret-key', target.secret.name = 'google-client-secret', target.secret.name = 'credential-encryption-keys'}") &&
      contains(oci_identity_policy.app_instance.statements, "Allow dynamic-group learningx-alert-instance to manage objects in compartment id ${var.app_compartment_ocid} where target.bucket.name = 'learningx-alert-backups'") &&
      contains(oci_identity_policy.app_instance.statements, "Allow service objectstorage-ap-chuncheon-1 to manage object-family in compartment id ${var.app_compartment_ocid} where target.bucket.name = 'learningx-alert-backups'")
    )
    error_message = "policy must limit instance and lifecycle access to approved secrets and backup objects"
  }

  assert {
    condition = (
      oci_core_network_security_group_security_rule.http.tcp_options[0].destination_port_range[0].min == 80 &&
      oci_core_network_security_group_security_rule.http.tcp_options[0].destination_port_range[0].max == 80 &&
      oci_core_network_security_group_security_rule.https.tcp_options[0].destination_port_range[0].min == 443 &&
      oci_core_network_security_group_security_rule.https.tcp_options[0].destination_port_range[0].max == 443
    )
    error_message = "web NSG must expose only the approved HTTP and HTTPS ports"
  }

  assert {
    condition     = length(oci_core_instance.app_host.create_vnic_details[0].nsg_ids) == length(var.instance_existing_nsg_ids) + 1
    error_message = "the app instance must retain existing NSGs and add exactly the web NSG"
  }
}

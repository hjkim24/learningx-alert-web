resource "oci_core_vcn" "existing" {
  compartment_id = var.existing_compartment_ocid
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "tossterm-vcn"
  dns_label      = var.vcn_dns_label
  is_ipv6enabled = var.vcn_is_ipv6enabled

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [defined_tags, freeform_tags]
  }
}

resource "oci_core_subnet" "existing" {
  cidr_block                 = "10.0.1.0/24"
  compartment_id             = var.existing_compartment_ocid
  vcn_id                     = oci_core_vcn.existing.id
  display_name               = "tossterm-subnet"
  dns_label                  = var.subnet_dns_label
  dhcp_options_id            = var.subnet_dhcp_options_ocid
  route_table_id             = var.subnet_route_table_ocid
  security_list_ids          = var.subnet_security_list_ocids
  prohibit_public_ip_on_vnic = var.subnet_prohibit_public_ip_on_vnic
  prohibit_internet_ingress  = var.subnet_prohibit_internet_ingress

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [defined_tags, freeform_tags]
  }
}

resource "oci_core_instance" "app_host" {
  availability_domain  = var.instance_availability_domain
  compartment_id       = var.existing_compartment_ocid
  display_name         = "lab-hjkim24"
  shape                = "VM.Standard.A1.Flex"
  preserve_boot_volume = true

  shape_config {
    memory_in_gbs = 12
    ocpus         = 2
  }

  source_details {
    boot_volume_size_in_gbs = var.instance_boot_volume_size_in_gbs
    boot_volume_vpus_per_gb = var.instance_boot_volume_vpus_per_gb
    source_id               = var.instance_image_ocid
    source_type             = "image"
  }

  create_vnic_details {
    assign_private_dns_record = var.instance_assign_private_dns_record
    assign_public_ip          = var.instance_assign_public_ip
    display_name              = var.instance_vnic_display_name
    hostname_label            = "tossterm"
    nsg_ids                   = concat(var.instance_existing_nsg_ids, [oci_core_network_security_group.web.id])
    private_ip                = "10.0.1.31"
    skip_source_dest_check    = var.instance_skip_source_dest_check
    subnet_id                 = oci_core_subnet.existing.id
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      defined_tags,
      extended_metadata,
      freeform_tags,
      metadata,
      preserve_boot_volume,
    ]
  }
}

resource "oci_core_public_ip" "reserved" {
  compartment_id = var.existing_compartment_ocid
  display_name   = var.reserved_public_ip_display_name
  lifetime       = "RESERVED"
  private_ip_id  = var.primary_private_ip_ocid

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [defined_tags, freeform_tags]
  }
}

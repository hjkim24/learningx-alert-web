variable "region" {
  type    = string
  default = "ap-chuncheon-1"
}

variable "oci_profile" {
  type    = string
  default = "LEARNINGX_ALERT"
}

variable "tenancy_ocid" {
  type = string
}

variable "existing_compartment_ocid" {
  type = string
}

variable "app_compartment_ocid" {
  type = string
}

variable "object_storage_namespace" {
  type = string
}

variable "instance_ocid" {
  type = string
}

variable "instance_availability_domain" {
  type = string
}

variable "instance_image_ocid" {
  type = string
}

variable "instance_boot_volume_size_in_gbs" {
  type = number
}

variable "instance_boot_volume_vpus_per_gb" {
  type = number
}

variable "instance_assign_public_ip" {
  type = bool
}

variable "instance_assign_private_dns_record" {
  type = bool
}

variable "instance_vnic_display_name" {
  type = string
}

variable "instance_skip_source_dest_check" {
  type = bool
}

variable "instance_existing_nsg_ids" {
  type = list(string)
}

variable "vcn_ocid" {
  type = string
}

variable "vcn_dns_label" {
  type = string
}

variable "vcn_is_ipv6enabled" {
  type = bool
}

variable "subnet_ocid" {
  type = string
}

variable "subnet_dns_label" {
  type = string
}

variable "subnet_dhcp_options_ocid" {
  type = string
}

variable "subnet_route_table_ocid" {
  type = string
}

variable "subnet_security_list_ocids" {
  type = list(string)
}

variable "subnet_prohibit_public_ip_on_vnic" {
  type = bool
}

variable "subnet_prohibit_internet_ingress" {
  type = bool
}

variable "reserved_public_ip_ocid" {
  type = string
}

variable "reserved_public_ip_display_name" {
  type = string
}

variable "primary_private_ip_ocid" {
  type = string
}

variable "google_client_id" {
  type = string
}

variable "pilot_allowed_emails" {
  type = string
}

variable "canvas_base_url" {
  type    = string
  default = "https://canvas.skku.edu"
}

variable "app_domain" {
  type    = string
  default = "alert.sobok-app.com"
}

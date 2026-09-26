resource "oci_core_network_security_group" "web" {
  compartment_id = oci_identity_compartment.app.id
  display_name   = "learningx-alert-web-nsg"
  vcn_id         = oci_core_vcn.existing.id
}

resource "oci_core_network_security_group_security_rule" "http" {
  network_security_group_id = oci_core_network_security_group.web.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "0.0.0.0/0"
  source_type               = "CIDR_BLOCK"
  stateless                 = false
  description               = "Public HTTP for Caddy certificate redirects"

  tcp_options {
    destination_port_range {
      min = 80
      max = 80
    }
  }
}

resource "oci_core_network_security_group_security_rule" "https" {
  network_security_group_id = oci_core_network_security_group.web.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "0.0.0.0/0"
  source_type               = "CIDR_BLOCK"
  stateless                 = false
  description               = "Public HTTPS for LearningX Alert"

  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

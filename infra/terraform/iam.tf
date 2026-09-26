resource "oci_identity_dynamic_group" "app_instance" {
  compartment_id = var.tenancy_ocid
  name           = "learningx-alert-instance"
  description    = "LearningX Alert production instance principal"
  matching_rule  = "instance.id = '${var.instance_ocid}'"
}

resource "oci_identity_policy" "app_instance" {
  compartment_id = var.tenancy_ocid
  name           = "learningx-alert-instance-policy"
  description    = "Least-privilege access for the LearningX Alert instance"
  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.app_instance.name} to read secret-bundles in compartment id ${var.app_compartment_ocid} where any {target.secret.name = 'django-secret-key', target.secret.name = 'google-client-secret', target.secret.name = 'credential-encryption-keys'}",
    "Allow dynamic-group ${oci_identity_dynamic_group.app_instance.name} to manage objects in compartment id ${var.app_compartment_ocid} where target.bucket.name = 'learningx-alert-backups'",
    "Allow service objectstorage-${var.region} to manage object-family in compartment id ${var.app_compartment_ocid} where target.bucket.name = 'learningx-alert-backups'",
  ]
}

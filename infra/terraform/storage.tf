resource "oci_identity_compartment" "app" {
  compartment_id = var.tenancy_ocid
  description    = "LearningX Alert production resources"
  name           = "learningx-alert-prod"
  enable_delete  = false

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [defined_tags, freeform_tags]
  }
}

resource "oci_objectstorage_bucket" "terraform_state" {
  compartment_id        = oci_identity_compartment.app.id
  name                  = "learningx-alert-tfstate"
  namespace             = var.object_storage_namespace
  access_type           = "NoPublicAccess"
  auto_tiering          = "Disabled"
  object_events_enabled = false
  storage_tier          = "Standard"
  versioning            = "Enabled"

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [defined_tags, freeform_tags]
  }
}

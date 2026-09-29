#!/usr/bin/env bash
set -euo pipefail

TERRAFORM_BIN=${TERRAFORM_BIN:-terraform}
TF_DIR=${TF_DIR:-infra/terraform}
TFVARS_FILE=${TFVARS_FILE:-terraform.tfvars}

[[ -f "$TF_DIR/$TFVARS_FILE" || "$TERRAFORM_BIN" != "terraform" ]] || {
    printf 'missing %s/%s\n' "$TF_DIR" "$TFVARS_FILE" >&2
    exit 1
}

tf_value() {
    local variable_name=$1
    local value
    value=$(printf 'var.%s\n' "$variable_name" | \
        "$TERRAFORM_BIN" -chdir="$TF_DIR" console -var-file="$TFVARS_FILE")
    value=${value#\"}
    value=${value%\"}
    [[ -n "$value" && "$value" != "null" ]] || {
        printf 'missing Terraform variable: %s\n' "$variable_name" >&2
        exit 1
    }
    printf '%s\n' "$value"
}

import_if_missing() {
    local address=$1
    local import_id=$2
    if "$TERRAFORM_BIN" -chdir="$TF_DIR" state show "$address" >/dev/null 2>&1; then
        printf 'already_imported address=%s\n' "$address"
        return
    fi
    "$TERRAFORM_BIN" -chdir="$TF_DIR" import \
        -var-file="$TFVARS_FILE" \
        "$address" \
        "$import_id"
}

app_compartment_id=$(tf_value app_compartment_ocid)
namespace=$(tf_value object_storage_namespace)
instance_id=$(tf_value instance_ocid)
vcn_id=$(tf_value vcn_ocid)
subnet_id=$(tf_value subnet_ocid)
public_ip_id=$(tf_value reserved_public_ip_ocid)

import_if_missing oci_identity_compartment.app "$app_compartment_id"
import_if_missing oci_objectstorage_bucket.terraform_state "n/$namespace/b/learningx-alert-tfstate"
import_if_missing oci_core_instance.app_host "$instance_id"
import_if_missing oci_core_vcn.existing "$vcn_id"
import_if_missing oci_core_subnet.existing "$subnet_id"
import_if_missing oci_core_public_ip.reserved "$public_ip_id"

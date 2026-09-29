#!/usr/bin/env bash
set -euo pipefail

OCI_BIN=${OCI_BIN:-oci}
OCI_PROFILE=${OCI_PROFILE:-LEARNINGX_ALERT}
OCI_REGION=${OCI_REGION:-ap-chuncheon-1}
APP_COMPARTMENT_NAME=${APP_COMPARTMENT_NAME:-learningx-alert-prod}
STATE_BUCKET_NAME=${STATE_BUCKET_NAME:-learningx-alert-tfstate}

oci_call() {
    "$OCI_BIN" "$@" \
        --profile "$OCI_PROFILE" \
        --auth security_token \
        --region "$OCI_REGION"
}

tenancy_id=$(oci_call iam availability-domain list \
    --query 'data[0]."compartment-id"' \
    --raw-output)
[[ -n "$tenancy_id" && "$tenancy_id" != "null" ]] || {
    printf 'unable to resolve tenancy\n' >&2
    exit 1
}

compartment_count=$(oci_call iam compartment list \
    --compartment-id "$tenancy_id" \
    --name "$APP_COMPARTMENT_NAME" \
    --lifecycle-state ACTIVE \
    --all \
    --query 'length(data)' \
    --raw-output)
compartment_count=${compartment_count:-0}
case "$compartment_count" in
    0)
        oci_call iam compartment create \
            --compartment-id "$tenancy_id" \
            --name "$APP_COMPARTMENT_NAME" \
            --description "LearningX Alert production resources" \
            --wait-for-state ACTIVE \
            --query 'data.id' \
            --raw-output >/dev/null
        app_compartment_id=$(oci_call iam compartment list \
            --compartment-id "$tenancy_id" \
            --name "$APP_COMPARTMENT_NAME" \
            --lifecycle-state ACTIVE \
            --all \
            --query 'data[0].id' \
            --raw-output)
        ;;
    1)
        app_compartment_id=$(oci_call iam compartment list \
            --compartment-id "$tenancy_id" \
            --name "$APP_COMPARTMENT_NAME" \
            --lifecycle-state ACTIVE \
            --all \
            --query 'data[0].id' \
            --raw-output)
        ;;
    *)
        printf 'ambiguous app compartment: %s active matches\n' "$compartment_count" >&2
        exit 1
        ;;
esac
[[ -n "$app_compartment_id" && "$app_compartment_id" != "null" ]] || {
    printf 'unable to resolve app compartment\n' >&2
    exit 1
}

namespace=$(oci_call os ns get --query data --raw-output)
[[ -n "$namespace" && "$namespace" != "null" ]] || {
    printf 'unable to resolve object storage namespace\n' >&2
    exit 1
}

bucket_count=$(oci_call os bucket list \
    --compartment-id "$app_compartment_id" \
    --namespace-name "$namespace" \
    --all \
    --query "length(data[?name=='$STATE_BUCKET_NAME'])" \
    --raw-output)
bucket_count=${bucket_count:-0}
case "$bucket_count" in
    0)
        oci_call os bucket create \
            --compartment-id "$app_compartment_id" \
            --namespace-name "$namespace" \
            --name "$STATE_BUCKET_NAME" \
            --public-access-type NoPublicAccess \
            --storage-tier Standard \
            --versioning Enabled \
            --query 'data.name' \
            --raw-output >/dev/null
        ;;
    1)
        oci_call os bucket update \
            --namespace-name "$namespace" \
            --name "$STATE_BUCKET_NAME" \
            --public-access-type NoPublicAccess \
            --versioning Enabled \
            --query 'data.name' \
            --raw-output >/dev/null
        ;;
    *)
        printf 'ambiguous state bucket: %s matches\n' "$bucket_count" >&2
        exit 1
        ;;
esac

printf 'app_compartment_id=%s\n' "$app_compartment_id"
printf 'state_bucket_name=%s\n' "$STATE_BUCKET_NAME"
printf 'namespace=%s\n' "$namespace"

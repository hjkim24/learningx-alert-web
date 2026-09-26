#!/usr/bin/env bash
set -euo pipefail

OCI_BIN=${OCI_BIN:-oci}
SECRETS_DIR=${SECRETS_DIR:-/run/learningx-alert/secrets}
SECRET_UID=${SECRET_UID:-0}
SECRET_GID=${SECRET_GID:-10001}

: "${DJANGO_SECRET_KEY_OCID:?DJANGO_SECRET_KEY_OCID is required}"
: "${GOOGLE_CLIENT_SECRET_OCID:?GOOGLE_CLIENT_SECRET_OCID is required}"
: "${CREDENTIAL_ENCRYPTION_KEYS_OCID:?CREDENTIAL_ENCRYPTION_KEYS_OCID is required}"

staging_dir=""
cleanup() {
    if [[ -n "$staging_dir" && -d "$staging_dir" ]]; then
        rm -rf -- "$staging_dir"
    fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

fail_bundle() {
    printf 'secret_fetch_failed name=%s\n' "$1" >&2
    exit 1
}

fetch_bundle() {
    local secret_id=$1
    local output_name=$2
    local staged_path="$staging_dir/$output_name"

    if ! "$OCI_BIN" secrets secret-bundle get \
        --secret-id "$secret_id" \
        --stage CURRENT \
        --auth instance_principal \
        --query 'data."secret-bundle-content".content' \
        --raw-output | base64 -d >"$staged_path"; then
        fail_bundle "$output_name"
    fi
    [[ -s "$staged_path" ]] || fail_bundle "$output_name"
}

secrets_parent=$(dirname "$SECRETS_DIR")
install -d -m 0750 -o "$SECRET_UID" -g "$SECRET_GID" "$secrets_parent"
staging_dir=$(mktemp -d "$secrets_parent/.secrets.XXXXXX")
chmod 0700 "$staging_dir"

fetch_bundle "$DJANGO_SECRET_KEY_OCID" django-secret-key
fetch_bundle "$GOOGLE_CLIENT_SECRET_OCID" google-client-secret
fetch_bundle "$CREDENTIAL_ENCRYPTION_KEYS_OCID" credential-encryption-keys

install -d -m 0750 -o "$SECRET_UID" -g "$SECRET_GID" "$SECRETS_DIR"
for name in django-secret-key google-client-secret credential-encryption-keys; do
    install -m 0440 -o "$SECRET_UID" -g "$SECRET_GID" "$staging_dir/$name" "$SECRETS_DIR/$name"
done

printf 'secrets_ready\n'

#!/usr/bin/env bash
set -euo pipefail

OCI_BIN=${OCI_BIN:-oci}
SECRETS_DIR=${SECRETS_DIR:-/run/learningx-alert/secrets}
SECRET_UID=${SECRET_UID:-0}
SECRET_GID=${SECRET_GID:-10001}

: "${DJANGO_SECRET_KEY_OCID:?DJANGO_SECRET_KEY_OCID is required}"
: "${GOOGLE_CLIENT_SECRET_OCID:?GOOGLE_CLIENT_SECRET_OCID is required}"
: "${CREDENTIAL_ENCRYPTION_KEYS_OCID:?CREDENTIAL_ENCRYPTION_KEYS_OCID is required}"

download_dir=""
generation_dir=""
legacy_dir=""
link_path=""
cleanup() {
    if [[ -n "$legacy_dir" && -d "$legacy_dir" && ! -e "$SECRETS_DIR" ]]; then
        mv "$legacy_dir" "$SECRETS_DIR"
    fi
    if [[ -n "$link_path" && -L "$link_path" ]]; then
        rm -f -- "$link_path"
    fi
    if [[ -n "$download_dir" && -d "$download_dir" ]]; then
        rm -rf -- "$download_dir"
    fi
    if [[ -n "$generation_dir" && -d "$generation_dir" ]]; then
        rm -rf -- "$generation_dir"
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
    local staged_path="$download_dir/$output_name"

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
generations_dir="$secrets_parent/secret-sets"
install -d -m 0750 -o "$SECRET_UID" -g "$SECRET_GID" "$generations_dir"
download_dir=$(mktemp -d "$secrets_parent/.secret-download.XXXXXX")
generation_dir=$(mktemp -d "$generations_dir/.generation.XXXXXX")
chmod 0700 "$download_dir"
chown "$SECRET_UID:$SECRET_GID" "$generation_dir"
chmod 0750 "$generation_dir"

fetch_bundle "$DJANGO_SECRET_KEY_OCID" django-secret-key
fetch_bundle "$GOOGLE_CLIENT_SECRET_OCID" google-client-secret
fetch_bundle "$CREDENTIAL_ENCRYPTION_KEYS_OCID" credential-encryption-keys

secret_names=(django-secret-key google-client-secret credential-encryption-keys)
# Optional: only present once the app moves off SQLite.
if [[ -n "${DATABASE_PASSWORD_OCID:-}" ]]; then
    fetch_bundle "$DATABASE_PASSWORD_OCID" database-password
    secret_names+=(database-password)
fi

for name in "${secret_names[@]}"; do
    install -m 0440 -o "$SECRET_UID" -g "$SECRET_GID" "$download_dir/$name" "$generation_dir/$name"
done

link_path="$secrets_parent/.secrets-link.$$"
ln -s "$generation_dir" "$link_path"
if [[ -d "$SECRETS_DIR" && ! -L "$SECRETS_DIR" ]]; then
    legacy_dir="$generations_dir/legacy-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mv "$SECRETS_DIR" "$legacy_dir"
fi
if ! python3 - "$link_path" "$SECRETS_DIR" <<'PY'
import os
import sys

os.replace(sys.argv[1], sys.argv[2])
PY
then
    exit 1
fi
generation_dir=""

printf 'secrets_ready\n'

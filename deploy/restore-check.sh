#!/usr/bin/env bash
set -euo pipefail

OCI_BIN=${OCI_BIN:-oci}
SQLITE_BIN=${SQLITE_BIN:-sqlite3}

: "${OCI_NAMESPACE:?OCI_NAMESPACE is required}"
: "${BACKUP_BUCKET:?BACKUP_BUCKET is required}"

if [[ $# -ne 1 || "$1" == *..* ]] || ! [[ "$1" =~ ^sqlite/[A-Za-z0-9][A-Za-z0-9._/-]*\.sqlite3$ || "$1" =~ ^mysql/[A-Za-z0-9][A-Za-z0-9._/-]*\.sql\.gz$ ]]; then
    printf 'usage: restore-check.sh sqlite/path/to/backup.sqlite3 | mysql/path/to/backup.sql.gz\n' >&2
    exit 2
fi
object_name=$1

restore_dir=$(mktemp -d "${TMPDIR:-/tmp}/learningx-alert-restore.XXXXXX")
cleanup() {
    rm -rf -- "$restore_dir"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

restore_path="$restore_dir/restored.sqlite3"
"$OCI_BIN" os object get \
    --namespace "$OCI_NAMESPACE" \
    --bucket-name "$BACKUP_BUCKET" \
    --name "$object_name" \
    --file "$restore_path" \
    --auth instance_principal >/dev/null

if [[ "$object_name" == mysql/* ]]; then
    # A dump is only complete if gzip is intact and mysqldump wrote its trailer.
    if ! gzip -t "$restore_path" 2>/dev/null \
        || ! gzip -dc "$restore_path" | tail -n 1 | grep -q '^-- Dump completed'; then
        printf 'restore_integrity_failed\n' >&2
        exit 1
    fi
    printf 'restore_ok object=%s\n' "$object_name"
    exit 0
fi

integrity=$($SQLITE_BIN "$restore_path" 'PRAGMA integrity_check;')
if [[ "$integrity" != "ok" ]]; then
    printf 'restore_integrity_failed\n' >&2
    exit 1
fi

printf 'restore_ok object=%s\n' "$object_name"

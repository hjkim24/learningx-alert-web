#!/usr/bin/env bash
set -euo pipefail

OCI_BIN=${OCI_BIN:-oci}
SQLITE_BIN=${SQLITE_BIN:-sqlite3}
DATABASE_PATH=${DATABASE_PATH:-/var/lib/learningx-alert/db.sqlite3}
BACKUP_DIR=${BACKUP_DIR:-/var/lib/learningx-alert/backups}

: "${OCI_NAMESPACE:?OCI_NAMESPACE is required}"
: "${BACKUP_BUCKET:?BACKUP_BUCKET is required}"

case "$BACKUP_DIR" in
    ""|/|/var|/var/lib)
        printf 'unsafe_backup_directory\n' >&2
        exit 1
        ;;
esac

if [[ ! -f "$DATABASE_PATH" ]]; then
    printf 'database_absent\n'
    exit 0
fi

install -d -m 0750 "$BACKUP_DIR"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
object_date=$(date -u +%Y/%m/%d)
file_name="learningx-alert-${timestamp}-$$.sqlite3"
backup_path="$BACKUP_DIR/$file_name"
escaped_backup_path=${backup_path//\'/\'\'}

"$SQLITE_BIN" "$DATABASE_PATH" ".backup '$escaped_backup_path'"
chmod 0600 "$backup_path"

integrity=$($SQLITE_BIN "$backup_path" 'PRAGMA integrity_check;')
if [[ "$integrity" != "ok" ]]; then
    printf 'backup_integrity_failed\n' >&2
    exit 1
fi

object_name="sqlite/$object_date/$file_name"
"$OCI_BIN" os object put \
    --namespace "$OCI_NAMESPACE" \
    --bucket-name "$BACKUP_BUCKET" \
    --name "$object_name" \
    --file "$backup_path" \
    --force \
    --auth instance_principal >/dev/null

find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.sqlite3' -mtime +14 -delete
printf 'backup_uploaded object=%s\n' "$object_name"

#!/usr/bin/env bash
set -euo pipefail

OCI_BIN=${OCI_BIN:-oci}
SQLITE_BIN=${SQLITE_BIN:-sqlite3}
DOCKER_BIN=${DOCKER_BIN:-docker}
MYSQL_IMAGE=${MYSQL_IMAGE:-mysql:8.4}
DATABASE_ENGINE=${DATABASE_ENGINE:-sqlite}
DATABASE_PATH=${DATABASE_PATH:-/var/lib/learningx-alert/db.sqlite3}
BACKUP_DIR=${BACKUP_DIR:-/var/lib/learningx-alert/backups}
SECRETS_DIR=${SECRETS_DIR:-/run/learningx-alert/secrets}

: "${OCI_NAMESPACE:?OCI_NAMESPACE is required}"
: "${BACKUP_BUCKET:?BACKUP_BUCKET is required}"

case "$BACKUP_DIR" in
    ""|/|/var|/var/lib)
        printf 'unsafe_backup_directory\n' >&2
        exit 1
        ;;
esac

install -d -m 0750 "$BACKUP_DIR"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
object_date=$(date -u +%Y/%m/%d)

work_dir=""
cleanup() {
    if [[ -n "$work_dir" && -d "$work_dir" ]]; then
        rm -rf -- "$work_dir"
    fi
}
trap cleanup EXIT

upload() {
    local path=$1 object_name=$2
    "$OCI_BIN" os object put \
        --namespace "$OCI_NAMESPACE" \
        --bucket-name "$BACKUP_BUCKET" \
        --name "$object_name" \
        --file "$path" \
        --force \
        --auth instance_principal >/dev/null
    printf 'backup_uploaded object=%s\n' "$object_name"
}

backup_mysql() {
    : "${DATABASE_HOST:?DATABASE_HOST is required for mysql backups}"
    local database_name=${DATABASE_NAME:-learningx_alert}
    local database_user=${DATABASE_USER:-learningx}
    local password_file="$SECRETS_DIR/database-password"
    [[ -s "$password_file" ]] || { printf 'database_password_missing\n' >&2; exit 1; }

    local file_name="learningx-alert-${timestamp}-$$.sql.gz"
    local backup_path="$BACKUP_DIR/$file_name"
    work_dir=$(mktemp -d "$BACKUP_DIR/.mysqldump.XXXXXX")
    chmod 0700 "$work_dir"
    # Credentials go through an option file, never argv; quoted because the
    # password may contain '#', which my.cnf would otherwise treat as a comment.
    {
        printf '[client]\nuser="%s"\n' "$database_user"
        printf 'password="%s"\n' "$(<"$password_file")"
    } >"$work_dir/client.cnf"
    chmod 0444 "$work_dir/client.cnf"

    "$DOCKER_BIN" run --rm --network host -v "$work_dir:/cfg:ro" "$MYSQL_IMAGE" \
        mysqldump --defaults-extra-file=/cfg/client.cnf \
        -h "$DATABASE_HOST" --ssl-mode=REQUIRED \
        --single-transaction --no-tablespaces --routines --triggers \
        --set-gtid-purged=OFF "$database_name" \
        | gzip -c >"$backup_path"
    chmod 0600 "$backup_path"

    # mysqldump writes this trailer only when it finished cleanly.
    if ! gzip -dc "$backup_path" | tail -n 1 | grep -q '^-- Dump completed'; then
        printf 'backup_integrity_failed\n' >&2
        exit 1
    fi
    upload "$backup_path" "mysql/$object_date/$file_name"
}

backup_sqlite() {
    if [[ ! -f "$DATABASE_PATH" ]]; then
        printf 'database_absent\n'
        exit 0
    fi
    local file_name="learningx-alert-${timestamp}-$$.sqlite3"
    local backup_path="$BACKUP_DIR/$file_name"
    local escaped_backup_path=${backup_path//\'/\'\'}

    "$SQLITE_BIN" "$DATABASE_PATH" ".backup '$escaped_backup_path'"
    chmod 0600 "$backup_path"

    local integrity
    integrity=$($SQLITE_BIN "$backup_path" 'PRAGMA integrity_check;')
    if [[ "$integrity" != "ok" ]]; then
        printf 'backup_integrity_failed\n' >&2
        exit 1
    fi
    upload "$backup_path" "sqlite/$object_date/$file_name"
}

case "$DATABASE_ENGINE" in
    mysql) backup_mysql ;;
    sqlite) backup_sqlite ;;
    *) printf 'unknown_database_engine\n' >&2; exit 1 ;;
esac

# Local copies follow the bucket's 14-day lifecycle rule.
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name '*.sqlite3' -o -name '*.sql.gz' \) -mtime +14 -delete

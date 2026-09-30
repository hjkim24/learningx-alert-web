#!/usr/bin/env bash
# Restore drill: load the newest MySQL dump from Object Storage into a
# throwaway MySQL container (no network) and compare per-table row counts with
# the live database. Never touches the live database; prints counts only.
#
#   sudo ./deploy/restore-drill.sh            # run from the current release dir
set -euo pipefail

RUNTIME_ENV=${RUNTIME_ENV:-/etc/learningx-alert/runtime.env}
BACKUP_DIR=${BACKUP_DIR:-/var/lib/learningx-alert/backups}
MYSQL_IMAGE=${MYSQL_IMAGE:-mysql:8.4}
COMPOSE=(docker compose -p learningx-alert -f compose.prod.yaml)

set -a
# shellcheck disable=SC1090
source "$RUNTIME_ENV"
set +a
: "${OCI_NAMESPACE:?}" "${BACKUP_BUCKET:?}"

work_dir=$(mktemp -d "$BACKUP_DIR/.restore-drill.XXXXXX")
chmod 0700 "$work_dir"
container="learningx-restore-drill-$$"
cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
    rm -rf -- "$work_dir"
}
trap cleanup EXIT

object=$(
    oci os object list --namespace "$OCI_NAMESPACE" --bucket-name "$BACKUP_BUCKET" \
        --prefix mysql/ --all --auth instance_principal --query 'data[].name' \
        --raw-output | python3 -c 'import json, sys; print(sorted(json.load(sys.stdin))[-1])'
)
printf 'drill_object=%s\n' "$object"
oci os object get --namespace "$OCI_NAMESPACE" --bucket-name "$BACKUP_BUCKET" \
    --name "$object" --file "$work_dir/dump.sql.gz" --auth instance_principal >/dev/null
gzip -t "$work_dir/dump.sql.gz"

# A random root password that lives only in this drill's work dir.
python3 -c 'import secrets; print(secrets.token_hex(16))' >"$work_dir/root-password"
printf '[client]\nuser=root\npassword="%s"\n' "$(<"$work_dir/root-password")" >"$work_dir/root.cnf"
chmod 0444 "$work_dir/root-password" "$work_dir/root.cnf"

docker run -d --name "$container" --network none \
    -e MYSQL_ROOT_PASSWORD_FILE=/drill/root-password \
    -v "$work_dir:/drill:ro" "$MYSQL_IMAGE" >/dev/null
mysql_in() { docker exec -i "$container" mysql --defaults-extra-file=/drill/root.cnf "$@"; }
# No -i: inside `while read` loops stdin must stay with the loop.
mysql_q() { docker exec "$container" mysql --defaults-extra-file=/drill/root.cnf "$@"; }
for _ in $(seq 1 90); do
    mysql_in -e 'SELECT 1' >/dev/null 2>&1 && break
    sleep 2
done
mysql_in -e 'CREATE DATABASE restore_drill CHARACTER SET utf8mb4'

started=$(date +%s)
gzip -dc "$work_dir/dump.sql.gz" | mysql_in restore_drill
printf 'restore_seconds=%s\n' "$(($(date +%s) - started))"

mysql_q -N restore_drill -e "SELECT table_name FROM information_schema.tables
    WHERE table_schema='restore_drill' ORDER BY table_name" >"$work_dir/tables"
restored_counts() {
    while read -r table; do
        printf '%s %s\n' "$table" "$(mysql_q -N restore_drill -e "SELECT COUNT(*) FROM \`$table\`")"
    done <"$work_dir/tables"
}
restored_counts >"$work_dir/restored"

"${COMPOSE[@]}" exec -T web python manage.py shell -c "
from django.db import connection
tables = sorted(connection.introspection.table_names())
with connection.cursor() as cursor:
    for table in tables:
        cursor.execute('SELECT COUNT(*) FROM ' + connection.ops.quote_name(table))
        print(table, cursor.fetchone()[0])
" >"$work_dir/live"

python3 - "$work_dir/restored" "$work_dir/live" <<'PY'
import re
import sys

ROW = re.compile(r"^(\w+) (\d+)$")

def load(path):
    rows = {}
    for line in open(path):
        match = ROW.match(line.strip())  # skips Django check warnings etc.
        if match:
            rows[match[1]] = int(match[2])
    return rows

restored, live = load(sys.argv[1]), load(sys.argv[2])
missing = sorted(set(live) - set(restored))
different = []
for table in sorted(set(live) | set(restored)):
    r, l = restored.get(table), live.get(table)
    if r != l:
        different.append(f"{table}: backup={r} live={l}")
print(f"tables_restored={len(restored)} tables_live={len(live)} rows_restored={sum(restored.values())}")
print("missing_tables=" + (",".join(missing) or "none"))
print("count_differences=" + (len(different) and "\n  " + "\n  ".join(different) or "none"))
sys.exit(1 if missing else 0)
PY
printf 'restore_drill_ok\n'

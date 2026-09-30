#!/usr/bin/env bash
# Monthly restore drill (learningx-alert-restore-drill.timer): run
# deploy/restore-drill.sh, then report the outcome through the web container's
# log pipeline so Grafana can post it to Discord. Counts only, never data.
set -uo pipefail

cd /opt/learningx-alert/current || exit 1
log=$(mktemp)
trap 'rm -f "$log"' EXIT

./deploy/restore-drill.sh >"$log" 2>&1
code=$?
cat "$log"

value() { sed -n "s/.*$1=\([0-9]*\).*/\1/p" "$log" | head -1; }
tables=$(value tables_restored)
rows=$(value rows_restored)
seconds=$(value restore_seconds)
# "count_differences=none" or a count followed by one indented line per table.
differences=$(grep -c '^  .*: backup=' "$log" || true)

status=failed
if [[ $code -eq 0 ]] && grep -q '^restore_drill_ok$' "$log"; then
    status=ok
fi

docker compose -p learningx-alert -f compose.prod.yaml exec -T web \
    python manage.py report_restore_drill \
    --status "$status" \
    --tables "${tables:-0}" \
    --rows "${rows:-0}" \
    --restore-seconds "${seconds:-0}" \
    --differences "${differences:-0}" \
    --exit-code "$code"

exit "$code"

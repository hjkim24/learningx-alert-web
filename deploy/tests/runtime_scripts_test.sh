#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    exit 1
}

assert_equal() {
    [[ "$1" == "$2" ]] || fail "expected [$2], got [$1]"
}

assert_contains() {
    [[ "$1" == *"$2"* ]] || fail "expected output to contain [$2]"
}

assert_not_contains() {
    [[ "$1" != *"$2"* ]] || fail "output unexpectedly contained [$2]"
}

file_mode() {
    if stat -c '%a' "$1" >/dev/null 2>&1; then
        stat -c '%a' "$1"
    else
        stat -f '%Lp' "$1"
    fi
}

file_owner() {
    if stat -c '%u:%g' "$1" >/dev/null 2>&1; then
        stat -c '%u:%g' "$1"
    else
        stat -f '%u:%g' "$1"
    fi
}

[[ -x deploy/fetch-secrets.sh ]] || fail "deploy/fetch-secrets.sh is missing"
[[ -x deploy/backup.sh ]] || fail "deploy/backup.sh is missing"
[[ -x deploy/restore-check.sh ]] || fail "deploy/restore-check.sh is missing"

test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT

fake_oci="$test_root/oci"
cat >"$fake_oci" <<'FAKE_OCI'
#!/usr/bin/env bash
set -euo pipefail

command_line="$*"
secret_id=""
destination=""
while (($#)); do
    case "$1" in
        --secret-id)
            shift
            secret_id="$1"
            ;;
        --file)
            shift
            destination="$1"
            ;;
    esac
    shift
done

if [[ "$command_line" == secrets\ secret-bundle\ get* ]]; then
    if [[ "${FAKE_OCI_MODE:-success}" == "fail-google" && "$secret_id" == "google-ocid" ]]; then
        exit 17
    fi
    case "$secret_id" in
        django-ocid) value="test-django-value" ;;
        google-ocid)
            if [[ "${FAKE_OCI_MODE:-success}" == "empty-google" ]]; then
                value=""
            else
                value="test-google-value"
            fi
            ;;
        encryption-ocid) value="test-encryption-value" ;;
        *) exit 18 ;;
    esac
    printf '%s' "$value" | base64 | tr -d '\n'
    exit 0
fi

if [[ "$command_line" == os\ object\ put* ]]; then
    printf '%s\n' "$command_line" >>"$OCI_LOG"
    exit 0
fi

if [[ "$command_line" == os\ object\ get* ]]; then
    cp "$OCI_DOWNLOAD_SOURCE" "$destination"
    exit 0
fi

exit 19
FAKE_OCI
chmod +x "$fake_oci"

current_uid=$(id -u)
current_gid=$(id -g)
secrets_dir="$test_root/secrets"
mkdir -p "$secrets_dir"
for name in django-secret-key google-client-secret credential-encryption-keys; do
    printf 'old-value' >"$secrets_dir/$name"
done

run_fetch() {
    SECRETS_DIR="$secrets_dir" \
    SECRET_UID="$current_uid" \
    SECRET_GID="$current_gid" \
    OCI_BIN="$fake_oci" \
    DJANGO_SECRET_KEY_OCID=django-ocid \
    GOOGLE_CLIENT_SECRET_OCID=google-ocid \
    CREDENTIAL_ENCRYPTION_KEYS_OCID=encryption-ocid \
    FAKE_OCI_MODE="$1" \
    bash deploy/fetch-secrets.sh
}

failure_output=$(run_fetch fail-google 2>&1) && fail "failed bundle unexpectedly succeeded"
for name in django-secret-key google-client-secret credential-encryption-keys; do
    assert_equal "$(<"$secrets_dir/$name")" "old-value"
done
assert_not_contains "$failure_output" "test-django-value"
assert_not_contains "$failure_output" "$test_root"

empty_output=$(run_fetch empty-google 2>&1) && fail "empty bundle unexpectedly succeeded"
for name in django-secret-key google-client-secret credential-encryption-keys; do
    assert_equal "$(<"$secrets_dir/$name")" "old-value"
done
assert_not_contains "$empty_output" "test-google-value"
assert_not_contains "$empty_output" "$test_root"

success_output=$(run_fetch success 2>&1)
assert_contains "$success_output" "secrets_ready"
assert_equal "$(<"$secrets_dir/django-secret-key")" "test-django-value"
assert_equal "$(<"$secrets_dir/google-client-secret")" "test-google-value"
assert_equal "$(<"$secrets_dir/credential-encryption-keys")" "test-encryption-value"
for name in django-secret-key google-client-secret credential-encryption-keys; do
    assert_equal "$(file_mode "$secrets_dir/$name")" "440"
    assert_equal "$(file_owner "$secrets_dir/$name")" "$current_uid:$current_gid"
done

database_path="$test_root/db.sqlite3"
backup_dir="$test_root/backups"
oci_log="$test_root/oci.log"
sqlite3 "$database_path" "CREATE TABLE sample (value TEXT); INSERT INTO sample VALUES ('kept');"

backup_output=$(
    DATABASE_PATH="$database_path" \
    BACKUP_DIR="$backup_dir" \
    OCI_BIN="$fake_oci" \
    OCI_LOG="$oci_log" \
    OCI_NAMESPACE=test-namespace \
    BACKUP_BUCKET=test-backups \
    bash deploy/backup.sh
)
assert_contains "$backup_output" "backup_uploaded object=sqlite/"
backup_path=$(find "$backup_dir" -type f -name '*.sqlite3' -print -quit)
[[ -n "$backup_path" ]] || fail "backup file was not created"
assert_equal "$(sqlite3 "$backup_path" 'PRAGMA integrity_check;')" "ok"
upload_log=$(<"$oci_log")
assert_contains "$upload_log" "os object put"
assert_contains "$upload_log" "--auth instance_principal"
assert_contains "$upload_log" "--namespace test-namespace"
assert_contains "$upload_log" "--bucket-name test-backups"

missing_output=$(
    DATABASE_PATH="$test_root/missing.sqlite3" \
    BACKUP_DIR="$backup_dir" \
    OCI_BIN="$fake_oci" \
    OCI_LOG="$oci_log" \
    OCI_NAMESPACE=test-namespace \
    BACKUP_BUCKET=test-backups \
    bash deploy/backup.sh
)
assert_equal "$missing_output" "database_absent"

restore_tmp="$test_root/restore-tmp"
mkdir -p "$restore_tmp"
restore_output=$(
    TMPDIR="$restore_tmp" \
    OCI_BIN="$fake_oci" \
    OCI_DOWNLOAD_SOURCE="$backup_path" \
    OCI_NAMESPACE=test-namespace \
    BACKUP_BUCKET=test-backups \
    bash deploy/restore-check.sh sqlite/test.sqlite3
)
assert_equal "$restore_output" "restore_ok object=sqlite/test.sqlite3"
[[ -z "$(find "$restore_tmp" -mindepth 1 -print -quit)" ]] || fail "restore temp files were not removed"

printf 'runtime_scripts_test: PASS\n'

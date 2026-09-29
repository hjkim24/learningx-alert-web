#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    exit 1
}

assert_contains() {
    [[ "$1" == *"$2"* ]] || fail "expected output to contain [$2]"
}

assert_not_contains() {
    [[ "$1" != *"$2"* ]] || fail "output unexpectedly contained [$2]"
}

[[ -x scripts/push-runtime-config.sh ]] || fail "scripts/push-runtime-config.sh is missing"

test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
repo="$test_root/repo"
fake_bin="$test_root/bin"
mkdir -p "$repo/scripts" "$fake_bin"
cp scripts/push-runtime-config.sh "$repo/scripts/push-runtime-config.sh"
printf 'SSH_TARGET=ubuntu@example.test\n' >"$repo/.deploy.env"

terraform_log="$test_root/terraform.log"
ssh_log="$test_root/ssh.log"
outputs_json="$test_root/outputs.json"

cat >"$fake_bin/terraform" <<'FAKE_TERRAFORM'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$TERRAFORM_LOG"
cat "$OUTPUTS_JSON"
FAKE_TERRAFORM

cat >"$fake_bin/ssh" <<'FAKE_SSH'
#!/usr/bin/env bash
set -euo pipefail
printf 'ARGS %s\n' "$*" >>"$SSH_LOG"
cat >>"$SSH_LOG"
FAKE_SSH
chmod +x "$fake_bin/terraform" "$fake_bin/ssh"

write_outputs() {
    local google_client_id=$1
    cat >"$outputs_json" <<JSON
{
  "app_domain": {"value": "alert.sobok-app.com"},
  "app_private_ip": {"value": "10.0.1.31"},
  "backup_bucket": {"value": "learningx-alert-backups"},
  "canvas_base_url": {"value": "https://canvas.skku.edu"},
  "credential_encryption_keys_ocid": {"value": "ocid1.vaultsecret.keys"},
  "django_secret_key_ocid": {"value": "ocid1.vaultsecret.django"},
  "google_client_id": {"value": "$google_client_id"},
  "google_client_secret_ocid": {"value": "ocid1.vaultsecret.google"},
  "object_storage_namespace": {"value": "testnamespace"},
  "pilot_allowed_emails": {"value": "pilot@example.com"},
  "forbidden_extra": {"value": "content-secret-value-base64"}
}
JSON
}

run_push() {
    (
        cd "$repo"
        TERRAFORM_BIN="$fake_bin/terraform" \
        SSH_BIN="$fake_bin/ssh" \
        JQ_BIN=/usr/bin/jq \
        TERRAFORM_LOG="$terraform_log" \
        SSH_LOG="$ssh_log" \
        OUTPUTS_JSON="$outputs_json" \
        bash scripts/push-runtime-config.sh
    )
}

write_outputs test.apps.googleusercontent.com
success_output=$(run_push)
assert_contains "$success_output" "runtime_config_updated"
assert_not_contains "$success_output" "ocid1."

terraform_calls=$(<"$terraform_log")
assert_contains "$terraform_calls" "-chdir=infra/terraform output -json"

ssh_calls=$(<"$ssh_log")
for expected in \
    "APP_DOMAIN='alert.sobok-app.com'" \
    "APP_PRIVATE_IP='10.0.1.31'" \
    "GOOGLE_CLIENT_ID='test.apps.googleusercontent.com'" \
    "PILOT_ALLOWED_EMAILS='pilot@example.com'" \
    "DJANGO_SECRET_KEY_OCID='ocid1.vaultsecret.django'" \
    "GOOGLE_CLIENT_SECRET_OCID='ocid1.vaultsecret.google'" \
    "CREDENTIAL_ENCRYPTION_KEYS_OCID='ocid1.vaultsecret.keys'" \
    "OCI_NAMESPACE='testnamespace'" \
    "BACKUP_BUCKET='learningx-alert-backups'" \
    "DATABASE_PATH='/var/lib/learningx-alert/db.sqlite3'" \
    "BACKUP_DIR='/var/lib/learningx-alert/backups'" \
    "chmod 0600" \
    "chown root:root" \
    "/etc/learningx-alert/runtime.env"; do
    assert_contains "$ssh_calls" "$expected"
done
for forbidden in forbidden_extra content-secret-value-base64 '"content"'; do
    assert_not_contains "$ssh_calls" "$forbidden"
done

: >"$ssh_log"
write_outputs ""
set +e
blank_output=$(run_push 2>&1)
blank_status=$?
set -e
[[ $blank_status -ne 0 ]] || fail "blank Google client ID unexpectedly pushed"
[[ ! -s "$ssh_log" ]] || fail "blank configuration reached ssh"
assert_not_contains "$blank_output" "ocid1."

printf 'push_runtime_config_test: PASS\n'

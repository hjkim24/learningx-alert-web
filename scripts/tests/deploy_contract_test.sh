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

[[ -x scripts/deploy.sh ]] || fail "scripts/deploy.sh is missing"

test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
repo="$test_root/repo"
fake_bin="$test_root/bin"
mkdir -p "$repo/scripts" "$fake_bin"
cp scripts/deploy.sh "$repo/scripts/deploy.sh"

for path in accounts config learningx_alert templates static deploy; do
    mkdir -p "$repo/$path"
    printf 'fixture\n' >"$repo/$path/fixture.txt"
done
for path in Dockerfile compose.prod.yaml manage.py pyproject.toml .dockerignore; do
    printf 'fixture\n' >"$repo/$path"
done
printf '.deploy.env\n' >"$repo/.gitignore"
printf 'SSH_TARGET=ubuntu@example.test\n' >"$repo/.deploy.env"

python_log="$test_root/python.log"
ssh_log="$test_root/ssh.log"
rsync_log="$test_root/rsync.log"
curl_log="$test_root/curl.log"

cat >"$fake_bin/python" <<'FAKE_PYTHON'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$PYTHON_LOG"
FAKE_PYTHON
cat >"$fake_bin/ssh" <<'FAKE_SSH'
#!/usr/bin/env bash
printf 'ARGS %s\n' "$*" >>"$SSH_LOG"
cat >>"$SSH_LOG"
FAKE_SSH
cat >"$fake_bin/rsync" <<'FAKE_RSYNC'
#!/usr/bin/env bash
printf 'ARGS %s\n' "$*" >>"$RSYNC_LOG"
cat >>"$RSYNC_LOG"
FAKE_RSYNC
cat >"$fake_bin/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$CURL_LOG"
printf 'ok\n'
FAKE_CURL
chmod +x "$fake_bin/python" "$fake_bin/ssh" "$fake_bin/rsync" "$fake_bin/curl"

git -C "$repo" init -q
git -C "$repo" config user.name test
git -C "$repo" config user.email test@example.invalid
git -C "$repo" add .
git -C "$repo" commit -qm initial

run_deploy() {
    (
        cd "$repo"
        PYTHON_BIN="$fake_bin/python" \
        SSH_BIN="$fake_bin/ssh" \
        RSYNC_BIN="$fake_bin/rsync" \
        CURL_BIN="$fake_bin/curl" \
        PYTHON_LOG="$python_log" \
        SSH_LOG="$ssh_log" \
        RSYNC_LOG="$rsync_log" \
        CURL_LOG="$curl_log" \
        HEALTH_ATTEMPTS=1 \
        HEALTH_DELAY_SECONDS=0 \
        bash scripts/deploy.sh
    )
}

printf 'dirty\n' >"$repo/untracked.txt"
set +e
dirty_output=$(run_deploy 2>&1)
dirty_status=$?
set -e
[[ $dirty_status -ne 0 ]] || fail "dirty worktree unexpectedly deployed"
assert_contains "$dirty_output" "worktree_not_clean"
[[ ! -e "$ssh_log" ]] || fail "dirty worktree reached ssh"
[[ ! -e "$rsync_log" ]] || fail "dirty worktree reached rsync"

rm "$repo/untracked.txt"
success_output=$(run_deploy 2>&1)
assert_contains "$success_output" "deploy_success revision="

python_calls=$(<"$python_log")
assert_contains "$python_calls" "manage.py test"
assert_contains "$python_calls" "-m unittest discover -s tests"

rsync_calls=$(<"$rsync_log")
for path in Dockerfile compose.prod.yaml manage.py pyproject.toml .dockerignore accounts/ config/ learningx_alert/ templates/ static/ deploy/; do
    assert_contains "$rsync_calls" "$path"
done
for excluded in .deploy.env .git/ .env db.sqlite3 terraform.tfstate tfplan /opt/tossterm; do
    assert_not_contains "$rsync_calls" "$excluded"
done

ssh_calls=$(<"$ssh_log")
for expected in "for command_name in docker oci sqlite3 systemctl sudo rsync" "install it before deployment" "docker compose version" "docker compose" "fetch-secrets.sh" "backup.sh" "manage.py check --deploy" "manage.py migrate --noinput" "systemctl restart learningx-alert.service" "ln -s"; do
    assert_contains "$ssh_calls" "$expected"
done

curl_calls=$(<"$curl_log")
assert_contains "$curl_calls" "https://alert.sobok-app.com/healthz/"

printf 'deploy_contract_test: PASS\n'

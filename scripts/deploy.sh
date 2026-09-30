#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}
SSH_BIN=${SSH_BIN:-ssh}
RSYNC_BIN=${RSYNC_BIN:-rsync}
CURL_BIN=${CURL_BIN:-curl}
HEALTH_URL=${HEALTH_URL:-https://alert.sobok-app.com/healthz/}
HEALTH_ATTEMPTS=${HEALTH_ATTEMPTS:-30}
HEALTH_DELAY_SECONDS=${HEALTH_DELAY_SECONDS:-2}

if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
    printf 'worktree_not_clean\n' >&2
    exit 1
fi

if [[ ! -f .deploy.env ]]; then
    printf 'missing .deploy.env\n' >&2
    exit 1
fi
# shellcheck disable=SC1091
source .deploy.env
: "${SSH_TARGET:?SSH_TARGET is required in .deploy.env}"
if [[ ! "$SSH_TARGET" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$ ]]; then
    printf 'invalid SSH_TARGET\n' >&2
    exit 1
fi

for executable in "$PYTHON_BIN" "$SSH_BIN" "$RSYNC_BIN" "$CURL_BIN"; do
    command -v "$executable" >/dev/null || {
        printf 'missing local command: %s\n' "$executable" >&2
        exit 1
    }
done

"$PYTHON_BIN" manage.py test -v 1
"$PYTHON_BIN" -m unittest discover -s tests -v

revision=$(git rev-parse HEAD)
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'invalid git revision\n' >&2
    exit 1
}
release_dir="/opt/learningx-alert/releases/$revision"

report_failure() {
    local status=$?
    printf 'deploy_failed revision=%s release=%s backup_dir=/var/lib/learningx-alert/backups\n' \
        "$revision" "$release_dir" >&2
    exit "$status"
}
trap report_failure ERR

"$SSH_BIN" "$SSH_TARGET" bash -s -- "$release_dir" <<'REMOTE_PREFLIGHT'
set -euo pipefail
release_dir=$1
for command_name in docker oci sqlite3 systemctl sudo rsync; do
    command -v "$command_name" >/dev/null || {
        printf 'missing remote command: %s; install it before deployment\n' "$command_name" >&2
        exit 1
    }
done
docker compose version >/dev/null
sudo install -d -m 0755 /opt/learningx-alert/releases
sudo install -d -m 0755 "$release_dir"
sudo chown "$(id -u):$(id -g)" "$release_dir"
sudo install -d -m 0750 -o 10001 -g 10001 /var/lib/learningx-alert
sudo install -d -m 0750 -o root -g root /var/lib/learningx-alert/backups
sudo install -d -m 0750 -o root -g root /var/lib/learningx-alert/caddy
sudo install -d -m 0750 -o root -g root /var/lib/learningx-alert/caddy/data
sudo install -d -m 0750 -o root -g root /var/lib/learningx-alert/caddy/config
REMOTE_PREFLIGHT

source_paths=(
    Dockerfile
    compose.prod.yaml
    manage.py
    pyproject.toml
    .dockerignore
    accounts/
    config/
    learningx_alert/
    templates/
    static/
    deploy/
)
printf '%s\n' "${source_paths[@]}" | "$RSYNC_BIN" \
    --archive \
    --recursive \
    --relative \
    --files-from=- \
    ./ \
    "$SSH_TARGET:$release_dir/"

"$SSH_BIN" "$SSH_TARGET" sudo bash -s -- "$release_dir" <<'REMOTE_DEPLOY'
set -euo pipefail
release_dir=$1
revision=${release_dir##*/}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'invalid remote revision\n' >&2
    exit 1
}
runtime_env=/etc/learningx-alert/runtime.env
[[ -f "$runtime_env" ]] || {
    printf 'missing remote runtime environment\n' >&2
    exit 1
}
set -a
# shellcheck disable=SC1090
source "$runtime_env"
set +a

cd "$release_dir"
# Compose reads this .env for interpolation: the app reports its own revision.
printf 'APP_REVISION=%s\n' "$revision" >.env
docker compose -p learningx-alert -f compose.prod.yaml build web
docker image tag "learningx-alert:${IMAGE_TAG:-local}" "learningx-alert:$revision"
# Caddy serves the image's collected (hashed) static files, so the URLs the app
# renders and the files on disk always come from the same build.
static_container=$(docker create "learningx-alert:$revision")
rm -rf staticfiles
docker cp "$static_container:/app/staticfiles" ./staticfiles
docker rm "$static_container" >/dev/null
[[ -f staticfiles/staticfiles.json ]] || {
    printf 'missing collected static manifest\n' >&2
    exit 1
}
./deploy/fetch-secrets.sh
./deploy/backup.sh
docker compose -p learningx-alert -f compose.prod.yaml run --rm --no-deps --interactive=false --no-tty web python manage.py check --deploy
docker compose -p learningx-alert -f compose.prod.yaml run --rm --no-deps --interactive=false --no-tty web python manage.py migrate --noinput

install -m 0644 deploy/learningx-alert.service /etc/systemd/system/learningx-alert.service
install -m 0644 deploy/learningx-alert-backup.service /etc/systemd/system/learningx-alert-backup.service
install -m 0644 deploy/learningx-alert-backup.timer /etc/systemd/system/learningx-alert-backup.timer
new_link="/opt/learningx-alert/.current-new"
rm -f "$new_link"
ln -s "$release_dir" "$new_link"
mv -Tf "$new_link" /opt/learningx-alert/current
systemctl daemon-reload
systemctl enable learningx-alert.service learningx-alert-backup.timer
if systemctl is-active --quiet learningx-alert.service; then
    # Replace only what changed instead of `restart` (a full `down` + `up`
    # took the site offline ~25 s per deploy). web and scheduler are
    # recreated because their image changed; Caddy keeps serving meanwhile
    # and retries the web upstream (lb_try_duration in deploy/Caddyfile).
    compose=(docker compose -p learningx-alert -f /opt/learningx-alert/current/compose.prod.yaml)
    (cd /opt/learningx-alert/current && "${compose[@]}" up -d --wait --remove-orphans)
    # Caddy's bind mounts (Caddyfile, staticfiles) resolved the `current`
    # symlink when it was created, so it still points at the previous
    # release; recreate it (about a second) to pick up this one.
    (cd /opt/learningx-alert/current && "${compose[@]}" up -d --wait --no-deps --force-recreate caddy)
else
    systemctl restart learningx-alert.service
fi
systemctl enable --now learningx-alert-backup.timer
REMOTE_DEPLOY

for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++)); do
    if body=$(
        "$CURL_BIN" --fail --silent --show-error --max-time 5 "$HEALTH_URL"
    ) && [[ "$body" == "ok" ]]; then
        trap - ERR
        printf 'deploy_success revision=%s\n' "$revision"
        exit 0
    fi
    sleep "$HEALTH_DELAY_SECONDS"
done

printf 'public_health_failed url=%s\n' "$HEALTH_URL" >&2
false

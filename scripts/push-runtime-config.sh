#!/usr/bin/env bash
set -euo pipefail

TERRAFORM_BIN=${TERRAFORM_BIN:-terraform}
JQ_BIN=${JQ_BIN:-jq}
SSH_BIN=${SSH_BIN:-ssh}
TF_DIR=${TF_DIR:-infra/terraform}

[[ -f .deploy.env ]] || {
    printf 'missing .deploy.env\n' >&2
    exit 1
}
# shellcheck disable=SC1091
source .deploy.env
: "${SSH_TARGET:?SSH_TARGET is required in .deploy.env}"
if [[ ! "$SSH_TARGET" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$ ]]; then
    printf 'invalid SSH_TARGET\n' >&2
    exit 1
fi

for executable in "$TERRAFORM_BIN" "$JQ_BIN" "$SSH_BIN"; do
    command -v "$executable" >/dev/null || {
        printf 'missing local command: %s\n' "$executable" >&2
        exit 1
    }
done

runtime_env=$(
    "$TERRAFORM_BIN" -chdir="$TF_DIR" output -json | "$JQ_BIN" -er '
        def required($name):
            .[$name].value as $value
            | if ($value | type) == "string"
                and ($value | length) > 0
                and (($value | test("[\\r\\n]")) | not)
              then $value
              else error("missing required Terraform output: " + $name)
              end;
        def optional_hosts($name):
            (.[$name].value // "") as $value
            | if ($value | type) == "string"
                and ($value | test("^[a-z0-9.,-]*$"))
              then $value
              else error("invalid Terraform output: " + $name)
              end;

        def optional_text($name):
            (.[$name].value // "") as $value
            | if ($value | type) == "string"
                and (($value | test("[\\r\\n]")) | not)
              then $value
              else error("invalid Terraform output: " + $name)
              end;
        def optional_flag($name):
            (.[$name].value // false) as $value
            | if ($value | type) == "boolean"
              then (if $value then "1" else "0" end)
              else error("invalid Terraform output: " + $name)
              end;

        . as $root
        | ($root | required("app_domain")) as $domain
        | [
            "APP_DOMAIN=" + ($domain | @sh),
            "APP_PRIVATE_IP=" + ($root | required("app_private_ip") | @sh),
            "IMAGE_TAG=" + ("production" | @sh),
            "DJANGO_ALLOWED_HOSTS=" + ($domain | @sh),
            "CSRF_TRUSTED_ORIGINS=" + (("https://" + $domain) | @sh),
            "GOOGLE_CLIENT_ID=" + ($root | required("google_client_id") | @sh),
            "SIGNUP_OPEN=" + ($root | optional_flag("signup_open") | @sh),
            "PILOT_ALLOWED_EMAILS=" + ($root | optional_text("pilot_allowed_emails") | @sh),
            "PRIVACY_CONTACT_EMAIL=" + ($root | optional_text("privacy_contact_email") | @sh),
            "ADMIN_EMAILS=" + ($root | optional_text("admin_emails") | @sh),
            (($root | optional_text("database_host")) as $db_host
              | if $db_host == "" then
                  "DATABASE_ENGINE=" + ("sqlite" | @sh)
                else
                  "DATABASE_ENGINE=" + ("mysql" | @sh),
                  "DATABASE_HOST=" + ($db_host | @sh),
                  "DATABASE_PASSWORD_FILE=" + ("/run/secrets/all/database-password" | @sh),
                  "DATABASE_PASSWORD_OCID=" + ($root | required("database_password_ocid") | @sh)
                end),
            (($root | optional_text("grafana_otlp_endpoint")) as $otlp
              | if $otlp == "" then
                  "COMPOSE_PROFILES=" + ("" | @sh)
                else
                  "COMPOSE_PROFILES=" + ("telemetry" | @sh),
                  "OTEL_EXPORTER_OTLP_ENDPOINT=" + ("http://otel-collector:4318" | @sh),
                  "GRAFANA_OTLP_ENDPOINT=" + ($otlp | @sh),
                  "GRAFANA_INSTANCE_ID=" + ($root | required("grafana_instance_id") | @sh),
                  "GRAFANA_OTLP_TOKEN_OCID=" + ($root | required("grafana_otlp_token_ocid") | @sh)
                end),
            "CANVAS_BASE_URL=" + ($root | required("canvas_base_url") | @sh),
            "LEARNINGX_ALLOWED_HOSTS=" + ($root | optional_hosts("learningx_allowed_hosts") | @sh),
            "DJANGO_SECRET_KEY_OCID=" + ($root | required("django_secret_key_ocid") | @sh),
            "GOOGLE_CLIENT_SECRET_OCID=" + ($root | required("google_client_secret_ocid") | @sh),
            "CREDENTIAL_ENCRYPTION_KEYS_OCID=" + ($root | required("credential_encryption_keys_ocid") | @sh),
            "OCI_NAMESPACE=" + ($root | required("object_storage_namespace") | @sh),
            "BACKUP_BUCKET=" + ($root | required("backup_bucket") | @sh),
            "DATABASE_PATH=" + ("/var/lib/learningx-alert/db.sqlite3" | @sh),
            "BACKUP_DIR=" + ("/var/lib/learningx-alert/backups" | @sh)
        ]
        | .[]
    '
)

remote_lines=(
    'set -euo pipefail'
    'install -d -m 0755 /etc/learningx-alert'
    'staging=$(mktemp /etc/learningx-alert/.runtime.env.XXXXXX)'
    "trap 'rm -f \"\$staging\"' EXIT"
    'cat >"$staging"'
    'chown root:root "$staging"'
    'chmod 0600 "$staging"'
    'mv -f "$staging" /etc/learningx-alert/runtime.env'
    'trap - EXIT'
)
printf -v remote_script '%s\n' "${remote_lines[@]}"
printf -v quoted_remote_script '%q' "$remote_script"

printf '%s\n' "$runtime_env" | \
    "$SSH_BIN" "$SSH_TARGET" "sudo bash -c $quoted_remote_script"
printf 'runtime_config_updated\n'

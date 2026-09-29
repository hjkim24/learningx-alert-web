# OCI Terraform Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the existing Django service at `https://alert.sobok-app.com` on the existing OCI ARM64 instance without disrupting TossTerm or exposing runtime secret values.

**Architecture:** Terraform imports and protects the existing Compute/network resources, then adds the approved compartment, storage, Vault, IAM, and NSG resources. A manual release script builds one Django image on the host and runs it as separate web and scheduler services behind Caddy; host-side systemd units fetch Vault secrets and back up the shared SQLite database.

**Tech Stack:** Python 3.12, Django 5.2, Gunicorn, Docker Compose, Caddy 2, Bash, systemd, SQLite, Terraform >=1.12,<2.0, Oracle OCI provider 8.29.x, OCI CLI Instance Principal.

**Spec:** `docs/superpowers/specs/2026-09-26-oci-terraform-deployment-design.md`

## Global Constraints

- Region is `ap-chuncheon-1`; the imported instance remains `lab-hjkim24`, `VM.Standard.A1.Flex`, 2 OCPUs, 12 GB, Ubuntu 22.04 ARM64.
- Preserve public IP `168.107.37.170`, private IP `10.0.1.31`, VCN `tossterm-vcn`, subnet `tossterm-subnet`, and VNIC hostname `tossterm`.
- Never stop, modify, proxy, or delete `tossterm.service`, Tailscale, `/opt/tossterm`, or `/opt/tossterm-data`.
- Publish Caddy only on `10.0.1.31:80` and `10.0.1.31:443`; never publish an application container port or bind host port 443 to `0.0.0.0`.
- Terraform version is `>=1.12,<2.0`; provider is constrained to `~>8.29.0`; authentication uses the `LEARNINGX_ALERT` SecurityToken profile.
- Every imported foundation, bucket, Vault, key, and compartment uses `prevent_destroy` where supported.
- Secret plaintext never enters Git, Terraform configuration/state/plan, Compose environment metadata, command arguments, or normal logs.
- Only the secret names `django-secret-key`, `google-client-secret`, and `credential-encryption-keys` are accepted from OCI Vault.
- Production uses `DJANGO_DEBUG=0`, host `alert.sobok-app.com`, trusted origin `https://alert.sobok-app.com`, and the existing SQLite scheduler lock.
- Deployment and Terraform apply remain manual; Route 53, Google OAuth configuration, and Vault secret content stay outside Terraform.

## Review Focus

- An unreadable or empty `*_FILE` value must stop production startup without printing the file path or secret value (Task 1 tests).
- Compose rendering must prove port 443 is bound only to `10.0.1.31` and that no app service publishes a host port (Task 2 check).
- A failed or partial Vault download must leave no new partial secret set for the next container start (Task 3 test).
- The first deployment, where `db.sqlite3` does not yet exist, must skip the pre-deploy backup but still permit migration; later deployments must fail closed on backup or integrity errors (Tasks 3 and 4 tests).
- Any Terraform replacement/deletion or imported-resource drift must stop before apply, especially around the primary VNIC and existing security-list associations (Tasks 5 and 6 plan gates).

## File Map

- `config/settings.py`, `config/urls.py`: production secret-file loading, trusted proxy/origin settings, and `/healthz/`.
- `accounts/tests/test_settings.py`, `accounts/tests/test_pages.py`: application-level production contracts.
- `Dockerfile`, `compose.prod.yaml`, `deploy/Caddyfile`: ARM64-compatible application image and private Compose topology.
- `deploy/fetch-secrets.sh`, `deploy/backup.sh`, `deploy/restore-check.sh`: host-side Vault and SQLite operations.
- `deploy/*.service`, `deploy/*.timer`: reboot startup and daily backup orchestration.
- `scripts/deploy.sh`: clean-revision test, allowlisted release sync, remote build, migration, replacement, and HTTPS health gate.
- `infra/terraform/*.tf`: imported OCI foundation and new production resources.
- `scripts/bootstrap-oci-state.sh`, `scripts/import-oci-existing.sh`, `scripts/push-runtime-config.sh`: explicit operator workflows around Terraform and the host.
- `docs/operations/oci-production.md`: bootstrap, secret entry, deploy, restore, rollback, and coexistence runbook.

---

### Task 1: Pin the Django production boundary

**Files:**
- Modify: `config/settings.py`
- Modify: `config/urls.py`
- Modify: `.env.example`
- Modify: `accounts/tests/test_settings.py`
- Modify: `accounts/tests/test_pages.py`

**Interfaces:**
- Produces: `_secret_setting(name: str) -> str`, environment variables `DJANGO_SECRET_KEY_FILE`, `GOOGLE_CLIENT_SECRET_FILE`, `CREDENTIAL_ENCRYPTION_KEYS_FILE`, and route name `healthz`.
- Produces: `CSRF_TRUSTED_ORIGINS` from a comma-separated environment value and `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` in production.

- [ ] **Step 1: Add failing production and health tests**

Add subprocess tests named `test_file_secrets_override_environment`, `test_empty_file_secret_fails_closed_without_echo`, and `test_production_configures_expected_proxy_origin_and_host`. Add a client test named `test_healthz_is_public_and_minimal` asserting status `200`, `text/plain`, body `ok\n`, and no redirect.

- [ ] **Step 2: Run the focused tests and confirm the missing behavior**

Run: `.venv/bin/python manage.py test accounts.tests.test_settings accounts.tests.test_pages -v 2`

Expected: FAIL because file-backed values, proxy/origin settings, and `/healthz/` do not exist.

- [ ] **Step 3: Implement the minimum production settings**

In `config/settings.py`, implement `_secret_setting(name: str) -> str`: a non-empty `<NAME>_FILE` takes precedence, UTF-8 text is stripped, and unreadable/empty files raise a generic `RuntimeError` naming only the environment variable. Use it for the three secret values, retain existing Fernet validation, parse `CSRF_TRUSTED_ORIGINS`, and set the proxy header only when `DEBUG` is false. In `config/urls.py`, add `healthz(_request) -> HttpResponse` with the fixed response only.

- [ ] **Step 4: Verify focused and full application tests**

Run: `.venv/bin/python manage.py test -v 2 && .venv/bin/python -m unittest discover -s tests -v`

Expected: all existing and new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add config/settings.py config/urls.py .env.example accounts/tests/test_settings.py accounts/tests/test_pages.py
git commit -m "feat: load production secrets from files"
```

### Task 2: Add the production container stack

**Files:**
- Modify: `pyproject.toml`
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `compose.prod.yaml`
- Create: `deploy/Caddyfile`
- Create: `deploy/production.env.example`

**Interfaces:**
- Consumes: Task 1's three `*_FILE` variables and `/healthz/`.
- Produces: Compose project `learningx-alert` with services `caddy`, `web`, and `scheduler`; both app services use the same locally built image.
- Consumes: non-secret `GOOGLE_CLIENT_ID`, `PILOT_ALLOWED_EMAILS`, `CANVAS_BASE_URL`, domain, allowed-host, and trusted-origin values from the host runtime environment.

- [ ] **Step 1: Establish the failing artifact checks**

Run: `docker compose --env-file deploy/production.env.example -f compose.prod.yaml config`

Expected: FAIL because the production artifacts do not exist.

- [ ] **Step 2: Create the minimal image and Compose topology**

Add Gunicorn `>=23,<24` to `pyproject.toml`. Build from `python:3.12-slim`, install the project, copy only runtime source, and run as numeric non-root UID/GID `10001`. Configure `web` to run Gunicorn on container port 8000 and `scheduler` to run `python manage.py run_scheduler`. Mount `/var/lib/learningx-alert` at `/data`, set `DATABASE_PATH=/data/db.sqlite3`, and mount each host secret file read-only at `/run/secrets/<name>`.

- [ ] **Step 3: Configure Caddy and health checks**

Serve `/static/*` from the release's existing `static/` directory and proxy all other paths to `web:8000`. Persist Caddy state at `/var/lib/learningx-alert/caddy`. Publish exactly `10.0.1.31:80:80` and `10.0.1.31:443:443`; give app containers no `ports` entries. Add container health checks for the web response, scheduler PID, and Caddy configuration, plus `restart: unless-stopped`.

- [ ] **Step 4: Render and build without secret plaintext**

Run:

```bash
docker compose --env-file deploy/production.env.example -f compose.prod.yaml config
docker compose --env-file deploy/production.env.example -f compose.prod.yaml build web
```

Expected: both commands succeed; rendered output contains only `/run/secrets/...` paths, contains `10.0.1.31:443`, and contains neither `0.0.0.0:443` nor any secret value.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml Dockerfile .dockerignore compose.prod.yaml deploy/Caddyfile deploy/production.env.example
git commit -m "build: add production container stack"
```

### Task 3: Fetch secrets and back up SQLite on the host

**Files:**
- Create: `deploy/fetch-secrets.sh`
- Create: `deploy/backup.sh`
- Create: `deploy/restore-check.sh`
- Create: `deploy/learningx-alert.service`
- Create: `deploy/learningx-alert-backup.service`
- Create: `deploy/learningx-alert-backup.timer`
- Create: `deploy/runtime.env.example`
- Create: `deploy/tests/runtime_scripts_test.sh`

**Interfaces:**
- Consumes: `DJANGO_SECRET_KEY_OCID`, `GOOGLE_CLIENT_SECRET_OCID`, `CREDENTIAL_ENCRYPTION_KEYS_OCID`, `OCI_NAMESPACE`, and `BACKUP_BUCKET` from `/etc/learningx-alert/runtime.env`.
- Produces: non-empty mode `0440`, owner `root:10001` files under `/run/learningx-alert/secrets`; timestamped verified backups under `/var/lib/learningx-alert/backups`; OCI objects under `sqlite/YYYY/MM/DD/`.

- [ ] **Step 1: Write failing shell contract tests**

Use temporary directories and fake `oci` executables to assert: all three valid Base64 bundles install; an empty or failed bundle exits non-zero before installation; errors contain neither decoded values nor temp paths. Build a temporary SQLite database and assert backup integrity/upload invocation; assert a missing database exits zero with `database_absent`.

- [ ] **Step 2: Run the contract and confirm failure**

Run: `bash deploy/tests/runtime_scripts_test.sh`

Expected: FAIL because the scripts do not exist.

- [ ] **Step 3: Implement fail-closed host scripts**

`fetch-secrets.sh` must fetch `CURRENT` bundles with `oci ... --auth instance_principal`, decode into a root-only staging directory, validate all three before `install`, and never echo values. `backup.sh` must use `sqlite3 .backup`, require `PRAGMA integrity_check` to return `ok`, upload with Instance Principal, and delete only local `*.sqlite3` files older than 14 days. `restore-check.sh <object-name>` must download to `mktemp -d`, verify integrity there, and clean the temp directory on exit.

- [ ] **Step 4: Add systemd orchestration and verify syntax**

The app unit loads `/etc/learningx-alert/runtime.env`, runs after `network-online.target` and `docker.service`, fetches secrets in `ExecStartPre`, and executes `docker compose -p learningx-alert -f /opt/learningx-alert/current/compose.prod.yaml up -d --wait`. The daily timer loads the same environment and runs the backup service with a randomized delay. Run: `bash -n deploy/*.sh deploy/tests/*.sh && bash deploy/tests/runtime_scripts_test.sh`.

Expected: syntax checks and contract tests PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy
git commit -m "ops: add Vault fetch and SQLite backup units"
```

### Task 4: Add guarded manual deployment

**Files:**
- Create: `scripts/deploy.sh`
- Create: `scripts/tests/deploy_contract_test.sh`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: local `SSH_TARGET` from ignored `.deploy.env`, Task 2's Compose files, and Task 3's host scripts/unit files.
- Produces: immutable release directory `/opt/learningx-alert/releases/<git-sha>`, symlink `/opt/learningx-alert/current`, and a healthy `learningx-alert` Compose project.

- [ ] **Step 1: Write the failing guard tests**

Test with fake `ssh` and `rsync` commands that a dirty or untracked worktree exits before either command, a clean worktree sync list contains only the approved runtime paths, and `.env`, `.git`, SQLite files, Terraform state/plans, and TossTerm paths are never selected.

- [ ] **Step 2: Run the contract and confirm failure**

Run: `bash scripts/tests/deploy_contract_test.sh`

Expected: FAIL because `scripts/deploy.sh` does not exist.

- [ ] **Step 3: Implement the release sequence**

Require a clean Git worktree, run both existing Python test commands, derive the commit SHA, and `rsync` an explicit allowlist into a new release directory. Remotely require `docker`, the Compose plugin, `oci`, `sqlite3`, and `systemctl`; stop with install guidance if any are missing. Build without touching running containers, fetch secrets, run the pre-deploy backup, run `manage.py check --deploy` and migrations with the new image, atomically update `current`, install/enable the units, and start the Compose project. Do not prune images or old releases.

- [ ] **Step 4: Gate completion on public health**

Poll `https://alert.sobok-app.com/healthz/` with a bounded timeout and accept only body `ok`. If build, secret fetch, backup, check, migration, Compose health, or public health fails, exit non-zero and print the preserved release and backup locations without attempting automatic database rollback.

- [ ] **Step 5: Verify and commit**

Run: `bash -n scripts/deploy.sh scripts/tests/deploy_contract_test.sh && bash scripts/tests/deploy_contract_test.sh`

```bash
git add .gitignore scripts/deploy.sh scripts/tests/deploy_contract_test.sh
git commit -m "ops: add guarded manual deployment"
```

### Task 5: Bootstrap remote state and import the OCI foundation

**Files:**
- Modify: `.gitignore`
- Create: `infra/terraform/versions.tf`
- Create: `infra/terraform/provider.tf`
- Create: `infra/terraform/variables.tf`
- Create: `infra/terraform/existing.tf`
- Create: `infra/terraform/storage.tf`
- Create: `infra/terraform/outputs.tf`
- Create: `infra/terraform/backend.hcl.example`
- Create: `infra/terraform/terraform.tfvars.example`
- Create: `scripts/bootstrap-oci-state.sh`
- Create: `scripts/import-oci-existing.sh`

**Interfaces:**
- Produces: native OCI backend key `prod/terraform.tfstate`; imported addresses `oci_identity_compartment.app`, `oci_objectstorage_bucket.terraform_state`, `oci_core_instance.app_host`, `oci_core_vcn.existing`, `oci_core_subnet.existing`, and `oci_core_public_ip.reserved`.
- Consumes: real OCIDs from ignored `infra/terraform/terraform.tfvars` and the short-lived `LEARNINGX_ALERT` profile.
- Consumes: non-secret Google client ID, pilot allowlist, Canvas base URL, and deployment domain from ignored operator tfvars so Task 7 can deliver them without hard-coding personal configuration.

- [ ] **Step 1: Upgrade and pin the toolchain**

Install a current Terraform release and run `terraform version`.

Expected: version is `>=1.12,<2.0`. Set `required_version` accordingly, constrain `oracle/oci` to `~>8.29.0`, and configure provider authentication as `SecurityToken` with profile `LEARNINGX_ALERT`.

- [ ] **Step 2: Write bootstrap/import scripts and ignored-file rules**

`bootstrap-oci-state.sh` idempotently creates only compartment `learningx-alert-prod` and versioned bucket `learningx-alert-tfstate`; it must fail on ambiguous duplicate names. Ignore `.terraform/`, `*.tfstate*`, `*.tfplan`, real `*.tfvars`, `backend.hcl`, `.deploy.env`, and runtime secret files. `backend.hcl.example` fixes region, key, authentication method, and profile but leaves namespace explicit.

- [ ] **Step 3: Define imported resources without destructive defaults**

Model the verified instance, VCN, subnet, reserved public IP, application compartment, and state bucket. Put actual identifiers and existing metadata/security-list/route-table values only in ignored tfvars. Add `prevent_destroy`, preserve the VNIC hostname and existing associations, and expose only the primary VNIC's `nsg_ids` for Task 6.

- [ ] **Step 4: Initialize, import, and prove zero drift**

Run the bootstrap script, create ignored `backend.hcl` and `terraform.tfvars`, then:

```bash
terraform -chdir=infra/terraform init -backend-config=backend.hcl
bash scripts/import-oci-existing.sh
terraform -chdir=infra/terraform plan -target=oci_identity_compartment.app -target=oci_objectstorage_bucket.terraform_state -target=oci_core_instance.app_host -target=oci_core_vcn.existing -target=oci_core_subnet.existing -target=oci_core_public_ip.reserved -detailed-exitcode
```

Expected: exit code `0`, with zero add/change/destroy. Any replacement, deletion, or update stops this task.

- [ ] **Step 5: Validate and commit configuration only**

Run: `terraform -chdir=infra/terraform fmt -check -recursive && terraform -chdir=infra/terraform validate && git status --short`

Expected: no state, plan, backend config, real tfvars, token, or OCID-bearing generated file is staged.

```bash
git add .gitignore infra/terraform scripts/bootstrap-oci-state.sh scripts/import-oci-existing.sh
git commit -m "infra: import OCI deployment foundation"
```

### Task 6: Add the approved OCI production resources

**Files:**
- Create: `infra/terraform/network.tf`
- Create: `infra/terraform/vault.tf`
- Create: `infra/terraform/iam.tf`
- Modify: `infra/terraform/storage.tf`
- Modify: `infra/terraform/outputs.tf`

**Interfaces:**
- Produces: backup bucket `learningx-alert-backups`, default Vault `learningx-alert-vault`, AES-256 SOFTWARE key `learningx-alert-secrets-key`, exact-instance Dynamic Group, least-privilege instance policy, NSG `learningx-alert-web-nsg`, and primary-VNIC NSG attachment.
- Produces: Vault/key identifiers needed for the operator to create the three secret values before Task 7.

- [ ] **Step 1: Add resources and lifecycle guards**

Add the private backup bucket and a 14-day object delete lifecycle, the default Vault and symmetric key, an exact `instance.id` Dynamic Group rule, and policy statements limited to reading secret bundles and managing objects in `learningx-alert-backups`. Protect data-bearing resources with `prevent_destroy`.

- [ ] **Step 2: Add only the approved network access**

Create stateful TCP ingress rules for public ports 80 and 443. Attach only this NSG through `oci_core_instance.app_host.create_vnic_details.nsg_ids`; do not add or alter subnet security-list, route, SSH, public-IP, hostname-label, or Tailscale configuration.

- [ ] **Step 3: Validate and review the full plan**

Run:

```bash
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -out=approved.tfplan
terraform -chdir=infra/terraform show approved.tfplan
```

Expected: only the approved backup/Vault/key/IAM/NSG resources plus the NSG attachment are added or updated; zero resources are replaced or destroyed.

- [ ] **Step 4: Apply and prove idempotence**

Run: `terraform -chdir=infra/terraform apply approved.tfplan`, then run a fresh plan with `-detailed-exitcode`.

Expected: apply succeeds and the second plan exits `0` with no changes.

- [ ] **Step 5: Commit**

```bash
git add infra/terraform
git commit -m "infra: add LearningX production resources"
```

### Task 7: Resolve Vault metadata and configure the host

**Files:**
- Create: `infra/terraform/secrets.tf`
- Modify: `infra/terraform/outputs.tf`
- Create: `scripts/push-runtime-config.sh`
- Create: `scripts/tests/push_runtime_config_test.sh`

**Interfaces:**
- Consumes: three operator-created Vault secrets with the exact approved names.
- Produces: Terraform outputs containing only secret OCIDs and non-secret runtime coordinates/configuration; writes `/etc/learningx-alert/runtime.env` mode `0600` without bundle content.

- [ ] **Step 1: Create the secret values outside Terraform**

In OCI Console, enter non-empty values for `django-secret-key`, `google-client-secret`, and `credential-encryption-keys` using the Task 6 key. Do not paste them into a shell, Terraform variable, plan, issue, or chat.

- [ ] **Step 2: Add metadata-only lookups and assertions**

Use one `oci_vault_secrets` data source per exact name, scoped to the app compartment and Vault with active-state filtering. Add Terraform checks that each result count is exactly one. Output only each secret OCID, Object Storage namespace/bucket, public/private IP, domain, Google client ID, pilot allowlist, and Canvas base URL; never use `oci_secrets_secretbundle`.

- [ ] **Step 3: Test the host-config transport**

With fake `terraform` and `ssh` executables, assert `push-runtime-config.sh` writes the expected variable names, mode `0600`, and no `content`, Base64 bundle, or secret value. Run: `bash scripts/tests/push_runtime_config_test.sh`.

Expected: the test FAILS before the script exists, then PASSES after implementation.

- [ ] **Step 4: Validate live metadata and push the config**

Run a Terraform plan; expect three unique metadata matches and no infrastructure changes. Then run `scripts/push-runtime-config.sh`.

Expected: `/etc/learningx-alert/runtime.env` exists with root ownership and mode `0600`; it contains OCIDs and non-secret configuration only. No bundle content appears locally, remotely, or in command output.

- [ ] **Step 5: Commit**

```bash
git add infra/terraform/secrets.tf infra/terraform/outputs.tf scripts/push-runtime-config.sh scripts/tests/push_runtime_config_test.sh
git commit -m "infra: connect Vault secret metadata"
```

### Task 8: Roll out and verify the production service

**Files:**
- Create: `docs/operations/oci-production.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-7 and the external DNS record already resolving `alert.sobok-app.com`.
- Produces: an operator-repeatable deployment, restore, rollback, and coexistence runbook.

- [ ] **Step 1: Document the operator-owned prerequisites**

Record the Terraform/OCI session refresh command, ignored-file setup, Vault Console entry, Google OAuth authorized domain `sobok-app.com`, redirect URI `https://alert.sobok-app.com/accounts/google/login/callback/`, Docker/Compose/OCI CLI host prerequisites, and the explicit prohibition on changing Route 53's other records.

- [ ] **Step 2: Run all local/static checks**

Run:

```bash
.venv/bin/python manage.py test -v 2
.venv/bin/python -m unittest discover -s tests -v
bash deploy/tests/runtime_scripts_test.sh
bash scripts/tests/deploy_contract_test.sh
bash scripts/tests/push_runtime_config_test.sh
bash -n deploy/*.sh scripts/*.sh deploy/tests/*.sh scripts/tests/*.sh
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
docker compose --env-file deploy/production.env.example -f compose.prod.yaml config
```

Expected: every command passes, and scans of tracked files/staged diff show no private key, session token, secret content, state, plan, or real tfvars.

- [ ] **Step 3: Deploy and verify the public path**

Run `scripts/deploy.sh`. Confirm the three fetched files are non-empty with `root:10001` and mode `0440`, DNS resolves to `168.107.37.170`, HTTP redirects to HTTPS, the certificate is publicly trusted, `/healthz/` returns `ok`, Google OAuth completes, and exactly one scheduler holds the host lock. Send a test notification only after the user explicitly chooses the approved destination.

- [ ] **Step 4: Verify recovery and coexistence**

Run one backup, use `restore-check.sh` on the uploaded object, and confirm integrity. On the host confirm `tossterm.service` is active, `127.0.0.1:8720` still listens, Tailscale remains active on its tailnet address, Caddy listens only on `10.0.1.31:80/443`, and `/opt/tossterm*` timestamps/content were not changed by deployment.

- [ ] **Step 5: Record rollback and commit the runbook**

Document operator-directed rollback to the previous release/image and pre-deploy database backup, explicitly noting that migrations are never auto-rolled back. Update the README from “OCI 배포 미완료” to the truthful production status only after every live check succeeds.

```bash
git add docs/operations/oci-production.md README.md
git commit -m "docs: add OCI production runbook"
```

## Final Branch Gate

- [ ] Run the full Task 8 static test matrix again from a clean worktree.
- [ ] Run `terraform plan -detailed-exitcode`; require exit code `0`.
- [ ] Inspect `git log --oneline` and `git diff main...HEAD --check`.
- [ ] Review the whole branch with the selected Superpowers execution workflow before merging.

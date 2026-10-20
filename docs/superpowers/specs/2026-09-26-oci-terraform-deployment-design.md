# OCI Terraform Deployment Design

> **과거 설계·구현 기록 (2026-10-20 분류):** 아래 상태·제약·체크리스트는 작성 당시의 기록이며 현재 실행할 작업 지시가 아니다. 현재 기능·지원 학교·한도는 [FEATURE_SPEC.md](../../../FEATURE_SPEC.md), 실제 계정 검증은 [FEASIBILITY.md](../../../FEASIBILITY.md), 작업 규칙·남은 일은 [HANDOFF](../../HANDOFF.md)를 따른다. 기존 도메인·SQLite·단일 학교·2계정 관문 등은 현재와 다를 수 있다.

## Status

- Approved section by section in conversation on 2026-09-26.
- The deployment implementation has not started.
- The target is the existing OCI Always Free-style ARM64 host, not a newly
  provisioned replacement host.
- A live import probe completed before approval: the existing Compute instance,
  VCN, subnet, and reserved public IP imported with zero add, change, or destroy
  actions, and the immediate follow-up plan reported `No changes`.

## Intent and success criteria

Deploy the existing LearningX alert web application at
`https://alert.sobok-app.com` while preserving the unrelated TossTerm service
already running on the host. Terraform owns the approved OCI infrastructure and
security relationships. Runtime secret values never pass through Terraform,
Git, Docker environment metadata, or ordinary logs.

The deployment is successful when:

1. The existing OCI resources are imported without replacement or deletion.
2. Terraform state is stored in versioned OCI Object Storage with locking.
3. The application starts on host reboot only after retrieving its secrets by
   Instance Principal.
4. Public HTTP redirects to trusted HTTPS and Google OAuth returns to the
   deployed application.
5. The web and scheduler processes share the persistent SQLite database and
   remain healthy.
6. A backup can be uploaded, restored to a temporary location, and pass an
   SQLite integrity check.
7. The existing TossTerm service and Tailscale endpoint continue to work.

## Verified existing environment

### OCI

- Region: `ap-chuncheon-1`.
- Compute display name: `lab-hjkim24`, renamed from `tossterm` during design.
- Shape: `VM.Standard.A1.Flex`, 2 OCPUs and 12 GB RAM.
- Image family: Canonical Ubuntu 22.04, ARM64.
- Primary private IP: `10.0.1.31`.
- Reserved public IP: `168.107.37.170`.
- Existing VCN: `tossterm-vcn`, `10.0.0.0/16`.
- Existing subnet: `tossterm-subnet`, `10.0.1.0/24`.
- The primary VNIC currently has no NSG.
- The VNIC hostname label remains `tossterm`. It is deliberately not renamed in
  this slice because it is independent from the OCI display name and may be
  referenced by the existing workload.

### Existing host workload

- `tossterm.service` is active and listens on `127.0.0.1:8720`.
- Tailscale is active and listens on its own tailnet address on port 443.
- Existing data lives below `/opt/tossterm` and `/opt/tossterm-data`.
- Nothing currently listens on the OCI private address on ports 80 or 443.
- The new deployment must not stop, rewrite, proxy, or delete these services or
  paths.

### DNS

- Route 53 remains outside this Terraform configuration.
- `alert.sobok-app.com` already resolves to `168.107.37.170`.
- Existing Route 53 NS, SOA, TXT, and certificate-validation CNAME records stay
  untouched.

## Selected architecture

```text
Route 53: alert.sobok-app.com
                |
                v
OCI reserved public IP 168.107.37.170
                |
                v
OCI private IP 10.0.1.31:80/443
                |
              Caddy
                |
                v
       Django + Gunicorn ------ SQLite
                                   ^
                                   |
       scheduler worker -----------+

Tailscale 100.125.x.x:443 ------ existing TossTerm access
TossTerm 127.0.0.1:8720 -------- existing service
```

The deployment uses one Docker image for separate `web` and `scheduler`
services. Caddy is the only public reverse proxy. Its host port publications
bind specifically to `10.0.1.31:80` and `10.0.1.31:443`; binding to
`0.0.0.0:443` is forbidden because it would collide with Tailscale's address-
specific listener.

No application container publishes a host port. Caddy reaches Gunicorn over a
private Compose network. The web and scheduler containers are the only
containers that mount the SQLite data directory.

## Terraform scope

### Imported and protected resources

Terraform imports and manages the existing:

- Compute instance.
- VCN.
- Subnet.
- Reserved public IP.

Every imported foundational resource uses `prevent_destroy`. Existing instance
metadata, cloud-init data, SSH metadata, hostname labels, routes, and security
list associations are preserved unless a later reviewed change explicitly
makes them Terraform-owned. The first repository-backed import must reproduce
the verified zero-change plan before any new resource is applied.

### New Terraform-managed resources

- A child compartment named `learningx-alert-prod`.
- A versioned Object Storage bucket for Terraform state.
- A private Object Storage bucket for SQLite backups with a 14-day lifecycle.
- A default shared OCI Vault.
- An AES-256 master key with software protection mode.
- A Dynamic Group that matches only the verified Compute instance OCID.
- An IAM policy allowing that Dynamic Group to read secret bundles only in the
  application compartment and manage backup objects only there.
- A dedicated NSG with TCP ingress for ports 80 and 443.
- Attachment of that NSG to the existing primary VNIC through the imported
  instance's updatable VNIC configuration.

The existing subnet security list remains untouched. SSH access continues to
use its current rule. The new NSG adds only the public web ports and does not
broaden unrelated ingress.

Vaults, keys, buckets, and the application compartment also use
`prevent_destroy` where the provider supports it safely.

## Terraform state and authentication

Terraform is upgraded from 1.5.7 to a version greater than or equal to 1.12 and
less than 2.0. The configuration uses Terraform's native `oci` backend rather
than the deprecated S3-compatible backend.

The state bucket and its parent compartment must exist before the backend can
initialize. They are created once with OCI CLI using the short-lived
`LEARNINGX_ALERT` security-token profile, then imported into the remote state.
This bootstrap is the only intended out-of-band infrastructure creation.

The native backend provides Object Storage persistence, locking, and workspace
support. Bucket versioning permits recovery from accidental state overwrites.
The backend configuration contains only non-secret identifiers, the region,
and the profile name. The expiring security token remains in the OCI CLI
session directory and is refreshed interactively when required.

The following never enter Git:

- `.terraform/`.
- `*.tfstate` and state backups.
- `*.tfplan`.
- Real `*.tfvars` files.
- OCI session tokens and CLI configuration.

All applies are manual. Before each apply, the operator reviews the plan for
replacement and deletion actions. No workflow automatically applies Terraform
or reboots the VM.

## Runtime secret handling

Terraform creates the compartment, Vault, key, Dynamic Group, and policy, but
does not create secret content. The operator enters these values directly in
the OCI Console after the Vault and key exist:

- `django-secret-key`.
- `google-client-secret`.
- `credential-encryption-keys`.

The Terraform configuration uses Vault secret metadata data sources filtered by
name to resolve only their OCIDs. Secret bundle content is never read by
Terraform. The Google client ID, Canvas base URL, pilot email allowlist, domain,
region, and secret OCIDs are non-secret deployment configuration.

At service start, a host-side script authenticates as the Compute instance,
downloads the latest versions of all three secret bundles, validates that all
values are non-empty, and atomically installs them below
`/run/learningx-alert/secrets`. `/run` is ephemeral and is recreated after
reboot. Secret values are not written to a Compose environment file.

The web and scheduler containers receive read-only file mounts. Django settings
gain `*_FILE` support for the three deployment secrets. File-backed production
values take precedence over ordinary environment variables. Missing or invalid
production secrets stop startup without logging the values.

## Persistent data and backups

- Application source: `/opt/learningx-alert`.
- SQLite database: `/var/lib/learningx-alert/db.sqlite3`.
- Local backup staging: `/var/lib/learningx-alert/backups`.
- Caddy state and certificates: `/var/lib/learningx-alert/caddy`.

The existing TossTerm directories are excluded from deployment sync and volume
configuration.

A systemd timer creates a consistent SQLite backup using SQLite's backup
operation, runs `PRAGMA integrity_check`, uploads the result to the private
Object Storage bucket using Instance Principal, and removes expired local
staging files. Object Storage lifecycle rules retain cloud backups for 14 days.
Canvas tokens and webhook URLs remain Fernet ciphertext inside the backup; the
Fernet key history stays separately in Vault. The bucket is private and uses
OCI server-side encryption.

## Application deployment

Deployment is deliberately manual for the pilot. There is no GitHub Actions
deployment, container registry, or long-lived GitHub credential on the VM.

`scripts/deploy.sh` performs this sequence:

1. Require a clean, tested local source revision.
2. Synchronize an explicit source allowlist to the VM with `rsync`.
3. Build the ARM64 application image on the VM without changing running
   containers.
4. Fetch and validate Vault secrets.
5. Create and validate a pre-deployment SQLite backup.
6. Run Django checks and migrations with the newly built image.
7. Start or replace Caddy, web, and scheduler with Docker Compose.
8. Wait for container health and request the public health endpoint.
9. Report success only when HTTPS health succeeds.

The production Compose services are:

- `caddy`: HTTPS termination and reverse proxy.
- `web`: Gunicorn serving the Django WSGI application.
- `scheduler`: the existing long-running scheduler management command.

Docker and the Compose plugin are installed once on the host. A systemd unit
orders startup after the network and Docker, fetches secrets, then starts the
Compose project. Existing host units are not added as dependencies and are not
restarted by deployment.

If tests, source sync, build, secret retrieval, backup, or migration fails, the
script exits non-zero and does not intentionally replace the running
containers. After a migration, the script does not automatically restore the
database because doing so could discard writes. It preserves the pre-deploy
backup and previous image for an operator-directed recovery.

## Django production configuration

Production uses:

- `DJANGO_DEBUG=0`.
- `DJANGO_ALLOWED_HOSTS=alert.sobok-app.com`.
- `CSRF_TRUSTED_ORIGINS=https://alert.sobok-app.com`.
- Django's secure session and CSRF cookies.
- `SECURE_PROXY_SSL_HEADER` for Caddy's forwarded HTTPS scheme.
- An operator-controlled Canvas base URL and pilot allowlist.

A minimal unauthenticated `/healthz/` route returns only a fixed `200 OK`
response. It contains no account, database, build, or infrastructure data.

The Google OAuth client uses:

- Authorized domain: `sobok-app.com`.
- Redirect URI:
  `https://alert.sobok-app.com/accounts/google/login/callback/`.

HTTP is used only for Caddy's redirect and ACME challenge. Users submit Canvas
tokens and webhook URLs only after trusted HTTPS is active.

## Verification and acceptance

### Automated checks

- Existing Django and feasibility tests remain green.
- Tests cover file-backed secret loading, precedence, invalid or missing
  production secrets, proxy HTTPS settings, allowed hosts, and `/healthz/`.
- `terraform fmt -check` and `terraform validate` pass.
- Docker Compose configuration renders successfully without secret values.
- Deployment scripts pass shell syntax checks.
- Git, Terraform state, saved plans, Compose output, and ordinary logs are
  scanned for known secret patterns and sentinel test values.

### Infrastructure checks

- Repository-backed imports produce no replacement or deletion actions.
- New-resource plans contain only the approved compartment, state and backup
  buckets, Vault, key, IAM, Dynamic Group, NSG, and NSG attachment changes.
- A second plan after apply reports no changes.
- DNS still resolves to the reserved IP.
- Only ports 80, 443, and the existing restricted administration path are
  reachable as intended.

### Runtime checks

- HTTP redirects to HTTPS with a publicly trusted certificate.
- `/healthz/` succeeds through Caddy.
- Google OAuth completes on the production redirect URI.
- Web and scheduler containers are healthy and exactly one scheduler owns the
  host lock.
- A user-initiated test notification remains explicit and succeeds only in the
  approved test destination.
- A cloud backup restores into a temporary database and passes integrity check.
- `tossterm.service`, its `127.0.0.1:8720` listener, and Tailscale remain active
  after Docker installation and application deployment.

## Deliberate exclusions

- Automatic deployment from GitHub.
- OCIR or GHCR.
- Load balancers, multiple VMs, Kubernetes, Redis, Celery, and PostgreSQL.
- Terraform management of Route 53.
- Terraform-managed secret values.
- Renaming the OS hostname or VNIC hostname label.
- Replacing, proxying, or migrating TossTerm.
- Automatic database rollback or automatic VM reboot.

These exclusions keep the pilot reversible and avoid introducing credentials,
services, or failure modes that the single-host deployment does not need.

# OCI 운영 런북

LearningX Alert 운영 환경은 OCI 춘천 리전의 Ubuntu 22.04 ARM64 인스턴스에서 실행된다. 공개 주소는 `https://alert.sobok-app.com`, 예약 공인 IP는 `168.107.37.170`이다. Caddy는 인스턴스 사설 주소 `10.0.1.31:80/443`에만 바인딩하며, 기존 `tossterm.service`와 Tailscale은 별도로 유지한다.

## 보안 경계

- 실제 시크릿 값은 OCI Secret Management 콘솔에만 입력한다. Git, Terraform 변수·상태·계획, 채팅, 명령행 인수 또는 로그에 넣지 않는다.
- Terraform은 시크릿 이름과 OCID만 조회한다. 운영 호스트가 instance principal로 현재 번들을 가져온다.
- Route 53에서는 `alert.sobok-app.com` 레코드만 이 서비스 범위다. 기존 NS, SOA, TXT, CNAME 및 다른 호스트 레코드는 변경하거나 삭제하지 않는다.
- Canvas 개인 액세스 토큰과 Discord/Slack 웹훅은 로그인한 사용자가 웹 폼으로만 입력한다.
- 시험 알림 전송은 사용자가 승인한 대상에서만 실행한다.

## 로컬 운영 준비

다음 세 파일은 `.gitignore` 대상이다.

```bash
cp infra/terraform/backend.hcl.example infra/terraform/backend.hcl
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
printf '%s\n' 'SSH_TARGET=ubuntu@168.107.37.170' > .deploy.env
```

`backend.hcl`과 `terraform.tfvars`에는 실제 OCI 식별자, Google Client ID, 쉼표로 구분한 정확한 허용 이메일을 입력한다. Google Client Secret은 tfvars에 넣지 않는다.

OCI CLI와 Terraform은 `LEARNINGX_ALERT` 프로필의 API 키로 인증한다. 개인 키는 `~/.oci/learningx_alert_api_key.pem`(권한 600, PKCS#1 `RSA PRIVATE KEY` 형식)에만 두고, 공개 키만 OCI 사용자에 등록한다. Terraform의 Go SDK는 PKCS#8 키를 읽지 못해 401을 낸다.

```ini
[LEARNINGX_ALERT]
user=<사용자 OCID>
fingerprint=<등록한 공개 키 지문>
key_file=~/.oci/learningx_alert_api_key.pem
tenancy=<테넌시 OCID>
region=ap-chuncheon-1
```

키가 유출됐거나 교체할 때는 콘솔의 사용자 → API 키에서 기존 키를 삭제하고 새 키를 등록한다. 새로 등록한 키는 모든 인증 서버에 퍼지기까지 몇 분 동안 401이 섞여 나올 수 있다. 세션 인증이 필요하면 `-var oci_auth=SecurityToken`과 `oci session authenticate --profile-name LEARNINGX_ALERT --region ap-chuncheon-1`을 쓴다.

백엔드를 처음 연결하거나 인증 방식을 바꾼 뒤에는 다음 명령으로 초기화한다.

```bash
terraform -chdir=infra/terraform init \
  -reconfigure \
  -backend-config=backend.hcl
```

## Vault와 Google OAuth

`learningx-alert-prod` 컴파트먼트의 `learningx-alert-vault`에서 `learningx-alert-secrets-key`를 사용해 아래 시크릿을 수동 `Plain-Text` 방식으로 만든다.

- `django-secret-key`
- `google-client-secret`
- `credential-encryption-keys`

값을 바꿀 때는 시크릿 메타데이터 편집이 아니라 상세 화면의 **Versions → Create Secret Version**을 사용한다. 새 버전을 보류 상태로 둘 의도가 없다면 Current로 승격한다.

Google OAuth 웹 애플리케이션 설정은 다음과 같다.

- 승인 도메인: `sobok-app.com`
- 승인된 JavaScript 원본: `https://alert.sobok-app.com`
- 리디렉션 URI: `https://alert.sobok-app.com/accounts/google/login/callback/`
- 앱이 Testing 상태라면 각 허용 계정을 Google Cloud의 테스트 사용자에도 등록한다.

## 호스트 필수 도구

호스트에는 Docker Engine, Docker Compose 플러그인, OCI CLI, `sqlite3`, `rsync`, `systemd`가 필요하다. Docker는 [공식 Ubuntu apt 저장소](https://docs.docker.com/engine/install/ubuntu/), OCI CLI는 [Oracle 공식 설치 절차](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm)를 따른다. 운영 배포는 root로 Docker를 실행하므로 `ubuntu` 사용자를 `docker` 그룹에 추가하지 않는다.

설치 확인:

```bash
ssh ubuntu@168.107.37.170 \
  'docker --version; docker compose version; oci --version; sqlite3 --version'
```

호스트 재부팅이나 커널 교체는 이 배포와 분리된 유지보수 창에서 수행한다. 재부팅 후 LearningX Alert, `tossterm.service`, Tailscale을 모두 재검증한다.

## Terraform과 런타임 설정

적용 전 계획에서 교체나 삭제가 없는지 확인한다.

```bash
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -detailed-exitcode
```

`scripts/push-runtime-config.sh`는 allowlist에 포함된 비밀값 OCID와 비밀이 아닌 설정만 `/etc/learningx-alert/runtime.env`에 원자적으로 기록한다. 결과 파일은 `root:root`, 모드 `0600`이어야 한다.

```bash
scripts/push-runtime-config.sh
ssh ubuntu@168.107.37.170 \
  'sudo stat -c "%U:%G %a %n" /etc/learningx-alert/runtime.env'
```

## 배포

배포는 커밋된 깨끗한 작업 트리에서만 실행된다.

```bash
git status --short
scripts/deploy.sh
```

배포 스크립트는 로컬 테스트, 리비전별 릴리스 업로드, 이미지 빌드와 Git 리비전 태그 보존, Vault 시크릿 가져오기, 배포 전 DB 백업, Django 점검·마이그레이션, `current` 링크 전환, systemd 재시작, 공개 health check 순서로 실행된다.

운영 확인:

```bash
curl -I http://alert.sobok-app.com/
curl --fail https://alert.sobok-app.com/healthz/
ssh ubuntu@168.107.37.170 \
  'systemctl is-active learningx-alert.service learningx-alert-backup.timer'
```

HTTP는 HTTPS로 리다이렉트되어야 하고 health 응답은 `ok`여야 한다. Caddy가 외부 TLS 종료와 HTTP 리다이렉트를 담당한다. 첫 파일럿에서는 HSTS를 설정하지 않았으며, 도메인과 인증서 운영이 안정된 뒤 별도 변경으로 활성화한다.

시크릿 내용은 보지 않고 파일 상태만 확인한다.

```bash
ssh ubuntu@168.107.37.170 'for name in django-secret-key google-client-secret credential-encryption-keys; do sudo test -s "/run/learningx-alert/secrets/$name"; sudo stat -c "%n %u:%g %a" "/run/learningx-alert/secrets/$name"; done'
```

세 파일은 모두 숫자 소유권 `0:10001`, 모드 `0440`이어야 한다. 스케줄러 컨테이너는 정확히 하나여야 한다.

## 백업과 복원 검사

일일 timer 외에 즉시 백업을 실행할 수 있다.

```bash
ssh ubuntu@168.107.37.170 \
  'sudo systemctl start learningx-alert-backup.service; sudo journalctl -u learningx-alert-backup.service -n 20 --no-pager'
```

로그에 나온 `sqlite/...sqlite3` 객체를 내려받아 임시 SQLite 무결성 검사만 수행한다.

```bash
OBJECT_NAME='sqlite/YYYY/MM/DD/learningx-alert-TIMESTAMP-PID.sqlite3'
ssh ubuntu@168.107.37.170 "sudo bash -c 'set -a; source /etc/learningx-alert/runtime.env; set +a; cd /opt/learningx-alert/current; ./deploy/restore-check.sh $OBJECT_NAME'"
```

`restore_ok`가 나오기 전에는 운영 DB 교체를 시도하지 않는다. 실제 복원은 서비스 중지, 현재 DB 별도 보존, 검증된 객체 다운로드, `10001:10001`/`0600` 권한 설정, 서비스 시작을 운영자가 명시적으로 승인한 경우에만 수행한다.

## 롤백

배포 스크립트는 각 애플리케이션 이미지를 `learningx-alert:<40자리 Git 리비전>`으로 보존한다. 롤백할 릴리스 디렉터리와 이미지가 모두 있는지 먼저 확인한다.

```bash
PREVIOUS_REVISION='<40-character-git-revision>'
ssh ubuntu@168.107.37.170 "sudo test -d /opt/learningx-alert/releases/$PREVIOUS_REVISION && sudo docker image inspect learningx-alert:$PREVIOUS_REVISION >/dev/null"
```

DB 마이그레이션이 이전 코드와 호환되는 경우 애플리케이션만 롤백한다.

```bash
ssh ubuntu@168.107.37.170 "sudo bash -s -- '$PREVIOUS_REVISION'" <<'ROLLBACK'
set -euo pipefail
revision=$1
release_dir="/opt/learningx-alert/releases/$revision"
systemctl stop learningx-alert.service
docker image tag "learningx-alert:$revision" learningx-alert:production
rm -f /opt/learningx-alert/.rollback-current
ln -s "$release_dir" /opt/learningx-alert/.rollback-current
mv -Tf /opt/learningx-alert/.rollback-current /opt/learningx-alert/current
systemctl start learningx-alert.service
ROLLBACK
curl --fail https://alert.sobok-app.com/healthz/
```

마이그레이션은 자동으로 되돌리지 않는다. 이전 스키마가 필요하면 배포 전 생성된 백업 객체를 먼저 `restore-check.sh`로 검증하고, 별도의 명시적 승인과 중단 창에서 DB를 복원한다.

## 기존 서비스 공존 확인

배포는 `/opt/tossterm*`를 수정하지 않는다. 다음 조건을 함께 확인한다.

```bash
ssh ubuntu@168.107.37.170 'systemctl is-active tossterm.service tailscaled.service; sudo ss -ltnp | grep -E "10[.]0[.]1[.]31:(80|443)|127[.]0[.]0[.]1:8720|100[.]125[.]0[.]76:443"'
```

- `tossterm.service`: active, `127.0.0.1:8720`
- Tailscale: active, tailnet 주소의 `:443`
- Caddy: `10.0.1.31:80/443`에만 공개 포트 바인딩
- 배포 전후 `/opt/tossterm*` 내용·타임스탬프 해시 동일

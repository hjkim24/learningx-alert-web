# LearningX Alert Web

Canvas 과제와 LearningX 강의 마감을 모아 정해 둔 시각에 Discord·Slack 웹훅이나 브라우저 푸시(PWA)로 보내 주는 서비스입니다. 운영 주소는 [alert.sobok-app.com](https://alert.sobok-app.com)입니다. Google 로그인(공개 가입, Google이 인증한 이메일만), 사용자별 Canvas 연결, 과목별 알림 켜기·끄기, 항목별 알림 끄기, 미리보기, 알림 규칙(조회 범위·알림 시각), 여러 알림 대상, 시험 전송, 예약 전송 이력을 지원합니다.

## 구성

- **앱:** Django 5.2(gunicorn), 예약 워커(`run_scheduler`, 매분 확인), django-allauth(Google)
- **DB:** 운영은 MySQL HeatWave 무료 DB(사설 IP, TLS, PyMySQL), 로컬 기본값은 SQLite. `DATABASE_ENGINE`으로 고릅니다.
- **배포:** OCI 춘천 ARM 인스턴스 1대에서 Docker Compose(caddy, web, scheduler, otel-collector)로 실행합니다. 인프라는 `infra/terraform`, 시크릿은 OCI Vault에 있습니다.
- **모니터링:** OpenTelemetry로 metric·trace·로그를 Grafana Cloud에 보내고, 스케줄러 멈춤·예약 알림 실패·사이트 응답 없음을 Discord로 알립니다. 웹훅 경로, 토큰, 이메일, 쿼리 문자열은 보내지 않습니다.
- **디자인:** [DESIGN.md](DESIGN.md)의 토큰(남색 브랜드, 호박색 마감 신호)을 `static/app.css`가 그대로 씁니다. 앱 아이콘 원본은 `static/icons/*.svg`입니다. 같은 토큰으로 Figma에 디자인 시스템을 만드는 플러그인은 [tools/figma-design-system](tools/figma-design-system/README.md)에 있습니다.
- **개인정보처리방침:** `/privacy/` (`templates/legal/privacy.html`)

알림 대상은 과목별로 Canvas 과제와 LearningX 강의(주차학습에서 출석 대상인 미수강 항목)를 선택할 수 있습니다. 강의 알림은 `LEARNINGX_ALLOWED_HOSTS`(SKKU는 `canvas.skku.edu`)가 설정된 경우에만 켤 수 있고, 수강 완료 여부나 식별자가 불분명한 강의는 알림에서 빼고 과목을 “확인 실패”로 표시합니다. 출석 대상인 문서(pdf 등)는 같은 선택으로 켜지며 알림에는 `[학습자료]`로 표시됩니다. 별도의 필수 학습자료 유형은 제공하지 않습니다. 시험 알림은 사용자가 버튼을 누른 경우에만 한 번 전송을 시도합니다.

## 로컬 웹 실행

Python 3.12 환경을 만들고 의존성을 설치합니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
```

암호화 키를 생성해 `.env`의 `CREDENTIAL_ENCRYPTION_KEYS`에 넣습니다.

```bash
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

키를 교체할 때는 쉼표로 구분한 키 목록의 맨 앞에 새 키를 둡니다. 예를 들어 `CREDENTIAL_ENCRYPTION_KEYS=새키,이전키` 순서이며, 새로 저장되는 값은 첫 번째 키로 암호화되고 기존 값은 뒤의 키로도 복호화됩니다.

Google OAuth 웹 애플리케이션에는 다음 로컬 콜백을 등록합니다.

```text
http://127.0.0.1:8000/accounts/google/login/callback/
```

`.env`에서 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`을 설정합니다. 로컬에서 가입을 열려면 `SIGNUP_OPEN=1`, 닫아 두려면 `PILOT_ALLOWED_EMAILS`에 허용할 이메일을 넣습니다. 그다음 환경을 불러오고 실행합니다.

```bash
set -a
source .env
set +a
.venv/bin/python manage.py migrate
```

`.env`, Django secret, Google OAuth secret, Fernet 키는 Git에 커밋하지 않습니다. Canvas 개인 액세스 토큰은 `.env`에 넣지 않고 로그인 후 웹 폼으로만 제출합니다.

웹과 예약 워커는 같은 환경과 DB를 쓰는 별도 프로세스로 실행합니다.

```bash
.venv/bin/python manage.py runserver
```

다른 터미널에서도 같은 환경을 불러온 뒤 워커를 실행합니다.

```bash
.venv/bin/python manage.py run_scheduler
```

운영 점검이나 테스트에서는 시작 시 중단 실행을 정리하고 현재 분을 한 번만 확인한 뒤 종료할 수 있습니다.

```bash
.venv/bin/python manage.py run_scheduler --once
```

## 알림 대상과 시험 전송

웹훅 URL은 저장 전에 Discord 또는 Slack의 공식 HTTPS 형식과 공개 IP 해석 여부를 확인하고 Fernet으로 암호화합니다. 저장만으로는 메시지를 보내지 않습니다. 대상마다 있는 “시험 알림”을 누르면 한 번만 시도하며, 응답이 애매하거나 연결이 끊긴 경우 자동 재시도하지 않고 대상 채널을 직접 확인하도록 표시합니다.

사용자당 알림 대상은 최대 10개이며, 예약 알림은 대상마다 따로 전송합니다. 한 대상이 실패해도 나머지는 계속 받고, 실행 이력에는 대상별 전송 결과가 남습니다.

브라우저 푸시(PWA)는 `/sw.js` 서비스 워커와 `/manifest.webmanifest`로 동작합니다. 구독 엔드포인트는 브라우저 공식 푸시 서비스(FCM, Mozilla, Apple, Windows) 호스트만 허용하고 웹훅과 같은 공개 IP 검사를 거치며, 구독 정보는 암호화해 저장합니다. 페이로드는 RFC 8291(aes128gcm)로 암호화하고 VAPID(RFC 8292)로 서명합니다. VAPID 키는 기본적으로 `DJANGO_SECRET_KEY`에서 파생하므로 별도 비밀값이 필요 없지만, 비밀키를 교체하면 모든 브라우저가 다시 구독해야 합니다. 고정 키가 필요하면 `WEB_PUSH_VAPID_PRIVATE_KEY`(base64url P-256 스칼라, `_FILE` 지원)를 설정하고, 끄려면 `WEB_PUSH_ENABLED=0`을 설정합니다. 푸시 서비스가 404/410을 돌려준 구독은 자동으로 삭제합니다. iOS는 16.4 이상에서 홈 화면에 추가한 뒤에만 푸시를 받을 수 있습니다.

예약 전송도 자동 재시도하지 않습니다. `definitely_failed`는 공급자가 거부를 확정한 경우이고, `needs_review`는 타임아웃이나 전송 중 중단처럼 수신 여부를 확정할 수 없어 대상 채널을 직접 확인해야 하는 경우입니다.

## 운영 배포

배포는 `scripts/deploy.sh` 하나로 합니다. 로컬 테스트, 릴리스 업로드, 이미지 빌드, 시크릿 가져오기, 배포 전 DB 백업, 마이그레이션, 재시작, 공개 health check 순서로 실행하고, 테스트가 실패하면 멈춥니다.

- **백업:** 매일 `mysqldump`로 Object Storage에 올리고 14일 보관합니다.
- **같은 서버의 다른 서비스:** `tossterm`과 Tailscale이 같은 인스턴스에서 돌고 있어서 배포 때마다 함께 확인합니다.
- **절차:** 배포, 백업 확인, 롤백, 모니터링은 [OCI 운영 런북](docs/operations/oci-production.md)을 따릅니다.

## 테스트

```bash
.venv/bin/python manage.py test
.venv/bin/python -m unittest discover -s tests -v
bash deploy/tests/runtime_scripts_test.sh
bash scripts/tests/deploy_contract_test.sh
```

## 읽기 전용 feasibility probe

운영자가 관리하는 Canvas origin과 승인된 LearningX 호스트를 설정합니다.

```bash
read -r -p 'Canvas base URL: ' CANVAS_BASE_URL
export CANVAS_BASE_URL
read -r -p 'Allowed LearningX hosts, comma-separated: ' LEARNINGX_ALLOWED_HOSTS
export LEARNINGX_ALLOWED_HOSTS
python3 -m learningx_alert.feasibility courses
read -r -p 'Course IDs to inspect, space-separated: ' LEARNINGX_COURSE_IDS
python3 -m learningx_alert.feasibility inspect $LEARNINGX_COURSE_IDS
```

Probe도 토큰을 화면에 표시하지 않고 입력받습니다. 토큰을 명령행, `.env`, 스크린샷, 이슈 또는 Git 커밋에 남기지 마세요.

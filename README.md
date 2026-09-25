# LearningX Alert Web

SKKU LearningX/Canvas 마감 알림 서비스의 비공개 파일럿입니다. 현재 웹에서는 allowlist 기반 Google 로그인, 사용자별 Canvas 연결, 활성 과목 선택, 미완료 과제 미리보기, 알림 규칙과 Discord 또는 Slack 웹훅 설정, 명시적인 시험 전송, 예약 전송 이력을 지원합니다.

현재 알림 대상으로 활성화된 항목은 Canvas 과제뿐입니다. LearningX 강의/출석과 필수 학습자료는 계정별 동작 근거가 더 필요하므로 화면에서 “검증 후 제공”으로 비활성화되어 있습니다. 시험 알림은 사용자가 버튼을 누른 경우에만 한 번 전송을 시도합니다.

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

`.env`에서 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PILOT_ALLOWED_EMAILS`를 설정한 뒤 환경을 불러오고 실행합니다.

```bash
set -a
source .env
set +a
.venv/bin/python manage.py migrate
```

`.env`, Django secret, Google OAuth secret, Fernet 키는 Git에 커밋하지 않습니다. Canvas 개인 액세스 토큰은 `.env`에 넣지 않고 로그인 후 웹 폼으로만 제출합니다.

웹과 예약 워커는 같은 환경과 SQLite 파일을 사용하는 별도 프로세스로 실행합니다.

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

웹훅 URL은 저장 전에 Discord 또는 Slack의 공식 HTTPS 형식과 공개 IP 해석 여부를 확인하고 Fernet으로 암호화합니다. 저장만으로는 메시지를 보내지 않습니다. “시험 알림 보내기”를 누르면 한 번만 시도하며, 응답이 애매하거나 연결이 끊긴 경우 자동 재시도하지 않고 대상 채널을 직접 확인하도록 표시합니다.

예약 전송도 자동 재시도하지 않습니다. `definitely_failed`는 공급자가 거부를 확정한 경우이고, `needs_review`는 타임아웃이나 전송 중 중단처럼 수신 여부를 확정할 수 없어 대상 채널을 직접 확인해야 하는 경우입니다. OCI 배포는 아직 완료 상태로 간주하지 않으며 별도 Terraform 및 실환경 검증 단계에서 진행합니다.

## 테스트

```bash
.venv/bin/python manage.py test
.venv/bin/python -m unittest discover -s tests -v
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

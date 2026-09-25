# LearningX Alert Web

SKKU LearningX/Canvas 마감 알림 서비스의 비공개 파일럿입니다. 현재 웹 범위는 allowlist 기반 Google 로그인과 사용자별 Canvas 토큰 연결·교체·해제까지입니다. 과목 선택과 알림 전송은 아직 구현되지 않았습니다.

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
.venv/bin/python manage.py runserver
```

`.env`, Django secret, Google OAuth secret, Fernet 키는 Git에 커밋하지 않습니다. Canvas 개인 액세스 토큰은 `.env`에 넣지 않고 로그인 후 웹 폼으로만 제출합니다.

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

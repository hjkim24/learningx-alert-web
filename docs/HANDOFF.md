# 인수인계 (2026-09-30 기준)

다음 작업자(Claude Code 세션)가 이 문서만 읽고 바로 이어서 일할 수 있게 쓴 문서다. 세부 운영 절차는 `docs/operations/oci-production.md`(런북)에 있고, 이 문서는 현재 상태, 규칙, 남은 일을 모은다.

## 1. 서비스 한 줄 요약

- **무엇:** 학생이 Canvas 액세스 토큰을 연결하면, 마감이 다가오는 과제와 LearningX 강의를 정해진 시각에 Discord·Slack 웹훅이나 브라우저 푸시(PWA)로 알려 주는 Django 웹 서비스다.
- **주소:** https://alert.sobok-app.com. 로그인은 Google만 쓴다.
- **학교:** 성균관대(`canvas.skku.edu`), 한양대(`learning.hanyang.ac.kr`). 한 서버에서 같이 운영한다(2026-09-30부터).
- **운영자:** 사용자(hjkim4842@gmail.com) 한 명이다.
- **규모:** 가입 3~4명. 전체 가입 상한은 100명, 학교별 연결 상한은 50명이다.

## 2. 작업 규칙 (사용자가 정한 것, 반드시 지킬 것)

**소통**
- 사용자에게는 한국어로 답한다. 코드와 식별자는 영어로 둔다.
- 불확실한 것은 가정이라고 밝힌다. 보고는 "확인한 것 / 확인하지 못한 것 / 제안"을 나눠서 한다.

**비밀 값**
- 토큰, 비밀번호, 웹훅 URL 값은 절대 출력하지 않는다. 키 이름으로만 말한다.

**변경과 배포 흐름**
- feature 브랜치를 만들고, 테스트를 통과시킨 뒤 `git push -u origin <브랜치명>`으로 올린다. 브랜치 이름을 반드시 적는다. 이름 없는 `git push`는 정책에 막힌다.
- 이어서 `gh pr create --head <브랜치> --base main`으로 PR을 만들고, `gh pr merge <번호> --merge --delete-branch`로 머지한다.
- main에서 `./scripts/deploy.sh`로 배포한다. 이 스크립트는 워크트리가 깨끗해야 돌고, 테스트도 직접 실행한다. 문서만 바꾼 PR은 배포하지 않는다.
- `main`에 직접 push하지 않는다. 위험하거나 되돌리기 어려운 작업은 먼저 사용자에게 묻는다.
- 명령을 `&&`로 묶을 때, 앞 단계(커밋 등)가 끝나기 전에 push나 PR 생성이 실행되지 않게 하나씩 실행한다.

**정책상 막힌 것 (우회하지 말 것)**
- `curl --data @file`처럼 로컬 파일을 외부 서비스로 보내는 요청
- 홈 디렉터리의 `rm -rf ~/...`
- 브랜치 없는 push

**임시 파일**
- 저장소 안 `.git/<이름>/` 아래에 두고, 작업이 끝나면 지운다. 세션 scratch 디렉터리는 sandbox 때문에 쓰기가 안 될 수 있다.

**화면 확인**
- `aside repl`로 한다. 호출할 때마다 세션이 새로 열리므로 한 번의 호출 안에서 다 한다.
  - `await openTab(url)`을 부른 뒤 전역 `page`를 쓴다.
  - `page.screenshot({path:"./artifacts/x.png"})`로 찍는다. 파일은 `~/.aside/u/0/sessions/<id>/artifacts/`에 저장된다.
- `setViewportSize`와 `clip`은 동작하지 않는다. 특정 요소만 찍으려면 DOM에서 그 요소만 남기고 찍는다.
- 로컬 정적 서버는 `python3 -m http.server <port> --bind 127.0.0.1`로 띄운다.

## 3. 구조

**운영 환경**
- OCI VM `168.107.37.170`, Docker Compose(`compose.prod.yaml`). 컨테이너는 web(Django/gunicorn), scheduler, caddy, otel-collector 네 개다.
- DB는 OCI MySQL HeatWave 무료 인스턴스(`10.0.1.9`, TLS)다. 앱 계정은 `learningx`이고 비밀번호는 Vault의 `database-password`에 있다.
- 백업: 매일 mysqldump를 Object Storage `mysql/`에 올리고 14일 보관한다. 복원 연습 스크립트는 `deploy/restore-drill.sh`다.
- 비밀 값은 OCI Vault에 있고, 배포할 때 `deploy/fetch-secrets.sh`로 가져온다. Vault 항목: `django-secret-key`, `database-password`, `mysql-admin-password`, `credential-encryption-keys`, `google-client-secret`, `grafana-otlp-token`, `grafana-sa-token`.

**접속 정보**
- SSH 대상은 `.deploy.env`의 `SSH_TARGET`이다.
- OCI CLI와 Terraform은 API 키 프로필 `LEARNINGX_ALERT`를 쓴다.
- 인프라 코드는 `infra/terraform/`에 있다. 런타임 설정은 `terraform.tfvars` → `scripts/push-runtime-config.sh`로 들어간다.

**tailnet 관리 화면**
- Tailscale 호스트 이름은 `lab-hjkim24.taild71a2d.ts.net`이다.
- `:443`은 tossterm(`127.0.0.1:8720`)이다. 옛 `tossterm.taild71a2d.ts.net` serve 항목은 2026-09-30에 지웠다.
- `:8443`은 Caddy `:8081` 블록을 거쳐 피드백 관리 화면 `/ops-7f3c/`로 간다.

**주요 코드**

| 파일 | 역할 |
|---|---|
| `learningx_alert/canvas.py` | `CanvasClient` (profile, courses, assignments, submission) |
| `learningx_alert/learningx.py` | `LearningXClient`: sessionless_launch → LTI form POST → `xn_api_token`, 모듈·출결 API. `allowed_hosts`로 SSRF 방어 |
| `accounts/schools.py` | 학교 목록(코드 고정). `get_school`, `enabled_schools`, `school_full`, `record_school_gauges` |
| `accounts/services.py` | 토큰 암호화(Fernet), `verify_and_store_connection` (학교·정원 검사 포함) |
| `accounts/courses.py` | 과목 동기화, 학기 분류 |
| `accounts/collection.py` | 과제·강의 수집. 강의는 `/modules` 항목의 `content_data.use_attendance`, `due_at`, `completed`로 판단 |
| `accounts/scheduling.py` | 알림 시각 계산(`matching_slot`, `slot_minutes`), 실행(`execute_run`), 병렬 처리(ThreadPool 4, MySQL만), 학교별 동시 실행 상한 |
| `accounts/management/commands/run_scheduler.py` | scheduler 루프(매분 스캔, 직전 스캔 이후 분을 최대 15분까지 따라잡음) |
| `accounts/notifications.py`, `webpush.py` | 전송(Discord/Slack/PWA push) |
| `accounts/telemetry.py` | OTel metric. 속성은 status/kind/error_code/school만 쓴다(개인정보 없음) |
| `accounts/admin_site.py` | 피드백 전용 admin(`/ops-7f3c/`) |
| `config/csp.py` | CSP report-only 헤더와 `/csp-report/` |
| `deploy/Caddyfile` | HSTS, 정적 파일, tailnet 전용 블록 |
| `DESIGN.md` | 디자인 토큰의 기준. `accounts/tests/test_design_tokens.py`가 `DESIGN.md`, `static/app.css`, `tools/figma-design-system/code.js`가 같은지 검사 |

**한도 (코드 상수·설정)**
- 알림 시각은 사용자당 3개다(`AlarmTime.MAX_PER_RULE`).
- 알림 대상은 사용자당 3개다(`Destination.MAX_PER_USER`).
- 학교별 연결은 50개다(`SCHOOL_MAX_USERS`). 전체 가입은 100개다(`SIGNUP_MAX_USERS`).
- 스레드는 `SCHEDULER_CONCURRENCY=4`, 학교별 동시 실행은 `SCHOOL_CONCURRENCY=3`이다.

**테스트**
- `.venv/bin/python manage.py test`: 427개, 약 3초.
- `.venv/bin/python -m unittest discover -s tests`: 클라이언트 테스트.
- `deploy/tests/runtime_scripts_test.sh`: 배포 스크립트 테스트.

## 4. 관측 (Grafana Cloud)

- **스택:** `merryjelly2786`(`https://merryjelly2786.grafana.net`). 데이터소스 uid는 `grafanacloud-prom`(metric)과 `grafanacloud-logs`다.
- **API 인증:** Vault `grafana-sa-token`(Editor 권한, 약 30일)을 헤더 파일 `.git/gf.hdr`에 담아 `curl -H @.git/gf.hdr`로 쓰고, 끝나면 파일을 지운다.
  - Vault 항목에서 값을 읽는 법은 런북 "Vault와 Google OAuth"에 있다: `oci vault secret list` → `oci secrets secret-bundle get` → base64 디코드.
- **대시보드:** `learningx-alert-overview`. 저장소 사본은 `deploy/grafana/dashboard-learningx-alert.json`이다.
  - 행은 서비스, 학교, 웹, 외부 호출, 서버, 로그 순서다.
  - "실제 시작 지연 (대기 포함)"과 학교별 p95 패널로 스케줄러 지연을 본다.
- **경보 규칙:** 폴더와 그룹 모두 `learningx-alert`이고, 모두 contact point `Discord`로 간다. 사본은 `deploy/grafana/alert-rules.yaml`이다.

  | uid | 조건 |
  |---|---|
  | `lx-scheduler-stalled` | 5분 동안 scan 1회 미만이 2분 지속 |
  | `lx-runs-failed` | 15분 안에 failed/needs_review/interrupted 실행 |
  | `lx-site-down` | 마지막 정상 헬스체크가 180초보다 오래됨, 1분 지속 (배포 중 실패 1번에는 안 울림) |
  | `lx-feedback-received` | 로그 "feedback received" |
  | `lx-school-capacity` | 학교별 연결/정원이 0.8 초과, 5분 지속 |

  - 규칙마다 annotation `summary`(무슨 일인지)와 `description`(값의 뜻)이 있다.
- **Discord 서식:** 알림 템플릿 `lx-discord`(사본 `deploy/grafana/discord-template.tmpl`). contact point는 title `{{ template "lx.discord.title" . }}`, message `{{ template "lx.discord.message" . }}`, `use_embed_description=true`로 설정했다.
  - 규칙을 새로 만들 때도 `summary`와 `description`을 넣어야 서식이 제대로 나온다.
- **Grafana API 주의점:**
  - contact point를 PUT할 때 `url`에 `[REDACTED]`를 넣으면 저장된 웹훅이 유지된다.
  - 옛 `receivers/test` 엔드포인트는 없어졌다. 테스트 전송은 `POST /apis/notifications.alerting.grafana.app/v1beta1/namespaces/stacks-1848825/receivers/RGlzY29yZA/test`로 한다(`integration` + `alert` body, `secureFields.url=true`).
  - 템플릿은 먼저 `POST /api/alertmanager/grafana/config/api/v1/templates/test`로 렌더링해 보고 올린다.

## 5. 2026-09-30에 한 일 (PR 순서)

| PR | 내용 |
|---|---|
| #39 | 토큰 폼 정렬 |
| #40 | HSTS 3600, CSP report-only, 해시된 정적 파일(이미지 빌드 시 collectstatic) |
| #41 | 가입 상한 100, 스캔 metric, 알림 대상 생성 잠금, 복원 연습, PWA 가이드 `/guide/home-screen/` |
| #42 | 병렬 스케줄러(ThreadPool 4, MySQL만) |
| #43 | 대시보드 "남은 과제·강의", PWA 가이드 링크 |
| #44 | 피드백 버튼·모델·전용 admin, Grafana 경보 |
| #45, #46 | tailnet 관리 화면, 런북 |
| #47, #49 | 확장 검토 문서, 여러 학교 설계(`docs/superpowers/specs/2026-09-30-*.md`) |
| #48 | 스케줄러 누락 분 따라잡기(`slot_minutes`, 15분 상한, 시작 시 15분 전부터 확인, `late slot claimed` 경고) |
| #50 | 여러 학교: `CanvasConnection.school`(migration 0011), 라디오 선택, 학교별 정원, 학교별 LearningX 호스트, 학교별 동시 실행 상한, 방침 갱신 |
| #51, #52 | 알림 시각과 알림 대상을 사용자당 3개로 |
| #53 | 학교별 연결 수·정원 gauge(`learningx_school_connections`, `learningx_school_capacity`) |

Grafana 쪽 변경(코드 밖):
- Discord 템플릿과 contact point 서식
- 규칙 description
- `lx-school-capacity` 규칙
- 대시보드 "학교" 행

한양대 실측 결과는 `docs/superpowers/specs/2026-09-30-expansion-review.md` 끝에 있다. 사용자가 한양대 계정으로 운영 연결까지 확인했다.

## 6. 남은 일 — 이 세션이 맡을 것

### 6-1. 스케줄러 확인 (2026-10-01 09:00 KST 이후)

목표는 병렬 스케줄러(#42)와 따라잡기(#48)가 실제 09:00 실행에서 정상인지 확인하는 것이다.

1. **Grafana에서 확인할 것:**
   - "실제 시작 지연 (대기 포함)"의 p95가 몇 초 수준인지 본다. 직렬로 돌던 때는 첫 두 실행이 6.6초와 9.3초였다. 병렬이면 거의 동시에 시작해야 한다.
   - "스캔 1회 시간"이 60초보다 짧은지 본다.
2. **로그에서 확인할 것:**
   - 스케줄러: `ssh $SSH_TARGET "sudo docker logs --since 30m learningx-alert-scheduler-1 2>&1 | grep -E 'late slot claimed|run crashed|ERROR'"`
   - `late slot claimed`가 있으면 누락 분을 따라잡았다는 뜻이다. 몇 초 늦었는지(`delay_seconds`)를 적는다.
3. **DB에서 확인할 것:** 오늘 09:00 실행 상태를 본다. `ScheduledRun`의 `status`, `started_at`, `finished_at`을 `manage.py shell -c`로 조회한다. 읽기만 한다.
4. **판단:**
   - 문제가 없으면 사용자에게 수치와 함께 보고하고 끝낸다.
   - 지연이 크거나 실패가 있으면 원인을 조사하고 수정안을 먼저 제안한다.

### 6-2. 보안 헤더 강화 (1~2주 뒤, 약 2026-10-07~14)

1. **CSP를 차단 모드로 바꾸기**
   - 전제: 지난 1~2주 동안 `csp violation` 경고 로그가 없어야 한다.
   - 확인: Grafana Loki `{service_name="learningx-alert-web"} |= "csp violation"` 또는 `docker logs learningx-alert-web-1 | grep "csp violation"`
   - 바꾸는 법:
     - 방법 1: `config/settings.py`의 `CSP_REPORT_ONLY` 기본값을 `"0"`으로 바꾼다.
     - 방법 2: `compose.prod.yaml`의 web environment에 `CSP_REPORT_ONLY: ${CSP_REPORT_ONLY:-0}`을 추가한다.
     - 지금 compose에는 이 값이 없어서, 설정의 기본값 `"1"`(report-only)이 쓰인다.
   - 테스트: `config/csp.py` 관련 테스트를 확인하고 필요하면 고친다.
   - 배포 뒤 확인할 페이지: 로그인(Google 버튼), 대시보드, 알림 설정(시간 선택기), PWA 푸시 등록, 토큰 가이드 이미지, 피드백 대화상자. 실제로 열어서 콘솔 오류가 없는지 본다.
   - 위반이 있었다면 원인을 먼저 고친다. 인라인 스크립트나 외부 도메인이 원인일 수 있다.
2. **HSTS를 1년으로 올리기**
   - 전제: 몇 주 동안 HTTPS 문제가 없어야 한다.
   - 바꾸는 법: `deploy/Caddyfile`의 `Strict-Transport-Security "max-age=3600"`을 `"max-age=31536000"`으로 바꾼다.
   - `includeSubDomains`와 `preload`는 `sobok-app.com`의 다른 서브도메인에 영향이 있으므로 넣지 않는다. 필요하면 사용자에게 묻는다.
   - 되돌리기 어려운 변경이다. 브라우저가 1년 동안 기억한다. 적용하기 전에 사용자에게 확인받는다.

## 7. 그 밖에 알아 둘 것

- **한양대 녹화 강의:** 마감(`due_at`)이 채워지는지는 아직 모른다. 확인한 과목의 출석 대상은 실시간 수업(`video_conference`, 마감 없음)뿐이었다. 한양대 과목에 녹화 강의가 올라오면 미리보기와 `RunItem`으로 확인한다.
- **로컬 파일:** 저장소 루트의 `IMG_0899.PNG`~`IMG_0901.PNG`는 사용자의 로컬 스크린샷이다. git이 무시하는 파일이니 건드리지 않는다.
- **grafana-sa-token:** 약 30일 뒤 만료된다. 사용자는 이 토큰으로 경보를 에이전트에 연결할 계획이라 지우지 말라고 했다. 만료되면 사용자에게 재발급을 요청한다.
- **사용자가 정리할 것:** 예전 OCI API 키.
- **OCI 세션 디렉터리:** `~/.oci/sessions/LERNINGX_ALERT`가 남아 있다. 오타 프로필의 흔적이고, 삭제는 정책에 막혔다. 필요하면 사용자가 직접 지운다.

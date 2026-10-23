# 인수인계 (2026-10-24 갱신)

다음 작업자(Claude Code 세션)가 이 문서만 읽고 바로 이어서 일할 수 있게 쓴 문서다. 세부 운영 절차는 `docs/operations/oci-production.md`(런북), Actions 배포는 `docs/operations/github-actions-deploy.md`에 있다. 이 문서는 현재 상태, 규칙, 남은 일을 모은다.

**문서 갱신의 확인 범위**

- 문서·ruleset 정리 당시 애플리케이션 기준은 `main`의 `35419cb`(2026-10-01 KST)였다. 기능·상한·설정을 해당 코드와 대조했으며, 이후 첫 사용 가이드 추가는 아래 기록을 따른다.
- 이 리비전의 [CI 실행 36743633624](https://github.com/hjkim24/learningx-alert-web/actions/runs/36743633624)는 테스트·배포 성공으로 기록돼 있다. 이는 당시 결과이며 현재 운영 정상 여부의 재검증은 아니다.
- GitHub `main-owner-only` ruleset을 2026-10-20 활성화하고 API로 재확인했다. 예외는 `hjkim24` 한 명이다. 아래 2절과 Actions 문서를 따른다.
- VM·운영 DB·Grafana·실제 수신 기기는 이번 갱신에서 조회하지 않았다. 운영 수치와 실계정 결과는 적힌 날짜의 과거 기록으로 읽는다.
- 현재 기능 범위는 [FEATURE_SPEC.md](../FEATURE_SPEC.md), 학교별 실계정 근거·미확인은 [FEASIBILITY.md](../FEASIBILITY.md)를 따른다. `docs/superpowers/`의 날짜별 문서는 당시 설계·계획을 보존한 기록이다.

**첫 사용 가이드 추가 (2026-10-20)**

- `feat/first-use-guide`는 문서·ruleset 정리 완료 후 `78319ee`에서 시작했다. 로그인 화면에 활성 학교와 설정 순서를 보강하고, 대시보드에 Canvas 연결 → 과목 선택 → 알림 대상 → 시험 알림 4단계 가이드를 넣었다.
- 기존 연결·과목·수신처 시험 결과·켜진 알림 시각으로 진행 상태를 판단한다. 별도 DB 필드는 없다. 완료 뒤 접히며 다시 펼칠 수 있고, 토큰 재연결·시각 비활성화는 다음 조치를 안내한다. 전송 성공을 기기 수신 확인으로 표시하지 않는다.
- 로컬 Django 463개(2개 건너뜀), 클라이언트 35개, 배포 스크립트 2종 통과. 마이그레이션 변경 없음. Chromium 1280·768·390·320px에서 넘침·버튼 연결·키보드 펼침·접힘·JavaScript 없는 탐색·자동 POST 없음 확인. 실제 토큰·웹훅·푸시 전송은 사용하지 않았다.
- [PR #79](https://github.com/hjkim24/learningx-alert-web/pull/79)는 최종 커밋 `0f228b2`의 CI test 통과 후 사용자의 운영 반영 승인을 받아 `a5eeb4e`로 머지했다. 별도 전체 변경 리뷰에서 지적 사항이 없었고, 리뷰어가 onboarding·alarms 29개 테스트를 독립 실행해 통과했다.
- [main CI 실행 39395326014](https://github.com/hjkim24/learningx-alert-web/actions/runs/39395326014)의 test·deploy가 모두 성공했다. 운영 배포는 2026-10-20 17:45:48 KST에 완료됐다. 17:46 KST 공개 GET 검증에서 `/healthz/`는 `200 / ok`, 로그인 화면은 `200`과 4단계 안내, 해시된 `app.280e20cb3007.css`는 `200`과 새 가이드 스타일을 확인했다.
- 이번 운영 검증은 공개 화면·정적 파일·헬스체크까지다. 운영 Google 로그인, 인증 후 대시보드, 실제 기기의 알림 수신은 다시 실행하지 않았다. 인증 후 가이드의 상태별 동작과 화면 검증은 위 로컬 합성 데이터 결과를 따른다.

**로그인 화면 재구성 (2026-10-21, 운영 반영 완료)**

- `feat/login-redesign`은 `main`의 `2230563`에서 시작했다. 로그인 전 4열 설정 상자와 큰 남색 예시 배경을 걷어내고, 서비스 소개·Google 시작 버튼과 메시지 예시 하나를 배치했다. 연결 방법은 네이티브 `<details>` 안에 두며 대시보드의 4단계 가이드는 유지한다.
- 활성 학교 조회, Google POST·CSRF, 공개/초대 가입 문구, 개인정보·이용약관·문의 링크는 기존 흐름을 따른다. CSS 변경은 로그인 선택자에 한정하고 사용하지 않는 로그인 규칙을 삭제했다. 새 의존성·스크립트·모델·설정은 없다.
- 로컬 Django 463개(2개 건너뜀), 클라이언트 35개, 배포 스크립트 2종 통과. Chromium 1440·1280·960·768·390·320px에서 넘침과 예시 헤더 줄바꿈을 확인했다. Google 버튼은 첫 화면 안에 표시되며, 도움말 키보드 펼침·접힘, 가이드 링크 응답, JavaScript 없는 사용, 자동 POST 없음도 확인했다. Aside가 실행 중이 아니어서 로컬 Playwright를 사용했다.
- [PR #81](https://github.com/hjkim24/learningx-alert-web/pull/81)은 최종 커밋 `a6744d5`의 CI test 통과와 사용자 승인 후 `1a7bfd0`으로 머지했다. [main CI 실행 39446228820](https://github.com/hjkim24/learningx-alert-web/actions/runs/39446228820)의 test·deploy가 모두 성공했고, 운영 배포는 2026-10-21 00:15:43 KST에 완료됐다.
- 00:16 KST 운영 Chromium 검증에서 로그인 화면과 새 CSS(`app.a88067f812d7.css`)는 `200`, `/healthz/`는 `200 / ok`였다. 1440·768·390·320px 표시, 넘침 없음, 첫 화면의 Google 버튼, 도움말 키보드 펼침·접힘을 확인했고 데스크톱·모바일 스크린샷도 검토했다. 브라우저 오류와 자동 쓰기 요청은 없었다.
- 인증·알림 발송 동작은 바꾸지 않았으며, 실제 Google 로그인과 기기 알림 수신은 재시험하지 않았다.

**Canvas 설정 바로가기 (2026-10-24, 운영 반영 완료)**

- 배경: 사용자 피드백에 토큰 발급이 번거롭다는 의견이 많았다. `feat/canvas-settings-shortcut`은 `main`의 `a54f0b1`에서 시작했다.
- 미연결·재연결 필요 상태의 대시보드 Canvas 연결 칸에 3단계 안내와 학교별 "Canvas 설정 열기" 링크(`School.token_settings_url` = `{canvas_base_url}/profile/settings`, 새 탭)를 넣었다. 정원이 찬 학교는 링크를 빼고, 재연결은 연결된 학교만 보여 준다. 새 의존성·모델·설정은 없다.
- [PR #83](https://github.com/hjkim24/learningx-alert-web/pull/83)은 CI test 통과와 사용자 승인 후 사용자가 직접 `dcfbb9e`로 머지했다(에이전트의 `--admin` 머지는 Claude Code 권한 검사에서 차단됨). [main CI 실행 39977433255](https://github.com/hjkim24/learningx-alert-web/actions/runs/39977433255)의 test·deploy가 성공했고 배포는 2026-10-24 00:24 KST에 끝났다. 공개 GET에서 `/healthz/` `200 ok`, 새 CSS `app.459b4e541280.css`의 바로가기 스타일을 확인했다. 운영 로그인 후 대시보드는 Aside가 서비스에 로그인돼 있지 않아 보지 못했다.
- 후속 `feat/guide-settings-shortcut`: 토큰 가이드의 지름길 한 줄을 1단계 위 "바로 가기" 상자와 학교별 버튼으로 바꿨다(로그인 없이 사용 가능). 사용자 요청으로 화면 전체의 중복도 정리했다.
  - 처음 시작하기: 1단계 "토큰 받는 방법" 링크와 하단 도움말 줄(`setup-help`)을 지웠다. 사이트 하단과 Canvas 연결 칸에 같은 링크가 있다.
  - 대시보드: 연결·과목·알림 대상·알림 시각이 없을 때의 상단 안내 4개를 지웠다. 처음 시작하기의 현재 단계가 같은 내용을 보여 준다. 재연결 필요·푸시 만료 경고는 유지한다.
  - 대시보드 "남은 과제·강의": 빈 상태의 "지금 확인하기" 버튼을 지웠다. 상단 "알림 미리보기"와 같은 동작이어서 그 버튼을 가리키는 문구로 바꿨다.
  - 알림 대상: 상단 "아직 등록된 알림 대상이 없어요" 안내를 지우고, 그 내용을 "등록된 대상"의 빈 상태 문구로 옮겼다.
  - 과목 선택: 강의 토글의 `title` 툴팁을 지웠다. 아래 설명 문구와 같은 내용이다.
  - 로컬 Django 469개(2개 건너뜀), 클라이언트 35개, 배포 스크립트 2종 통과. Chromium 1280·390·320px에서 넘침 없음.
  - [PR #84](https://github.com/hjkim24/learningx-alert-web/pull/84)는 CI test 통과 후 사용자가 직접 `868d1c9`로 머지했다. [main CI 실행 39980373058](https://github.com/hjkim24/learningx-alert-web/actions/runs/39980373058)의 test·deploy가 성공했고 배포는 2026-10-24 00:44 KST에 끝났다. 공개 GET에서 `/healthz/` `200 ok`, 토큰 가이드의 "바로 가기" 상자와 두 학교 링크를 확인했다.
- 후속 `feat/school-first-shortcut`: 학교가 여럿이면 Canvas 연결 칸에서 학교 선택을 3단계 안내 위로 올렸다. 학교를 고르면 `static/app.js`가 다른 학교의 "Canvas 설정 열기" 버튼을 숨긴다(`data-school-choice`, `data-school-link`). JavaScript가 없으면 모든 학교 버튼이 그대로 보인다. 모델·설정 변경은 없다. 학교를 계정에 저장하는 방식과 학교별 서브도메인은 사용자와 검토한 뒤 채택하지 않았다(푸시 구독이 origin마다 따로라 서브도메인은 기존 구독을 깨뜨림). `?school=` 링크로 학교를 미리 고르는 방식은 제안만 한 상태다.
  - 로컬 Django 470개(2개 건너뜀), 클라이언트 35개, 배포 스크립트 2종 통과. Chromium 1280·320px에서 선택 전 두 버튼, 한양대 선택 후 한양대만, 성균관대 선택 후 성균관대만 보이는 것과 콘솔 오류·넘침 없음을 확인했다.
  - [PR #85](https://github.com/hjkim24/learningx-alert-web/pull/85)는 사용자가 직접 `fb87c46`으로 머지했다. [main CI 실행 39981462784](https://github.com/hjkim24/learningx-alert-web/actions/runs/39981462784)의 test·deploy가 성공했고 배포는 2026-10-24 00:52 KST에 끝났다. `/healthz/` `200 ok`, 배포된 `app.41237616e801.js`에 학교 선택 스크립트가 있음을 확인했다.

**출시 전 UI 점검과 수정 (2026-10-24, `feat/launch-ui-fixes`)**

- 점검 방법: 테스트 클라이언트로 상태별 화면 23개(대시보드 신규·2단계·재연결·완료, 각 설정 페이지의 빈/채운 상태, 미리보기, 실행 상세, 계정, 피드백, 접근 거부)를 합성 데이터로 렌더링해 Chromium 1440·390(iPhone 13)·320px에서 넘침·콘솔 오류·실패 요청·44px 미만 터치 대상·이미지 alt를 자동 점검하고 스크린샷을 검토했다. 운영 공개 페이지(404, allauth 로그인 확인·취소·오류)도 같은 방식으로 봤다. Aside는 뷰포트·CDP를 열어 주지 않아 모바일 점검에 쓰지 못했다.
- 사용자 승인으로 고친 것(1~9):
  1. allauth 화면: `templates/allauth/layouts/base.html`이 사이트 `base.html`을 쓰게 했고, 로그인 취소·로그인 오류·GET 로그인 확인·GET 로그아웃 확인을 한국어 안내 페이지로 덮었다. 로그인 오류 페이지는 앱 내장 브라우저면 Safari·Chrome으로 열라고 안내한다.
  2. 대시보드 "최근 실행에서 문제가 있던 항목"이 모바일에서 과목명을 한 글자씩 세로로 쪼개던 문제: 모바일 `.problem-row`를 한 열로 바꿨다.
  3. 404는 사이트 레이아웃, 500·CSRF 실패(`403_csrf.html`)는 request 없이 렌더링되므로 단독 `error_base.html`을 쓴다.
  4. 모든 페이지에 description·Open Graph·twitter 카드 태그를 넣었다. 공유 이미지는 `static/og-image.png`(1200×630, 홍보물 표지와 같은 디자인)다.
  5. 연결 전·재연결 필요 상태에서 Canvas 연결 칸(`_connection_panel.html`)을 처음 시작하기 바로 아래로 올렸다. 연결 전에는 알림 미리보기 버튼과 실행 기록 없는 빈 카드를 숨기고, 처음 시작하기 1단계의 중복 안내·버튼을 지웠다. 모바일 단계 카드 여백도 줄여 신규 화면 높이가 2354px에서 1775px가 됐다.
  6. 과목 선택: 과목이 없으면 저장 바를 숨긴다. 모바일 저장 바는 "미리보기 | 저장" 한 줄(약 120px → 66px)이다.
  7. 내부 코드 노출 제거: 실행·전송 오류 코드는 `accounts/templatetags/run_labels.py`의 `error_label`로 문장을 보여 주고 코드는 `data-error-code`에만 둔다. 실행 상세는 `과목 101` 대신 과목명, `assignment · unsubmitted` 대신 항목 종류를 보여 준다. 채팅 알림의 "조회 실패" 줄에서 `(error_code)`를 뺐다.
  8. 알림 대상이 3개로 차면 웹훅 추가 칸 대신 "먼저 하나를 삭제해 주세요" 안내를 보인다(입력 오류로 다시 그릴 때는 칸 유지).
  9. 알림 끈 항목 빈 상태 문장이 세 줄로 쪼개지던 문제를 고치고, 링크 이름을 실제 이동 위치인 "대시보드"로 바꿨다.
- 로컬 Django 488개(2개 건너뜀), 클라이언트 35개, 배포 스크립트 2종 통과. 바뀐 화면 17개를 같은 방식으로 다시 점검해 넘침·콘솔 오류(로컬 `sw.js` 404 제외)·작은 터치 대상이 없음을 확인했다.
- 남겨 둔 개선점(사용자 결정 전): 실패 과목의 Canvas 원문 이름 표시, 날짜·시각 표기 혼재, 알림 설정 저장 바 자리의 빈 공간, 이름 없는 Slack 대상의 "Slack Slack", 재연결 사용자에게 처음 시작하기가 다시 펼쳐지는 것, 실행 상세 모바일 breadcrumb 들여쓰기, 모바일에서 작은 토큰 가이드 스크린샷, "로컬 계정" 용어, `robots.txt` 없음.
- 실기기 확인 필요: 인스타그램·에브리타임·카카오톡 앱 내장 브라우저에서 Google 로그인(Google의 embedded webview 차단 정책. 헤드리스 시뮬레이션에서는 막히지 않았다), iPhone 홈 화면 앱·Android 푸시 수신, 한양대 설정 화면 복귀.
- 리디렉션 확인: 쿠키 없는 요청에서 두 학교 모두 `/profile/settings` → `/login` → 학교 SSO로 가며, SSO 복귀 주소는 `/learningx/login`으로 고정이다. 사용자가 성균관대 로그아웃 상태에서 로그인 후 설정 화면으로 돌아오는 것을 확인했다. **한양대 복귀는 미확인**이라 안내 문구에 "설정 화면이 아니면 버튼을 한 번 더 눌러 주세요"를 넣었다.
- 로컬 Django 467개(2개 건너뜀), 클라이언트 35개, 배포 스크립트 2종 통과. 데스크톱(Aside)과 Chromium 390·320px에서 넘침 없음을 확인했고, 320px의 버튼 줄바꿈은 단어 단위로 맞췄다.
- 붙여넣기 버튼(클립보드 API)은 브라우저 권한 창이 뜨고 기본 붙여넣기로 충분해 넣지 않았다. Canvas OAuth(학교의 Developer Key 필요)는 사용자 결정 전 제안 단계다.

## 1. 서비스 한 줄 요약

- **무엇:** 학생이 Canvas 액세스 토큰을 연결하면, 마감이 다가오는데 아직 안 한 과제·퀴즈·LearningX 강의를 정해진 시각에 Discord·Slack 웹훅이나 브라우저 푸시(PWA)로 알려 주는 Django 웹 서비스다.
- **주소:** https://learningx-alert.com (2026-09-30에 옮김). 옛 주소 `alert.sobok-app.com`은 Caddy가 새 주소로 301 리디렉션한다(`APP_REDIRECT_DOMAINS`). 로그인은 Google만 쓴다.
- **학교:** 성균관대(`canvas.skku.edu`), 한양대(`learning.hanyang.ac.kr`). 한 서버에서 같이 운영한다.
- **운영자:** 사용자(hjkim4842@gmail.com) 한 명이다.
- **과거 규모(2026-09-30):** 가입 4명(성균관대 3, 한양대 1), 브라우저 푸시 7개·Slack 1개. 현재 수치는 미확인이다. 코드의 기본 상한은 전체 가입 100명·학교별 연결 50개다.

## 2. 작업 규칙 (사용자가 정한 것, 반드시 지킬 것)

**소통**
- 사용자에게는 한국어로 답한다. 코드와 식별자는 영어로 둔다.
- 불확실한 것은 가정이라고 밝히고, 사용자 결정이 필요한 것은 먼저 묻는다. 보고는 "확인한 것 / 확인하지 못한 것 / 제안"을 나눠서 한다.
- 요청받지 않은 기존 동작은 바꾸지 않는다. 발견한 문제는 고치지 말고 보고한다.

**비밀 값**
- 토큰, 비밀번호, 웹훅 URL 값은 절대 출력하지 않는다. 키 이름으로만 말한다.
- 운영 DB에 저장된 사용자 Canvas 토큰으로 실측하지 않는다. 실측이 필요하면 사용자가 키체인(`security add-generic-password -s <이름>`)에 넣어 준 토큰을 쓴다.

**변경과 배포 흐름**
- feature 브랜치를 만들고, 테스트를 통과시킨 뒤 `git push -u origin <브랜치명>`으로 올린다. 브랜치 이름을 반드시 적는다.
- 이어서 `gh pr create --head <브랜치> --base main`으로 PR을 만들고, PR 검사(test)가 통과하면 소유자 `hjkim24` 계정으로 `gh pr merge <번호> --merge --admin --delete-branch`로 머지한다. 새 ruleset에서는 일반 CLI 머지가 정책 차단으로 표시돼 소유자 예외를 명시해야 한다. `--admin`은 테스트 통과 확인 뒤에만 사용한다.
- **배포는 GitHub Actions가 한다.** main에 머지되면 `.github/workflows/ci.yml`이 테스트 후 `./scripts/deploy.sh`를 실행한다. `docs/`, `deploy/grafana/`, `.github/`, `*.md`만 바뀐 머지는 배포를 건너뛴다.
  - 머지한 뒤 `gh run list --workflow ci.yml --branch main --limit 1`과 `gh run view <id>`로 배포 결과를 확인하고, `curl https://learningx-alert.com/healthz/`가 `ok`인지 본다.
  - Actions 배포가 도는 동안 로컬 `./scripts/deploy.sh`를 동시에 돌리지 않는다. Actions가 막혔을 때만 로컬에서 배포한다.
  - 배포 방식: 바뀐 컨테이너(web, scheduler)만 교체하고, Caddy는 요청을 붙잡았다가(`lb_try_duration 30s`) 넘긴 뒤 마지막에 1초 정도 다시 만든다. 사용자에게는 끊김이 없다(측정 결과 오류 0건).
- `main`에 직접 push하지 않는다. 데이터 삭제, 인프라·배포·CI 설정 변경처럼 위험하거나 되돌리기 어려운 작업은 먼저 사용자에게 묻는다.
- GitHub [main-owner-only ruleset](https://github.com/hjkim24/learningx-alert-web/rules/25458152)은 `refs/heads/main`의 생성·갱신·삭제 예외를 사용자 `hjkim24`(ID `37476664`, `User`, `always`) 한 명으로 제한한다. 다른 브랜치는 제한하지 않는다. 소유자 자격 증명을 쓰는 도구도 같은 사용자로 취급되지만 에이전트의 직접 push 금지 규칙은 유지한다. JSON 원본은 `docs/operations/main-owner-only.ruleset.json`이다.
- 명령을 `&&`로 묶을 때, 앞 단계(커밋 등)가 끝나기 전에 push나 PR 생성이 실행되지 않게 하나씩 실행한다.

**정책상 막히는 것 (우회하지 말 것)**
- `curl --data @file`처럼 로컬 파일을 외부 서비스로 보내는 요청. 작은 JSON은 명령 안에서 만들어 `-d "$BODY"`로 보낸다.
- 홈 디렉터리의 `rm -rf ~/...`, 브랜치 없는 push
- 한 명령 안에 `chmod`와 `/etc/` 경로가 같이 있는 경우. 권한 변경은 단독 명령으로 한다.
- heredoc 본문에 `git push`, `ssh …` 같은 문자열이 있으면 명령으로 오인돼 막힐 수 있다. 긴 스크립트나 문서 편집은 파일 작성 도구로 한다.
- 막히면 같은 일을 다른 모양으로 다시 시도하지 말고, 원인을 보고 다른 방법(파일 도구, 명령 분리)을 쓴다.

**임시 파일**
- 저장소 안 `.git/<이름>/` 아래에 두고, 작업이 끝나면 지운다. 세션 scratch 디렉터리는 sandbox 때문에 쓰기가 안 될 수 있다.

**화면 확인**
- **데스크톱:** `aside repl`로 한다. 호출할 때마다 세션이 새로 열리므로 한 번의 호출 안에서 다 한다.
  - `await openTab(url)`을 부른 뒤 전역 `page`를 쓰고, `page.screenshot({path:"./artifacts/x.png"})`로 찍는다. 파일은 `~/.aside/u/0/sessions/<id>/artifacts/`에 저장된다.
  - `setViewportSize`와 `clip`은 동작하지 않는다.
- **모바일 뷰포트:** Playwright 라이브러리를 임시로 설치해 쓴다.
  - `.git/pw`에서 `npm init -y` 후 `npm install playwright@1.63.0`. `package.json` 없이 설치하면 npm이 홈의 `~/package.json`·`~/node_modules`에 설치한다(2026-10-24 실제로 발생).
  - `chromium.launch({executablePath: "~/Library/Caches/ms-playwright/chromium_headless_shell-1247/chrome-headless-shell-mac-arm64/chrome-headless-shell"})` + `devices["iPhone SE"]`
- **렌더링할 페이지:** 로그인이 필요한 페이지는 임시 테스트(`accounts/tests/test_zz_vis_tmp.py`)로 테스트 클라이언트 HTML을 `.git/vis/`에 저장한다. `ln -s ../../static .git/vis/static` 후 `python3 -m http.server 8765 --bind 127.0.0.1`로 띄운다. 임시 테스트와 폴더는 끝나면 지운다.
- **모바일 CSS:** `static/app.css` 끝의 "Mobile fit (≤760px)" 블록에 모은다. 데스크톱 규칙은 건드리지 않는다.

## 3. 구조

**운영 환경**
- OCI VM `168.107.37.170`(ARM 2코어, 12GB), Docker Compose(`compose.prod.yaml`). 컨테이너는 web(Django/gunicorn), scheduler, caddy, otel-collector 네 개다.
- 기존 운영 기록의 DB는 OCI MySQL HeatWave 무료 인스턴스(`10.0.1.9`, TLS)다. 앱 계정은 `learningx`이고 비밀번호는 Vault의 `database-password`에 있다. 저장소의 최신 마이그레이션은 `0012`이며 당시 운영 적용도 기록됐다. 현재 운영 적용 상태는 재조회하지 않았다.
- **백업:** 매일 mysqldump를 Object Storage `mysql/`에 올리고 14일 보관한다(`learningx-alert-backup.timer`).
- **복원 연습:** 매월 1일 04:00 KST에 `learningx-alert-restore-drill.timer` → `deploy/restore-drill-report.sh`가 돈다. 네트워크 없는 임시 MySQL에 복원해 운영 DB와 행 수를 비교하고, 결과는 Grafana를 거쳐 Discord로 온다. 운영 DB는 건드리지 않는다.
- 비밀 값은 OCI Vault에 있고, 배포할 때 `deploy/fetch-secrets.sh`로 가져온다. Vault 항목: `django-secret-key`, `database-password`, `mysql-admin-password`, `credential-encryption-keys`, `google-client-secret`, `grafana-otlp-token`, `grafana-sa-token`.

**접속 정보**
- SSH 대상은 `.deploy.env`의 `SSH_TARGET`이다. Actions는 tailnet IP `100.125.0.76`과 배포 전용 키로 붙는다.
- OCI CLI와 Terraform은 API 키 프로필 `LEARNINGX_ALERT`를 쓴다.
- 인프라 코드는 `infra/terraform/`에 있다. 런타임 설정은 Terraform 출력 → `scripts/push-runtime-config.sh` → VM의 `/etc/learningx-alert/runtime.env`로 들어간다. 도메인(`app_domain`)도 여기서 온다.

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
| `accounts/collection.py` | 수집. 과제·퀴즈는 `submissions/self`가 `unsubmitted`일 때만, 강의는 `/modules` 항목의 `content_data.use_attendance`, `due_at`, `completed`로 판단. 종류: `assignment`, `quiz`, `lecture`, `material` |
| `accounts/scheduling.py` | 알림 시각 계산(`matching_slot`, `slot_minutes`), 실행(`execute_run`, 빈 알림 `_empty_notice_due`), 병렬 처리(ThreadPool 4, MySQL만), 학교별 동시 실행 상한 |
| `accounts/management/commands/run_scheduler.py` | scheduler 루프(매분 스캔, 직전 스캔 이후 분을 최대 15분까지 따라잡음) |
| `accounts/notifications.py`, `webpush.py` | 전송(Discord/Slack/PWA push). 푸시 410이면 대상 삭제 |
| `accounts/context_processors.py`, `templates/accounts/_install_banner.html` | 기기별 설치·푸시 배너. JS는 `static/app.js`의 `LXPush` |
| `accounts/views.py` | 대시보드(만료 푸시 안내 `_expired_push_since_resubscribe`), 알림 대상(대상별 마지막 예약 알림 `_attach_last_deliveries`) 등 |
| `accounts/telemetry.py` | OTel metric. 속성은 status/kind/error_code/school만 쓴다(개인정보 없음) |
| `accounts/management/commands/report_restore_drill.py` | 복원 연습 결과를 로그로 전송(개수만) |
| `accounts/admin_site.py` | 피드백 전용 admin(`/ops-7f3c/`) |
| `config/csp.py` | CSP report-only 헤더와 `/csp-report/` |
| `deploy/Caddyfile` | HSTS, 정적 파일, 옛 도메인 리디렉션, tailnet 전용 블록 |
| `tools/extract_texts.py` | 사이트 한국어 문구 전체를 `.git/copy/`에 CSV·MD로 뽑는 도구 |
| `DESIGN.md` | 디자인 토큰의 기준. `accounts/tests/test_design_tokens.py`가 `DESIGN.md`, `static/app.css`, `tools/figma-design-system/code.js`가 같은지 검사 |

**한도와 사용자 설정**
- 알림 시각은 사용자당 3개다(`AlarmTime.MAX_PER_RULE`). 알림 대상도 사용자당 3개다(`Destination.MAX_PER_USER`).
- 학교별 연결 50개(`SCHOOL_MAX_USERS`), 전체 가입 100개(`SIGNUP_MAX_USERS`)
- 스레드는 `SCHEDULER_CONCURRENCY=4`, 학교별 동시 실행은 `SCHOOL_CONCURRENCY=3`이다.
- `NotificationRule.notify_when_empty`(기본 꺼짐): 켜면 보낼 항목이 없는 날에도 하루 한 번(KST) "마감되는 과제·강의가 없어요"를 보낸다.

**테스트**
- 의존성을 설치한 가상환경에서 실행한다. `.venv`가 없으면 README의 설치 절차를 먼저 따른다. 운영 비밀값은 필요하지 않다.
- `.venv/bin/python manage.py test`: 첫 사용 가이드 포함 463개(이전 기준 452개). 로그에 `run crashed ... collector secret` ERROR 한 줄이 보이는 것은 의도된 테스트다.
- `.venv/bin/python -m unittest discover -s tests`: 클라이언트 테스트 35개.
- `bash scripts/tests/deploy_contract_test.sh`, `bash deploy/tests/runtime_scripts_test.sh`: 배포 스크립트 테스트
- CI는 이 모두와 `pip-audit`(경고만)을 돌린다.
- 452개·35개 수와 통과 기록은 위 `35419cb`의 CI 로그에서 2026-10-20 확인했다. 소요 시간은 환경에 따라 달라지므로 고정값으로 안내하지 않는다.
- 2026-10-20 로컬 재검증도 통과했다: Django 452개(2개 건너뜀), 클라이언트 35개, 위 배포 스크립트 2종. 프로젝트에 `.venv`가 없어 `/private/tmp/learningx-alert-docs-venv` 임시 환경에 현재 의존성 범위를 설치했다(Django 5.2.18, allauth 65.20.0, oauthlib 4.0.0). 운영 비밀값은 사용하지 않았다. 최초 실행의 DNS 제한과 `STATIC_MANIFEST=0` 상속 문제는 실행 환경을 바로잡아 해소했고 제품 코드는 바꾸지 않았다.

## 4. 관측 (Grafana Cloud)

- **스택:** `merryjelly2786`(`https://merryjelly2786.grafana.net`). 데이터소스 uid는 `grafanacloud-prom`(metric)과 `grafanacloud-logs`다.
- **API 인증:** Vault `grafana-sa-token`(Editor 권한, 약 30일)을 헤더 파일 `.git/gf.hdr`에 담아 `curl -H @.git/gf.hdr`로 쓰고, 끝나면 파일을 지운다.
  - 값을 읽는 법: `infra/terraform`에서 `terraform output -raw app_compartment_ocid`, `vault_ocid` → `oci vault secret list --name grafana-sa-token` → `oci secrets secret-bundle get` → base64 디코드
- **대시보드:** `learningx-alert-overview`. 저장소 사본은 `deploy/grafana/dashboard-learningx-alert.json`이다.
  - 행은 서비스, 학교, 웹, 외부 호출, 서버, 로그 순서다.
  - "실제 시작 지연 (대기 포함)"과 학교별 p95 패널로 스케줄러 지연을 본다.
- **경보 규칙:** 폴더와 그룹 모두 `learningx-alert`이고, 모두 contact point `Discord`로 간다. 사본은 `deploy/grafana/alert-rules.yaml`이다. 규칙을 바꾸면 이 사본도 export해 갱신한다.

  | uid | 조건 |
  |---|---|
  | `lx-scheduler-stalled` | 5분 동안 scan 1회 미만이 2분 지속 |
  | `lx-runs-failed` | 15분 안에 failed/needs_review/interrupted 실행 |
  | `lx-site-down` | 마지막 정상 헬스체크가 180초보다 오래됨, 1분 지속 (배포 중 실패 1번에는 안 울림) |
  | `lx-feedback-received` | 로그 "feedback received" |
  | `lx-school-capacity` | 학교별 연결/정원이 0.8 초과, 5분 지속 |
  | `lx-push-failures` | 최근 24시간 브라우저 푸시 실패 2건 이상이면서 실패율 30% 초과, 5분 지속 |
  | `lx-restore-drill-ok` / `lx-restore-drill-failed` | 월간 복원 연습 결과 (로그 `restore drill ok/failed`, 서비스 이름 `learningx-alert-ops`). 성공 경보는 1시간 뒤 "해결" 메시지가 한 번 더 온다 |

  - 규칙마다 annotation `summary`(무슨 일인지)와 `description`(값의 뜻)이 있다. 새 규칙에도 둘 다 넣어야 Discord 서식이 제대로 나온다.
- **Discord 서식:** 알림 템플릿 `lx-discord`(사본 `deploy/grafana/discord-template.tmpl`). contact point는 title `{{ template "lx.discord.title" . }}`, message `{{ template "lx.discord.message" . }}`, `use_embed_description=true`로 설정했다.
- **Grafana API 주의점:**
  - contact point를 PUT할 때 `url`에 `[REDACTED]`를 넣으면 저장된 웹훅이 유지된다.
  - 옛 `receivers/test` 엔드포인트는 없어졌다. 테스트 전송은 `POST /apis/notifications.alerting.grafana.app/v1beta1/namespaces/stacks-1848825/receivers/RGlzY29yZA/test`로 한다(`integration` + `alert` body, `secureFields.url=true`).
  - 템플릿은 먼저 `POST /api/alertmanager/grafana/config/api/v1/templates/test`로 렌더링해 보고 올린다.
  - 셸이 macOS bash 3이라 연관 배열(`declare -A`)이 없다. 여러 규칙을 고칠 때는 함수나 Python으로 한다.
- **의존성:** Dependabot(`.github/dependabot.yml`)이 매주 월요일 09:00 KST에 pip(OpenTelemetry는 한 PR로 묶음), GitHub Actions, Docker 업데이트 PR을 연다. 머지하면 배포되므로 일반 변경처럼 검토한다. CI의 `pip-audit`은 경고만 남기고 배포를 막지 않는다(사용자 결정).

## 5. 2026-09-30~10-01 구현 기록 (PR 순서)

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
| #54 | 이 문서와 `CLAUDE.md`, Grafana 사본(`deploy/grafana/`) |
| #55 | `lx-site-down` 규칙을 "마지막 정상 헬스체크 경과 초" 기준으로 변경 |
| #56 | 배포 중단 줄이기: `restart` 대신 바뀐 컨테이너만 교체, Caddy `lb_try_duration 30s`, Caddy만 강제 재생성 |
| #57 | GitHub Actions CI와 자동 배포(Tailscale `tag:ci`, 배포 전용 SSH 키) |
| #58 | 대시보드: 남은 항목이 없으면 카드 3개를 한 줄에 |
| #59, #60 | 도메인 `learningx-alert.com`으로 이전, 옛 주소 301 |
| #61 | 기기별 설치·푸시 배너(iPhone 인앱 브라우저 → Safari, Safari → 홈 화면 추가 안내, 설치 앱 → "알림 켜기" 한 번) |
| #62 | 모바일 레이아웃(320px에서 넘침 없음, 터치 대상 44px, 데스크톱 픽셀 동일) |
| #63 | 퀴즈 알림(예전 퀴즈와 New Quizzes, 제출 안 한 것만, "퀴즈" 배지) |
| #64 | 푸시 신뢰성: 대상별 마지막 예약 알림 성공·실패 표시, 만료 푸시 대시보드 안내, `lx-push-failures` 경보 |
| #65 | "알릴 게 없는 날도 알려 주기"(하루 한 번, 기본 꺼짐, migration 0012) |
| #66 | Dependabot, `pip-audit`(경고만), 월간 복원 연습 타이머와 Discord 보고 |
| #73 | 이용약관 `/terms/`, 사이트 하단, 빈 알림 도움말 |
| #74 | 하단 도움말 링크와 비공식 서비스 안내 |

Grafana 쪽 변경(코드 밖, 사본은 `deploy/grafana/`):
- Discord 템플릿과 contact point 서식
- 규칙 description
- `lx-site-down` 조건 변경
- `lx-school-capacity`, `lx-push-failures`, `lx-restore-drill-ok/failed` 규칙
- 대시보드 "학교" 행

한양대 실측 결과는 `docs/superpowers/specs/2026-09-30-expansion-review.md` 끝에 있다. 사용자가 한양대 계정으로 운영 연결까지 확인했다.

## 6. 남은 일

### 6-1. 스케줄러·정기 복원 연습 — 관측 결과 기록 대기

2026-10-01 이후 확인하도록 남긴 항목이다. 2026-10-20 갱신 시 저장소에서 후속 결과를 확인하지 못했다. 날짜가 지났다는 이유로 완료 처리하지 않는다. 목표는 병렬 스케줄러(#42)와 따라잡기(#48)의 실제 실행 결과를 확인하는 것이다.

1. **Grafana에서 확인할 것:**
   - "실제 시작 지연 (대기 포함)"의 p95가 몇 초 수준인지 본다. 직렬로 돌던 때는 첫 두 실행이 6.6초와 9.3초였다. 병렬이면 거의 동시에 시작해야 한다.
   - "스캔 1회 시간"이 60초보다 짧은지 본다.
2. **로그에서 확인할 것:**
   - 스케줄러: `ssh $SSH_TARGET "sudo docker logs --since 30m learningx-alert-scheduler-1 2>&1 | grep -E 'late slot claimed|run crashed|ERROR'"`
   - `late slot claimed`가 있으면 누락 분을 따라잡았다는 뜻이다. 몇 초 늦었는지(`delay_seconds`)를 적는다.
3. **DB에서 확인할 것:** 조사 대상 날짜의 09:00 실행 상태를 본다. `ScheduledRun`의 `status`, `started_at`, `finished_at`을 `manage.py shell -c`로 조회한다. 읽기만 한다.
4. **판단:**
   - 문제가 없으면 사용자에게 수치와 함께 보고하고 끝낸다.
   - 지연이 크거나 실패가 있으면 원인을 조사하고 수정안을 먼저 제안한다.
5. **같이 확인할 것:** 정기 복원 연습 결과를 본다. 최초 확인 요청은 2026-10-01 04:00 KST 실행이었다. 현재 확인 시에는 실행 날짜도 함께 기록한다.
   - `journalctl -u learningx-alert-restore-drill`에서 `restore_drill_ok`가 나왔는지
   - Discord에 "월간 복원 연습 성공"이 왔는지

### 6-2. 보안 헤더 강화 — 관측·승인 후 진행

원래 2026-10-07~14 검토 예정이었다. 현재 코드도 CSP 보고 전용·운영 HSTS 기본 1시간이다. 운영 로그를 다시 확인하고 필요한 승인을 받은 뒤 진행하며, 예정일 경과를 적용 완료로 해석하지 않는다.

1. **CSP를 차단 모드로 바꾸기**
   - 전제: 지난 1~2주 동안 `csp violation` 경고 로그가 없어야 한다.
   - 확인: Grafana Loki `{service_name="learningx-alert-web"} |= "csp violation"` 또는 `docker logs learningx-alert-web-1 | grep "csp violation"`
   - 바꾸는 법: 지금 코드에는 차단 모드가 없다. `CSP_REPORT_ONLY=0`은 차단이 아니라 CSP 헤더를 아예 끈다. `config/csp.py`의 미들웨어에 차단 모드를 추가해야 한다.
     - 예: 설정 `CSP_ENFORCE=1`이면 같은 `POLICY`를 `Content-Security-Policy` 헤더로 보낸다. 보고 받기를 유지하려면 `report-uri /csp-report/`를 정책에 둔다.
     - 설정을 새로 만들면 compose(web environment)에도 넣는다.
   - 테스트: `config/csp.py` 관련 테스트를 확인하고 필요하면 고친다.
   - 배포 뒤 확인할 페이지: 로그인(Google 버튼), 대시보드, 알림 설정(시간 선택기), PWA 푸시 등록과 설치 배너, 토큰 가이드 이미지, 피드백 대화상자. 실제로 열어서 콘솔 오류가 없는지 본다.
   - 위반이 있었다면 원인을 먼저 고친다. 인라인 스크립트나 외부 도메인이 원인일 수 있다.
2. **HSTS를 1년으로 올리기**
   - 전제: 몇 주 동안 HTTPS 문제가 없어야 한다.
   - 바꾸는 법: `deploy/Caddyfile`의 `Strict-Transport-Security "max-age=3600"`과 `config/settings.py`의 `SECURE_HSTS_SECONDS`를 함께 `31536000`으로 바꾼다.
   - `includeSubDomains`와 `preload`는 넣지 않는다. 넣으면 `learningx-alert.com`의 다른 서브도메인도 HTTPS만 쓸 수 있게 묶인다. 필요하면 사용자에게 묻는다.
   - 되돌리기 어려운 변경이다. 브라우저가 1년 동안 기억한다. 적용하기 전에 사용자에게 확인받는다.

### 6-3. 사용자 결정을 기다리는 일 — 사용자가 요청할 때만 한다

- **사이트 문구 수정:** 사용자가 문구를 직접 고치기로 했다.
  - 2026-09-30에 전체 목록(611개, T001~T611)을 CSV·MD로 보냈다.
  - 2026-10-01 기록에는 651개로 다시 매겨졌다고 돼 있다. 현재 목록은 필요할 때 `tools/extract_texts.py`로 다시 만들고 파일·추출 날짜를 확인한다. ID는 고정되지 않는다.
  - 수정안이 오면 ID가 아니라 "현재 텍스트"를 코드에서 찾아 바꾼다. 테스트가 문구를 확인하는 곳이 많으니 같이 고친다.
- **마감 직전 알림(보류):** 사용자는 "1·3·6시간 선택, 기본 꺼짐"을 골랐고, 구현은 보류했다. 제안했던 전제는 다음과 같다.
  - 30분마다 켠 사용자만 확인한다.
  - 같은 항목·마감에는 한 번만 보낸다.
  - 정기 알림 후 1시간 안에 알린 항목은 뺀다.
  - 새벽에 보낼지는 정하지 않았다.
- **Dependabot PR 6개(2026-10-20 GitHub 조회에서 열림):** 이번 문서 작업에서는 머지하지 않는다. 머지하면 자동 배포된다.
  - #70 Django 5.2 → 6.1
  - #68 gunicorn 23 → 26
  - #67 Python 3.12 → 3.14 이미지
  - #69 setuptools
  - #75 django-allauth 허용 범위 갱신(`>=65.19.7,<66`)
  - #76 cryptography 허용 범위 갱신(`>=50.0.2,<51`)
  - 하나씩 변경 사항(릴리스 노트)을 확인하고, PR 테스트 결과와 함께 사용자에게 머지 여부를 묻는다. allauth, OpenTelemetry, PyMySQL 호환성이 걸린다.
- **과거 의존성 감사 기록:** 2026-10-01 메모에는 `oauthlib 3.3.1` 관련 감사 결과와 4.0.0 호환성 확인 요청이 있었다. 현재 의존성 범위는 고정 lock이 아니며 2026-10-20 임시 환경 설치에서는 `oauthlib 4.0.0`이 선택됐다. 운영 설치 버전과 최신 전체 취약점 감사는 이번 문서 작업에서 확인하지 않았으므로 과거 결과를 현재 취약 상태로 단정하지 않는다.
- **퀴즈 추가 확인(사용자가 나중에 보기로 함):**
  - 응시 중인 퀴즈가 `unsubmitted`로 남는지 실측하지 않았다.
  - LearningX 쪽 퀴즈(`allcomponents_db`의 `quiz` 유형)는 알림에 없다.
- **푸시 재등록 문제(발견만):** 푸시 서비스가 만료(410)라고 한 구독을 브라우저가 아직 가지고 있으면, 설치 배너의 조용한 동기화가 그 구독을 다시 등록할 수 있다. 다음 알림에서 다시 410이 나고 삭제된다. 동작을 바꾸는 일이라 손대지 않았다.
- **아이디어:** 새 공지 알림(Canvas `announcements` API), 가입→연결→과목→대상→첫 알림 단계별 집계, 요일 칩을 두 줄로 바꿔 44px 맞추기, Play 스토어 TWA. 모두 사용자 요청 전에는 하지 않는다.

## 7. 그 밖에 알아 둘 것

- **한양대 녹화 강의:** 마감(`due_at`)이 채워지는지는 아직 모른다. 확인한 과목의 출석 대상은 실시간 수업(`video_conference`, 마감 없음)뿐이었다.
- **알림 판단 기준:** 알림 시각마다 Canvas를 새로 조회한다. 제출이나 시청을 마친 항목, 마감이 없거나 지난 항목, 사용자가 "알림 끄기"를 누른 항목은 뺀다. 제출 상태를 알 수 없으면 알리지도 않고 제출로 치지도 않고, 그 과목을 "확인 실패"로 표시한다.
- **로컬 파일:** 저장소 루트의 `IMG_0899.PNG`~`IMG_0901.PNG`는 사용자의 로컬 스크린샷이다. git이 무시하는 파일이니 건드리지 않는다. `.git/mobile-shots/`에는 모바일 수정 전후 비교 스크린샷이 있다.
- **grafana-sa-token:** 2026-09-30 기록상 유효기간 약 30일이었다. 현재 유효성·만료일은 재확인하지 않았다. 사용자는 이 토큰으로 경보를 에이전트에 연결할 계획이라 지우지 말라고 했다. 만료됐으면 사용자에게 재발급을 요청한다.
- **사용자가 정리할 것:** 예전 OCI API 키.
- **OCI 세션 디렉터리:** `~/.oci/sessions/LERNINGX_ALERT`가 남아 있다. 오타 프로필의 흔적이고, 삭제는 정책에 막혔다. 필요하면 사용자가 직접 지운다.

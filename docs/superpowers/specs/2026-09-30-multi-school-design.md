# 여러 학교 지원 설계 (한 서버)

## Status

- 2026-09-30 초안 → 같은 날 구현·배포(성균관대, 한양대 동시 오픈).
- 확정한 결정:
  - 토큰 가이드는 하나를 같이 쓴다. 1단계에 한양대 로그인 주소 한 줄만 추가했다.
  - 학교 선택은 라디오 버튼이다.
  - 학교별 상한은 `SCHOOL_MAX_USERS=50`이다. 전체 상한 `SIGNUP_MAX_USERS=100`은 유지한다.
  - 한양대 강의 알림은 성균관대와 같은 형식이라고 보고 켰다.
  - 배포는 설계의 5단계 대신 한 번에 했다. 운영 연결 3건이 모두 `skku`로 이관되는 것만 확인하면 됐기 때문이다.
- 전제: 학교별 서버가 아니라 **한 서버에서 여러 학교**를 받는다(`2026-09-30-expansion-review.md` 결론).
- 첫 대상: 성균관대(기존), 한양대(`https://learning.hanyang.ac.kr`, API 구조가 같은 것을 실측으로 확인).

## 목표

1. 사용자가 Canvas를 연결할 때 학교를 고르고, 그 학교의 Canvas로만 요청이 간다.
2. 기존 사용자는 아무것도 하지 않아도 성균관대로 계속 동작한다.
3. 학교를 하나 더 추가하는 일이 "학교 목록에 한 항목 + 가이드 스크린샷" 수준으로 끝난다.
4. 외부 요청 방어(SSRF)가 약해지지 않는다. 사용자가 주소를 직접 입력하지 않고, 코드에 적힌 목록에서만 고른다.

## 범위 밖

- 학교 SSO 로그인. 로그인은 지금처럼 Google이다.
- 학교별 가입자 상한. 전체 상한 하나(`SIGNUP_MAX_USERS`)를 그대로 쓴다. 필요해지면 나중에 추가한다.
- 학교별 관리자, 학교별 데이터 분리(DB나 스키마 분리).
- 실시간 수업(`video_conference`, 마감 없음)의 "수업 시작 알림"은 별도 기능으로 검토한다.

## 결정

### 1. 학교 목록은 코드에 둔다 (DB 테이블 아님)

`accounts/schools.py`에 불변 레지스트리를 둔다.

```python
@dataclass(frozen=True)
class School:
    code: str                 # "skku", "hanyang" — DB에 저장하는 값
    name: str                 # "성균관대학교"
    canvas_base_url: str      # "https://canvas.skku.edu"
    learningx_hosts: frozenset[str]  # 비어 있으면 강의 알림 끔
    guide_template: str       # "guide/canvas_token_skku.html"
    lms_home_url: str         # 토큰 가이드 1단계 링크 (icampus 등)

SCHOOLS = {school.code: school for school in (SKKU, HANYANG)}
```

- **코드에 두는 이유:**
  - 학교 주소와 허용 호스트는 외부 요청 방어의 경계다. 운영 화면에서 바꿀 수 있으면 SSRF 표면이 된다. 코드 리뷰와 테스트를 거쳐 PR로만 바뀌게 한다.
  - 학교마다 가이드 템플릿이 따로 있다.
  - 학교 추가는 드물다.
- **켜고 끄기:** 환경값 `ENABLED_SCHOOLS=skku,hanyang`으로 연결 화면에 보이는 학교를 켜고 끈다. 목록에 없는 코드는 무시한다. 새 학교를 코드에 넣어 두고, 가이드 준비가 끝난 뒤에 켤 수 있게 하려는 것이다.
- **기존 환경값:** `CANVAS_BASE_URL`, `LEARNINGX_ALLOWED_HOSTS`는 성균관대 항목의 값을 덮어쓰는 용도로만 남긴다. 운영 설정 호환 때문이다. 다음 정리 때 없앤다.

### 2. 데이터 모델

- `CanvasConnection.school = CharField(max_length=32, default="skku")`를 추가한다.
  - 마이그레이션은 컬럼 추가와 기본값뿐이다. 기존 행은 모두 `skku`가 된다. 되돌리기 쉽다.
  - 값 검증: 저장할 때 `SCHOOLS`에 있는 코드인지 확인한다. choices는 레지스트리에서 만든다.
- **학교는 연결에 붙인다.** 사용자에 붙이지 않는다. Canvas 토큰과 학교는 한 쌍이기 때문이다. 연결을 해제하면 학교 정보도 같이 사라진다.
- **학교를 바꿀 때:** 연결 해제 후 다시 연결하는 것으로만 한다. 해제하면 `CourseSelection`이 지워진다(기존 동작). 다른 학교의 과목 ID가 섞이지 않는다.
- `CourseSelection`, `ExcludedItem`, `RunItem`은 Canvas 과목 ID를 쓴다. 과목 ID는 학교마다 겹칠 수 있지만, 모두 사용자에 묶여 있고 한 사용자는 한 학교에만 연결되므로 충돌하지 않는다.

### 3. 클라이언트 만들기

학교별 값을 직접 읽는 곳 네 군데를 한 함수로 모은다.

```python
def canvas_client_for(connection, token, client_class=CanvasClient):
    return client_class(school_of(connection).canvas_base_url, token)
```

| 현재 | 변경 |
|---|---|
| `services.verify_and_store_connection`: `settings.CANVAS_BASE_URL` | 폼에서 고른 학교의 주소로 검증하고 `school`도 저장 |
| `courses.sync_courses`: `settings.CANVAS_BASE_URL` | `canvas_client_for(connection, …)` |
| `collection.collect_for_user`: `settings.CANVAS_BASE_URL` | 같음 |
| `collection.default_learningx_factory`: `settings.LEARNINGX_ALLOWED_HOSTS` | 학교의 `learningx_hosts`. 비어 있으면 `None`(지금과 같은 "강의 알림 준비 중") |
| `forms.CourseSelectionForm.lectures_available`: 전역 설정 | 사용자 연결의 학교 기준 |

`CanvasClient`와 `LearningXClient`는 바꾸지 않는다. 이미 주소와 허용 호스트를 인자로 받는다.

### 4. 화면

- **Canvas 연결 카드:** 토큰 입력칸 위에 학교 선택(라디오 또는 select)을 둔다. 켜진 학교가 하나뿐이면 숨기고 그 학교로 고정한다. 그래서 한양대를 켜기 전까지 화면은 지금과 같다.
- **연결된 뒤:** 카드 요약에 학교 이름을 보여 준다(예: "연결됨 · 한양대학교 · 김학생").
- **토큰 가이드:** `/guide/canvas-token/`은 학교 선택 화면으로 쓰고, `/guide/canvas-token/<code>/`에 학교별 가이드를 둔다.
  - 기존 주소는 성균관대 가이드로 연결되게 유지한다. 외부에 공유된 링크가 있기 때문이다.
  - 한양대 가이드 스크린샷은 사용자님이 찍어 주셔야 한다.
- **로그인 화면·방침:** "성균관대" 같은 특정 학교 문구가 있으면 학교 목록에서 만든다. 지금은 토큰 가이드 링크뿐이다.

### 5. 스케줄러·부하

- **학교별 동시 호출 상한:** 스레드 풀(4개)은 그대로 두고, 학교마다 세마포어(기본 3)를 둔다. 한 학교 Canvas가 느려져도 나머지 스레드가 다른 학교 실행을 계속 처리한다.
- **metric 라벨:** 실행과 외부 호출 metric에 `school` 라벨을 추가한다. 값이 학교 수만큼만 있어서 계열 수가 크게 늘지 않는다. 대시보드의 "실제 시작 지연"을 학교별로 볼 수 있다.

### 6. 개인정보처리방침

"정보가 거쳐 가는 곳"의 Canvas 항목을 "선택한 학교의 Canvas(예: 성균관대학교 canvas.skku.edu, 한양대학교 learning.hanyang.ac.kr)"로 바꾼다. 켜진 학교 목록으로 만든다. 시행일도 갱신한다.

## 테스트 계획

- **마이그레이션:** 기존 연결이 모두 `skku`가 되는지.
- **연결:**
  - 켜지지 않았거나 목록에 없는 학교 코드를 보내면 거절(400)한다.
  - 고른 학교의 주소로만 검증 요청이 간다(가짜 클라이언트로 주소 확인).
- **수집:** `collect_for_user`와 `sync_courses`가 학교별 주소와 LearningX 호스트를 쓰는지. 두 학교 사용자를 섞어서 확인한다.
- **SSRF:** 한양대 사용자의 LTI 실행이 `canvas.skku.edu`로 가면 막히는지(반대도 같음).
- **화면:**
  - 켜진 학교가 하나일 때 선택 UI가 보이지 않는다.
  - 둘일 때는 보인다.
  - 기존 가이드 주소가 유지된다.
- **스케줄러:** 학교별 세마포어가 한 학교의 동시 실행을 상한으로 막는지(MySQL 병렬 테스트와 같은 방식).
- **방침:** 켜진 학교가 방침에 나오는지.

## 배포 순서

1. 레지스트리, 마이그레이션, 클라이언트 함수를 넣고 배포한다. `ENABLED_SCHOOLS=skku`라 화면과 동작은 그대로다.
2. 운영 DB에서 모든 연결이 `skku`인지 확인한다.
3. 한양대 가이드를 넣고 방침을 갱신한다.
4. `ENABLED_SCHOOLS=skku,hanyang`으로 켠다.
5. 한양대 계정으로 연결 → 과목 동기화 → 미리보기를 실제로 확인한다(지난번 실측 계정).

## 정해야 할 것

1. **한양대 토큰 가이드 스크린샷:** 사용자님이 찍어 주셔야 한다. 성균관대 가이드와 같은 7단계 구성을 예상한다.
2. **학교 선택 UI:** 라디오 버튼(학교가 적을 때 한눈에 보임)과 select(학교가 많아질 때) 중 고른다. 두세 곳까지는 라디오를 권한다.
3. **학교별 가입자 상한:** 지금은 넣지 않는다. 한 학교가 100명을 다 차지하는 상황이 걱정되면 추가한다.
4. **한양대 강의 알림:** 녹화 강의에 `due_at`이 채워지는지 아직 모른다. 확인 전에는 한양대의 강의 알림을 켜 두되, "마감 없음" 항목이 보이면 사용자 안내를 추가한다.

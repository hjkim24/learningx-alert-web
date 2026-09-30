# GitHub Actions 자동 배포

`.github/workflows/ci.yml`이 하는 일:

| 이벤트 | 동작 |
|---|---|
| PR 생성·갱신 | `test` job: Django 테스트, 클라이언트 테스트, 배포 스크립트 계약 테스트 |
| main에 push(머지) | `test` → `deploy`. `deploy`는 Tailscale로 VM에 붙어 `./scripts/deploy.sh`를 실행 |
| 수동 실행(Actions → CI → Run workflow, main) | main 기준으로 테스트 후 무조건 배포 |

- `docs/`, `deploy/grafana/`, `.github/`, `*.md`만 바뀐 머지는 배포하지 않는다. job 요약에 "Only docs changed"라고 남는다.
- 배포는 한 번에 하나만 돈다(`concurrency: deploy-production`, 진행 중인 배포는 취소하지 않음).
- 로컬에서 `./scripts/deploy.sh`를 돌려도 되지만, Actions 배포가 도는 동안에는 돌리지 않는다. 동시에 돌면 막아 주는 장치가 없다.
- 실패하면 GitHub가 커밋 작성자에게 메일을 보낸다. 로그는 Actions 탭에서 본다.

## 접속 경로와 권한

- **Tailscale:** runner는 `tailscale/github-action`으로 tailnet에 임시(ephemeral) 노드 `tag:ci`로 들어온다. job이 끝나면 노드는 자동으로 사라진다.
- **SSH:** 배포 전용 ed25519 키를 쓴다.
  - VM `ubuntu`의 `~/.ssh/authorized_keys`에 `restrict,from="100.64.0.0/10"` 조건으로 등록했다. tailnet 주소에서만 쓸 수 있고, 포워딩과 pty는 막혀 있다. 공개 IP(22)로는 거부되는 것을 확인했다.
  - 이 키로 `sudo`가 된다. 배포에 필요하기 때문이다. 키가 새면 서버 관리자 권한이 넘어가므로, 의심되면 아래 "키 교체"를 바로 한다.
- **호스트 키:** VM의 ed25519 호스트 키를 `DEPLOY_KNOWN_HOSTS`로 고정했다. `StrictHostKeyChecking yes`다.
- **action 고정:** 서드파티를 포함한 모든 action은 커밋 SHA로 고정했다.
- **GitHub Environment `production`:** main 브랜치만 쓸 수 있다.

| 이름 | 종류 | 값 |
|---|---|---|
| `DEPLOY_SSH_KEY` | secret | 배포 전용 개인 키 |
| `TS_OAUTH_CLIENT_ID` | secret | Tailscale OAuth client ID (사용자가 등록) |
| `TS_OAUTH_SECRET` | secret | Tailscale OAuth client secret (사용자가 등록) |
| `DEPLOY_HOST` | variable | VM의 tailnet IP `100.125.0.76` |
| `DEPLOY_KNOWN_HOSTS` | variable | VM 호스트 키 한 줄 (지문 `SHA256:RZ11mTmXA294ZS3ItmT6kC5GYFfT7phq8ArYjHXu7sk`) |

## 처음 한 번: Tailscale 설정 (사용자)

1. **ACL(Access controls)에 태그와 접근 규칙 추가:**

   ```jsonc
   "tagOwners": {
     "tag:ci": ["autogroup:admin"],
   },
   "grants": [
     // GitHub Actions runner는 VM의 SSH에만 닿는다.
     {"src": ["tag:ci"], "dst": ["100.125.0.76"], "ip": ["tcp:22"]},
   ],
   ```

   - 주의: ACL에 기본 규칙(모두가 모두에게 접근 가능, `"src": ["*"], "dst": ["*"]`)이 남아 있으면 `tag:ci`도 tailnet 전체(개인 PC 포함)에 닿는다.
   - 그 경우 기본 규칙의 `src`를 `autogroup:member`로 좁혀서 태그 노드를 빼야 한다.
2. **OAuth client 만들기:** Settings → OAuth clients(Trust credentials) → Generate.
   - 권한 범위(scope): **Auth Keys: Write**
   - 태그: `tag:ci`
3. **GitHub에 등록:** 저장소 Settings → Environments → production → Environment secrets에서 추가한다.
   - `TS_OAUTH_CLIENT_ID`
   - `TS_OAUTH_SECRET`
   - 터미널에서 할 때: `gh secret set TS_OAUTH_CLIENT_ID --env production`을 실행하면 값을 묻는다. 셸 기록에 남지 않는다.
4. **확인:** Actions → CI → Run workflow(main)로 한 번 돌린다.
   - `Join the tailnet` 단계가 VM ping에 성공해야 한다.
   - `Deploy` 단계는 `deploy_success`로 끝나야 한다.

## 키 교체

1. 새 키를 만든다: `ssh-keygen -t ed25519 -N "" -C github-actions-deploy@learningx-alert -f <임시경로>`
2. VM `~/.ssh/authorized_keys`에서 `github-actions-deploy@learningx-alert` 줄을 새 공개 키로 바꾼다. 조건 `restrict,from="100.64.0.0/10"`은 그대로 둔다.
3. `gh secret set DEPLOY_SSH_KEY --env production < <임시경로>`로 등록하고, 임시 파일을 지운다.

## 끄기

- 자동 배포만 멈추려면 저장소 Settings → Environments → production에서 Required reviewers를 켠다. 배포마다 승인이 필요해진다.
- workflow 자체를 끄려면 Actions → CI → Disable workflow를 누른다.

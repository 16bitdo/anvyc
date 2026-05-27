# CP-4 — Snapshot / Rollback 설계

> Control Plane v2 의 첫 axis. autopilot 의 실수 (예: 브랜치 30 파일 수정) 를
> 명시적 marker → 복원 가능하게 한다. 본 문서는 DESIGN §35 의 본문 분리본 —
> README §12a 표 / CONTEXT §3 의 SoT.
>
> SoT 트리오는 `role-based-ruleset` 측 (ROADMAP §4 CP-4 / DESIGN §7 / manifest).

## 1. 설계 원칙

- **Non-disruptive capture**: `git stash create` 로 commit object 만 생성 —
  working tree 미변경. `git update-ref refs/anvyc-snapshots/<id>` 로 GC 방지
  anchor. 사용자가 `git stash drop` 같은 명령을 실행해도 영향 없음.
- **Workspace-local storage**: `<repo>/.anvyc/snapshots/<id>/meta.json` —
  기존 `.anvyc/backups/` 와 분리된 sub-tree. portability 가 필요하면 후속
  polish (예: `~/.anvyc/snapshots/` global mirror).
- **Schema 우선 안정화** (v1 cut-over 학습 L7 적용): 1/3 머지 시점에
  `schema_version: 1` 확정 → 2/3 의 list/diff, 3/3 의 restore 가 이 schema
  를 입력 contract 로 가정.

## 2. Snapshot Meta Schema v1

```json
{
  "schema_version": 1,
  "id": "20260524T013000Z-a1b2c3",
  "label": "before-refactor",
  "claude_session_id": "abc-def-...",
  "git_branch": "feat/foo",
  "git_stash_ref": "refs/anvyc-snapshots/20260524T013000Z-a1b2c3",
  "git_stash_sha": "<commit-sha>",
  "created_at": "2026-05-24T01:30:00Z",
  "uncommitted_count": 5,
  "working_clean": false
}
```

| key | 타입 | 의미 |
|---|---|---|
| `schema_version` | int | 현재 `1`. breaking change 시 증가. |
| `id` | str | `<UTC-timestamp>-<6-hex>` (sortable + unique). |
| `label` | str \| null | 사람 가독 marker (선택). |
| `claude_session_id` | str \| null | `--session-id` 명시 우선 → `CLAUDE*_SESSION_ID` env fallback. |
| `git_branch` | str \| null | 현재 branch (detached HEAD 시 sha). |
| `git_stash_ref` | str \| null | `refs/anvyc-snapshots/<id>` (clean tree 시 null). |
| `git_stash_sha` | str \| null | stash commit SHA (clean tree 시 null). |
| `created_at` | str | ISO8601 UTC. |
| `uncommitted_count` | int | tracked 변경 + untracked 파일 수. |
| `working_clean` | bool | `uncommitted_count == 0`. |

## 3. 명령 contract (CP-4 시리즈)

| 명령 | PR | 안전 등급 | 책임 |
|---|---|---|---|
| `anvyc snapshot create [--label X] [--session-id Y]` | 1/3 (#34, merged) | read+create | git stash + meta 적재. clean tree 도 anchor marker. |
| `anvyc snapshot list [--json] [--limit N]` | 2/3 (#35, merged) | read-only | `.anvyc/snapshots/*/meta.json` 인덱스, `created_at` 내림차순. 손상/version-미스매치 entry silently skip. |
| `anvyc snapshot diff <id> [--against <other-id>]` | 2/3 (#35, merged) | read-only | snapshot vs 현재 (또는 두 snapshot 간) `git diff`. `working_clean=true` snapshot 은 안내 메시지만. |
| `anvyc snapshot restore <id> [--force] [--yes]` | 3/3 (#36, merged) | **destructive** | `git stash apply <target.git_stash_sha>`. **dry-run 기본** (--force 없으면 plan 만), `--force` + confirm prompt + auto pre-restore snapshot. `--yes` 자동 수락. §7 절차 참조. |

## 4. git stash anchor 의 의미

`git update-ref refs/anvyc-snapshots/<id> <sha>` 로 stash commit 을 anchor
하면:
- `git stash list` 에는 안 보임 (전용 refspace)
- `git gc` 가 unreachable 로 판정 안 함 (ref 가 있음)
- `git stash apply <ref>` 또는 `git checkout <ref>` 로 복원 가능
- 사용자 의도 명시 (rm refs/anvyc-snapshots/<id>) 시 정리 가능

이 분리는 사용자의 native `git stash` workflow 와 anvyc snapshot 의
namespace 충돌을 방지한다.

### 4.1 Capture 구현 — `stash push -u` + 즉시 `pop --index`

untracked 파일까지 포함하려면 `git stash create -u` 가 자연스러운 후보이나
git plumbing 제한으로 untracked 가 실제로 캡쳐되지 않는다 (live-demo
시점에 발견된 behavior gap). 우회:

1. `git stash push -u --quiet -m "anvyc-snapshot-<id>"` — tracked + index +
   untracked 3-parent stash 생성 (working tree 일시 clean)
2. `git rev-parse stash@{0}` — top stash SHA 즉시 capture
3. `git update-ref refs/anvyc-snapshots/<id> <sha>` — anchor (GC 방지)
4. `git stash pop --quiet --index` — working tree 복원 (anchor 가 있으므로
   stack 에서 제거되어도 SHA 보존)

이 순서가 안전한 이유:
- step 4 (pop) 가 실패해도 stash entry 는 stack 에 남고 (msg `anvyc-snapshot-<id>`
  로 식별), anchor ref 도 이미 등록됨 → 양쪽 채널 모두로 복구 가능
- step 1~3 사이의 race window 는 단일 subprocess 시퀀스라 실용상 무시

clean working tree (변경 0 + untracked 0) 면 step 1 의 push 가 non-zero —
clean marker (stash_sha=null) 로 처리.

## 5. Out of scope (CP-4 axis 완결 기준)

- snapshot 자동 expiration (예: 30일 후 자동 삭제) — 후속 polish
- portable export (snapshot 을 다른 머신/repo 로 이동) — 후속 polish
- snapshot meta 에 anvyc doctor 결과 캡처 — CP-5 (creds) 와 cross-link 시 검토
- `diff --stat` 같은 git diff 추가 option — polish
- restore 시 branch 자동 전환 (`git checkout <target.git_branch>`) — 현재는
  사용자 명시 checkout 권장. autopilot 의 branch 자동 변경은 위험.
- restore 중 conflict 자동 resolve — 현재는 git conflict marker 그대로 남기고
  `SnapshotRestoreError` raise (사용자 수동 해결).

## 6. 보안 경계

- snapshot meta 에 **token 저장 금지** — `claude_session_id` 는 식별자라
  본문 아님; CP-5 `creds status` 결과는 별도 read-only API 참조로만 cross-link.
- `.anvyc/snapshots/` 의 stash sha 는 git object — 일반 git 파일 권한 적용.
  민감 정보가 working tree 에 있던 시점이면 stash 에도 포함됨 — 사용자
  책임 (rule `26-secrets-1password` 의 1Password 사용 원칙 유지).

## 7. Restore 안전 절차

restore 는 destructive — 본 절차로 회복성/재현성 모두 보장한다.

1. **`plan_restore(repo, anvyc_dir, id)`** — target snapshot + 현재 상태 비교,
   warnings list (branch 불일치, 현재 uncommitted 존재 등) + git apply 명령
   미리 산출. CLI 가 `--force` 없으면 본 plan 만 출력 후 종료 (working tree
   무변경 = **dry-run 기본**).
2. **`--force` 시** confirm prompt 1회 (`--yes` 또는 `-y` 로 자동 수락).
3. **auto pre-restore snapshot** — 실 apply 직전 현재 working tree 를
   `label=pre-restore-<target-id>` 로 자동 capture. 실패 시 restore 중단
   (보호 없이 진행 금지).
4. **`git stash apply <target.git_stash_sha>`** — 표준 stash apply. 성공 시
   working tree 가 target 시점 변경분 + 현재 변경분 합쳐진 상태.
5. **conflict 시** `SnapshotRestoreError` raise + pre-restore snapshot id
   안내 message 포함. git conflict marker (`<<<<<<<`) 는 working tree 에
   남음 → 사용자 수동 resolve 또는 `git reset --hard <pre.git_stash_sha>`
   로 회복.
6. **branch 전환 안 함** — target.git_branch 와 현재 branch 불일치는
   warning 만 (실 branch checkout 금지 — autopilot 의 branch 변경은 위험).

회복 채널 요약:
- restore 가 의도와 달랐다 → `anvyc snapshot list` 에서 `pre-restore-<id>`
  찾아 `anvyc snapshot restore <pre-id> --force` 로 원상 복구.
- restore 가 conflict 로 실패했다 → conflict marker 수동 resolve, 또는
  pre-restore snapshot 의 stash sha 로 `git reset --hard <pre.git_stash_sha>`.

# PR-기반 워크플로 강제 — 설계 문서

- **작성일**: 2026-06-01
- **상태**: 승인됨 (구현 플랜 대기)
- **대상 repo**: `~/dev` 하위 16bitdo 소유 16개 (whatap 6개는 범위 외)
- **호스트**: role-based-ruleset(정책 SoT) + anvyc(실행/관측)

## 1. 배경 / 문제

`~/dev` 하위 GitHub repo 는 16bitdo(개인) 16개 + whatap(조직) 6개 + 비-git 4개다.
현재 main 직접 push 를 막는 **실질적 강제 장치가 전무**하다.

조사로 확정한 사실:

- **서버측 protection 가능**: 16bitdo 16개(private 14 + public 2: anvyc·homebrew-anvyc) 모두
  branch-protection API 가 `"Branch not protected"`(=지원되나 미설정) 응답. `upgrade required`
  에러 없음 → 기존 `branch-strategies.yaml` 의 *"free 계정=protection 불가"* 주석은 **stale**.
  단 실제 적용은 **repository ruleset** 으로 하며, 1회 PUT 으로 최종 확인한다.
- **현재 protection 설정된 repo 0개**.
- **whatap 6개는 별도 권한 도메인**: 활성계정 16bitdo 로 `gh api repos/whatap/*` → 전부 404.
  heisgone 계정 + org admin 권한이 있어야 관리 가능 → 본 설계 범위 외.
- **기존 인프라는 전부 advisory**:
  - `role-based-ruleset/metadata/branch-strategies.yaml` — ~/dev 100% 커버, 필드 완비
    (`push_to_main_allowed`/`pr_required`/`pr_reviewers_min`/`merge_strategy`/`protected_branches`),
    그러나 16bitdo 대부분 `push_to_main_allowed=true` 로 **목표와 반대**.
  - rule `14-branch-first`, `19-project-branch-strategy` + `scripts/lookup_branch_strategy.py`
    — AI agent 안내(alwaysApply=false), 강제력 없음.
  - `scripts/hooks/pre-push` — ruleset 자기 repo 전용 lint, branch policy 게이트 없음.
  - **anvyc** — git hook 설치 패턴 보유(`storage/git.py`: `.anvyc` 영역 pre-commit secret scan),
    doctor 에 `project_*` check 군 + `hook_integrity` 보유 → 확장점 적합. branch 기능은 없음.

## 2. 목표 / 비목표

**목표**
- 16bitdo 16개 repo 에서 main(보호 브랜치) **직접 push 를 차단**하고 PR 생성→머지 경로를 강제한다.
- 정책을 **manifest 한 곳**에서 정의하고, 로컬·서버·관측이 그것을 따른다.
- 솔로 개발 마찰을 최소화한다(본인 self-merge 허용).

**비목표**
- whatap 조직 repo 강제(별도 트랙).
- 2인 이상 코드리뷰 강제(`pr_reviewers_min=0` 유지).
- 비-git 디렉터리(cloudflare/dba/hr-project/k8s) 처리.
- CI/CD 파이프라인 신설.

## 3. 결정 사항

확정(사용자 승인):
1. **강제 수준 = 3중 레이어**: manifest(SoT) + 로컬 pre-push hook + 서버 ruleset + anvyc doctor drift 관측.
2. **대상 = 16bitdo 16개만**.
3. **호스트 분리**: 정책 SoT/lookup = role-based-ruleset, hook 설치·서버 적용·drift 관측 = anvyc.

기본값(승인됨, 구현 중 재확인 가능):
4. `pr_reviewers_min: 0` — PR 필수, 본인 self-merge 허용. main 직접 push 만 차단.
5. **repository ruleset** 채택(classic branch protection 아님) — free private 지원.
6. **per-repo `.git/hooks/pre-push`** (marker 가드 + 기존 hook 체이닝). `core.hooksPath` 전역치환 안 함.
7. `merge_strategy: squash`. 차단 대상 = 각 repo `protected_branches`(기본 main).

## 4. 아키텍처

```
[SoT]  role-based-ruleset/metadata/branch-strategies.yaml      ← 정책 단일 출처
          push_to_main_allowed:false  pr_required:true  pr_reviewers_min:0
          │
          ├──▶ [L1 로컬]  pre-push hook (anvyc 설치)  →  main 직접 push 차단 (--no-verify 우회)
          ├──▶ [L2 서버]  GitHub repository ruleset (anvyc 적용)  →  직접 push hard reject, PR 필수
          └──▶ [L3 관측]  anvyc doctor: project-branch-protection  →  3자 drift WARNING
[L4 advisory]  rule 14/19 + lookup_branch_strategy.py (정책만 갱신)
```

대상 16개: `aiforge, analysis, anvyc, anvyc-internal, anvyx, api-test-hub, architecture,
ccinspector, ctxport, cursor-ide, dotfiles-claude, homebrew-anvyc, pulumi-dev, rca,
role-based-ruleset, security-scan`.

## 5. 컴포넌트 명세

### L0 — manifest 정책 전환 (role-based-ruleset)
- 파일: `metadata/branch-strategies.yaml`.
- 16개 entry 를 `push_to_main_allowed:false, pr_required:true, pr_reviewers_min:0,
  merge_strategy:squash, protected_branches:[main]` 로 설정.
  - `role-based-ruleset` 은 이미 false/true(유지), 나머지 ~15개 전환.
- stale 주석(*"16bitdo free → protection 미지원"*) → 검증된 사실(ruleset 지원)로 정정.
- 검증: `scripts/validate_branch_strategies.py` 통과. `lookup_branch_strategy.py --cwd <repo>` 출력 확인.
- 인터페이스: 변경 없음(기존 스키마 그대로). 소비자(L1/L2)가 이 값을 읽음.

### L1 — 로컬 pre-push hook (anvyc 신규 커맨드)
- 커맨드(가칭): `anvyc git install-guards [--root ~/dev] [--all | --project <name> ...] [--dry-run]`.
- 동작: 대상 repo 의 `.git/hooks/pre-push` 에 **marker 블록**(`# >>> anvyc-pr-guard >>>` … `# <<<`)
  설치. 기존 hook 있으면 보존+체이닝, 우리 블록만 idempotent 갱신.
- hook 로직: push 되는 ref 중 보호 브랜치(정책 `protected_branches`) 대상 직접 push 이고
  `push_to_main_allowed=false` 이면 **비영(非0) exit + 안내**("작업 브랜치 cut 후 PR 생성").
  feature 브랜치 push 는 통과.
- `--no-verify` 의 의미(중요): git 네이티브 `--no-verify` 는 **로컬 hook 만** 건너뛴다. L2 서버 ruleset 이
  적용된 repo 에서는 우회해도 **서버가 직접 push 를 여전히 reject** 한다. 따라서 `--no-verify` 는
  "서버 protection 이 아직 없는 repo(예: cross-machine hook 만 설치된 과도기)"에서의 방어선 완화용일 뿐,
  완전 보호된 repo 의 비상 탈출구가 아니다. hook 안내 메시지에 `--no-verify` 를 비상수단으로 권하지 않는다.
- **정책 해소(offline-safe)**: 설치 시점에 `lookup_branch_strategy.py` 로 정책을 해소해
  hook 에 스냅샷(`default_branch`, `protected_branches`, `push_to_main_allowed`)을 임베드.
  런타임에 ruleset repo 경로 의존 안 함. 스냅샷 staleness 는 L3 가 감지.
- 위치: `src/anvyc/storage/git.py` 의 기존 hook-install 패턴 확장 + `src/anvyc/cli.py` 커맨드.
- cross-machine: hook 은 git 비동기화 → 머신마다 재설치 필요. L3 가 미설치/stale 감지.

### L2 — 서버 repository ruleset (anvyc 신규 커맨드)
- 커맨드(가칭): `anvyc git protect [--apply] [--project <name> ...]` (기본 **dry-run**, safe).
- 동작: 대상 repo 에 이름표 `anvyc-pr-required` ruleset 을 default 브랜치에 생성/갱신.
  - rules: `pull_request`(required_approving_review_count=0, PR 자체는 필수),
    직접 push 차단(non_fast_forward + 기본 push 제한), `enforcement: active`.
  - bypass_actors: 기본 없음. 비상 탈출구는 `pr_reviewers_min=0` 이라 **빠른 self-merge PR**(열고 즉시 본인 머지)
    이 1차 수단이며, 진짜 긴급 시에만 repo admin 을 bypass_actors 에 한시 추가하거나 ruleset 을 일시 비활성한다(방법 문서화).
- idempotent: `GET /repos/{owner}/{repo}/rulesets` 로 이름표 매칭 → 없으면 POST, 다르면 PATCH.
- 계정 라우팅: 활성 gh 계정(16bitdo). whatap 은 skip.
- 사전조건: `gh` 존재 + `repo` scope(보유) + repo admin(16bitdo 소유 → 충족).
- **Phase B 확인 게이트**: 저위험 1개(예: security-scan) 선적용 → 직접 push reject 실측 후 일괄.
- 위치: `src/anvyc/` 신규 모듈(예: `core/git_protect.py`) + cli 커맨드. `gh api` 호출.

### L3 — anvyc doctor drift check (신규)
- 파일: `src/anvyc/checks/project_branch_protection.py`, `core/doctor.py` 에 등록.
- 대상: 등록 프로젝트(이미 설정된 `tools.cursor.projects.roots`) ∩ 활성계정 소유 repo.
- 비교 3자: ① manifest 정책(=protected 기대) ② 서버 ruleset 상태(gh api) ③ 로컬 hook marker 존재/스냅샷 일치.
- 발행:
  - WARNING: 정책=protected 인데 서버 ruleset 부재 또는 로컬 hook 미설치/stale.
  - INFO: 3자 정합.
- whatap/접근불가/`gh` 미설치 → **silent skip**(기존 creds-expiry·cost check 정책과 동일).
- statusline ⚠️N 헬스 인디케이터 연동(기존 메커니즘).

### L4 — advisory propagation (role-based-ruleset)
- manifest 갱신 후 `scripts/generate_claude_md.py` 재실행 → 각 프로젝트 CLAUDE.md 의 정책 컨텍스트 갱신.
- rule 14/19 본문 변경은 최소(정책값은 manifest 가 들고 있으므로 코드 변경 거의 없음).

## 6. 데이터 흐름

정책 변경은 **manifest 한 곳**만 수정:
`branch-strategies.yaml` → ① `lookup_branch_strategy.py` 가 install-guards 통해 로컬 hook 스냅샷 주입
→ ② anvyc 가 동일 정책을 서버 ruleset 으로 변환·적용 → ③ doctor 가 3자를 읽어 정합 검증.

## 7. 단계적 롤아웃 + 롤백 (safe-by-default)

| Phase | 작업 | 검증 | 롤백 |
|---|---|---|---|
| A | manifest 16개 정책 전환 + 주석 정정 | `validate_branch_strategies.py`, `lookup_branch_strategy.py` 출력 | git revert |
| B | ruleset **1개 선적용**(security-scan) | `gh api .../rulesets` 조회 + 직접 push reject 실측 | `gh api -X DELETE .../rulesets/{id}` |
| C | 나머지 15개 ruleset 일괄(`anvyc git protect --apply`) | 16개 전수 조회 | 일괄 DELETE |
| D | 16개 pre-push hook 설치(`anvyc git install-guards --all`) | 더미 main push 차단 / feature push 통과 확인 | marker 블록 제거 |
| E | doctor check 추가 + statusline 반영 | `anvyc doctor` drift 0 | check 파일/등록 제거 |

- DIRTY working tree(16개)에 영향 없음 — hook/ruleset 은 push 시점만 관여(작업트리·커밋 미변경).
- 마이그레이션 안내: 기존 "main 직접 commit→push" 흐름은 `feat/*` 브랜치 + PR 로 전환됨(1줄 안내).

## 8. 엣지 케이스 / 리스크

- **free private repo PUT 거부 가능성**: GET 은 지원 응답이나 실제 PUT 이 막힐 수 있음 → Phase B 게이트로 선검증.
- **기존 hook 충돌**: marker 없는 기존 pre-push 존재 시 보존+체이닝(클로버 금지).
- **cross-machine hook 부재**: 신규 머신에서 hook 미설치 → L3 가 WARNING, install-guards 재실행으로 해소.
- **정책 staleness**: manifest 변경 후 hook 스냅샷/서버 ruleset 미갱신 → L3 drift 로 가시화.
- **whatap 오인 처리**: 활성계정 접근불가를 "위반"으로 오판 금지 → silent skip 명시.

## 9. 테스트 전략

- L0: `validate_branch_strategies.py` 회귀 + lookup 출력 스냅샷.
- L1: hook 단위 테스트 — (보호브랜치 직접 push, feature push) × (정책 on/off) 매트릭스, 기존 hook 체이닝.
- L2: dry-run 출력 테스트, idempotency(2회 apply → no-op), `gh api` mock. live 호출 차단(autouse).
- L3: doctor check 픽스처(정합 / drift / 접근불가)별 발행 검증 — 기존 check 테스트 패턴 준수, hermetic.

## 10. 미해결 질문

없음(기본값 1~7 로 확정). 구현 중 커맨드 명칭(`git install-guards`/`git protect`)은
anvyc CLI 패널 컨벤션에 맞춰 최종 확정.

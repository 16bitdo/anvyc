# `anvyc gh` — race-immune gh account 라우팅 설계

- **날짜**: 2026-06-02
- **상태**: 승인됨 (구현 대기)
- **프로젝트**: anvyc (L2-environment)
- **관련**: rule 25 (github-ssh-host-selection), `docs/superpowers/plans/2026-06-02-gh-owner-routing-check.md`(감지 측면), `utils/git_remote.py`

## 1. 배경 / 문제

GitHub `gh` CLI 의 active account 는 **github.com 호스트당 하나, 전역 공유 가변 상태**(keyring)다. 세션·디렉터리별이 아니다. 따라서 어느 터미널/세션이든 `gh auth switch` 하면 **모든 세션에 즉시 반영**된다.

rule 25 는 "repo owner 에 맞춰 `gh auth switch` 하라"고 지시 → owner 가 다른 repo 를 병행하는 세션들이 이 전역 상태를 race 한다("last switch wins"). 실제 사례(2026-06-02): 16bitdo repo 작업 세션의 active account 가 외부 세션에 의해 heisgone 으로 바뀌어, `gh pr create`(16bitdo private repo)가 "Could not resolve repository" 로 실패. (git push 는 remote 의 SSH key alias `github.com-16bitdo` 로 인증 → active account 무관 → 성공. **인증 경로 이원화**로 gh-API 단계에서만 mismatch 표출.)

## 2. 목표 / Non-goals

**목표**: gh-API 호출 시점에 **올바른 account 를 race-immune 하게 보장**한다 — 전역 active 에 의존하지 않고, 호출당 명시 토큰으로.

**Non-goals**:
- 전역 active account 를 자동 전환(switch)하지 않는다 — 그게 race 의 근원. 토큰 주입으로 우회한다.
- `--repo owner/name`(로컬 클론 없음) 케이스는 커버하지 않는다(alias 부재).
- 훅 강제(enforcement)는 하지 않는다 — opt-in 관례(MVP).

## 3. 결정 (승인됨)

| 결정 | 선택 | 근거 |
|------|------|------|
| 메커니즘 | **token-injection** `GH_TOKEN=$(gh auth token --user X) gh ...` | 전역 active 안 건드림 → 동시 세션 race 면역 + 다른 세션 영향 0. gh 2.92.0 `gh auth token --user` capability 확인됨 |
| account 출처 | **remote SSH alias 도출** (`github.com-<account>`) | rule 25 인코딩 재사용, 별도 매핑 불필요. cwd 클론 내에서 완결 |
| 인터페이스 | **anvyc subcommand** `anvyc gh ...` | anvyc(L2) CLI 편입, `utils/git_remote.py` 재사용 |

## 4. 아키텍처

```
anvyc gh pr create ...
  └─ cwd/.git/config → origin ssh_alias "16bitdo"   (utils/git_remote.py 재사용)
  └─ gh auth token --user 16bitdo                     (전역 active 안 건드리고 토큰 추출)
  └─ GH_TOKEN=*** gh pr create ...                    (env 주입, exit code/stdio passthrough)
```

## 5. 컴포넌트

- **`src/anvyc/cli.py`** — `gh` subcommand 등록. argparse `nargs=REMAINDER` 로 gh 인자 전부 passthrough.
- **신규 `src/anvyc/core/gh_route.py`** — 함수 2개:
  - `resolve_account(start: Path) -> str | None` — `start` 에서 `.git` 을 상위로 탐색 → `git_remote.parse_git_config` 로 origin 의 `ssh_alias` 반환. origin 없음/alias 없음 → `None`.
  - `run_gh(account: str, args: list[str]) -> int` — `gh auth token --user <account>` 로 토큰 취득 → `GH_TOKEN` 을 child env 에 주입하여 `gh <args>` exec. child 의 stdin/stdout/stderr 상속, **gh 의 exit code 그대로 반환**.
- **재사용**: `src/anvyc/utils/git_remote.py` (`GitRemoteInfo.ssh_alias` 가 곧 account). 중복 0.

## 6. 데이터 흐름 / 에러 처리

흐름: `anvyc gh <args>` → `resolve_account(cwd)` → account → `run_gh(account, args)`.

account 는 **항상 cwd 의 origin remote 기준**으로 도출한다(gh args 에 `--repo` 가 있어도 무시 — cwd 클론을 대상으로 한다는 전제). 다른 owner repo 를 cwd 밖에서 다루는 케이스는 §2 Non-goals.

에러(안전 우선 — silent fallback 금지):
- **account 도출 불가**(origin 없음 / plain `github.com:` remote / `.git` 없음) → stderr 명확 메시지 + **비0 exit**. active 로 fallback 하지 않는다(그게 버그 근원).
- **`gh auth token --user X` 실패**(account 미인증/미존재) → "account X 미인증 — `gh auth login` / `gh auth switch` 로 추가" 안내 + 비0 exit.
- **`gh` 미설치** → 안내 + 비0 exit.

## 7. 보안

- 토큰은 **child gh 프로세스의 env(`GH_TOKEN`)로만** 전달. **argv 금지**(`ps` 노출 방지), **stdout/log 절대 출력 금지**.
- 런타임에 **필요한 단일 account 토큰만** 추출(즉시 소비, 미표시). 다계정 일괄 추출(harvest) 아님.
- `gh auth token` 의 출력(토큰)은 변수로 받아 env 로만 넘기고 어디에도 echo 하지 않는다.

## 8. 채택 (rule 25, rbr 별도 PR)

rbr `rule 25` 에 1줄 추가: *"gh-API write(예: `gh pr create`, `gh api` PATCH/POST)는 `anvyc gh ...` 로 실행 — race-immune account 보장. bare `gh` 는 read-only/단순 조회에 한정."* opt-in 관례(훅 강제 없음).

## 9. 테스트 (TDD, pytest — anvyc 표준)

- **`resolve_account`** 단위: fixture `.git/config` 들 —
  - `git@github.com-16bitdo:16bitdo/anvyc.git` → `"16bitdo"`
  - `git@github.com-heisgone:whatap/x.git` → `"heisgone"`
  - plain `https://github.com/owner/x.git` (alias 없음) → `None`
  - origin 없음 → `None`
  - 하위 디렉터리에서 호출 → `.git` 상위 탐색으로 동일 결과
- **`run_gh`** 단위(monkeypatch): `gh auth token --user X` 스텁 → `GH_TOKEN` 이 child env 에 설정되고 args 가 그대로 전달되는지 + 토큰이 stdout 에 안 나오는지 검증.
- **통합**(read-only): `anvyc gh auth status` 가 cwd repo 의 account 로 출력하는지(실 repo 에서).

## 10. 마이그레이션 / 롤백

- anvyc subcommand 추가 = 순수 가법(additive). 기존 동작 불변.
- rbr rule 25 1줄(별도 PR). 채택은 점진적(관례).
- 롤백: subcommand 제거 시 영향 없음(bare `gh` 로 회귀).

## 11. 성공 기준

- 동시 세션이 active account 를 heisgone 으로 바꿔도, 16bitdo repo 클론에서 `anvyc gh pr create` 가 **항상 16bitdo 로 성공**(전역 active 무관).
- 토큰이 argv/stdout/log 어디에도 노출되지 않음.
- account 도출 불가 시 silent fallback 없이 명확 에러.
- `resolve_account` / `run_gh` 단위 테스트 GREEN.

## 12. 미해결 질문

없음 — 핵심 결정 3건 확정(§3).

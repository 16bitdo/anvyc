# `anvyc project init` — per-project gh 라우팅 `.envrc` 스캐폴딩 설계

- **날짜**: 2026-06-05
- **상태**: 승인됨 (구현 대기)
- **프로젝트**: anvyc (L2-environment)
- **관련**: rule 25 (github-ssh-host-selection), `docs/superpowers/specs/2026-06-02-anvyc-gh-routing-design.md`(런타임 라우팅), `core/project_doctor.py:101`(`_check_gh_account_routing` — 감지 측면), `core/gh_route.py:21`(`resolve_account`), `utils/git_remote.py`, `core/project_info.py`(`_parse_envrc`/`_derive_gh_account`)

## 1. 배경 / 문제

per-project gh 라우팅은 `.envrc` 에 `export GH_CONFIG_DIR="$HOME/.config/gh-<account>"` 를 선언해 동작한다(direnv 가 cd 시 env 주입 → `gh` 가 올바른 계정 사용). 그러나 **신규 프로젝트에는 이 `.envrc` 가 없어** 수작업이 필요하다:

```
printf 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n' > .envrc
direnv allow
```

`.envrc` 누락 시 `.zshrc` 의 fail-loud 기본값 `GH_CONFIG_DIR=$HOME/.config/gh-none`(빈 dir) 이 상속되어:
- 터미널의 `gh` 호출이 미인증으로 실패
- ccinspector statusline 이 `⚠️ <account>→gh:none <repo>` 경고 표시(origin ssh alias=의도 계정 vs 상속 env=none 불일치)

anvyc 는 이 불일치를 **이미 감지**한다 — `project doctor` check #3 `gh_account_routing`(`core/project_doctor.py:101`)이 origin ssh alias ↔ `.envrc` GH_CONFIG_DIR 정합성을 검사하고, 누락 시 정확히 `export GH_CONFIG_DIR="$HOME/.config/gh-{alias}"` 를 suggestion 으로 출력한다(`project_doctor.py:134-136`). 그러나 **자동 교정(쓰기) 수단이 없다**.

## 2. 목표 / Non-goals

**목표**: 신규/기존 프로젝트에서 origin 으로부터 gh 계정을 도출해 **대화형 확인 후** per-project `.envrc` 라우팅을 1회 명령으로 스캐폴딩한다. doctor #3 의 "감지" 에 대응하는 "교정(remediation)" 측면.

**Non-goals**:
- plain-host origin(`github.com:` alias 없음)을 SSH alias 형태로 자동 교정(`git remote set-url`) 하지 않는다 — remote 변경은 동의 필요(rule 25). 후속 `--fix-remote` opt-in 으로 분리.
- `anvyc.yaml gh_owner_accounts` 에 신규 owner 를 자동 등록하지 않는다 — 매핑 SoT 는 수동 유지(rule 25).
- 전역 gh active account 를 전환하지 않는다(`anvyc gh` 의 token-injection 과 동일 철학 — race 근원 회피).
- 훅 강제(enforcement)는 하지 않는다 — 사용자가 명시 실행하는 opt-in 명령.

## 3. 결정 (승인됨)

| 결정 | 선택 | 근거 |
|------|------|------|
| 인터페이스 | **`anvyc project init`** | `project` 그룹(show/doctor/list)에 편입 → `project doctor` #3(감지)와 대칭되는 쓰기(교정). `anvyc init`/`anvyc git init` 과 충돌 없음 |
| 계정 도출 | **`gh_route.resolve_account` 재사용**(origin ssh alias) | doctor #3 와 **동일 도출** → 감지·교정 영원히 발산 안 함. alias 가 곧 계정, 매핑 불요 |
| `.envrc` 형식 | **정적 리터럴** `export GH_CONFIG_DIR="$HOME/.config/gh-<account>"` | statusline grep(`statusline.sh:288`)·anvyc `_parse_envrc`(`project_info.py:90`) 둘 다 `.envrc` 를 **정적 파싱**(실행 안 함) → 동적/함수형이면 양쪽 감지 깨짐(정합성 제약, 성능 아님) |
| `.envrc` 수정 | **멱등 replace**(기존 GH_CONFIG_DIR 줄 교체, 기존 injection 헬퍼 재사용) | 단순 append 시 GH_CONFIG_DIR 중복 줄 회귀 |
| 입력 방식 | **도출값 default + 확인 프롬프트**(Enter 수락 / override 가능) | "입력 요청받아 진행" 요건. `--account`/`--yes` 로 비대화 |

## 4. 아키텍처

```
anvyc project init                       (cwd = 신규 프로젝트)
  └─ resolve_account(cwd)                origin ssh alias → account  (gh_route.py 재사용)
  │     ├─ alias 있음 → account=alias    (예: github.com-16bitdo → "16bitdo")
  │     └─ alias 없음/remote 없음 → None → owner→account 제안(anvyc.yaml) 또는 프롬프트
  └─ prompt: "gh account [gh-<account>]?" (Enter=수락 / 직접입력=override / --yes·--account 시 skip)
  └─ validate ~/.config/gh-<account>/hosts.yml 존재 → 없으면 미인증 WARN + 계속 확인
  └─ .envrc:    export GH_CONFIG_DIR="$HOME/.config/gh-<account>"  (멱등 replace)
  └─ .gitignore: ".envrc" 없으면 추가
  └─ direnv allow                        (--no-allow 면 skip, direnv 부재 시 안내만)
  └─ 요약 출력 + "다음 Claude Code 재시작 후 statusline 🔑 <account>" 안내
```

## 5. 컴포넌트

- **`src/anvyc/cli.py`** — `project_app.command("init")` 등록. 옵션: `--path`(기존 project 커맨드와 일관, default cwd), `--account/-a`(프롬프트 skip), `--yes/-y`(비대화·도출값 수락), `--no-allow`(direnv allow skip).
- **신규 `src/anvyc/core/project_init.py`**(또는 `project_doctor` 와 paired 모듈) — 순수 로직:
  - `expected_gh_config_dir(account: str) -> str` — `"$HOME/.config/gh-<account>"` 단일 생성 지점. **doctor #3 도 이 헬퍼를 쓰도록 리팩터**(현재 f-string 인라인 → 공유) → 감지/교정 SoT 단일화.
  - `write_envrc_gh_routing(envrc: Path, account: str) -> Action` — GH_CONFIG_DIR export 줄 멱등 주입(있으면 replace, 없으면 추가). 기존 `.envrc` injection 로직 재사용.
  - `ensure_gitignore_entry(gitignore: Path, entry: str) -> bool` — `.envrc` 미존재 시 append.
- **재사용(중복 0)**:
  - `core/gh_route.py:resolve_account` — origin alias 도출(`anvyc gh` 와 동일).
  - `utils/git_remote.py` — origin/ssh_alias 파싱.
  - `core/project_info.py:_parse_envrc`, `_derive_gh_account` — 기존 GH_CONFIG_DIR 값 판독(멱등성 판단).
  - `anvyc.yaml gh_owner_accounts` — plain-host 일 때 owner→account 제안에만 사용.

## 6. 데이터 흐름 / 에러 처리

흐름: `anvyc project init` → `resolve_account(path)` → (account | 프롬프트) → validate → write `.envrc`/`.gitignore` → `direnv allow` → 요약.

계정 결정 우선순위:
1. `--account` 명시 → 그대로 사용(프롬프트 skip).
2. origin ssh alias 도출 성공 → 이를 default 로 프롬프트(`--yes` 면 즉시 수락).
3. alias 없음(plain host) → path owner 추출 → `anvyc.yaml gh_owner_accounts` 조회값을 default 로 프롬프트.
4. remote 없음/매핑 없음 → default 없는 필수 입력 프롬프트.

에러/가드(안전 우선):
- **git repo 아님**(`.git` 부재) → 명확 메시지 + 비0 exit, 파일 미생성.
- **`~/.config/gh-<account>/hosts.yml` 부재**(미인증 계정) → WARN + `gh auth login -h github.com`(또는 `GH_CONFIG_DIR=~/.config/gh-<account> gh auth login`) 안내 → `--yes` 아니면 계속 여부 확인(계속 시 `.envrc` 는 작성하되 미인증 경고 남김).
- **`.envrc` 이미 존재 + GH_CONFIG_DIR 값 상이** → 현재값·새값 표시 후 덮어쓸지 확인(`--yes` 면 replace).
- **direnv 미설치** → `.envrc`/`.gitignore` 는 작성하고 allow 는 skip + 수동 안내.
- 어떤 경우에도 토큰/비밀값 미접근(hosts.yml 은 **존재 여부만** 확인, 내용 미판독).

## 7. 보안

- 비밀값 미취급: `.envrc` 에 쓰는 값은 **경로**(`$HOME/.config/gh-<account>`)뿐, 토큰 아님. hosts.yml 은 존재만 stat.
- `.gitignore` 에 `.envrc` 등록을 보장해 로컬 라우팅 파일이 푸시되지 않게 한다(rule 15 위생).
- gh 토큰/`~/.gitconfig`/ssh config 미출력·미수정(rule 25/26).

## 8. 채택

- `project doctor` #3 WARN(라우팅 누락/불일치) 의 권장 액션 메시지에 *"또는 `anvyc project init` 으로 자동 적용"* 1줄 추가(`project_doctor.py` suggestion).
- README/`docs/multi-account.md` 에 신규 프로젝트 셋업 한 줄로 안내.
- (선택) `ghinit` 셸 단축 래퍼는 **YAGNI 보류** — `anvyc project init` 이 이미 충분히 짧음. 사용자 강력 선호 시에만 dotfiles `shell/` 에 1줄 래퍼.

## 9. 테스트 (TDD, pytest — anvyc 표준)

- **`expected_gh_config_dir`** 단위: `"16bitdo"` → `"$HOME/.config/gh-16bitdo"`. doctor #3 와 동일 출력 보장(공유 헬퍼 회귀 방지).
- **`write_envrc_gh_routing`** 단위(tmp_path):
  - `.envrc` 없음 → 생성 + 정확한 1줄.
  - 기존 GH_CONFIG_DIR 다른 값 → **replace(중복 줄 없음)**.
  - 기존 동일 값 → no-op(멱등).
  - 다른 export(AWS_PROFILE 등) 보존.
- **`ensure_gitignore_entry`** 단위: 없음→append / 이미 있음→no-op / `.gitignore` 부재→생성.
- **계정 결정** 단위(monkeypatch `resolve_account`): alias 도출 / plain-host→anvyc.yaml 제안 / no-remote→필수 프롬프트 / `--account` override / `--yes` 비대화.
- **가드** 단위: git repo 아님→비0 exit·파일 미생성 / 미인증 계정→WARN 경로.
- **통합**(tmp git repo, direnv stub): origin alias fixture → `anvyc project init --yes` → `.envrc`·`.gitignore` 내용 검증.
- 기존 `test_gh_route.py`·`test_project_gh_account.py`·`test_project_doctor_render.py` 패턴 미러.

## 10. 마이그레이션 / 롤백

- 순수 가법(additive): 신규 subcommand + 신규 모듈. 기존 동작 불변(단, doctor #3 가 공유 헬퍼 호출하도록 내부 리팩터 — 출력 동일, 테스트로 고정).
- 롤백: subcommand/모듈 제거 시 영향 없음(수작업 `.envrc` 로 회귀).
- 사용자 데이터 영향: 대상 repo 의 `.envrc`/`.gitignore` 에 가법 변경만. 비대상 파일 불변.

## 11. 성공 기준

- 신규 16bitdo repo 에서 `anvyc project init` (Enter 수락) → `.envrc` 라우팅 + `.gitignore` + `direnv allow` 완료, 새 셸/세션에서 `gh` 가 올바른 계정 사용.
- 같은 repo 에서 `anvyc project doctor` #3 가 INFO(OK) 로 전환.
- `.envrc` 재실행 멱등(중복 줄 없음).
- doctor #3 와 init 이 **동일 `expected_gh_config_dir`** 사용(공유 헬퍼).
- 단위/통합 테스트 GREEN.

## 12. 미해결 질문 / 알려진 한계

- **statusline 즉시성(한계, scaffold 무관)**: ccinspector statusline 은 상속 `$GH_CONFIG_DIR`(path 0)를 effective-cwd `.envrc`(path 1)보다 우선 판독(`statusline.sh:284-303`). 따라서 (a) **현재 실행 중인 세션**은 `.envrc` 추가 후에도 재시작 전까지 경고 유지(부모 프로세스 env 불변 — anvyc 서브프로세스가 변경 불가), (b) work-cwd swap 세션은 launch 프로젝트 계정 표시 가능. anvyc 범위 밖 — 필요 시 별도 ccinspector 개선(EFFECTIVE_CWD 자체 `.envrc` 우선)으로 분리.
- **커맨드 이름**: `project init` 로 확정(§3). 사용자가 본 초기 preview 는 `anvyc gh init` 이었으나 `gh` 는 passthrough 커맨드라 `project` 그룹이 적합. 단축감은 후속 래퍼(YAGNI 보류)로 보존.

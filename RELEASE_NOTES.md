# anvyc 릴리즈 노트

## v0.15.2 — 2026-05-26 (patch — MCP integration silent-failure hardening)

[End-to-end 보호 매트릭스] 신규 머신 dev 셋업에서 `anvyc serve --mcp` 가 silent 하게 `Failed to connect` 로 떨어지던 케이스를 트리거로, **dev 셋업 → 런타임 진단 → 에러 메시지 정확성 → CI 드리프트 → 문서화** 5 layer 를 일괄 정비. functional 변경 없음 — 사용자 영향은 셋업/진단/에러 안내 UX 개선과 신규 doctor check 1건.

### 사용자 영향 변경

- **`scripts/dev-install.sh`**: `ANVYC_EXTRAS` 기본값 `dev` → `dev,mcp` (anvyc#69). 신규 contributor 가 추가 설치 없이 `anvyc serve --mcp` 즉시 사용 가능.
- **`anvyc doctor`**: 18 check 로 증가 (17 → 18). 신규 **`mcp-extra-importable`** check 가 `mcp` 패키지 미설치를 WARNING 으로 즉시 감지 + 정확한 설치 명령 안내 (anvyc#72).
- **에러 메시지 — `anvyc serve --mcp`**: `[mcp]` 표기 silent strip 버그 fix (anvyc#71). `pip install 'anvyc[mcp]'` 안내가 정확히 노출.

```
BEFORE: error anvyc MCP server requires the  extra. Install: pip install 'anvyc'
AFTER:  error anvyc MCP server requires the [mcp] extra. Install: pip install 'anvyc[mcp]'
```

### 내부 hardening (사용자 직접 영향 없음)

- **`src/anvyc/utils/errors.py`**: `print_error()` / `safe_msg()` 헬퍼 신설 (anvyc#74). `cli.py` 의 15 exception interpolation + 3 diff coloring 사이트를 헬퍼 경유로 통일 → Rich markup strip 사고 재발 차단.
- **pre-commit mypy 범위 확장**: `src/anvyc/` → `src/anvyc/ tests/` (anvyc#73). CI 의 `Lint and type-check` job 과 동일 범위 — test 파일의 strict 위반이 push 전에 잡힘. 본 변경으로 PR-12E/PR-12F 가 머지 후 main 의 lint job 을 4 commit 연속 fail 상태로 방치하던 사건 패턴 차단.
- **test type annotation 정리**: `tests/unit/test_workctx.py` / `test_work_cwd_track_check.py` 의 32 mypy errors 해소 (anvyc#70). pre-existing main fail 상태 회복의 직접 원인.

### 문서

- **`CONTRIBUTING.md`** §4.4 정정 (mypy 범위) + §4.5 신규 — CLI 사용자 출력 `console.print` 가이드 (anvyc#75). `print_error()` / `safe_msg()` 사용 규칙과 절대 작성 금지 안티패턴 3건을 표/코드로 문서화.

### 변경된 사용자 워크플로

| 시나리오 | v0.15.1 | v0.15.2 |
|---|---|---|
| 신규 머신 dev 셋업 | `bash scripts/dev-install.sh` 후 `pip install -e '.[mcp]'` 별도 필요 | `bash scripts/dev-install.sh` 만으로 MCP 즉시 사용 |
| `mcp` extra 누락 진단 | 사용자가 `anvyc serve --mcp` 직접 호출해 SystemExit 메시지로 추적 | `anvyc doctor` 가 WARNING 으로 즉시 감지 + 설치 명령 안내 |
| MCP 미설치 시 안내 | `error ... requires the  extra. Install: pip install 'anvyc'` (잘못된 명령) | `error ... requires the [mcp] extra. Install: pip install 'anvyc[mcp]'` (정확한 명령) |

### 검증

```bash
$ anvyc --version
anvyc v0.15.2

$ anvyc doctor   # 18 check 등록 확인
```

### upgrade

functional 변경 없음 (셋업/진단/UX 개선만). 즉시 upgrade 권장.

```bash
uv tool install --reinstall https://github.com/16bitdo/anvyc/releases/download/v0.15.2/anvyc-0.15.2-py3-none-any.whl
```

---

## v0.15.1 — 2026-05-26 (patch — `__version__` 동적 lookup refactor)

[Display drift 영구 차단] v0.15.0 release PR (anvyc#67) 이 `pyproject.toml` 의 version 만 0.14.0 → 0.15.0 bump 하고 `src/anvyc/__init__.py:3` 의 hardcode `__version__ = "0.14.0"` 갱신 누락. 결과 — wheel artifact + editable install 양쪽에서 `anvyc --version` 이 `v0.14.0` 표시되는 display drift. functional 영향 없음 (workctx CLI / doctor check 모두 정상 작동) 이지만 향후 release 의 hardcode 갱신 잊음 방지 위해 **동적 lookup 으로 refactor**.

### 변경

- **`src/anvyc/__init__.py`**: hardcode `__version__` → `importlib.metadata.version("anvyc")` 동적 lookup. `PackageNotFoundError` fallback `"0.0.0+unknown"` (source 실행 등 metadata 부재 케이스).
- **`pyproject.toml`**: version `0.15.0` → `0.15.1`. **pyproject 가 SoT** — 향후 release 는 본 파일 1줄만 bump 하면 `__version__` 자동 동기화.

### 검증

```bash
$ anvyc --version
anvyc v0.15.1
```

editable install + wheel install 양쪽 모두 pyproject version 그대로 표시.

### upgrade

v0.15.0 → v0.15.1 의 functional 변경 없음 — display 정정만. 즉시 upgrade 권장.

```bash
uv tool install --reinstall https://github.com/16bitdo/anvyc/releases/download/v0.15.1/anvyc-0.15.1-py3-none-any.whl
```

---

## v0.15.0 — 2026-05-26 (Control Plane v6 — CP-12 agent work-cwd tracking)

[Control Plane v6 합류] anvyc 가 `role-based-ruleset` × `ccinspector` 와 함께 CP-12 (agent work-cwd tracking) axis 의 **L2 Environment layer 책임 2건** 완결. v0.14.0 직후 단일 axis 의 2 PR 묶음 release — CP-12 의 7-PR cross-repo 시퀀스 중 anvyc 측 산출물.

control plane SoT 위치: [role-based-ruleset/ROADMAP.md §4 CP-12](https://github.com/16bitdo/role-based-ruleset/blob/main/ROADMAP.md) + [docs/control-plane-v1-recap.md §13](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/control-plane-v1-recap.md) (v6 cut-over + v6.1 polish 회고, 누적 12 axes / 30 learnings).

### CP-12: agent work-cwd tracking (v6 axis)

launch dir 에 고정된 statusline 의 한계 해소 — agent 의 실 작업 디렉터리 (Bash `cd` / file Read·Write·Edit·MultiEdit / 명시 override) 가 cache (`.work-cwd-cache` schema v1) 에 누적되어 statusline `🔀` swap 으로 실시간 반영. anvyc 측 책임 2건:

- **`anvyc workctx` CLI** ([#65](https://github.com/16bitdo/anvyc/pull/65)) — explicit override 채널. Bash `cd` 가 불가능한 시나리오 (1Password sandbox / sub-shell 격리 / 명시 의도) 에서 statusline / cache 의 work 컨텍스트 강제 전환.
  - `anvyc workctx switch <path> [--ttl 1800]` — explicit row 작성, TTL 기본 1800s (soft expiry — statusline reader 는 row 존재 시 valid 로 간주, anvyc CLI 호출 시점에 lazy cleanup).
  - `anvyc workctx clear` — explicit row 만 제거 (activity row 는 보존).
  - `anvyc workctx show [--json]` — current effective work-cwd (statusline resolver 와 동일 priority: latest non-expired explicit > latest activity within 60s > stale → launch).
  - `core/workctx.py` 신규 — cache schema v1 호환 reader/writer + TTL 관리 (17 unit tests).

```bash
$ anvyc workctx switch ~/dev/anvyc --ttl 60
workctx switch → /Users/edward/dev/anvyc (ttl=60s, expires_at=1779781211)
  cache: /Users/edward/.claude-edward/.work-cwd-cache

$ anvyc workctx show
cache : /Users/edward/.claude-edward/.work-cwd-cache
rows  : 20
 kind           explicit
 path           /Users/edward/dev/anvyc
 expires_at     1779781211
 remaining_sec  47s
```

- **doctor check `work-cwd-track-wired`** ([#66](https://github.com/16bitdo/anvyc/pull/66)) — 3 profile (`.claude` / `.claude-edward` / `.claude-jklee`) 의 hook 배선 + `env.WORK_CWD_CACHE` 주입을 자동 검증. ccinspector `module_verify` (work-cwd-track) 의 **read-only mirror** — 단방향 의존 (DESIGN §7.7) 으로 별 채널 cross-validation. 검증 항목 3건: hooks.CwdChanged (Phase A 필수), hooks.PostToolUse (Phase B 권장), env.WORK_CWD_CACHE (필수). 누락 시 `Severity.WARNING` + 누락 항목 명시.

```bash
$ anvyc doctor --json | jq '.results[] | select(.check_name=="work-cwd-track-wired")'
# (3 profile 모두 wire 정합 시 결과 없음 — 정상)
```

### Cross-repo 페어 (CP-12 7-PR + v6.1 polish)

본 release 의 anvyc 2 PR 외 trace:

- **rbr#83** (PR-12A): `CwdChanged` event hook 본문 + cache schema v1 (Phase A writer).
- **cci#16** (PR-12B): `wire-hooks-cwd-changed.py` + `module_work_cwd_track` (cci install 자동화).
- **cci#17** (PR-12C): `core/statusline.sh` work_cwd_resolve + 🔀 swap 표시 (reader).
- **rbr#84** (PR-12D): PostToolUse Phase B (`Read|Write|Edit|MultiEdit` matcher, `file_op` row writer).
- **cci#18** (PR-12D'): `wire-hooks-posttooluse.py` + Phase B wire 확장.
- **anvyc#65** (PR-12E): **본 release — workctx CLI**.
- **anvyc#66** (PR-12F): **본 release — doctor check**.
- **rbr#85** (PR-12G): `common/rules/28-work-cwd-tracking.mdc` paired chore.

v6.1 polish (multi-session pollution 해소, 같은 일자 ~30 분):
- **rbr#87** (PR-X1): hook 2개 의 `session_id` row writer.
- **cci#19** (PR-X2): statusline 의 `session_id` filter.
- **rbr#88** (PR-X4): rule 28 트러블슈팅 + 회고 §13.7 L30 (workflow 6-step 패턴).

### 신규 학습 (L27~L30, 누적 30)

- **L27**: hook schema 미확정 시 claude-code-guide agent 1-shot 사전 검증 (axis planning 의 표준 step 후보).
- **L28**: axis 내부 cross-repo 시퀀스는 in-session 효율적 — axes 간 분할만 session 분리 trigger.
- **L29**: settings.json 실시간 reload — cci install 후 현 세션의 다음 tool call 부터 새 hook 자동 fire.
- **L30**: L27 의 실 적용 사례 (multi-session pollution polish). **workflow 6 step 패턴** — 사용자 발견 issue → 진단 → 옵션 비교 → 사전 검증 → writer/reader 짝 PR → live 검증 + chore.

### upgrade 가이드

- 사용자: `brew upgrade anvyc` 또는 `pip install --user --upgrade anvyc==0.15.0` 또는 GitHub Release wheel 직접 install.
- 설치 후: `anvyc workctx --help` 로 새 CLI 가용성 확인 + `anvyc doctor` 가 `work-cwd-track-wired` check 자동 포함.
- 기존 사용자 (CP-12 미사용): `anvyc workctx` 명령은 opt-in — cci `module_work_cwd_track=1` 활성화 + `cc-inspect install.sh` 재실행 후 hook + statusline swap 활성. v0.14.0 동작과 100% backward-compat (workctx CLI 호출 안 하면 영향 없음).

---

## v0.14.0 — 2026-05-25 (Control Plane v1+v2 — CP-1 audit · CP-4 snapshot · CP-5 creds)

[Control Plane 통합] anvyc 가 `role-based-ruleset` × `ccinspector` 와 함께 AI agent autopilot **control plane** 의 **L2 Environment layer** 로 정착. v0.13.0 직후 9 axis PR + 1 fix = **10 PR** 으로 3 axis (CP-1·4·5) 완결.

control plane SoT 위치: [role-based-ruleset/ROADMAP.md §4](https://github.com/16bitdo/role-based-ruleset/blob/main/ROADMAP.md) (사람 가독) + [metadata/control-plane-roadmap.yaml](https://github.com/16bitdo/role-based-ruleset/blob/main/metadata/control-plane-roadmap.yaml) (기계 가독) + [docs/control-plane-v1-recap.md](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/control-plane-v1-recap.md) (회고). 5축 (CP-1~CP-5) 전체 done, v1+v2 milestone closed.

### CP-1: 실행 audit / observability (v1 axis, anvyc primary)

Claude Code session transcript (`~/.claude*/projects/*/*.jsonl`) 의 read-only 집계 — autopilot 모드 사후 추적 가능.

- **`anvyc activity` CLI** ([#32](https://github.com/16bitdo/anvyc/pull/32)) — session 별 메타 + tool 호출 카운트 표/JSON 출력 (`--json` / `--limit`).
- **Collector module** (`core/activity.py`, [#31](https://github.com/16bitdo/anvyc/pull/31)) — 멀티계정 환경 (`.claude` / `.claude-edward` / `.claude-jklee`) session 묶음 처리.
- **MCP tools 노출** ([#33](https://github.com/16bitdo/anvyc/pull/33)) — `activity_summary` + `tool_call_stats` (총 7 tool) 로 외부 agent 가 직접 조회.

```bash
$ anvyc activity --limit 3
3 session(s) found  cwd=…  top tools: Bash=12 Read=8 Edit=5
```

### CP-4: 작업 회복 (snapshot / rollback) (v2 axis, anvyc primary)

autopilot 의 실수 (브랜치 30 파일 수정 등) 를 명시적 marker → restore 가능. **4-layer safety** (dry-run / confirm / auto pre-restore / tail capture).

- **`anvyc snapshot create [--label X]`** ([#34](https://github.com/16bitdo/anvyc/pull/34)) — `git stash + meta schema v1` (`schema_version: 1`, claude session id 포함). `.anvyc/snapshots/<id>/meta.json` + `refs/anvyc-snapshots/<id>` anchor.
- **`anvyc snapshot list` / `diff <id> [--against <other>]`** ([#35](https://github.com/16bitdo/anvyc/pull/35)) — read-only query. created_at 내림차순, 손상 entry silently skip.
- **`anvyc snapshot restore <id> [--force] [--yes]`** ([#36](https://github.com/16bitdo/anvyc/pull/36)) — destructive. 기본 dry-run, `--force` + confirm + **auto pre-restore snapshot** 자동 생성 + conflict 시 회복 채널 안내. DESIGN.md §35.7 (Restore 안전 절차 6단계) 신설.
- **fix: untracked 파일 capture** ([#40](https://github.com/16bitdo/anvyc/pull/40)) — `git stash create` 의 `-u` silent 무시 제한 회피 — `_capture_stash` 를 `git stash push -u` + 즉시 `pop --index` 4-step 으로 재작성. v2 cut-over 후 **라이브 시연** 에서 발견된 behavior gap 즉시 fix (회귀 테스트 2건 추가).

```bash
$ anvyc snapshot create --label before-refactor
snapshot created  id=20260525T120000Z-a1b2c3  branch:main  uncommitted:3

$ anvyc snapshot restore 20260525T120000Z-a1b2c3 --force --yes
restore plan ... auto pre-restore: yes (label=pre-restore-...)
restored  target=...
```

### CP-5: 자격 lifecycle (creds rotation) (v2 axis, anvyc primary)

GitHub PAT / AWS SSO / Claude OAuth 토큰의 만료 사전 감지 + 회전. **CP-3 scheduler 와 자연 시너지** (별 wire 작업 없이 doctor check 자동 합류).

- **`anvyc creds status`** ([#37](https://github.com/16bitdo/anvyc/pull/37)) — 3 kind detection (`aws_sso` from `~/.aws/sso/cache/*.json`, `github` from `~/.config/gh/hosts.yml` + 선택 gh probe, `claude_oauth` from `~/.claude*.json`) + `CredentialsReport` schema v1 + status (`valid`/`expiring`/`expired`/`unknown`) 분류.
- **doctor 의 `creds-expiry-within-7d` check** ([#38](https://github.com/16bitdo/anvyc/pull/38)) — 등록만으로 ccinspector 의 CP-3 scheduler 가 `anvyc doctor --strict --json` 호출 시 자동 포함 (L13 cross-axis 자동 합류 패턴). expired → `Severity.CRITICAL`, expiring → `Severity.WARNING`.
- **`anvyc creds rotate <kind> [--force]`** ([#39](https://github.com/16bitdo/anvyc/pull/39)) — destructive native re-auth 위임 (`aws sso login` / `gh auth refresh` / claude_oauth 는 사용자 수동 안내). CP-4 restore §35.7 패턴 미러 4-layer safety. token 본문 노출 회피 (stdout/stderr tail 2 KiB). DESIGN.md §36.8 (Rotate 안전 절차) 신설.

```bash
$ anvyc creds status --no-probe
4 credential(s) — expired=1 expiring=0 (threshold=7d)
  aws_sso       https://d-...../start     2026-05-10T15:13...  -15d (past)  expired
  ...

$ anvyc doctor --only creds-expiry-within-7d
critical — aws_sso 'https://d-...' expired
```

### DESIGN 갱신

- **§35** (Snapshot/Rollback) 신설 — 7 subsection (원칙 / schema v1 / 명령 contract / stash anchor / out-of-scope / 보안 / 안전 절차 §35.7)
- **§36** (Credentials Lifecycle) 신설 — 8 subsection (원칙 / schema v1 / 명령 contract / source detection / scheduler 자연 시너지 / out-of-scope / 보안 / 안전 절차 §36.8)

### 테스트

v0.13.0 대비 +66 hermetic assertion + 라이브 시연 검증:
- snapshot 33 (create 8 + 2 fix / list+diff 13 / restore 10) + creds 35 (status 15 + check 8 + rotate 12) = **68 신규**
- 라이브 시연: 4 demo / 17 케이스 / 1 behavior gap 발견 + fix

### Control Plane 자산 (외부 참조)

- 회고: [control-plane-v1-recap.md](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/control-plane-v1-recap.md) — v1 §1~§8 + v2 §9 (5/5 axis 완결 + 15 learnings 누적)
- 페어 secondary 작업: [rbr#56](https://github.com/16bitdo/role-based-ruleset/pull/56) (rule 18-git-codebase-sync, CP-4) + [rbr#58](https://github.com/16bitdo/role-based-ruleset/pull/58) (rule 26-secrets-1password, CP-5)
- ccinspector 측 CP-3 scheduler (`modules/scheduler/`): `anvyc doctor --strict --json` 을 일1회 호출 → 본 release 의 `creds-expiry-within-7d` check 가 자동 합류 (cross-axis 시너지 L13)


## v0.13.0 — 2026-05-22 (shell prompt 통합 + 개발 환경/CI 정비)

[shell prompt 통합] anvyc 의 per-project 계정 라우팅(AWS/GitHub/Claude/Pulumi)을
shell prompt 에 바로 노출하고, prompt 도구(starship/powerlevel10k) 의 설정
파일도 백업 대상에 추가한다.

### `anvyc prompt` — 계정 라우팅 세그먼트 명령

현재 디렉터리의 계정 라우팅을 shell prompt 용 한 줄로 출력한다 — `project show`
를 매번 실행하지 않고도 prompt 에 상시 표시.

- 설정된 필드만 공백 구분 `key:value` 출력 (`aws` / `gh` / `claude` / `pulumi`),
  없으면 빈 출력. `--json` 보조.
- prompt 컨텍스트라 **어떤 오류도 셸을 깨지 않는다** — 빈 출력 + exit 0.
- starship custom command / powerlevel10k 세그먼트 연동: `docs/shell-prompt.md`.

```bash
$ anvyc prompt
aws:company-dev gh:16bitdo claude:edward
```

### `shell_prompt` 어댑터 — starship/p10k 설정 백업

starship(`~/.config/starship.toml`)·powerlevel10k(`~/.p10k.zsh`) 의 prompt
설정 파일을 백업/동기화 대상에 추가한다 (어댑터 9 → 10). 두 도구를 단일
`shell_prompt` 어댑터로 묶어 존재하는 파일만 collect 한다 (`enabled: true`).

### 개발 환경 / CI 정비

- **dev wrapper PYTHONPATH 전환** — `~/.local/bin/anvyc` dev wrapper 가 editable
  `.pth` 대신 `PYTHONPATH` 로 `src/` 를 주입하고 `python -m anvyc` 로 실행 →
  macOS UF_HIDDEN trap 을 근본 회피 (chflags self-heal 제거). `src/anvyc/__main__.py`
  진입점 추가.
- **`dev-install.sh` 인터프리터 탐지 보강** — `python3.13` bare 명령 부재 시
  `uv python find 3.13` 으로 폴백해 의도치 않은 Python 버전 다운그레이드 방지.
- **CI macOS 과금 ~65% 절감** — lint·test matrix 를 `ubuntu-latest` 로 이전하고
  macOS 는 test 3.13 한 잡만 유지. mypy `platform = "darwin"` 고정으로 ubuntu
  에서도 `os.chflags` 등 macOS-only API 를 정상 인식.

---

## v0.12.0 — 2026-05-22 (per-project Claude/Pulumi 계정 라우팅)

[account-routing 확장 — anvyc 의 per-project 계정 라우팅 인식을 Claude Code 와
Pulumi 로 확장] anvyc 은 AWS(`AWS_PROFILE`)·GitHub(`GH_CONFIG_DIR`) 의
per-project 계정 라우팅을 인식·검증해 왔다. v0.12.0 은 같은 모델을 Claude Code
와 Pulumi 로 확장한다 (계획: `docs/improvement-plan-account-routing.md`).

> v0.11.0 cycle 변경분(scan-root 프로젝트 루트 SoT 단일화 `~/dev` 이전 +
> per-project gh-account routing 인식)도 본 릴리스에 함께 포함된다 — v0.11.0
> 은 별도 태깅 없이 v0.12.0 으로 통합 배포한다. 상세는 아래 v0.11.0 섹션 참조.

### Claude Code 계정 라우팅 (Phase 1)

`.envrc` 의 `export CLAUDE_CONFIG_DIR="$HOME/.claude-<account>"` 는 Claude Code
가 네이티브로 읽는 env var (`GH_CONFIG_DIR` 의 직접 analog) 다. anvyc 이 이
라우팅을 인식·검증한다.

- `ProjectInfo.claude_account` 필드 — `project show` / `project list` / MCP JSON
  에 추가. `CLAUDE_CONFIG_DIR` basename 의 `.claude-` prefix 제거로 도출
  (`$HOME/.claude-edward` → `edward`).
- 신규 global doctor check `project-claude-account-mapping` — `project_roots`
  아래 `.envrc` 의 `CLAUDE_CONFIG_DIR` 가 가리키는 config 디렉터리 존재 검증.
- 신규 per-cwd check `claude_account_dir_exists` (`anvyc project doctor`).
- `multi-account-detected` 가 `~/.claude-*` 계정별 디렉터리도 감지.

gh 와 달리 cross-check 할 remote 가 없어 검증은 디렉터리 존재 확인(1-way)이다.

```bash
$ anvyc project show --json | jq .claude_account
"edward"
```

### Pulumi backend 라우팅 (Phase 2)

Pulumi 의 "계정"은 단일 username 이 아니라 **backend**(state 저장 위치 + org)
다. `Pulumi.yaml` 의 `backend.url`(1순위 SoT)과 `.envrc` 의 `PULUMI_BACKEND_URL`
(env override) 정합성을 검증한다.

- `ProjectInfo.pulumi.backend` 필드 — `Pulumi.yaml` 의 `backend.url` 노출.
  `backend` 키 부재(Pulumi Cloud default)는 추적하지 않는다.
- 신규 global doctor check `project-pulumi-backend-mapping`.
- 신규 per-cwd check `pulumi_backend_routing` — 2-way 정합성 (URL 정규화 후 비교).
- `PULUMI_ACCESS_TOKEN` 은 secret → `dev_env` 에서 자동 마스킹 (값 추적 안 함).

### Cursor — 라우팅 제외 결정

Cursor 멀티 계정은 `cursor --user-data-dir=` 실행 플래그뿐 — `.envrc` env var
신호가 없어 anvyc 의 라우팅 패턴이 성립하지 않는다. account-routing 계획 §3.3
에서 옵션 A(제외)로 확정.

### doctor check 확장

- global `anvyc doctor` — 12 → **14 check** (`project-claude-account-mapping`,
  `project-pulumi-backend-mapping` 추가).
- `anvyc project doctor` — 6 → **8 check** (`claude_account_dir_exists`,
  `pulumi_backend_routing` 추가).

---

## v0.11.0 — 2026-05-20 (per-project gh-account routing 인식)

[Phase 2 — anvyc 의 기존 per-project AWS profile 기능을 GitHub 으로 미러링]
여러 GitHub 계정 (`16bitdo` 개인 / `secondary` org 봇) 을 쓰는 환경에서
`gh` CLI 의 single global active account 가 "whack-a-mole" false warning 을
유발한다. 해결책으로 project 별 `.envrc` 가
`export GH_CONFIG_DIR="$HOME/.config/gh-<account>"` 를 export 해 direnv 로
계정을 라우팅한다. v0.11.0 은 anvyc 가 이 라우팅을 인식하도록 확장한다.

### `ProjectInfo.gh_account` 필드 (P1)

`anvyc project show` / `project list` / MCP `project_show` 의 JSON 에
`gh_account` 키 추가. `.envrc` 의 `GH_CONFIG_DIR` 경로 값에서 basename 의
`gh-` prefix 를 제거해 도출 (`$HOME/.config/gh-16bitdo` → `16bitdo`).
`AWS_PROFILE` 과 달리 경로 값이라 basename 추출 한 단계를 더 거친다.
`GH_CONFIG_DIR` 부재 / basename 이 `gh-<name>` 형식 아님 → `null`.

```bash
$ anvyc project show --path ~/Documents/proj --json
{
  "path": "/Users/edward/Documents/proj",
  "aws_profile": "company-dev",
  "gh_account": "16bitdo",
  ...
}
```

### 신규 global doctor check: `project-gh-account-mapping` (P2)

`~/Documents/**/.git` 의 GitHub `origin` 이 ssh alias (`github.com-<alias>`)
를 쓰는 project 가, 같은 디렉터리 `.envrc` 의 `GH_CONFIG_DIR` 로 일치하는
gh 계정 라우팅을 선언했는지 검증 (`project-aws-profile-mapping` 의 GitHub
아날로그).

- routing OK (gh 계정 == ssh alias) → INFO 1건 (summary)
- `.envrc` 에 `GH_CONFIG_DIR` 없음 → project 마다 WARNING
- gh 계정 ≠ ssh alias → mismatch 마다 WARNING
- ssh alias 쓰는 GitHub origin 없음 → 결과 0건 (silent)

```bash
anvyc doctor --only project-gh-account-mapping
```

### `project doctor` 신규 per-cwd check: `gh_account_routing` (P3)

cwd 의 origin ssh alias ↔ `.envrc` `GH_CONFIG_DIR` 정합성 검증
(`github_remote_parseable` 와 동일 패턴). `project doctor` 가 5 check →
6 check 로 확장. plain `github.com` origin (ssh alias 없음) 은 silent skip.

### 신규 / 수정 파일

- `src/anvyc/checks/project_gh_account.py` (신규)
- `src/anvyc/core/project_info.py` (`gh_account` 필드 + `_derive_gh_account`)
- `src/anvyc/core/doctor.py` (`_REGISTRY` 등록)
- `src/anvyc/core/project_doctor.py` (`_check_gh_account_routing`)
- `src/anvyc/cli.py` (project show/list 의 `gh_account` 렌더링)
- `src/anvyc/mcp/server.py` (project_doctor docstring 5→6 check)
- `tests/unit/test_project_gh_account.py` (신규, 9 case)
- `tests/integration/test_project_show.py` / `test_project_doctor.py` /
  `test_project_list.py` / `test_mcp_server.py` (`gh_account` schema 반영)
- `DESIGN.md §27 / §32 / §33`, `README.md §11.6`, `CONTEXT.md`
- `pyproject.toml`, `src/anvyc/__init__.py` — version 0.10.0 → 0.11.0

### Backward compatibility

- JSON schema 는 key 추가만 (`gh_account`) — minor 변경, backward-compat
  (DESIGN §32.7 정책 그대로).
- 신규 check 추가 — 기존 doctor / project doctor check 동작 변경 없음.
- `GH_CONFIG_DIR` 미사용 환경은 모든 신규 check 가 silent (결과 0건).

### 통계

- pytest 기존 195 + 신규 14 (unit 9 + project doctor 4 + show 1) = 209
- ruff check / mypy (src + tests) green
- uv build → `anvyc-0.11.0-py3-none-any.whl` 정상

---

## v0.10.0 — 2026-05-19 (MCP tool naming cleanup — breaking)

[follow-up of v0.9.0 회귀 테스트 — `mcp__anvyc__anvyc_*` 의 redundant prefix
관찰됨. tool 이름에서 `anvyc_` prefix 제거]

### Breaking change — MCP tool 이름

| v0.9.0 | v0.10.0 |
|---|---|
| `anvyc_project_show` | `project_show` |
| `anvyc_project_list` | `project_list` |
| `anvyc_project_doctor` | `project_doctor` |
| `anvyc_doctor` | `doctor` |
| `anvyc_tools_list` | `tools_list` |

agent 가 호출하는 실제 이름은 server name 까지 포함되어 `mcp__anvyc__*`
→ v0.10.0 에서는 `mcp__anvyc__project_show` (이전: `mcp__anvyc__anvyc_project_show`).

### Migration

- agent / IDE 가 tool 이름을 직접 하드코딩한 경우만 영향.
- Claude Code / Cursor 의 mcp.json 자체는 변경 불필요 (server name `anvyc` 유지).
- v0.10.0 wheel 재설치만으로 새 이름 자동 노출 — agent 가 다시 tool 목록 fetch.
- 검증: `printf '...initialize+tools/list...' | anvyc serve --mcp` →
  `tools[].name` 이 `project_show` 등 5개.

### Schema 안정성 정정

DESIGN §34.9 — v0.9.0 첫 MCP release 의 tool 이름은 cleanup deferred 였음.
v0.10.0 부터 5 tool 이름 + input/output schema 는 **public API**. minor 변경
(key 추가) 만 backward-compat, breaking 은 v1.0+ 까지 보류.

### 신규 / 수정 파일

- `src/anvyc/mcp/server.py` — 5 tool name + dispatch 분기 + docstring
- `tests/integration/test_mcp_server.py` — _dispatch 인자
- `docs/mcp-integration.md`, `DESIGN.md §34`, `docs/improvement-plan-ai-agent.md`
- `pyproject.toml`, `src/anvyc/__init__.py` — version 0.9.0 → 0.10.0

### Backward compatibility

- 기존 14 CLI 명령 동작 변경 없음.
- 이전 v0.9.0 tool 이름은 **invalid** — `_dispatch("anvyc_project_show", ...)` 호출 시
  `ValueError: unknown tool`.

### 통계

- 1 commit (server + 5 docs + version + RELEASE_NOTES)
- pytest 영향 없음 (테스트 _dispatch 인자도 새 이름)

---

## v0.9.0 — 2026-05-19 (MCP server — AI agent direct integration)

[Wave 9 of docs/improvement-plan-ai-agent.md §7.3 — AI Agent Integration]
Claude Code / Cursor 가 anvyc 의 5 read-only tool 을 stdio Model Context
Protocol 로 직접 호출. subprocess + stdout parse 우회.

### 신규 명령: `anvyc serve --mcp` (P6)

```bash
# 설치 (optional extra):
uv tool install --upgrade 'anvyc[mcp]'

# Claude Code (~/.claude/mcp.json) 또는 Cursor (~/.cursor/mcp.json):
{
  "mcpServers": {
    "anvyc": {"command": "anvyc", "args": ["serve", "--mcp"]}
  }
}
```

### 노출 tool (5 read-only, D21)

| tool | 매핑 | 출력 |
|---|---|---|
| `project_show` | `anvyc project show` | ProjectInfo (DESIGN §32) |
| `project_list` | `anvyc project list` | array of ProjectInfo |
| `project_doctor` | `anvyc project doctor` | `{path, results}` |
| `doctor` | `anvyc doctor --json` | `{results}` (12 check) |
| `tools_list` | `anvyc tools list --json` | array of tool entries |

write 영역 (`backup`/`apply`/`restore`) 은 의도적 미포함 — agent 가
destructive 실행 못 함.

### 의존성 격리 — `[mcp]` optional extra (D20)

| 설치 | 의존 |
|---|---|
| core anvyc (default) | typer / rich / pathspec / pyyaml (4) — 변경 없음 |
| `anvyc[mcp]` | core + mcp + (pydantic, anyio, httpx, jsonschema, ...) |

- Homebrew Formula 영향 **없음** (core 만 build)
- MCP 사용자는 별도 `uv tool install 'anvyc[mcp]'`
- mcp 미설치 환경에서 `anvyc serve --mcp` → clean error + install 안내

### 보안 정책

- D11c redaction default — secret 패턴 매칭 → `***REDACTED***`
- `op://` 1Password reference 는 placeholder signal → redaction 면제
- `reveal_secrets=true` 명시 시만 raw 값 노출 (agent/log 유출 주의)
- raw secret 은 `project_doctor` 검증 시 메모리에만, message 에는 KEY 명만

### 신규 / 수정 파일

- `src/anvyc/mcp/__init__.py` (신규)
- `src/anvyc/mcp/server.py` (신규, 5 tool dispatch + stdio entry)
- `src/anvyc/cli.py` — `@app.command("serve")` 신규
- `pyproject.toml` — `[project.optional-dependencies] mcp` 추가
- `tests/integration/test_mcp_server.py` (9 case, importorskip)
- `docs/mcp-integration.md` (신규, Claude/Cursor 설정 + 사용 예 + 트러블슈팅)
- `DESIGN.md §34` (신규, MCP architecture)
- `README.md §5.5` (MCP install) + `§8` (serve 명령) + `§13` 로드맵

### Backward compatibility

- 신규 명령만 추가 (`anvyc serve`), 기존 14 명령 동작 변경 없음
- `[mcp]` extra 미설치 환경은 영향 없음 (default install 그대로)
- `ProjectInfo` / `DoctorReport` schema 재사용

### Schema 안정성

DESIGN §34.9 — v0.9.0 부터 5 tool 의 input/output schema 는 **public API**.
minor 변경 (key 추가) 만 backward-compat, breaking 은 v1.0+.

### 통계

- 4 commits (mcp extra + server + tests + docs/version-bump)
- pytest 기존 ~176 + 신규 9 = ~185 (mcp 설치 환경, 미설치 시 skip)
- core wheel `anvyc-0.9.0-py3-none-any.whl` size 변동 작음 (mcp 미포함)

---

## v0.8.1 — 2026-05-19 (Cross-Project + Audit)

[Wave 8 of docs/improvement-plan-ai-agent.md §7.2 — Cross-Project + Audit]
Wave 7 의 `anvyc project show` (single project) 를 fan-out + audit 로 확장.

### 신규 명령

| 명령 | 동작 |
|---|---|
| `anvyc project list [--root R...] [--json]` | 입력 root 아래 모든 project 의 connection matrix |
| `anvyc project doctor [--path P] [--json] [--strict]` | cwd connection 정합성 5 check |

### `anvyc project list` (P2)

```bash
$ anvyc project list --json | jq 'map(select(.pulumi != null)) | length'
4    # ~/Documents/ 의 Pulumi project 수

$ anvyc project list --json | jq 'map({path, aws_profile, github: .github[0].owner})'
[...]
```

- discovery rule (D12): `.git` 또는 `Pulumi.yaml` marker 보유 디렉터리 (depth ≤ 2)
- 각 entry 는 `anvyc project show` 와 **동일 schema** (DESIGN §32 재사용)
- D11c redaction 동일 적용 — `--reveal-secrets` opt-in
- `--root` 반복 가능 (default: `~/Documents`)

### `anvyc project doctor` (P7)

```bash
$ anvyc project doctor --json
{
  "path": "/.../proj",
  "results": [
    {"check_name": "aws_profile_defined", "severity": "info", ...},
    {"check_name": "github_remote_parseable", "severity": "info", ...},
    {"check_name": "pulumi_stacks_valid", "severity": "info", ...},
    {"check_name": "dev_env_secret_safety", "severity": "info", ...},
    {"check_name": "tool_versions_installed", "severity": "info", ...}
  ]
}
```

5 check (D14):

| check | trigger | issue severity |
|---|---|---|
| `aws_profile_defined` | `.envrc` AWS_PROFILE 있을 때만 | WARNING |
| `github_remote_parseable` | `.git/config` 있을 때만 | (parse 가능한 것만 INFO) |
| `pulumi_stacks_valid` | `Pulumi.yaml` 있을 때만 | WARNING |
| `dev_env_secret_safety` | `.envrc` 의 export 있을 때만 | **CRITICAL** (raw secret) |
| `tool_versions_installed` | `.python-version`/`.nvmrc`/`.tool-versions` 있을 때만 | WARNING |

- source 가 없으면 silent skip (bare path → `{"results": []}`)
- `--strict` 시 warning 이상 발견 → exit 1
- 기존 `anvyc doctor` (global) 와 별개 — `project doctor` 는 path-aware

### DESIGN §33 신규 (schema 정식화)

`project list` + `project doctor` 의 외부 호환 보장. `project list` 는 §32
ProjectInfo schema 재사용, `project doctor` 는 doctor `--json` 의 result entry
와 동일 6-field 형식.

### 신규 / 수정 파일

- `src/anvyc/core/project_discovery.py` (신규) — discover_projects
- `src/anvyc/core/project_doctor.py` (신규) — 5 check + ProjectDoctorReport
- `src/anvyc/cli.py` — project_app:list + project_app:doctor
- `tests/unit/test_project_discovery.py` (8 case)
- `tests/integration/test_project_list.py` (5 case)
- `tests/integration/test_project_doctor.py` (8 case)
- `DESIGN.md §33` 신규
- `README.md §8` 명령어 + `§13` 로드맵

### 안전 가드

- `project doctor` 가 raw secret 메모리 사용 — message 에는 KEY 명만 (raw 미포함)
- discovery 가 marker 발견 디렉터리 하위는 더 안 들어감 (성능)
- symlink 디렉터리는 alias 가능성으로 자동 skip
- bare path / missing source → silent (noise 없음)

### Backward compatibility

- 신규 명령만 추가 (`project list`, `project doctor`)
- 기존 13 명령 (project show 포함) 동작 변경 없음
- `ProjectInfo` schema (DESIGN §32) 재사용 — `project list` 와 `project show` 가 동일 schema

### 통계

- 3 commits (project list + project doctor + docs/version-bump)
- pytest 기존 ~155 + 신규 21 (8 + 5 + 8) = ~176
- uv build → `anvyc-0.8.1-py3-none-any.whl` 정상

---

## v0.8.0 — 2026-05-19 (Project-Centric View — AI agent integration)

[Wave 7 of docs/improvement-plan-ai-agent.md §7.1 — Project-Centric View]
AI agent (Claude Code / Cursor / ChatGPT) 가 cwd 의 모든 connection 정보
(AWS profile / GitHub remote / Pulumi project / dev_env / tool versions) 를
단일 JSON 으로 받기 위한 통합 view + machine-readable 확장.

### 신규 명령: `anvyc project show` (P1)

```bash
$ anvyc project show --path ~/Documents/proj --json
{
  "path": "/Users/edward/Documents/proj",
  "aws_profile": "company-dev",
  "github": [
    {
      "name": "origin",
      "url": "git@github.com-16bitdo:16bitdo/proj.git",
      "host": "github.com-16bitdo",
      "owner": "16bitdo",
      "repo": "proj",
      "ssh_alias": "16bitdo",
      "protocol": "ssh"
    }
  ],
  "pulumi": {
    "project_name": "proj",
    "runtime": "python",
    "stacks": ["dev", "prd"],
    "yaml_path": "/Users/edward/Documents/proj/Pulumi.yaml"
  },
  "dev_env": {
    "AWS_PROFILE": "company-dev",
    "NODE_ENV": "development",
    "GITHUB_TOKEN": "***REDACTED***"
  },
  "tool_versions": {"python": "3.13", "node": "20.10.0"}
}
```

- `--path P` 로 임의 path 지정 (default: cwd)
- `--json` 으로 machine-readable JSON 출력 (없으면 human rendering)
- **D11c**: dev_env 의 값에 anvyc `security.patterns.PATTERNS` 매칭 시
  자동 `***REDACTED***` 마스킹
- `op://` 1Password reference 는 placeholder signal 이므로 redaction 면제
- `--reveal-secrets` 명시 시 raw 값 노출 (agent/log 유출 주의)

### 신규 utility (P3 + P4)

| 모듈 | 동작 |
|---|---|
| `src/anvyc/utils/pulumi_project.py` | `<project>/Pulumi.yaml` + `Pulumi.<stack>.yaml` 추출 (name/runtime/stacks) |
| `src/anvyc/utils/git_remote.py` | `<project>/.git/config` 의 [remote "X"] 파싱 (SSH/HTTPS URL → owner/repo/ssh_alias) |
| `src/anvyc/core/project_info.py` | 위 둘 + dev_env + tool_versions 통합 + redaction |

backup 영역과 분리 — read-only utility, `anvyc project show` 의 backend.

### 신규 JSON output (P5)

- `anvyc tools list --json` — `[{tool, enabled, detected, files, secrets}]` 9 row
- `anvyc config show --effective --json` — AnvycConfig dataclass dict (default 채워짐)

기존 raw text 출력 backward compat — `--json` 미지정 시 동일.

### DESIGN.md §32 신규 (schema 정식화)

`anvyc project show --json` 의 외부 호환 보장. v0.8.0 부터 schema 는
**public API** — minor 변경 (key 추가) 만 허용, breaking 변경은 v1.0+.

### 신규 / 수정 파일

- `src/anvyc/utils/pulumi_project.py` (신규)
- `src/anvyc/utils/git_remote.py` (신규)
- `src/anvyc/core/project_info.py` (신규)
- `src/anvyc/cli.py` (project_app subcommand + tools_list/config_show --json)
- `tests/unit/test_pulumi_project_util.py` (8 case)
- `tests/unit/test_git_remote_util.py` (8 case)
- `tests/integration/test_project_show.py` (7 case)
- `tests/integration/test_tools_list_json.py` (2 case)
- `tests/integration/test_config_show_json.py` (2 case)
- `DESIGN.md §32` 신규
- `README.md §8` (명령어 요약) + `§13` 로드맵
- `docs/improvement-plan-ai-agent.md §12` Q1=완료, Q3=v0.8.0 정식화

### Backward compatibility

- 신규 명령만 추가 (`project show`), 기존 9 명령 동작 변경 없음
- `tools list` / `config show` 는 raw 출력 그대로, `--json` 만 신규 옵션
- doctor `--json` schema 와 별개 (각각 독립 정식화)

### 통계

- 3 commits (impl utilities + project show + JSON outputs + docs/version-bump)
- pytest 기존 ~128 + 신규 ~27 (8+8+7+2+2) = ~155
- uv build → `anvyc-0.8.0-py3-none-any.whl` 정상

---

## v0.7.2 — 2026-05-19 (dependency cleanup: pydantic removed)

### 배경

`brew install anvyc` 가 `pydantic-core 2.16.3` 의 Rust extension 빌드에서
실패. Homebrew Python virtualenv 의 install 단계는:
- `pip install --no-binary :all:` (wheel 금지)
- 빌드 단계 네트워크 sandbox

→ `pydantic-core` 의 build 의존성 `maturin` 다운로드 실패.

### 발견

`grep` 결과: anvyc 코드 어디에서도 `pydantic` 을 import 하지 않음.
v0.1.0 의 초기 schema 계획 때 declare 됐지만 실제 구현은 `dataclass` 로 진행
되어 잔존 의존성 (`pyproject.toml:dependencies` 만).

### 변경

- `pyproject.toml`: `pydantic>=2.6` dependency 제거
- Homebrew Formula: `annotated-types`, `pydantic`, `pydantic-core` resource
  3개 제거 (13 → 10 resources)

### Backward compatibility

- 코드/CLI 동작 변경 없음 (pydantic 미사용이라 영향 zero)
- 기존 `pip install anvyc` / `uv tool install` 도 그대로 작동 (의존성 감소만)

### 통계

- 1 commit (impl: pyproject + version + RELEASE_NOTES, Formula 는 별도 commit)
- pytest 영향 없음 (test suite 가 pydantic 미사용)

---

## v0.7.1 — 2026-05-19 (onboarding wizard + install one-liner)

[Wave 6 of docs/improvement-plan-ux-review.md §8.3 — onboarding]
새 사용자가 9 도구 설정을 한 번에 끝낼 수 있는 대화형 wizard + 외부 설치
스크립트.

### 신규 명령: `anvyc init --interactive` (alias `-i`)

```
$ anvyc init -i
anvyc init wizard — 9개 도구 설정

Enable shell? [Y/n]:
  files for shell [~/.zshrc, ~/.zprofile]:
Enable git? [Y/n]:
  files for git [~/.gitconfig, ~/.gitignore_global]:
...
Enable dev_env? [y/N]:           # ← default disabled (안전)
  project_roots [~/Documents]:
  patterns [.envrc, .tool-versions, .python-version, .nvmrc]:

preview:
  version: 1
  storage: { root: .anvyc, keep_backups: 5 }
  tools: { ... }

Write to .anvyc/anvyc.yaml? [Y/n]:
✓ wrote .anvyc/anvyc.yaml
```

- 9 도구 (8 default-enabled + dev_env default-disabled) prompt
- file-based adapter (shell/git/aws/gh/pulumi) 는 file path 입력
- dev_env 는 project_roots + patterns 입력
- cursor/claude/iterm2 는 default 설정 (path prompt skip)
- yaml preview 후 최종 확인 → 작성
- `--from-git` 과 mutual exclusion (exit 1)

### 신규 파일: `install.sh` (one-liner installer)

```bash
curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh | bash
```

- `set -euo pipefail` strict mode
- GitHub Release wheel + `SHA256SUMS` 자동 검증
- `uv tool` 또는 `pipx` 자동 감지 (없으면 명시 안내 + exit 1)
- env 옵션:
  - `ANVYC_VERSION=v0.7.1` (default: latest)
  - `ANVYC_METHOD=uv|pipx|auto` (default: auto)
- macOS (`shasum`) + Linux (`sha256sum`) 양쪽 호환
- shellcheck 통과

> **현재 repo 는 private 이라 raw URL 이 404.** Z4 (PUBLIC 전환) follow-up 후 활성화.

### 신규 / 수정 파일

- `src/anvyc/cli.py` — init 함수에 `--interactive` 옵션 + `_run_init_wizard()` 헬퍼
- `install.sh` — bash strict mode one-liner installer
- `tests/integration/test_init_interactive.py` (4 case)
- `tests/test_install_script.py` (6 case — syntax / strict / verify / shellcheck)

### 안전 가드

- wizard 가 기존 anvyc.yaml 위에 작성 시도 → fail-fast (`--force` 필요)
- `--interactive --from-git` 동시 지정 → exit 1 (의미 충돌)
- install.sh SHA256 mismatch → exit 1 + 명시 메시지
- install.sh trap 으로 temp dir cleanup (실패 경로 포함)
- install.sh 가 uv/pipx 둘 다 없으면 `pip install <wheel>` 안내 후 exit 1

### Backward compatibility

- `anvyc init` (no `--interactive`) 동작 v0.7.0 그대로
- install.sh 는 본 repo 안의 새 파일 (다른 코드 영향 없음)

### 통계

- 3 commits (wizard + install.sh + docs/version-bump)
- pytest 118 → 128 (+10: wizard 4 + install 6)
- uv build → `anvyc-0.7.1-py3-none-any.whl` 정상

---

## v0.7.0 — 2026-05-19 (dev_env adapter + AWS profile cleanup)

[Wave 5 of docs/improvement-plan-ux-review.md §8.3 — dev_env 묶음]
v0.6.0 부터 README §11 에 안내한 multi-AWS-profile 워크플로 (direnv + .envrc)
를 실제 코드로 묶음. 사용자 환경 (direnv 2.37.1 설치) 에서 즉시 가치.

### 신규 어댑터: `dev_env` (8 → 9 adapter)

`~/Documents/**` 같은 project root 아래에서 다음 패턴 추적:

| 패턴 | 도구 |
|---|---|
| `.envrc` | direnv (AWS_PROFILE / NODE_ENV / API_URL 등) |
| `.tool-versions` | asdf |
| `.python-version` | pyenv |
| `.nvmrc` | nvm |

기본 설정 (anvyc.yaml):

```yaml
tools:
  dev_env:
    enabled: false              # 안전 default — 사용자가 명시 enable
    project_roots:
      - "~/Documents"
    patterns:
      - ".envrc"
      - ".tool-versions"
      - ".python-version"
      - ".nvmrc"
    exclude:
      - "**/node_modules/**"
      - "**/.venv/**"
      - "**/.git/**"
```

- depth ≤ 3 (project root 기준 — 성능 보호)
- exclude pathspec (`gitignore` 형식)
- secret 정책: 기존 scanner 가 `.envrc` 안의 raw token 차단

사용 예:

```bash
$ anvyc backup --only dev_env
backup .anvyc/backups/20260519-140000
  dev_env  ~/Documents/proj-a/.envrc    a3f5b2c1...
  dev_env  ~/Documents/proj-b/.envrc    9d8e7f6a...
  dev_env  ~/Documents/proj-c/.tool-versions  4b2a1c8d...
```

### 신규 doctor check: `unused-aws-profiles` (10 → 11 check)

`~/.aws/config` 에 정의됐지만 `~/Documents/**/.envrc` 의 `AWS_PROFILE` 값으로
사용되지 않는 profile 을 INFO 로 안내 (cleanup 용, 강제력 없음).

`project-aws-profile-mapping` (v0.6.1) 의 reverse — A1 은 .envrc → config
검증, 본 check 는 config → .envrc 사용량 검증.

```bash
$ anvyc doctor --only unused-aws-profiles
info — 11 AWS profile(s) defined but not referenced in any .envrc:
       pulumi-dev, company-agency, company-audit, company-demo, ws-dev, ... (+6)
```

`[default]` profile 은 fallback 으로 가정되어 unused 판정에서 제외.

### 신규 / 수정 파일

- `src/anvyc/adapters/dev_env.py` — DevEnvAdapter
- `src/anvyc/checks/unused_aws_profiles.py` — UnusedAwsProfilesCheck
- `src/anvyc/core/backup.py` — ADAPTERS 등록 + `_select_adapters` dev_env 분기
- `src/anvyc/core/doctor.py` — _REGISTRY 등록
- `src/anvyc/templates.py` — dev_env 기본 yaml section (disabled by default)
- `tests/unit/test_dev_env_adapter.py` (7 case)
- `tests/integration/test_dev_env_backup.py` (2 case)
- `tests/unit/test_unused_aws_profiles.py` (5 case)
- README §4 (지원 도구 9), §13 로드맵

### Backward compatibility

- 신규 dev_env adapter 는 default `enabled: false` — 자동으로 사용자의 ~/Documents 를 스캔하지 않음 (안전)
- unused-aws-profiles check 는 다른 check 처럼 `--only` / `--skip` 으로 선택 가능
- 기존 어댑터 / check 동작 변경 없음

### 통계

- 2 commits (impl + docs/version-bump)
- pytest 104 → 118 (+14: dev_env 9 + unused-aws 5)
- adapters: 8 → 9
- doctor checks: 10 → 11
- uv build → `anvyc-0.7.0-py3-none-any.whl` 정상

---

## v0.6.4 — 2026-05-19 (host overlay)

[Wave 4 of docs/improvement-plan-ux-review.md §8.2 — multi-host overlay]
머신마다 다른 도구 enabled/files 설정을 별도 yaml 분기 없이 적용.

### 신규 동작

`.anvyc/anvyc.yaml` (base) 위에 같은 디렉터리의 `anvyc.<hostname>.yaml`
overlay 가 존재하면 자동 deep-merge:

| 타입 | 동작 |
|---|---|
| dict | recursive deep merge (overlay 우선) |
| list | overlay 가 base 대체 (concat 아님 — 안전성/명시성) |
| scalar | overlay 우선 |

- hostname source: `socket.gethostname().split(".")[0]` (FQDN 안전)
  - 예: `host-a.local` → `anvyc.host-a.yaml`
- `ANVYC_HOSTNAME` env override (테스트/머신 이동 시)

### 사용 예

```yaml
# .anvyc/anvyc.yaml (모든 머신 공통)
tools:
  shell:
    enabled: true
    files: ["~/.zshrc"]
  git:
    enabled: true
```

```yaml
# .anvyc/anvyc.macOS-A.yaml (macOS-A 머신 한정)
tools:
  git:
    enabled: false
```

merge 결과 확인:

```bash
anvyc config show --effective    # overlay 반영된 effective view
anvyc tools list                 # git 의 enabled 컬럼이 ✗
```

### 신규 / 수정 파일

- `src/anvyc/core/config.py` — `_hostname_short`, `_deep_merge`, `_resolve_overlay` 추가, `load_anvyc_config` 확장, `AnvycConfig.overlay_source` 신규 필드
- `tests/unit/test_config_overlay.py` — 9 case (3 deep_merge unit + 6 integration)
- README §12 신규 (host overlay 가이드)

### Backward compatibility

- overlay 부재 시 동작 v0.6.3 와 동일
- `AnvycConfig.overlay_source` 는 신규 optional 필드 (additive)
- 기존 yaml 형식 변경 없음

### 안전 가드

- list overlay 가 concat 이 아니라 대체 (사용자가 의도 명확히 표시 필요)
- overlay yaml 파싱 실패 시 graceful skip (`_read_yaml` 의 fallback)
- overlay 만 존재 (base 없음) 시 silent fail (기존 behavior — base 가 source 결정)
- secret_scan 정책은 merged 결과에 그대로 적용 (overlay 안의 secret 도 동일 차단)

### 통계

- 2 commits (impl + docs/version-bump)
- pytest 104 passed (기존 95 + 신규 9)
- uv build → `anvyc-0.6.4-py3-none-any.whl` 정상

---

## v0.6.3 — 2026-05-19 (Config UX 묶음)

[Wave 3 of docs/improvement-plan-ux-review.md §8.2 — Config UX 묶음]
chezmoi 의 `edit-config` / `managed` 와 대등한 일상 워크플로 + 모든 *Blocked
예외의 사용자 facing 메시지를 영어로 표준화.

### 새 명령

| 명령 | 동작 |
|---|---|
| `anvyc config edit` | `$EDITOR` 로 anvyc.yaml 편집, 종료 후 schema 검증. 편집 전 자동 `.bak.<ts>` 백업. invalid yaml 시 원본 복구 + exit 1. |
| `anvyc config show` | raw anvyc.yaml 출력 (사용자 코멘트 보존) |
| `anvyc config show --effective` | default 값 적용된 effective view (dataclass dump) |
| `anvyc tools list` | 8 도구의 enabled / detected / files / secrets count + 미지원 도구 안내 |

### 사용 예

```bash
$ EDITOR=vim anvyc config edit
# (vim 종료 후 schema 검증)
ok schema 검증 통과 (.anvyc/anvyc.yaml)
backup: .anvyc/anvyc.yaml.bak.20260519-121530

$ anvyc config show --effective | head -10
storage:
  root: .anvyc
  keep_backups: 5
  keep_local_backups: 5
security:
  secret_scan: true
  block_on_secret: true
  ...

$ anvyc tools list
┏━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━┓
┃ tool   ┃ enabled ┃ detected ┃ files ┃ secrets ┃
┡━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━┩
│ shell  │ ✓       │ ✓        │     2 │       0 │
│ git    │ ✓       │ ✓        │     2 │       0 │
...
└────────┴─────────┴──────────┴───────┴─────────┘
미지원 (v0.7+ 계획): vscode, helix, neovim
```

### 에러 메시지 표준화 — 영어 (E6 결정)

`BackupBlocked` / `ApplyBlocked` 등 secret-scan 차단 시점의 사용자 메시지를
`src/anvyc/utils/errors.py:print_blocked_error()` 헬퍼로 통일:

```
backup blocked: secret scan rejected the operation
  • a critical secret was found at ~/.aws/credentials
  • a high-severity finding remains
Next steps:
  - anvyc doctor
  - anvyc scan-secrets <path>  # inspect a specific path
  - --force allowed for medium-severity findings (critical/high cannot be forced)
```

기존 한국어 메시지 ("backup 중단: secret scan 차단" 등) 는 영어로 교체.
non-error 일반 출력 (cloned, ready, schema 검증 통과 등) 은 한국어 유지.

backward compat:
- `BackupBlocked(reasons)` 형식은 그대로 작동 (additive 추가)
- 신규 keyword args: `next_steps`, `allow_force` 모두 optional

### 신규 파일

- `src/anvyc/utils/errors.py` — `print_blocked_error()` 헬퍼
- `tests/integration/test_config_edit.py` (4 case)
- `tests/integration/test_tools_list.py` (2 case)
- `tests/integration/test_config_show.py` (2 case)
- `tests/unit/test_error_messages.py` (6 case)

### 수정 파일

- `src/anvyc/cli.py` — config_app / tools_app subcommand group + 3 catch site refactor
- `src/anvyc/core/backup.py` — BackupBlocked.next_steps / allow_force
- `src/anvyc/core/apply.py` — ApplyBlocked.next_steps / allow_force

### 안전 가드

- `config edit` 의 EDITOR exit code 가 비-0 이면 변경 폐기 + 원본 복구
- invalid yaml 시 `.bak.<ts>` 로부터 자동 복구
- `EDITOR` 파싱은 `shlex.split` (quoted argument 안전)
- `tools list` 의 adapter detect() 는 read-only — side-effect 없음
- `config show --effective` 는 internal field (`source: Path`) 노출 안 함

### 통계

- 3 commits (feat config/tools + refactor errors + docs/version-bump)
- pytest 95 passed (기존 81 + 신규 14)
- uv build → `anvyc-0.6.3-py3-none-any.whl` 정상

---

## v0.6.2 — 2026-05-19 (onboarding 묶음)

[Wave 2 of docs/improvement-plan-ux-review.md §8.2 — Onboarding 묶음]
새 사용자가 chezmoi 수준의 1-liner 부트스트랩을 사용할 수 있도록 다음 3가지
경로 정비.

### 새 기능: `anvyc init --from-git <url>`

```bash
anvyc init --from-git git@github.com:<you>/anvyc-config.git
anvyc doctor
anvyc apply --dry-run
anvyc apply
```

- target `.anvyc/` 가 이미 있으면 **fail-fast** (덮어쓰기 X, 안전 우선)
- `.anvyc/anvyc.yaml` 검증 실패 시 exit 1 (clone 디렉터리는 그대로 — 사용자 검증)
- `--apply` 자동 실행은 의도적으로 지원 안 함 (destructive 행동 분리)

### Homebrew Formula 초안

- `packaging/homebrew/Formula/anvyc.rb` — Formula 초안 (placeholder sha256 포함)
- 사용자가 별도 repo `16bitdo/homebrew-anvyc` 로 옮긴 후 사용
- 설치 흐름: `brew tap 16bitdo/anvyc && brew install anvyc`
- 갱신 절차: `docs/homebrew-publishing.md` 참조 (release 후 수동)

### GitHub Release 자동화

- `.github/workflows/release.yml` — `v*` tag push 시 자동 동작
- 산출물: `anvyc-X.Y.Z-py3-none-any.whl` + `anvyc-X.Y.Z.tar.gz` + `SHA256SUMS`
- runner: `macos-latest` + Python 3.13 + uv
- token: 기본 `GITHUB_TOKEN` 으로 동작 (별도 PAT 불필요)

### README §5 재작성

기존 "v0.1.0 릴리즈 후 사용 가능" placeholder 를 실제 4-path 설치 가이드로
교체:

| § | 경로 | 시나리오 |
|---|---|---|
| 5.1 | Homebrew tap | 일반 사용자 (가장 권장) |
| 5.2 | GitHub Release wheel + uv/pipx | tap 미사용/직접 설치 |
| 5.3 | `init --from-git` | 머신 간 부트스트랩 |
| 5.4 | 개발 설치 (`pip install -e`) | contributor |

### 신규 파일

- `src/anvyc/cli.py` (수정) — init 함수에 `--from-git` 옵션 추가
- `dist/homebrew/Formula/anvyc.rb`
- `.github/workflows/release.yml`
- `docs/homebrew-publishing.md`
- `tests/integration/test_init_from_git.py` (3 case)

### 안전 가드

- `--from-git` clone 실패 시 git stderr 그대로 출력 + exit code 전파
- git binary 미설치 시 명시적 오류 (`FileNotFoundError` 잡음)
- target 충돌 시 기존 `.anvyc/` 보존 — 실수로 사용자 백업 덮어쓰기 방지
- Formula placeholder sha256 은 build-from-source 시도 시 정상적 mismatch 오류 발생 — release 후 갱신 필요

### Follow-up (사용자가 별도 수행)

1. `16bitdo/homebrew-anvyc` repo 생성 + Formula 초안 commit
2. v0.6.2 tag push 후 release artifact 의 sha256 으로 Formula 갱신
3. resource sha256 (typer/rich/pydantic/pathspec/pyyaml) 5종 PyPI 에서 산출

`docs/homebrew-publishing.md` 의 step-by-step 절차 참조.

### 통계

- 3 commits (impl + Formula/release infra + docs/version-bump)
- pytest 81 passed (기존 78 + 신규 3)
- uv build → `anvyc-0.6.2-py3-none-any.whl` 정상

---

## v0.6.1 — 2026-05-19 (multi-account doctor checks)

[Wave 1 of docs/improvement-plan-ux-review.md §8.2 — multi-account 묶음]
3종의 doctor check 추가로 사용자의 multi-account 환경 (12 AWS profile,
다중 GitHub ssh alias, Cursor user alias) 을 즉시 진단/안내.

### 신규 doctor check (7 → 10)

| Check | 동작 | 발행 severity |
|---|---|---|
| `project-aws-profile-mapping` | `~/Documents/**/.envrc` 의 `AWS_PROFILE` 값 ↔ `~/.aws/config` 정합성 검증 (depth 3 한정) | INFO (모두 정의됨) / WARNING (누락) |
| `aws-profile-status` | 현재 shell 의 `AWS_PROFILE` env var 와 `~/.aws/config` 정의 정합성 | INFO (미설정 / 정의됨) / WARNING (정의 안 됨) |
| `multi-account-detected` | AWS profile ≥ 2 + GitHub ssh alias (`Host github.com-*`) + Cursor user alias symlink | INFO (영역별 1건씩) |

### 사용 예

```bash
anvyc doctor --only project-aws-profile-mapping
anvyc doctor --only aws-profile-status
anvyc doctor --only multi-account-detected

# 새 check 만 모아서
anvyc doctor --only project-aws-profile-mapping \
             --only aws-profile-status \
             --only multi-account-detected
```

### 신규 파일

- `src/anvyc/utils/aws_config.py` — shared helper, `~/.aws/config` profile 이름 추출
- `src/anvyc/checks/project_aws_profile.py`
- `src/anvyc/checks/aws_profile_status.py`
- `src/anvyc/checks/multi_account_detected.py`
- `tests/unit/test_project_aws_profile.py` (5 case)
- `tests/unit/test_aws_profile_status.py` (3 case)
- `tests/unit/test_multi_account_detected.py` (6 case)

### 안전 가드

- `~/.aws/config` 부재 → graceful (모든 mapping 을 missing 처리)
- `~/Documents` 부재 → silent skip
- `[sso-session *]` 같은 다른 section 은 profile 로 인식 안 함 (`default` + `profile *` 만)
- doctor JSON schema 변경 없음 (6 필드 유지) — 외부 도구 호환

### 회귀

- `tests/unit/test_smoke.py` 의 `__version__` assertion 을 0.6.1 로 동기화 (v0.6.0 에서 누락된 회귀 함께 수정)
- 기존 7 check 동작/출력 변경 없음 — `--skip` 옵션으로 새 check 비활성화 가능

### 통계

- 2 commits (impl + docs/version-bump)
- pytest 78 passed (기존 64 + 신규 14, smoke 회귀 1 fix)
- uv build → `anvyc-0.6.1-py3-none-any.whl` 정상

---

## v0.6.0 — 2026-05-19 (OSS 공개 준비)

**OSS 공개 준비 완료**. LICENSE / CONTRIBUTING / SECURITY / pyproject metadata
정비, README §11 multi-AWS-profile 워크플로 가이드 신설, Git history rewrite.

### 신규 파일

- `LICENSE` — MIT License (Copyright (c) 2026 edward (16bitdo))
- `CONTRIBUTING.md` — 기여 가이드 (환경 셋업, 테스트, PR 가이드, Issue 가이드)
- `SECURITY.md` — 보안 신고 절차 (GitHub Security Advisory 우선)
- `docs/improvement-plan-ux-review.md` — UX 개선 계획 (설치/다중계정/설정)

### README 갱신

- `§9.3` doctor `--json` schema 정식화 (v0.5.3 추가분 통합)
- **`§11` 신규** — multi-AWS-profile 워크플로 가이드:
  - `§11.1` direnv + .envrc 프로젝트별 패턴
  - `§11.2` PR 별 임시 전환 (shell function / aws-vault)
  - `§11.3` anvyc 가 추적하는 것
  - `§11.4` anvyc scope 경계
  - `§11.5` 향후 doctor check 계획 (v0.6.x)
- `§12` 로드맵 갱신 — v0.1.0~v0.5.3 ✓ / v0.6.0 현재 / v0.6.x / v0.7+ / v1.0
- `§13` 기여 / `§14` 보안 / `§15` 라이선스 섹션 추가

### pyproject.toml 갱신

- version `0.1.0` → `0.6.0`
- description 보강 (도구 차별점 명시)
- keywords 보강 (`sops`, `1password`, `age-encryption`, `secret-management`)
- classifiers — Development Status `3 Alpha → 4 Beta`, MIT License OSI,
  macOS X 명시, Python 3.13, Topic Security, Typed
- `[project.urls]` — Homepage / Repository / Documentation / Issues / Changelog
  / Contributing / Security 7 URL

### .gitignore 확장

- IDE artifact (`.cursor/`, `.cursorindexingignore*`) — Z2 결정: 로컬 보존, 추적 차단
- Claude Code artifact (`CLAUDE.md`, `.claude/`)
- vim swap (`*.swp`, `*.swo`)
- coverage.xml 추가

### CLI docstring 보강

- `apply` 에 `--dry-run` 권장 + 사용 예
- `restore` 에 backup_id 예시

### Git history rewrite (destructive — force-push)

- Co-Authored-By: Claude 트레일러 제거 (K2 결정, 30 commits)
- `<company>-*` 식별자 → `<company>-*` 익명화 (L1=c)
- author identity → `16bitdo` 단일 통합
- 모든 tag (v0.1.0~v0.5.3) 새 commit hash 로 재발행
- **기존 clone 사용자는 rebase 필요** — `git fetch && git reset --hard origin/main`

### v0.6.x 예고

- doctor checks: `project-aws-profile-mapping`, `aws-profile-status`,
  `unused-aws-profiles`, `multi-account-detected`
- `anvyc init --from-git <url>` (chezmoi-like 부트스트랩)
- `anvyc config edit` + `anvyc tools list`
- 호스트별 `anvyc.yaml.<hostname>` overlay
- Homebrew tap

### v0.7+ 예고

- `dev_env` 어댑터 (.envrc/.tool-versions/.nvmrc 추적)
- 어댑터 추가 (vscode/helix/neovim)
- 어댑터별 dev_env 통합

### 통계

- 5 commits (Phase A.3 + Phase B + Phase B')
- pytest 64 passed (회귀 없음)
- uv build → wheel `anvyc-0.6.0-py3-none-any.whl` 정상

---

## v0.2.0 — 2026-05-18

**SOPS encryption-at-rest 통합**. 1Password Secret Reference (v0.1.0) 와 보완 관계로, 다수 secret 묶음을 git-tracked SOPS 파일로 안전하게 백업/적용한다.

### 신규

- **`security.sops.*` schema** (anvyc.yaml): `enabled`, `age_recipients`, `age_identity_file`
- **`tools.<name>.secret_files`** 키: 항목은 SOPS encrypt 후 백업
- **`core/sops.py`** subprocess wrapper (binary 모드, byte-for-byte 보존)
- **backup orchestrator** 의 SOPS encrypt branch: `backup/<ts>/<tool>/sops/<name>.sops.json`
- **apply orchestrator** 의 SOPS decrypt branch: `sops -d` 후 평문 target 에 저장
- **scanner SOPS 인식**: `.sops.*` 파일 또는 `sops:` metadata 보유 시 scan skip
- **doctor check `sops-keys-available`**: sops/age binary + age identity file 부재 자동 안내
- **integration test 4건** (sops round-trip + key 부재 + scanner skip)

### 결정 사항 (V1~V4)

| # | 항목 | 결정 |
|---|---|---|
| V1 | SOPS 파일 저장 위치 | `.anvyc/` 안에 git-tracked (SOPS 본래 목적) |
| V2 | 키 backend 기본값 | **age** (clean slate, cross-platform) |
| V3 | mcp.json 자동 마스킹 | v0.2.1 분리 |
| V4 | 1Password Reference 와의 관계 | 양립 — 사용자 선택 |

### 사용 흐름

```bash
brew install sops age
mkdir -p ~/.config/sops/age && age-keygen -o ~/.config/sops/age/keys.txt
# Public key 를 anvyc.yaml security.sops.age_recipients 에 등록
# tools.<X>.secret_files 에 secret 묶음 파일 지정
anvyc backup    # → SOPS 자동 암호화
anvyc apply     # → SOPS 자동 복호화 (identity file 필요)
```

### 의존성

- `sops` binary (사용자 설치)
- `age` binary (사용자 설치)
- anvyc Python 의존성 변경 없음

### 알려진 한계

- v0.2 는 **binary 모드만** 지원 (byte-for-byte 보존). YAML/JSON in-place 부분 암호화는 v0.2.1+ 옵션.
- SOPS entry 의 `state_before` 는 항상 `modified` 로 표시 (encrypted backup vs plain target sha256 불일치). 동작 안전성 영향 X. iTerm2 와 동일한 PoC 한계.
- mcp.json 자동 마스킹은 v0.2.1 로 분리.

### Phase 통계

- 4 commits
- 9 sub-tasks (V2.1~V2.9)
- 43 test cases (v0.1.0 39 + SOPS 4)
- ~10 hours

---

## v0.1.0 — 2026-05-18

첫 정식 MVP. macOS 개발자 환경의 설정/규칙을 **여러 머신 사이에서 안전하게 백업·비교·복원·동기화**하는 CLI.

### 하이라이트

- **8개 도구 어댑터**: shell · git · aws · gh · pulumi · cursor · claude · iterm2
- **9개 CLI 명령**: `init` · `doctor` · `backup` · `list` · `status` · `diff` · `apply` · `restore` · `scan-secrets` + `git {init/status/commit/push}` subcommand
- **5개 doctor check**: cross-user · venv-hidden-flag · op-references-valid · adapter-validate · cursor-projects-suggest
- **secret 기본 제외 + 1Password Secret Reference (`op://`) 통합**
- **Git 동기화 + pre-commit hook** 으로 push 전 secret 자동 차단
- **39 test cases** (unit 17 + integration 22) — 회귀 안전망

### 핵심 가치 시나리오

```bash
# 머신 A
anvyc init && anvyc backup
anvyc git init
anvyc git commit -m "snapshot"
git -C .anvyc remote add origin <private-repo>
anvyc git push

# 머신 B
git clone <private-repo> .anvyc
anvyc apply
```

### 어댑터별 안전 정책

| 어댑터 | 포함 | 절대 제외 |
|---|---|---|
| shell | `.zshrc`, `.zprofile`, `.zshenv`, `.zlogin` | `.zsh_history`, `.zsh_sessions` |
| git | `.gitconfig`, `.gitignore_global` | `.git-credentials`, `~/.ssh/id_*` |
| aws | `~/.aws/config` | `credentials`, `sso/cache`, `cli/cache` |
| gh | `~/.config/gh/config.yml` | `hosts.yml` (token) |
| pulumi | `~/.pulumi/config.json` | `credentials.json`, `access_tokens` |
| claude | settings/keybindings/CLAUDE.md/hooks/plugins/plans | sessions, tokens, cache, projects, history.jsonl, config.json (token), plugins/marketplaces |
| iterm2 | safe subset 31 keys (profiles/keybindings/colors/AI 설정 등) | NSWindow Frame *, NoSync*, SU*, NS*, Apple*, NeverWarnAbout*, iTerm Version |
| cursor | 3-layer (Global ~/.cursor / IDE Library/User / Project opt-in) | cli-config.json, projects/, plugins/marketplaces, workspaceStorage, History, globalStorage(allowlist 외), state.vscdb |

### Doctor checks

- **cross-user**: 디렉터리 이름 prefix / symlink target / 텍스트 content / iTerm2 plist 안의 `/Users/<x>/` 경로 5단계 분류
- **venv-hidden-flag**: macOS Python 3.13 의 UF_HIDDEN 트랩 (`.venv` dotfile + site.py skip) 자동 감지
- **op-references-valid**: 파일 안의 `op://` URI 들을 `op CLI` 로 resolve 검증 (미설치/미인증 시 안전 skip)
- **adapter-validate**: 각 어댑터의 자체 validate 호출 — 현재 cursor 의 broken symlink 탐지 구현
- **cursor-projects-suggest**: candidate root (`~/Documents/`, `~/Projects/`, ...) 에서 `.cursor/` 발견 시 INFO 안내

### Secret 정책 — 1Password Secret Reference (v0.1.0)

- raw token → `op://<vault>/<item>/<field>` reference 사용 권장
- secret scanner: 같은 라인에 `op://` 가 있으면 다른 secret 패턴 매칭을 `low` 로 강등
- pre-commit hook: push 전 `scan-secrets --staged` 강제

> v0.2 계획: SOPS 통합 (encryption-at-rest), Doctor `--fix` 모드

### 설치

```bash
# 빌드
git clone git@github.com:16bitdo/anvyc.git
cd anvyc
uv build

# 격리 설치 (uv tool 또는 pipx 동등)
uv tool install --force dist/anvyc-0.1.0-py3-none-any.whl
anvyc --version    # → anvyc v0.1.0
```

### Phase 진행 현황 (개발 기록)

| Phase | 영역 | 상태 |
|---|---|---|
| 1 | apply / restore round-trip | ✓ |
| 2 | 어댑터 8개 (shell→cursor) | ✓ |
| 3 | Git 동기화 + pre-commit hook + scan-secrets CLI | ✓ |
| 4 | Doctor 보강 (5 check) | ✓ |
| 5 | 1Password Secret Reference 통합 | ✓ |
| 6 | 테스트 (39 cases) + uv 패키징 + v0.1.0 tag | ✓ |

### 알려진 한계

- iTerm2 status 가 항상 `modified` 로 표시됨 (XML safe subset vs binary 전체 plist sha256 mismatch). 동작 안전성 영향 X. 향후 adapter 별 `compute_target_hash()` 로 정합화 가능.
- pathspec `gitwildmatch` DeprecationWarning (cursor/claude adapter): 동작 영향 X. `gitignore` 패턴 마이그레이션은 v0.2.
- macOS Python 3.13 venv UF_HIDDEN 트랩: `chflags -R nohidden .venv` 필요. doctor 가 자동 감지·안내함.

### v0.2 후보

- SOPS 기반 encryption-at-rest (`~/.anvyc-secrets/`)
- Doctor `--fix` 모드 (SSH config `/Users/<alias>/` → `~/` 정규화)
- pathspec gitwildmatch → gitignore 패턴 마이그레이션
- mcp.json 자동 마스킹 (raw token → `{{REDACTED}}`)
- Windows / Linux 지원
- 어댑터 추가 (vscode, helix 등)

### 기여자

- edward (16bitdo) — 설계 / 구현 / 검증
- Claude Opus 4.7 — pair-programming

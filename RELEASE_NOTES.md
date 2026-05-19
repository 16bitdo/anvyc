# anvyc 릴리즈 노트

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
- author identity → `16bitdo <16bitdo@gmail.com>` 단일 통합
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

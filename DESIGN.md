# DESIGN.md — anvyc 개발환경 설정 동기화 도구 설계서

> 문서 버전: v0.3
> 작성일: 2026-05-17
> 개정일: 2026-05-27 (v0.3 — CP-13 cost observability 추가, axis 본문 분리)
> 프로젝트 가칭: `anvyc`
> 목적: 여러 장치에서 Claude Code, Cursor IDE, AWS CLI, GitHub CLI, Pulumi, iTerm2 등 로컬 개발환경 설정을 안전하고 일관되게 동기화한다.

## 목차

### 핵심 설계
- [§1 배경과 문제 정의](#1-배경과-문제-정의)
- [§2 선행 사례: chezmoi](#2-선행-사례-chezmoi)
- [§3 제품 정의](#3-제품-정의) · [§4 범위](#4-범위) · [§5 설계 원칙](#5-설계-원칙)
- [§6 주요 명령어](#6-주요-명령어) · [§7 디렉터리 구조](#7-디렉터리-구조) · [§8 Runtime 데이터 구조](#8-runtime-데이터-구조)
- [§9 설정 파일 예시](#9-설정-파일-예시) · [§10 Core Architecture](#10-core-architecture) · [§11 Adapter 인터페이스](#11-adapter-인터페이스) · [§12 Core Workflow](#12-core-workflow)

### 보안 / 도구별 adapter
- [§13 Secret Scanner 설계](#13-secret-scanner-설계)
- [§14 iTerm2](#14-iterm2-adapter-설계) · [§15 Cursor IDE](#15-cursor-ide-adapter-설계) · [§16 Claude Code](#16-claude-code-adapter-설계)
- [§17 외부 도구 Adapter 모음 (AWS / GitHub CLI / Pulumi / shell_prompt)](#17-외부-도구-adapter-모음-aws--github-cli--pulumi--shell_prompt)
- [§30 Secret 분리 정책 (1Password)](#30-secret-분리-정책-v010-1password-secret-reference) · [§31 SOPS 통합](#31-sops-통합-v02)

### 진단 / 메타
- [§18 Metadata](#18-metadata-설계) · [§19 기술 스택](#19-기술-스택) · [§20 테스트 전략](#20-테스트-전략) · [§21 개발 일정](#21-개발-일정)
- [§22 성공 케이스](#22-성공-케이스) · [§23 실패 케이스](#23-실패-케이스와-대응) · [§24 chezmoi 비교](#24-chezmoi-사용-vs-직접-개발-비교) · [§25 MVP 완료 기준](#25-mvp-완료-기준) · [§26 초기 작업](#26-바로-실행-가능한-초기-작업)
- [§27 Doctor](#27-doctor-명령-설계) · [§28 의사결정](#28-최종-의사결정) · [§29 로드맵](#29-릴리스-로드맵)

### AI agent integration (P6+ / Control Plane)
- [§32 project show JSON schema (v0.8.0)](#32-project-show-json-schema-v080-ai-agent-integration)
- [§33 project list / project doctor (v0.8.1)](#33-project-list--project-doctor-schema-v081)
- [§34 MCP server (v0.9.0)](#34-mcp-server-architecture-v090-p6)
- **§35 CP-4 Snapshot** → [docs/design-axes/cp-04-snapshot.md](./docs/design-axes/cp-04-snapshot.md)
- **§36 CP-5 Credentials** → [docs/design-axes/cp-05-creds.md](./docs/design-axes/cp-05-creds.md)
- **§37 CP-6 Sync** → [docs/design-axes/cp-06-sync.md](./docs/design-axes/cp-06-sync.md)
- **§38 CP-13 Cost** → [docs/design-axes/cp-13-cost.md](./docs/design-axes/cp-13-cost.md)
- **§39 CP-15 Secret Broker** → [docs/design-axes/cp-15-secret-broker.md](./docs/design-axes/cp-15-secret-broker.md)
- **§40 CP-14 Run ledger** → [docs/design-axes/cp-14-run-ledger.md](./docs/design-axes/cp-14-run-ledger.md)

---

## 1. 배경과 문제 정의

개발자는 여러 장치에서 동일한 개발환경을 유지해야 한다. 하지만 shell, terminal, IDE, AI coding tool, cloud CLI, IaC 도구의 설정 파일은 각기 다른 위치와 형식으로 존재한다. 수동 복사나 단순 Git 저장소 방식은 다음 문제가 있다. 같은 도구에서 여러 개의 계정을 사용하는 케이스도 존재한다.

| 문제 | 설명 |
|---|---|
| 설정 위치 분산 | `.zshrc`, Cursor settings, iTerm2 plist, AWS config 등 경로가 제각각이다. |
| 장비별 차이 | hostname, OS, path, email, profile 등 장비별 값이 다르다. |
| 코드베이스별 차이 | user, email, profile, signing key 등이 repo마다 달라야 할 수 있다. |
| Secret 혼입 위험 | credentials, token, private key 등이 dotfiles에 섞여 Git에 올라갈 수 있다. |
| 적용 시 무결성 부재 | 단순 복사 방식은 적용 전 diff/검증/백업 절차가 없다. |
| 다중 계정 처리 어려움 | AWS profile, GitHub host, Pulumi org 등에서 여러 계정을 분리 관리해야 한다. |

---

## 2. 선행 사례: chezmoi

chezmoi는 개인 설정 파일, 즉 dotfiles를 여러 머신에서 관리하기 위한 대표적인 도구다. 공식 문서는 chezmoi가 `~/.gitconfig` 같은 개인 설정 파일을 여러 머신에서 관리하고, 단순 symlink나 bare Git repo보다 다양한 기능을 제공한다고 설명한다.
참조: https://chezmoi.io/

chezmoi GitHub 저장소는 "Manage your dotfiles across multiple diverse machines, securely."라고 설명한다.
참조: https://github.com/twpayne/chezmoi

chezmoi는 age 기반 파일 암호화와 password manager integration을 지원한다. password manager integration은 public dotfiles repository를 유지하면서 secret을 안전하게 관리하고, template 적용 시 password manager에서 값을 가져와 destination file에 삽입하는 방식을 제공한다.
참조: https://chezmoi.io/user-guide/encryption/age/
참조: https://chezmoi.io/user-guide/password-managers/

이 설계는 chezmoi의 다음 아이디어를 참고한다.

| chezmoi 아이디어 | anvyc 적용 |
|---|---|
| source state / target state 분리 | backup state와 local state를 명시적으로 분리 |
| template 기반 장비별 값 처리 | hostname/email 등 장비별 값은 metadata로 분리 |
| age 기반 secret 암호화 | `~/.anvyc-secrets/` 영역에 동일 방식 적용 |
| diff/apply/dry-run 모델 | `anvyc diff`, `anvyc apply --dry-run` 동일 모델 채택 |
| password manager integration | 향후 1Password CLI 연동 고려 |

다만 anvyc는 범용 dotfiles manager가 아니라 **Claude Code, Cursor, AWS, GitHub CLI, Pulumi, iTerm2 중심의 개발환경 특화 동기화 도구**다.

> 사용자 hero 의 압축 인용: [README §2 왜 만들었나](./README.md). README 는 외부 사용자 진입점, 본 DESIGN §2 는 비교 표 5항목 + 차별점의 정식 frame.

---

## 3. 제품 정의

### 3.1 한 줄 정의

```text
anvyc는 여러 장치에서 개발 도구 설정 정보와 인증 정보를 안전하게 백업, 비교, 복원, 동기화하는 CLI 도구다.
```

### 3.2 핵심 목표

1. 여러 Mac 또는 개발 장비에서 동일한 개발환경 설정을 유지한다.
2. secret은 기본적으로 수집하지 않는다. 필요한 경우 변수에 담아서 처리할 수 있도록 제안한다.
3. apply 전 변경 내용을 diff로 확인한다.
4. apply 또는 restore 전 현재 로컬 설정을 자동 백업한다.
5. 도구별 안전한 adapter를 제공한다.
6. Git 기반으로 설정 이력을 관리한다.
7. 향후 팀 표준 개발환경 배포에도 확장 가능하도록 설계한다.

---

## 4. 범위

### 4.1 MVP 포함 대상

| 도구 | 포함 대상 | 제외 대상 |
|---|---|---|
| Shell | `.zshrc`, `.zprofile`, aliases | shell history, local-only secrets |
| Git | `.gitconfig`, `.gitignore_global` | `.git-credentials`, GPG/SSH key |
| AWS CLI | `~/.aws/config` | `~/.aws/credentials`, SSO cache |
| GitHub CLI | `~/.config/gh/config.yml` | `~/.config/gh/hosts.yml` (token 포함) |
| Cursor | `settings.json`, `keybindings.json`, snippets, `~/.cursor/rules`, `~/.cursor/skills`, `mcp.json` | `workspaceStorage`, `History`, `globalStorage` 전체 |
| Claude Code | `settings.json`, hooks, plugins, CLAUDE.md template | sessions, tokens, cache, logs, conversation history |
| iTerm2 | profiles, key mappings, color presets | window state, recent sessions, device-specific UI state |
| Pulumi | non-secret config 일부 | `~/.pulumi/credentials.json`, access token |

### 4.2 MVP 제외 대상

| 제외 대상 | 이유 |
|---|---|
| OS 전체 구성관리 | Nix/home-manager/Ansible 영역이다. |
| 패키지 매니저 전체 동기화 | Homebrew bundle 등 별도 기능으로 분리한다. |
| SSH private key 관리 | 보안 위험이 높아 별도 secret manager 연동 후 검토한다. |
| 모든 앱 설정 자동 수집 | secret/cache/history 유출 위험이 크다. |
| Windows 지원 | MVP는 macOS 중심으로 시작한다. |

---

## 5. 설계 원칙

### 5.1 Secret 기본 제외

```text
credentials는 기본적으로 수집하지 않는다.
secret은 별도 채널 또는 암호화 방식으로만 관리한다.
```

기본 제외 예:

```text
~/.aws/credentials
~/.pulumi/credentials.json
~/.ssh/id_rsa
~/.ssh/id_ed25519
.env
Cursor workspaceStorage
Cursor History
Claude sessions
Claude tokens
shell history
```

### 5.2 Apply 전 diff & dry-run

```text
anvyc diff
anvyc apply --dry-run
anvyc apply
```

apply 전 항상 diff를 보여주고, dry-run으로 실제 변경 없이 변경 예정 사항만 확인할 수 있도록 한다.

### 5.3 Restore 전 local backup

기존 설정을 덮어쓰기 전 현재 target 파일을 반드시 local backup에 저장한다.

```text
local-backups/<timestamp>/
```

### 5.4 도구별 safe adapter

각 도구는 파일 위치, secret 위험도, 적용 방식이 다르다. 따라서 범용 파일 복사보다 adapter 기반 설계가 안전하다.

### 5.5 Git-friendly, secret-hostile

설정 파일은 Git 이력 관리에 적합해야 하지만, secret이 Git에 들어가는 것은 강하게 차단해야 한다.

---

## 6. 주요 명령어

```bash
anvyc init
anvyc doctor
anvyc backup
anvyc status
anvyc diff
anvyc apply
anvyc apply --dry-run
anvyc restore <backup-id>
anvyc list
anvyc scan-secrets
anvyc git init
anvyc git status
anvyc git commit -m "message"
anvyc git push
```

### 6.1 명령어별 역할

| 명령어 | 역할 |
|---|---|
| `init` | anvyc 프로젝트 초기화 (`.anvyc/`, `anvyc.yaml` 생성) |
| `doctor` | 도구 설치 여부, 경로, 권한, 위험 경로 진단 |
| `backup` | 현재 환경 설정을 `.anvyc/backups/<timestamp>/`에 저장 |
| `status` | 현재 target 상태와 마지막 backup의 차이 요약 |
| `diff` | target과 source(backup) 간 unified diff 출력 |
| `apply` | source 설정을 target에 적용 (전 local backup 자동) |
| `apply --dry-run` | 실제 변경 없이 적용 시나리오만 출력 |
| `restore <backup-id>` | 특정 backup으로 target 복원 |
| `list` | 보관 중인 backup 목록 표시 |
| `scan-secrets` | backup 대상/현재 target에 secret이 있는지 스캔 |
| `git *` | `.anvyc/` 영역에 대한 Git 작업 wrapper |

---

## 7. 디렉터리 구조

```text
anvyc/
├── README.md
├── DESIGN.md
├── pyproject.toml
├── src/
│   └── anvyc/
│       ├── __init__.py
│       ├── __main__.py            # python -m anvyc 진입점 (v0.13.0+, §27.7)
│       ├── cli.py
│       ├── templates.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── inventory.py
│       │   ├── backup.py
│       │   ├── diff.py
│       │   ├── apply.py
│       │   ├── restore.py
│       │   ├── metadata.py
│       │   ├── project_info.py    # §32 ProjectInfo
│       │   ├── project_doctor.py  # §33 per-cwd doctor
│       │   ├── project_discovery.py
│       │   ├── project_roots.py   # §27.8 프로젝트 루트 SoT
│       │   └── doctor.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── shell.py
│       │   ├── git.py
│       │   ├── aws.py
│       │   ├── gh.py
│       │   ├── cursor.py
│       │   ├── claude.py
│       │   ├── iterm2.py
│       │   ├── pulumi.py
│       │   ├── dev_env.py         # v0.7.0+ — .envrc / .tool-versions / .python-version / .nvmrc
│       │   └── shell_prompt.py    # v0.13.0+ — starship / powerlevel10k 설정 (§17.4)
│       ├── checks/                # doctor check 모듈 (§27.1.1)
│       │   ├── cross_user.py
│       │   ├── venv_hidden.py
│       │   ├── project_aws_profile.py
│       │   ├── project_gh_account.py
│       │   ├── project_claude_account.py
│       │   ├── project_pulumi_backend.py
│       │   ├── multi_account_detected.py
│       │   ├── aws_profile_status.py
│       │   ├── unused_aws_profiles.py
│       │   ├── cursor_projects_suggest.py
│       │   ├── adapter_validate.py
│       │   ├── op_references.py
│       │   ├── sops_keys.py
│       │   └── mcp_tokens.py
│       ├── mcp/                   # v0.9.0+ — anvyc serve --mcp ([mcp] extra, §34)
│       │   ├── __init__.py
│       │   └── server.py
│       ├── security/
│       │   ├── __init__.py
│       │   ├── scanner.py
│       │   ├── patterns.py
│       │   └── policy.py
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── local.py
│       │   ├── git.py
│       │   └── encryption.py
│       └── utils/
│           ├── __init__.py
│           ├── paths.py
│           ├── hashing.py
│           └── logging.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/
└── examples/
```

---

## 8. Runtime 데이터 구조

### 8.1 기본 저장 구조

```text
.anvyc/
├── backups/
│   └── 20260517-132000/
│       ├── shell/
│       │   └── zshrc
│       ├── git/
│       │   └── gitconfig
│       ├── aws/
│       │   └── config
│       ├── cursor/
│       │   ├── settings.json
│       │   └── keybindings.json
│       ├── claude/
│       │   └── settings.json
│       ├── iterm2/
│       │   └── profiles.json
│       ├── pulumi/
│       │   └── config.json
│       └── metadata.json
├── current -> backups/20260517-132000
├── local-backups/
│   └── 20260517-133000/
├── reports/
│   └── secret-scan-20260517-132000.json
└── .anvycignore
```

### 8.2 Secret 분리 영역

```text
~/.anvyc-secrets/
├── backups/
│   └── 20260517-132000/
├── local-backups/
└── current -> backups/20260517-132000
```

암호화 대상 설정은 `~/.anvyc-secrets/`를 분리한다. `.anvyc/`는 Git 동기화 가능 영역이고, `~/.anvyc-secrets/`는 Git 동기화 대상이 아니다.

---

## 9. 설정 파일 예시

```yaml
version: 1

storage:
  root: ".anvyc"
  keep_backups: 5
  keep_local_backups: 5

security:
  secret_scan: true
  block_on_secret: true
  allow_encrypted_secrets: true

tools:
  shell:
    enabled: true
    files:
      - "~/.zshrc"
      - "~/.zprofile"

  git:
    enabled: true
    files:
      - "~/.gitconfig"
      - "~/.gitignore_global"

  aws:
    enabled: true
    include:
      - "~/.aws/config"
    exclude:
      - "~/.aws/credentials"

  gh:
    enabled: true
    include:
      - "~/.config/gh/config.yml"
    exclude:
      - "~/.config/gh/hosts.yml"

  cursor:
    enabled: true
    include:
      - "~/Library/Application Support/Cursor/User/settings.json"
      - "~/Library/Application Support/Cursor/User/keybindings.json"
      - "~/Library/Application Support/Cursor/User/snippets"
      - "~/.cursor/rules"
      - "~/.cursor/skills"
    exclude:
      - "~/Library/Application Support/Cursor/User/workspaceStorage"
      - "~/Library/Application Support/Cursor/User/History"
      - "~/Library/Application Support/Cursor/User/globalStorage"

  claude:
    enabled: true
    include:
      - "~/.claude/settings.json"
      - "~/.claude/hooks"
      - "~/.claude/plugins"
    exclude:
      - "~/.claude/sessions"
      - "~/.claude/tokens"
      - "~/.claude/cache"
      - "~/.claude/logs"

  iterm2:
    enabled: true
    mode: "safe"
    include:
      - "profiles"
      - "key_mappings"
      - "color_presets"
    exclude:
      - "window_state"
      - "recent_sessions"

  pulumi:
    enabled: true
    include:
      - "~/.pulumi/config.json"
    exclude:
      - "~/.pulumi/credentials.json"
```

---

## 10. Core Architecture

```text
┌─────────────────────────────────────────────┐
│ CLI Layer (Typer)                           │
│ init / doctor / backup / status / diff /    │
│ apply / restore / scan-secrets / git        │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│ Core Layer                                  │
│ - inventory                                 │
│ - source state                              │
│ - target state                              │
│ - diff engine                               │
│ - apply engine                              │
│ - backup manager                            │
│ - metadata manager                          │
└─────────────────────┬───────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
┌───────▼──────┐ ┌────▼─────┐ ┌─────▼────────┐
│ Adapter Layer│ │ Security │ │ Storage Layer│
│ shell/git/   │ │ scanner  │ │ local/git/   │
│ aws/gh/      │ │ policy   │ │ encryption   │
│ cursor/      │ │ patterns │ │              │
│ claude/      │ │          │ │              │
│ iterm2/      │ │          │ │              │
│ pulumi       │ │          │ │              │
└──────────────┘ └──────────┘ └──────────────┘
```

---

## 11. Adapter 인터페이스

```python
class Adapter:
    name: str

    def detect(self) -> bool:
        """도구 설치 여부 또는 설정 경로 존재 여부를 확인한다."""

    def collect(self) -> list[ManagedFile]:
        """백업 대상 파일 목록을 반환한다."""

    def exclude(self) -> list[str]:
        """기본 제외 대상 목록을 반환한다."""

    def validate(self) -> list[Finding]:
        """위험 설정, secret 후보, 손상된 파일 등을 탐지한다."""

    def diff(self, source: Path, target: Path) -> DiffResult:
        """source와 target의 차이를 계산한다."""

    def apply(self, source: Path, target: Path) -> ApplyResult:
        """source 설정을 target에 적용한다."""
```

### 11.1 AdapterMeta — 도구 메타데이터 단일 SoT

각 adapter 는 `name`/메서드 외에 정적 메타데이터 `meta: AdapterMeta` 를 클래스 속성으로
노출한다. 런타임 상태(enabled/detected/file count)와 무관한 "설명용" 정보만 담는다.

```python
@dataclass(frozen=True)
class AdapterMeta:
    name: str            # registry key·class.name 과 일치
    label: str           # 'AWS CLI'
    summary: str         # '~/.aws/config 백업 (credentials·SSO cache 제외)'
    category: str        # shell|vcs|cloud|iac|ide|ai-agent|terminal|dev-env
    includes: tuple[str, ...]   # 기본 포함 — file-based 는 DEFAULT_FILES 동일 참조
    excludes: tuple[str, ...]   # 기본 제외(표시용; 경로형은 exclude() 의 부분집합)
    default_enabled: bool = True   # dev_env=False
    config_kind: str = "files"     # 'files' | 'structured'
    since: str = ""
```

이 메타는 다음 **5개 표면의 단일 소스**다 (과거 분산/드리프트 제거):
`anvyc tools list` · MCP `tools_list` · `anvyc tools configure`(선택 화면) ·
`init --interactive` wizard(도구별 default) · README §4 표(`scripts/gen_supported_tools.py` 생성).
정합성은 테스트로 강제한다 — `test_adapter_meta`(file-based `includes==DEFAULT_FILES`,
표시 `excludes ⊆ exclude()`, category 허용값, default_enabled 정책),
`test_wizard_sot`(순서가 ADAPTERS 전체 커버), `test_gen_supported_tools`(README↔SoT 동기).
상세 설계/진행: `docs/archive/improvement-plan-tools-selection.md`.

### 11.2 ExtraReq — 동반 도구(외부 CLI + Python extras) 의존성 SoT

anvyc 의 일부 기능은 PATH 의 **외부 CLI 바이너리**(sops/age/op/aws-vault/gh/…) 또는
**pip extras**(boto3/httpx/textual/mcp/cryptography)가 있어야 동작한다. 이 의존성 메타와
설치 안내(`brew install …` / `pip install 'anvyc[…]'`)의 단일 SoT 는
`src/anvyc/core/extras.py` 의 `EXTRAS_REGISTRY` 다 (AdapterMeta(§11.1)와 동형 패턴).

```python
@dataclass(frozen=True)
class ExtraReq:
    name: str            # 'sops', 'boto3'
    kind: str            # 'binary' | 'pyextra'
    label: str
    purpose: str         # 잠금 해제하는 anvyc 기능
    probe: tuple[str, ...]      # binary: which 후보 / pyextra: dist 이름
    install_cmd: str
    pip_extra: str | None = None    # pyextra 의 pyproject extras 키
    install_url: str | None = None
    required: bool = False          # git 등 핵심 vs 선택
    platform: str | None = None     # 'darwin' (pbcopy/security)
```

헬퍼 `is_available(name)` / `install_hint(name)` / `installed_version(name)` /
`collect_extras_status()` 를 제공한다. 과거 `shutil.which`+`brew install …` 안내가
`core/sops.py`·`core/secrets.py`·`checks/sops_keys.py`·`checks/op_references.py`·`cli.py`
에 분산·불일치했던 것을 이 레지스트리 참조로 일원화했다 — 안내 문구 drift 제거.
소비처: 위 call site(설치 여부·안내) + `anvyc extras` 명령(설치 상태·잠금 기능·설치법
표, `--json`/`--missing`/`--check`) + README 동반 도구 표(`scripts/gen_extras.py` 생성,
`render_extras_markdown`). 정합성은 `test_extras_registry`(필수 필드·kind 허용값·핵심 도구
존재·헬퍼 계약), `test_extras_command`(JSON/표/--check), `test_gen_extras`(README↔SoT 동기)로 강제한다.

---

## 12. Core Workflow

### 12.1 Backup Workflow

```text
1. anvyc.yaml 로드
2. enabled adapter 목록 결정
3. adapter.detect() 호출로 설치 확인
4. adapter.collect()로 source path 계산
5. secret scan 수행
6. 위험 파일 발견 시 backup 중단
7. backup/<timestamp>/에 파일 복사
8. hash 계산
9. metadata.json 생성
10. current symlink 갱신
```

### 12.2 Apply Workflow

```text
1. anvyc.yaml 로드
2. source state 와 target state inventory 생성
3. diff 계산
4. secret scan 수행
5. apply 전 local backup 생성
6. 파일 적용
7. 권한 보정
8. hash 검증
9. apply report 생성
```

### 12.3 Restore Workflow

```text
1. backup-id 확인
2. metadata 검증
3. 현재 target local backup 생성
4. restore diff 출력
5. restore 수행
6. 결과 검증
```

---

## 13. Secret Scanner 설계

### 13.1 탐지 대상

| 유형 | 패턴 예 |
|---|---|
| AWS Access Key | `AKIA`, `ASIA` prefix |
| GitHub Token | `ghp_`, `github_pat_` |
| OpenAI Key | `sk-` 계열 |
| Anthropic Key | `sk-ant-` 계열 |
| Pulumi Token | `pul-` 계열 |
| Private Key | `BEGIN PRIVATE KEY` |
| Generic Secret | `api_key=`, `token=`, `secret=`, `password=` |

### 13.2 정책

| 등급 | 예시 | 기본 동작 |
|---|---|---|
| Critical | private key, AWS secret key | 중단 |
| High | GitHub token, Pulumi token | 중단 |
| Medium | `.env`, `password=` | 경고 + `--force` 필요 |
| Low | email, username | 허용 (정보 로그만) |

### 13.3 실행 시점

```text
init:
  warning 출력

backup:
  대상 파일 secret scan

apply:
  source와 target 모두 secret scan

git push:
  pre-commit hook으로 다시 한 번 secret scan
```

---

## 14. iTerm2 Adapter 설계

iTerm2는 전체 plist 동기화가 위험하다. `com.googlecode.iterm2.plist`에는 프로필 외에도 window arrangement, recent sessions, local path, UI state 등이 포함될 수 있다.

### 14.1 기본 정책

```text
MVP에서는 iTerm2 전체 plist 동기화 금지
profiles / key mappings / color presets만 safe subset으로 추출
plistlib로 파싱 후 필요한 키만 직렬화
```

### 14.2 포함 대상 (실측 기반)

사용자 plist (iTerm2 3.6.10, 102 top-level keys) 조사 후 다음을 안전한 포터블 키로 결정한다.

| 카테고리 | 키 |
|---|---|
| 프로필 | `New Bookmarks`, `Default Bookmark Guid` |
| 키바인딩 | `GlobalKeyMap` |
| 포인터 | `PointerActions` |
| 색 프리셋 | `Custom Color Presets` |
| 동작 prefs | `DoubleClickPerformsSmartSelection`, `EnableProxyIcon`, `HideTab`, `IRMemory`, `PreventEscapeSequenceFromClearingHistory`, `SavePasteHistory`, `SplitPaneDimmingAmount` |
| 음/시각 알림 | `SoundForEsc`, `VisualIndicatorForEsc`, `HapticFeedbackForEsc` |
| Dim | `DimBackgroundWindows`, `DimInactiveSplitPanes`, `DimOnlyText` |
| Hotkey | `HotkeyMigratedFromSingleToMulti` |
| AI 통합 (iTerm2 AI feature) | `AIFeatureFunctionCalling`, `AIFeatureHostedCodeInterpeter`, `AIFeatureHostedFileSearch`, `AIFeatureHostedWebSearch`, `AIFeatureStreamingResponses`, `AITermAPI`, `AIVectorStore`, `AIVendor`, `AiMaxTokens`, `AiModel`, `AiResponseMaxTokens`, `AitermURL` |

### 14.3 제외 대상 (실측 기반)

| 카테고리 | 패턴 | 이유 |
|---|---|---|
| 윈도우 위치 | `NSWindow Frame *` (12+ keys) | 장비별 화면 크기 |
| iTerm2 동기화 비대상 표시 | `NoSync*` (26+ keys) | iTerm2 자체가 "동기화 안 함"으로 표시한 키 |
| macOS 시스템 prefs | `NS*`, `Apple*` | 시스템이 자동으로 관리. 동기화 부적절 |
| 절대 경로 포함 | `LoadPrefsFromCustomFolder`, `PrefsCustomFolder` | 사용자별 절대 경로 (`/Users/edward/...`) |
| 자동 업데이트 메타 | `SU*` (Sparkle) | 장비별 마지막 체크 시각 등 휘발성 |
| 기기 식별 | `iTerm Version`, `NoSyncInstallationId` | 장비 의존 |
| UI dismissal 기록 | `NeverWarnAbout*` | 사용자 환경별 누적 선호 |
| URL handler | `URLHandlersByGuid` | 시스템 보안 영향 가능 |

### 14.4 저장 형식

plist 전체 동기화 금지 → 위 include 키만 추출해 `iterm2.plist` 또는 `iterm2.json` 으로 정규화 저장. apply 시 기존 plist 와 deep-merge (덮어쓰기 X) 한다.

---

## 15. Cursor IDE Adapter 설계

Cursor IDE는 3개 layer의 설정을 가진다. anvyc는 layer별 정책을 분리한다.

| Layer | 경로 | 역할 |
|---|---|---|
| A: User-global | `~/.cursor/` | rules / skills / mcp / plugins |
| B: IDE user config | `~/Library/Application Support/Cursor/User/` | settings / keybindings / snippets / profiles |
| C: Project-local (옵트인) | `<repo>/.cursor/`, `<repo>/.cursorrules` | 프로젝트별 rules |

### 15.1 Layer A — User-global (`~/.cursor/`)

#### 포함 (Tier 1)

| 경로 | 설명 |
|---|---|
| `~/.cursor/rules/` | 전역 cursor rules |
| `~/.cursor/skills/` | 전역 skills |
| `~/.cursor/skills-cursor/` | Cursor 특화 skills |
| `~/.cursor/mcp.json` | MCP server 등록 (secret scan 필수) |
| `~/.cursor/plugins/local/` | 로컬 플러그인 |
| `~/.cursor/plans/` | plan 템플릿 (선택) |

#### 제외 (Tier 1)

| 경로 | 이유 |
|---|---|
| `~/.cursor/cli-config.json` | 0600 perms, 토큰 가능성 (기존 v0.1에서 잘못 포함되어 있었음) |
| `~/.cursor/argv.json` | 기기별 launch arg |
| `~/.cursor/ide_state.json` | 기기별 UI state |
| `~/.cursor/extensions/` | 용량 큼, IDE가 자동 재설치 가능 |
| `~/.cursor/projects/` | 절대 경로 캐시, 기기/사용자별 |
| `~/.cursor/workers/` | 런타임 캐시 |
| `~/.cursor/ai-tracking/` | 세션/사용량 추적 |
| `~/.cursor/chats/` | 대화 이력 (개인 정보) |
| `~/.cursor/plugins/cache/` | 캐시 |
| `~/.cursor/rules.bak-*` | 백업 사본, 동기화 대상 아님 |
| `~/.cursor/prompt_history.json` | 사용자 입력 이력 (개인 정보) |

#### Symlink 정책

`~/.cursor/` 하위 일부 항목이 외부 repo로 symlink 되어 있을 수 있다 (예: `rules.bak-* → /Users/.../role-based-ruleset/.../rules`).

- `follow_symlinks: false` 가 기본값이다.
- symlink는 대상 경로만 `metadata.json`에 기록한다 (`{"path": ..., "symlinkTarget": "..."}`).
- 적용 시 동일 symlink를 재생성한다. 대상 경로가 존재하지 않으면 경고 + skip.

### 15.2 Layer B — IDE user config (`~/Library/Application Support/Cursor/User/`)

#### 포함 (Tier 1)

| 경로 | 설명 |
|---|---|
| `settings.json` | 사용자 설정 |
| `keybindings.json` | 키바인딩 |
| `snippets/` | 코드 스니펫 |
| `profiles/<id>/{settings,keybindings,snippets}` | 다중 프로필 (캐시는 제외) |

#### 제외 (Tier 1)

| 경로 | 이유 |
|---|---|
| `History/` | 파일 변경 이력 (실측 ~23M) |
| `workspaceStorage/` | 워크스페이스 캐시 (실측 ~1.4G) |
| `globalStorage/state.vscdb*` | 통합 SQLite, 세션/토큰 가능성 |
| `globalStorage/<ext>/` (allowlist 외) | 확장별 데이터, 일반적으로 동기화 부적합 |
| `*.bak`, `*.49f*.bak` | 자동 백업 사본 |
| `profiles/<id>/State/` 등 캐시 | 프로필 캐시 |

#### globalStorage allowlist

```yaml
cursor:
  ide:
    global_storage_allowlist:
      - "publisher.extension-id"
```

명시된 extension의 globalStorage만 포함. 기본은 empty.

### 15.3 Layer C — Project-local (`.cursor/`) 옵트인

anvyc는 dotfile sync 도구이므로 **프로젝트 repo 내부의 `.cursor/`는 기본 대상이 아니다**. 활성화 시에만 지정된 root 디렉터리에서 수집한다.

```yaml
cursor:
  projects:
    enabled: false
    roots:
      - "~/dev/anvyc"
      - "~/dev/another-project"
    patterns:
      - ".cursor/rules"
      - ".cursor/skills"
      - ".cursor/mcp.json"
      - ".cursorrules"
```

저장 위치: `.anvyc/backups/<ts>/cursor-projects/<project-name>/`. 각 root는 사용자가 명시한 절대/`~` 확장 경로만 허용한다 (자동 스캔 X).

### 15.4 보안 정책 (확장)

| 파일 | 위험 | 정책 |
|---|---|---|
| `~/.cursor/cli-config.json` | 토큰 | 기본 제외, scan으로 토큰 잔존 확인 |
| `~/.cursor/mcp.json` | OAuth/API 토큰 inline 가능 | 포함 + secret scan + 토큰 필드 자동 마스킹 옵션 (`mask_mcp_tokens: true`) |
| `globalStorage/state.vscdb` | 통합 DB, 세션 포함 가능 | 항상 제외 |
| `globalStorage/<ext>/` | extension별 secret 저장 가능 | allowlist 외 제외 |
| Symlink 대상 외부 repo | 의도치 않은 외부 백업 | follow_symlinks=false, metadata만 |

### 15.5 구현 단계

| 단계 | 작업 | 시기 |
|---|---|---|
| 1 | exclude() 목록 확정 (이 문서 반영) | 즉시 |
| 2 | collect() — Layer A 구현 | 1주차 PoC |
| 3 | collect() — Layer B 구현 | 1주차 PoC |
| 4 | symlink 처리 (metadata 보존) | 1주차 |
| 5 | profiles/ 다중 프로필 처리 | 2주차 MVP |
| 6 | globalStorage allowlist 처리 | 2주차 MVP |
| 7 | mcp.json 토큰 마스킹 옵션 | 2주차 MVP |
| 8 | Layer C (projects 모드) 옵트인 | 3주차 또는 v0.2 |

---

## 16. Claude Code Adapter 설계

### 16.1 포함 후보

```text
settings.json
hooks/
plugins/
project instructions
CLAUDE.md template
```

### 16.2 제외 후보

```text
sessions/
tokens/
conversation history/
cache/
logs/
```

### 16.3 정책

Claude Code는 개인 세션과 토큰 유출 가능성이 있으므로, `doctor`에서 경로별 위험도를 표시한다. 설정 파일이라도 token 또는 session reference가 포함되면 backup을 중단한다.

---

## 17. 외부 도구 Adapter 모음 (AWS / GitHub CLI / Pulumi / shell_prompt)

### 17.1 AWS

| 경로 | 정책 |
|---|---|
| `~/.aws/config` | 포함 가능 |
| `~/.aws/credentials` | 기본 제외 |
| SSO cache | 제외 |

### 17.2 GitHub CLI

| 경로 | 정책 |
|---|---|
| `~/.config/gh/config.yml` | 포함 가능 |
| `~/.config/gh/hosts.yml` | 기본 제외 (oauth token 포함) |

### 17.3 Pulumi

| 경로 | 정책 |
|---|---|
| `~/.pulumi/config.json` | 포함 가능 |
| `~/.pulumi/credentials.json` | 기본 제외 |
| Access token env | 절대 백업 안 함 |

### 17.4 shell_prompt (v0.13.0)

shell prompt 도구(starship, powerlevel10k)의 **설정 파일**을 백업·동기화한다.
`anvyc prompt` 명령(§27.9)이 prompt 에 anvyc 라우팅 세그먼트를 노출한다면,
이 어댑터는 prompt 도구 자신의 설정(컬러·세그먼트 정의 등)을 다른 머신에
재현할 수 있게 한다.

#### 17.4.1 포함 / 제외 정책

| 경로 | 정책 | 이유 |
|---|---|---|
| `~/.config/starship.toml` | 기본 포함 | starship 의 단일 설정 파일 — 순수 텍스트, 머신 비의존 |
| `~/.p10k.zsh` | 기본 포함 | powerlevel10k wizard 결과 — `~/.zshrc` 가 `source` 하는 표준 위치 |
| `~/.cache/p10k-*` | **제외** | instant-prompt 캐시 — 재생성 가능한 머신 로컬 파일 |
| p10k 테마 fork | 미추적 | `~/.zsh/themes/` 등 사용자 정의 위치는 명시 적용 필요 |

두 도구는 동일 도메인(shell prompt 설정)이고 사용자는 보통 하나만 쓰므로
**단일 `shell_prompt` 어댑터**로 묶는다 — `collect()` 가 존재하는 파일만
포함해, 두 도구 동시 설치를 강제하지 않는다.

#### 17.4.2 어댑터 표면

```python
class ShellPromptAdapter:
    name = "shell_prompt"
    DEFAULT_FILES = ("~/.config/starship.toml", "~/.p10k.zsh")

    def detect(self) -> bool:        # 둘 중 하나라도 존재하면 True
    def collect(self) -> [ManagedFile]:  # 존재하는 파일만 ManagedFile 로
    def validate(self) -> []:        # 추가 검증 없음 (텍스트 파일)
```

`apply` / `diff` / `target_hash` 는 기본 텍스트 어댑터 패턴(§11)을 따른다 —
별도 plist/JSON 파싱 없이 raw 텍스트 동기화. starship.toml 의 TOML 파싱 오류
검증은 starship 자체에 위임한다 (anvyc 가 도구 동작을 추측하지 않음).

#### 17.4.3 secret 영역

starship/p10k 설정 파일은 일반적으로 secret 을 포함하지 않는다. 단, 사용자가
custom command 에 raw token 을 박을 가능성이 있으므로 secret scanner 의
일반 패턴(§13)을 그대로 적용한다 — 별도 allowlist 없음.

#### 17.4.4 호환성 / 마이그레이션

- 신규 어댑터 추가 — 어댑터 수 9 → **10** (`anvyc tools list` 카운트 변경).
- 기존 사용자: `~/.config/starship.toml` 또는 `~/.p10k.zsh` 가 없으면 silent
  (`enabled: true` 가 기본이지만 `detect()` False).
- yaml 명시 비활성화 가능: `tools.shell_prompt.enabled: false`.

---

## 18. Metadata 설계

### 18.1 metadata.json 예시

```json
{
  "schemaVersion": 1,
  "generatedAtUtc": "2026-05-17T04:20:00Z",
  "hostname": "Edwardui-MacBookAir.local",
  "os": "macOS",
  "osVersion": "26.5",
  "arch": "arm64",
  "anvycVersion": "0.1.0",
  "includedTools": ["shell", "git", "aws", "cursor", "claude", "iterm2"],
  "excludedSensitivePaths": [
    "~/.aws/credentials",
    "~/.pulumi/credentials.json",
    "~/Library/Application Support/Cursor/User/workspaceStorage"
  ],
  "files": [
    {
      "sourcePath": "shell/zshrc",
      "targetPath": "~/.zshrc",
      "sha256": "example",
      "mode": "0600"
    }
  ]
}
```

### 18.2 Metadata 용도

| 용도 | 설명 |
|---|---|
| 무결성 검증 | backup 파일 손상 탐지 |
| drift 판단 | target과 backup hash 비교 |
| 복구 추적 | 어떤 장비에서 어떤 설정을 적용했는지 추적 |
| 호환성 확인 | OS/arch 차이에 따른 적용 가능 여부 판단 |

---

## 19. 기술 스택

### 19.1 MVP 권장: Python

| 항목 | 선택 |
|---|---|
| CLI | Typer |
| 출력 | Rich |
| 설정 검증 | pydantic |
| 경로 패턴 | pathspec |
| 테스트 | pytest |
| 패키징 | pipx 또는 uv |
| plist 처리 | plistlib |
| 암호화 | age (또는 cryptography) |

### 19.2 장기 옵션: Go

Go는 단일 바이너리 배포에 유리하다. chezmoi 자체도 Go 기반이다. 다만 MVP 속도와 adapter 실험 편의성을 고려하면 초기에는 Python이 적합하다.

---

## 20. 테스트 전략

### 20.1 Unit Test

| 대상 | 테스트 |
|---|---|
| path normalization | `~`, symlink, relative path 처리 |
| secret scanner | token pattern 탐지 |
| metadata generator | hash, timestamp 생성 |
| ignore rule | include/exclude 우선순위 |
| adapter collect | 예상 파일 목록 반환 |
| plist parser | iTerm2 safe subset 추출 |

### 20.2 Integration Test

| 시나리오 | 검증 |
|---|---|
| clean backup | 정상 백업 |
| secret 포함 파일 | backup 중단 |
| apply dry-run | target 미변경 |
| apply 실제 적용 | target 갱신 및 local backup 존재 |
| restore | target 복원 및 무결성 검증 |
| 권한 없음 | 명확한 오류 메시지 |
| target 파일 충돌 | diff 표시 후 중단 |
| symlink 대상 불명 | 경고 |
| Git repo dirty | commit 전 경고 |
| encrypted secret 복호화 실패 | apply 중단 |
| JSON 깨짐 | adapter validation 실패 |
| plist 파싱 실패 | iTerm2 adapter 중단 |

---

## 21. 개발 일정

### 21.1 1주차 — PoC

| 작업 | 산출물 |
|---|---|
| CLI skeleton | `anvyc init/backup/status` |
| config schema | `anvyc.yaml` 로더 |
| shell adapter | `.zshrc`, `.zprofile` 백업 |
| git adapter | `.gitconfig` 백업 |
| aws adapter | `~/.aws/config` 백업 (credentials 제외) |
| secret scanner v0 | 기본 패턴 6종 지원 |

### 21.2 2주차 — MVP

| 작업 | 산출물 |
|---|---|
| Cursor adapter | settings/keybindings/snippets |
| Claude adapter | settings/hooks 중심 |
| iTerm2 safe adapter | profiles/key mappings |
| diff 구현 | unified diff |
| apply dry-run | 변경 미적용 검증 |
| restore 전 local backup | 자동 백업 |
| pre-commit hook | secret 차단 |
| Git integration | status/commit helper |
| encrypted secrets PoC | age 또는 GPG |
| doctor | 위험 경로/권한 진단 |
| README | 사용 절차 문서화 |

### 21.3 3주차 — 정비

| 작업 | 산출물 |
|---|---|
| unit test 보강 | 핵심 모듈 커버리지 80%+ |
| integration test | fixtures 기반 |
| macOS 경로 검증 | 실제 환경 테스트 |
| failure handling | 오류 메시지 정리 |
| release packaging | pipx 또는 Homebrew tap |
| v0.1.0 릴리즈 | MVP 배포 |

---

## 22. 성공 케이스

### 22.1 새 Mac 부트스트랩

```text
새 Mac에서 anvyc init → anvyc apply <repo>
shell/git/cursor/claude/iterm2 설정 즉시 복원
credentials는 복원하지 않고 config만 복원
→ secret은 1Password 또는 별도 encrypted channel에서만 주입
```

### 22.2 iTerm2 단축키 표준화

```text
기존 Mac에서 iTerm2 key mappings 백업
새 Mac에서 적용
→ Command+←/→, Option+←/→ 등 동일 동작
```

### 22.3 팀 표준 Cursor 설정 배포

```text
공통 rules, keybindings, formatter 설정만 repo에 포함
개인 token, workspace history는 제외
```

---

## 23. 실패 케이스와 대응

| 실패 케이스 | 영향 | 대응 |
|---|---|---|
| `~/.aws/credentials` 백업 | AWS key 유출, 비용 피해 | 기본 제외, secret scan, pre-commit hook |
| iTerm2 plist 전체 덮어쓰기 | UI 상태, 창 배치, 최근 세션 꼬임 | safe subset만 추출 |
| Claude session/token 백업 | 계정 탈취 위험 | sessions/tokens/cache 기본 제외 |
| apply 중 실패 | 설정 일부만 반영 | local backup, transactional apply 설계 |
| secret scanner false positive | 사용성 저하 | confidence 등급, allow rule 제공 |

---

## 24. chezmoi 사용 vs 직접 개발 비교

| 항목 | chezmoi 사용 | anvyc 직접 개발 |
|---|---:|---:|
| 즉시 사용성 | 높음 | 낮음 |
| 개발 비용 | 낮음 | 높음 |
| 범용성 | 높음 | 제한적 |
| Cursor/Claude/iTerm2 특화 | 직접 구성 필요 | 기본 제공 |
| Secret 정책 | 일반적 | 도구별 특화 |
| macOS plist safe subset | 직접 구성 필요 | 기본 제공 |
| 팀 표준 배포 | 가능 | 향후 자연스럽게 확장 |

---

## 25. MVP 완료 기준

| 기준 | 완료 조건 |
|---|---|
| 백업 | shell/git/aws/cursor/claude/iterm2 설정 백업 가능 |
| 보안 | AWS credentials, token, private key 백업 차단 |
| 복원 | apply 전 local backup 자동 생성 |
| 검토 | diff/dry-run 지원 |
| 이력 | metadata와 hash 저장 |
| 문서 | README/DESIGN 최신화 |
| 배포 | pipx 또는 Homebrew로 설치 가능 |

---

## 26. 바로 실행 가능한 초기 작업

### 26.1 저장소 생성

```bash
mkdir anvyc
cd anvyc
git init
```

### 26.2 Python 프로젝트 초기화

```bash
cat > pyproject.toml <<'EOF'
[project]
name = "anvyc"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "typer",
  "rich",
  "pydantic",
  "pathspec",
  "pyyaml"
]

[project.scripts]
anvyc = "anvyc.cli:app"
EOF
```

### 26.3 기본 구조 생성

```bash
mkdir -p src/anvyc/{core,adapters,security,storage,utils}
mkdir -p tests/{unit,integration,fixtures}
mkdir docs examples
touch src/anvyc/__init__.py
touch src/anvyc/cli.py
```

### 26.4 MVP adapter 우선순위

```text
1. shell
2. git
3. aws
4. cursor
5. claude
6. iterm2
7. pulumi
```

---

## 27. Doctor 명령 설계

`anvyc doctor`는 backup/apply 전에 환경을 read-only로 진단한다. 자동 수정은 하지 않는다.

### 27.1 진단 카테고리

| 카테고리 | 내용 |
|---|---|
| 도구 설치 | 각 adapter `detect()` |
| 경로 권한 | 0600 파일이 읽기 가능한지, 쓰기 권한 |
| Secret 잔존 | `scan-secrets` 일부 (configurable) |
| Cross-user 경로 | 본 §27.3 |
| iTerm2 plist 안전성 | window state / recent sessions 잔존 여부 |
| Cursor symlink 무결성 | `~/.cursor/**` symlink 대상 존재 여부 |
| Multi-account 환경 (v0.6.1) | `.envrc` ↔ `~/.aws/config` mapping, active profile, ssh/cursor alias |

#### 27.1.1 등록된 check 목록 (20종, CP-13 머지 시점)

SoT = `src/anvyc/core/doctor.py` 의 `_REGISTRY`. 카테고리별 묶음:

**기본 환경 / adapter**

| check_name | 영역 | 추가 |
|---|---|---|
| `cross-user` | 경로 username 분류 (§27.3) | v0.1.0 |
| `venv-hidden-flag` | macOS UF_HIDDEN trap (`.venv`) | v0.1.0 |
| `op-references-valid` | `op://` reference 검증 | v0.1.0 |
| `adapter-validate` | adapter 자체 validate wrap | v0.1.0 |
| `cursor-projects-suggest` | candidate root 의 `.cursor/` 발견 안내 | v0.1.0 |
| `sops-keys-available` | sops/age binary + age identity | v0.2.0 |

**MCP**

| check_name | 영역 | 추가 |
|---|---|---|
| `mcp-tokens-warn` | mcp.json 의 raw token 패턴 | v0.2.1 |
| `mcp-extra-importable` | `[mcp]` extra 미설치 silent failure 차단 | v0.15.2 |

**per-project 계정 라우팅** (§32.4)

| check_name | 영역 | 추가 |
|---|---|---|
| `project-aws-profile-mapping` | `.envrc` AWS_PROFILE ↔ `~/.aws/config` | v0.6.1 |
| `project-gh-account-mapping` | `.envrc` `GH_CONFIG_DIR` ↔ GitHub origin ssh alias | v0.11.0 |
| `project-claude-account-mapping` | `.envrc` `CLAUDE_CONFIG_DIR` → config 디렉터리 존재 | v0.12.0 |
| `project-pulumi-backend-mapping` | `Pulumi.yaml` backend ↔ `.envrc` `PULUMI_BACKEND_URL` | v0.12.0 |

**multi-account 환경 진단**

| check_name | 영역 | 추가 |
|---|---|---|
| `aws-profile-status` | 현재 `AWS_PROFILE` env var 정합성 | v0.6.1 |
| `multi-account-detected` | AWS ≥ 2 + ssh alias + cursor alias + `~/.claude-*` | v0.6.1 |
| `unused-aws-profiles` | `~/.aws/config` 에만 있고 미사용인 profile | v0.7.0 |

**Control plane axes** (각 axis 본문은 [docs/design-axes/](../docs/design-axes/) 참조)

| check_name | 영역 | 추가 |
|---|---|---|
| `creds-expiry-within-7d` | AWS SSO / GitHub PAT / Claude OAuth 만료 사전 감지 (CP-5) | v0.14.0 |
| `cost-aws-explorer-iam` | `SimulatePrincipalPolicy` 로 `ce:GetCostAndUsage` 권한 부재 감지 (CP-13) | CP-13 |
| `cost-github-pat-scope` | fine-grained PAT 의 billing endpoint smoke 호출 (CP-13) | CP-13 |
| `hook-integrity-risk-gate` | risk-gate hook 의 배선 정합성 (CP-8) | v0.14.x |
| `work-cwd-track-wired` | work-cwd hook + `env.WORK_CWD_CACHE` 주입 검증 (CP-12) | v0.15.0 |

### 27.2 모듈 구조

```
src/anvyc/
├── checks/                  # 재사용 Check 컴포넌트
│   ├── __init__.py
│   ├── base.py              # Severity, CheckResult, CheckContext
│   └── cross_user.py        # §27.3 구현
└── core/
    ├── doctor.py            # check 등록/실행 orchestrator
    └── project_roots.py     # 프로젝트 루트 SoT (§27.8)
```

`CheckResult`는 `(check_name, severity, message, location, line?, suggestion?)` 5~6필드 dataclass.
Adapter `validate()`도 동일 `CheckResult`를 반환하도록 통합한다 → doctor가 adapter validate까지 묶어 단일 리포트.

### 27.3 Cross-user audit (핵심)

#### 27.3.1 배경

macOS에서 사용자 이름을 바꾸거나 `/Users/<old> -> /Users/<new>` symlink로 호환성을 유지하는 경우, dotfile 내부에 `/Users/<old>/...` 절대 경로가 남는다. 같은 머신에서는 alias 덕에 동작하지만 다른 머신에 적용하면 dangling이 된다.

#### 27.3.2 분류 (5단계)

| Severity | 조건 | 의미 |
|---|---|---|
| Info | path username == `whoami` | 자기 자신 |
| Info-aliased | path가 symlink로 현재 user home에 resolve | 현재 머신에서 동작, 타 머신에서 broken |
| Warning-foreign | path username이 실재 다른 user (다른 UID) | 머신 간 이식 시 권한 충돌 가능 |
| Warning-dangling | path 미존재 | 깨진 참조 |
| Critical | secret 영역 파일 (SSH key/AWS profile 등) 안의 cross-user 경로 | 의도치 않은 sync 위험 |

#### 27.3.3 탐지 범위

| 카테고리 | 대상 | 탐지 방법 |
|---|---|---|
| 디렉터리 이름 prefix | `~/.cursor/projects/Users-*-*` | name decode |
| Symlink target | `~/.cursor/**` (depth 3) | `readlink` |
| 텍스트 content | `.zshrc`, `.zprofile`, `.gitconfig`, `~/.ssh/config{,.d/*}`, Cursor `settings.json`/`keybindings.json`, `~/.claude/{settings.json,CLAUDE.md}` | regex `/Users/([a-z][a-z0-9_.-]+)/` |
| iTerm2 plist | profile working directory 키 (Phase 2) | plistlib + 동일 regex |

#### 27.3.4 alias 선언

```yaml
doctor:
  cross_user:
    enabled: true
    known_user_aliases:
      aliasuser: edward
    scan_targets:
      - "~/.cursor/projects"
      - "~/.zshrc"
      - "~/.zprofile"
      - "~/.gitconfig"
      - "~/.ssh/config"
      - "~/.ssh/config.d"
      - "~/Library/Application Support/Cursor/User/settings.json"
      - "~/Library/Application Support/Cursor/User/keybindings.json"
      - "~/.claude/settings.json"
      - "~/.claude/CLAUDE.md"
    severity_overrides: {}    # path glob → severity
```

선언된 alias는 Warning-foreign → Info-aliased로 강등된다.

#### 27.3.5 출력 예 (실측 환경 기반)

```
[cross-user audit]
  Aliased users:
    aliasuser → edward (declared)
  Findings:
    cursor/projects        13 entries reference /Users/aliasuser/...
                           → Info (aliased, regenerable cache, 백업 대상 아님)
    ssh/config.d/30-teleport.conf:3-5
                           → Info-aliased, NOT portable
                           → suggest: $HOME 또는 ~/ 형식으로 정규화
    cursor/rules.bak-20260206-092948 → /Users/aliasuser/.../role-based-ruleset
                           → Info (Layer A `rules.bak-*` 제외 정책에 의해 백업 대상 아님)
  Summary: 0 critical, 0 warning, 20 info
```

### 27.4 CLI 옵션

```bash
anvyc doctor                       # 요약
anvyc doctor --verbose             # 모든 finding 나열
anvyc doctor --strict              # warning 이상 시 exit code 1
anvyc doctor --json                # 기계 가독 JSON 출력
anvyc doctor --only cross-user     # 특정 check만
anvyc doctor --skip cross-user     # 특정 check 제외
```

#### 27.4.1 `--json` schema (v0.5.3 정식화)

```json
{
  "results": [
    {
      "check_name": "cross-user",
      "severity": "warning-foreign",
      "message": "/Users/aliasuser/ in plist key '…'",
      "location": "/Users/edward/Library/Preferences/com.googlecode.iterm2.plist",
      "line": null,
      "suggestion": "…"
    }
  ],
  "summary": {
    "info": 11,
    "info-aliased": 0,
    "warning": 1,
    "warning-foreign": 21,
    "warning-dangling": 0,
    "critical": 0
  }
}
```

필수 필드:
- top-level: `results` (list), `summary` (dict)
- result entry: `check_name`/`severity`/`message` 필수, `location`/`line`/`suggestion` 은 `null` 가능
- summary: 6 severity 모두 포함 (0 카운트도 명시)

회귀 안전망: `tests/integration/test_doctor_json.py` 가 5 case 로 schema 안정성을 검증한다.

### 27.5 안전 원칙

- Doctor는 **read-only**. 어떤 파일도 수정하지 않는다.
- Cross-user finding은 backup/apply에 영향을 주지 않는다 (정보 제공만).
- `--fix` 모드는 v0.2 이후 별도 검토. 1차 후보: SSH config의 `/Users/<alias>/` → `$HOME` 또는 `~/` 정규화 제안.

### 27.6 구현 단계

| 단계 | 작업 | 시기 |
|---|---|---|
| 1 | `checks/base.py` — Severity/CheckResult/Context 정의 | 1주차 PoC |
| 2 | `checks/cross_user.py` — regex + alias resolution + 분류 | 1주차 |
| 3 | `core/doctor.py` — orchestrator + cli 옵션 | 1주차 |
| 4 | iTerm2 plist 대응 (profile working directory) | 2주차 |
| 5 | Adapter `validate()`를 CheckResult로 통합 | 2주차 |
| 6 | `--fix` 모드 검토 | v0.2 이후 |

### 27.7 dev wrapper / contributor 설치 자동화 (v0.11.0)

`§27.1.1` 의 `venv-hidden-flag` check 는 macOS `UF_HIDDEN` trap 을 *진단*만 한다.
contributor 환경에서 이를 *회피*하는 메커니즘이 dev wrapper 다.

**문제**: macOS + Python 3.13.13+ 에서 editable install (`pip install -e .`) 의
`.pth` 가 `UF_HIDDEN` flag 때문에 `site.addpackage()` 에서 silent skip 되어 `anvyc`
가 주기적으로 `ModuleNotFoundError` 로 깨진다 (상세: `docs/troubleshooting-macos.md`).

**설계 결정**:

| 결정 | 내용 | 근거 |
|---|---|---|
| PYTHONPATH wrapper | `~/.local/bin/anvyc` 가 repo `src/` 를 `PYTHONPATH` 로 주입하고 `python -m anvyc` 로 `exec` | editable `.pth` 미경유 → UF_HIDDEN trap 자체를 회피 (chflags self-heal 불필요) |
| wrapper 정본 = 저장소 자산 | `scripts/anvyc-wrapper.sh` 가 SoT, 손수 작성 금지 | 경로·버전 하드코딩 재발 방지 (사례: `~/Documents`→`~/dev` 이전 시 실행 불능) |
| 환경 비의존 | wrapper 가 `$HOME` + `ANVYC_VENV` override 로 venv 해석, sibling `src/anvyc` 로 anvyc repo 확인 | 디렉터리 이전·Python 마이너 업그레이드에 견딤. venv 부재 시 침묵 대신 명시적 에러 |
| 멱등 설치 스크립트 | `scripts/dev-install.sh` — venv·editable 설치·wrapper 설치를 1회 실행으로 | contributor 가 환경을 한 줄로 복구 |
| `scripts/` wheel 제외 | `pyproject.toml` `packages = ["src/anvyc"]` 가 `src/anvyc` 만 포함 | wrapper 는 contributor 전용 — 배포 wheel 과 분리 |

**적용 범위**: editable install 에 한정. 일반 사용자 경로(`uv tool install` / `pipx`
— `install.sh`)는 격리 venv 에 비-editable 설치라 `.pth` 를 쓰지 않아 trap 과 무관하다.

**`.pth` trap 근본 회피 (v0.13.0, §3.4)**: wrapper 는 editable `.pth` 대신
`PYTHONPATH` 로 `src/` 를 주입하고 `python -m anvyc` (진입점 `src/anvyc/__main__.py`)
로 실행한다. `.pth` 를 거치지 않으므로 UF_HIDDEN trap 이 wrapper 실행 경로에
영향을 주지 않는다 (chflags self-heal 제거). 상세는
`docs/archive/improvement-plan-dev-wrapper.md` §3.4.

### 27.8 프로젝트 루트 SoT (v0.11.0)

anvyc 가 "사용자 프로젝트 루트" 아래를 스캔하는 모든 경로 — doctor 의
`project-aws-profile-mapping`·`project-gh-account-mapping`·`project-claude-account-mapping`
·`project-pulumi-backend-mapping`·`unused-aws-profiles` 다섯 check, `anvyc project list`
(및 MCP `project_list`), `dev_env` 어댑터, `cursor-projects-suggest` check — 는
`core/project_roots.py` 를 SoT 로 참조한다.

- `DEFAULT_PROJECT_ROOTS` — `~/dev` 를 선두로 한 7-루트 기본값. 정적 fallback 이
  필요한 곳(`discover_projects`·`dev_env`·`cursor-projects-suggest`)이 직접 참조.
- `resolve_project_roots(config)` — anvyc.yaml 의 top-level `project_roots` 를 읽고,
  없으면 `DEFAULT_PROJECT_ROOTS` 로 fallback. config 인지가 필요한 진입점
  (doctor 5 check, `project list`, MCP `project_list`)이 호출.

설정 예:

```yaml
project_roots:
  - ~/dev
  - ~/work
```

doctor 세 check 와 `project list`/MCP 진입점은 `resolve_project_roots()` 로 멀티
루트를 순회하며 `Path.resolve()` 로 중복 디렉터리를 제거한다. `dev_env` 어댑터는
별도로 `tools.dev_env.project_roots` config 를 쓰고 SoT 상수는 fallback 으로만 쓴다.

### 27.9 `anvyc prompt` 명령 (v0.13.0)

`anvyc prompt` 는 현재 디렉터리의 per-project 계정 라우팅(§32.4a/b/c) 을 shell
prompt 용 한 줄로 출력한다. `project show` 를 매번 실행하지 않고도 라우팅
상태를 prompt 에 상시 표시할 수 있게 한다. starship custom command / p10k
세그먼트 연동 가이드는 `docs/shell-prompt.md`.

**출력 형식**:

| 모드 | 출력 | 빈 결과 |
|---|---|---|
| default | `aws:<v> gh:<v> claude:<v> pulumi:<v>` (설정된 키만 공백 구분) | 빈 출력 |
| `--json` | `{"aws":"...", "gh":"...", ...}` | `{}` |

**필드 매핑** — 모두 `ProjectInfo` 파생 값:

| key | 출처 |
|---|---|
| `aws` | `.envrc` 의 `AWS_PROFILE` (§32.4) |
| `gh` | `.envrc` 의 `GH_CONFIG_DIR` → 계정 (§32.4a) |
| `claude` | `.envrc` 의 `CLAUDE_CONFIG_DIR` → 계정 (§32.4b) |
| `pulumi` | `Pulumi.yaml` 의 `backend.url` (§32.4c) |

**설계 결정**:

| 결정 | 내용 | 근거 |
|---|---|---|
| **never break the shell** | 어떤 예외도 잡아 빈 출력 + exit 0 | prompt 호출이 셸을 깨면 사용자 경험이 무너짐 — read-only 명령이라 안전 |
| 파생 필드만 출력 | `ProjectInfo.aws_profile` 등 라우팅 값만, raw secret 없음 | dev_env redaction 불필요 → `redact_secrets=False` 로 호출 후 secret 필드 미참조 |
| 도구 비의존 — stdout 한 줄 | starship/p10k 모두 stdout 텍스트를 그대로 임베드하는 인터페이스 | 어댑터 매뉴얼 분리 — anvyc 는 텍스트만 책임, 스타일링은 prompt 도구 |
| `--path` 옵션 | default `Path.cwd()` | 테스트·tab 전환 시 임의 디렉터리 조회 가능 |
| 호출 비용 ~70ms | starship `command_timeout` 기본 500ms 이내 | 매 prompt 호출 — `project show` 보다 가벼운 read-only path 만 사용 |

`prompt` 자체는 어떤 파일도 쓰지 않으며 secret 을 출력하지 않는다 — apply/backup
경로의 secret 정책(§13)과 직교한다.

---

## 28. 최종 의사결정

이 프로젝트는 chezmoi를 대체하는 범용 dotfiles manager가 아니라, chezmoi의 안전 원칙을 참고한 **개발환경 특화 config sync tool**로 개발한다.

핵심 차별점은 다음이다.

```text
1. 도구별 adapter
2. secret 기본 제외
3. apply 전 diff
4. restore 전 local backup
5. iTerm2/Cursor/Claude Code safe subset 정책
6. Git push 전 secret scan
7. macOS 개발자 환경에 최적화된 UX
```

MVP는 Python으로 빠르게 구현하고, 실제 Mac 2대에서 end-to-end 검증한 뒤 필요 시 Go 기반 단일 바이너리 배포로 전환을 검토한다.

---

## 29. 릴리스 로드맵

릴리스별 변경 내역의 **단일 소스**는 [RELEASE_NOTES.md](./RELEASE_NOTES.md) 다.
본 섹션은 마일스톤 수준의 진행 상태만 요약하고, 상세 변경 내역·근거·migration
은 RELEASE_NOTES 를 참조한다.

### 29.1 출시된 마일스톤

| 버전 | 핵심 변경 | 관련 §·문서 |
|---|---|---|
| v0.1.0 | MVP — apply/restore + 8 adapter + Git sync + 1Password reference | §10~17, §30 |
| v0.2 | SOPS encryption-at-rest | §31 |
| v0.5.x | iTerm2 status 정합화 + SOPS per-file override + sops 단독 CLI | §14, §31 |
| v0.6.x | Homebrew tap + `--from-git` + multi-account doctor checks + 호스트별 overlay | §27.1.1 |
| v0.7.x | `dev_env` 어댑터 + interactive wizard + `install.sh` one-liner | §17.4 인접 |
| v0.8.x | `project show/list/doctor` (AI agent multi-project view) | §32, §33 |
| v0.9.0 | MCP server (`anvyc serve --mcp`, 5 read-only tool) | §34 |
| v0.10.0 | MCP tool naming cleanup (`anvyc_` prefix 제거, breaking) | §34.9 |
| v0.11.0 / v0.12.0 | per-project gh/Claude/Pulumi 계정 라우팅 인식 + 프로젝트 루트 SoT | §27.8, §32.4a/b/c |
| v0.13.0 | shell prompt 통합 — `anvyc prompt` 세그먼트 + `shell_prompt` 어댑터 + dev wrapper PYTHONPATH | §17.4, §27.7, §27.9 |

§21·구 Post-PoC 로드맵의 phase 분류·일일 일정은 v0.1.0 MVP 단계에서 소진되어
RELEASE_NOTES 의 버전별 릴리스 노트로 대체되었다.

### 29.2 진행 중 / 후속 작업

본 섹션은 RELEASE_NOTES 와 중복되지 않게, **DESIGN 차원에서 추적 가치가 있는**
미해결 항목만 명시한다.

| 항목 | 상태 | 비고 |
|---|---|---|
| v1.0 API stable + PyPI 배포 | 계획 | §32.7 / §34.9 schema 안정성 정책 그대로 — major 변경만 허용 |
| MCP write 영역 노출 (backup/apply 등) | 의도적 보류 | §34.5 — destructive 자동 실행 위험, 사용자 명시 CLI 유지 |
| MCP SSE / multi-client transport | 향후 | §34.8 — stdio 단일 client 한계 |

---

## 30. Secret 분리 정책 (v0.1.0: 1Password Secret Reference)

§13 Secret Scanner 와 보완 관계. v0.1.0 은 1Password Secret Reference 를 1차 솔루션으로 채택한다.

### 30.1 1Password Secret Reference 란

```
op://<vault>/<item>/<field>
```

1Password 의 실제 secret 을 가리키는 URI. 이 URI 자체는 secret 이 아니며 (값 노출 없음), Git 에 commit 해도 안전하다.

사용자는 dotfile 에 raw secret 대신 reference 를 적고, 런타임에 `op inject` / `op run` 등으로 resolve 한다.

```bash
# .zshrc 예
export AWS_ACCESS_KEY_ID="op://Personal/AWS/access_key_id"
export AWS_SECRET_ACCESS_KEY="op://Personal/AWS/secret_access_key"
```

### 30.2 anvyc 의 처리 정책

1. **Backup**: 파일 내용을 그대로 보존한다. `op://` reference 는 안전하므로 마스킹/제외 X.
2. **Secret scan**:
   - `op://...` URI 가 같은 라인에 있으면, **그 라인의 다른 secret 패턴 매칭을 false-positive 로 강등** 한다 (값이 placeholder 라는 신호).
   - `op://` 가 없는데 raw secret 이 발견되면 기존 정책대로 차단.
3. **Apply**: 파일을 그대로 복원. resolve 는 shell/도구가 런타임에 수행.
4. **Doctor**: `op-references-valid` check (op CLI 설치 시) — 발견된 `op://` URI 들을 `op read --no-newline` 으로 resolve 시도. 실패 시 WARNING.

### 30.3 패턴 정의

```python
OP_REFERENCE_RE = re.compile(r"\bop://[^/\s\"']+/[^/\s\"']+/[^/\s\"']+(?:/[^/\s\"']+)?")
```

vault/item/field, optional sub-field.

### 30.4 사용자 가이드 (README 에 반영)

```
1. 1Password CLI 설치 + 로그인 (op signin)
2. 민감 값을 1Password 에 등록
3. dotfile 안의 raw secret 을 op:// reference 로 치환
4. anvyc backup → reference 는 그대로 들어감
5. 다른 머신에서 anvyc apply 후 1Password 로그인만 하면 동일 환경
```

### 30.5 SOPS (v0.2)

암호화-at-rest 가 필요한 secret (1Password 에 두기 곤란한 대용량 key 등) 은 v0.2 에서 SOPS 통합으로 다룬다. `~/.anvyc-secrets/` 영역에 SOPS-encrypted YAML 로 저장, age/gpg/cloud KMS key 로 복호화.

### 30.6 안전 원칙

- 1Password Secret Reference 는 **placeholder** 다. raw secret 의 대체이지 보안 솔루션이 아니다.
- 1Password 자체 인증 (계정, 마스터 키) 은 anvyc 가 다루지 않는다.
- `op://` reference 가 가리키는 vault/item/field 이름이 secret 성격을 내포하는 경우 (예: `op://Personal/CompanyTopSecret/Project`) 는 사용자 책임. anvyc 는 reference 문자열 자체만 안전한 것으로 처리.

---

## 31. SOPS 통합 (v0.2)

§30 의 1Password Secret Reference 와 보완 관계. 다수 secret 묶음 (`.env`, `.toml`, 바이너리 등) 을 encryption-at-rest 로 처리한다.

### 31.1 결정 확정 (V1~V4, 2026-05-18)

| # | 항목 | 결정 |
|---|---|---|
| V1 | SOPS 파일 저장 위치 | `.anvyc/` 안에 git-tracked. SOPS 본래 목적 (암호화 자체가 보호) |
| V2 | 키 backend 기본 | **age** (cross-platform, key file 단순) |
| V3 | mcp.json 자동 마스킹 처리 시점 | v0.2.1 분리 (SOPS 와 결이 다름) |
| V4 | 1Password Reference 와의 관계 | 양립 — 사용자 선택 |

### 31.2 사용 모델

| 시나리오 | 권장 도구 |
|---|---|
| 단일 변수 raw secret (`export AWS_KEY=...`) | `op://...` reference (§30) |
| `.env`, `.toml`, `.json` 등 다수 secret 묶음 | SOPS 암호화 (본 절) |
| 사용자가 1Password 미사용 | SOPS 단독 |

### 31.3 의존성

- `sops` binary (사용자 설치: `brew install sops`)
- `age` binary (사용자 설치: `brew install age`)
- anvyc 는 둘 다 subprocess 로 호출 — Python 의존성 추가 X

### 31.4 anvyc.yaml schema 확장

```yaml
security:
  secret_scan: true
  block_on_secret: true
  sops:
    enabled: true
    age_recipients:         # 암호화 대상 키 (여러 머신/사용자의 public key)
      - "age1abc...edward-mac"
      - "age1xyz...edward-laptop"
    age_identity_file: "~/.config/sops/age/keys.txt"

tools:
  pulumi:
    enabled: true
    files: ["~/.pulumi/config.json"]
    secret_files:           # 신규 — SOPS 로 암호화 백업
      - "~/.pulumi/credentials.json"
  shell:
    enabled: true
    files: ["~/.zshrc"]
    secret_files: ["~/.env"]
```

### 31.5 Backup workflow

```text
1. 일반 files       → shutil.copy2 (기존 그대로)
2. secret_files     → sops -e --age <recipients> <src> > backup/<ts>/<tool>/sops/<name>.enc
3. metadata.json files[] 에 추가 필드:
     "encryption": "sops/age"
4. 암호화 파일의 sha256 도 기록 (변경 감지용)
```

### 31.6 Apply workflow

```text
1. 일반 entry             → _default_apply
2. encryption=sops/age   → sops -d <src> > <target> + chmod
3. key 부재 시            → state_after="error", error="sops decrypt failed: 키 부재"
```

### 31.7 새 doctor check: `sops-keys-available`

```text
- sops binary 미설치  → WARNING + "brew install sops"
- age binary 미설치   → WARNING + "brew install age"
- age identity 미존재 → WARNING + "age-keygen -o ~/.config/sops/age/keys.txt"
- 모두 OK            → 0 결과 (clean)
```

### 31.8 scanner 의 SOPS 인식

`security/scanner.py` 가 다음 조건 중 하나면 scan skip:
- 파일명에 `.sops.` 포함 (예: `secret.sops.json`)
- 파일 내용 첫 4KB 안에 `"sops":` 또는 `sops:` metadata block

암호화된 파일에서 base64 등이 secret 처럼 보여도 false-positive 방지.

### 31.9 구현 단계

| 단계 | 작업 |
|---|---|
| V2.1 | doctor check `sops-keys-available` + 설치 가이드 |
| V2.2 | anvyc.yaml schema 확장 (security.sops, tools.*.secret_files) |
| V2.3 | core/sops.py — subprocess wrapper (encrypt/decrypt/is_sops_encrypted) |
| V2.4 | backup orchestrator 의 SOPS encrypt branch |
| V2.5 | apply orchestrator 의 SOPS decrypt branch |
| V2.6 | scanner 의 .sops.* 파일 자동 인식 |
| V2.7 | CLI 출력 (encrypted 마커) |
| V2.8 | integration test (round-trip + key 부재 시나리오) |
| V2.9 | README §9.2 / DESIGN §31 / RELEASE_NOTES v0.2 + tag |

### 31.10 보안 원칙

- anvyc 는 age private key 를 직접 다루지 않는다 (sops/age binary 에 위임).
- key 부재 시 apply 는 **fail-safe**: 부분 적용 X, 에러 + 다음 entry 진행.
- pre-commit hook 의 scan-secrets 는 SOPS 파일을 통과시킨다 — 이미 암호화되어 있어 raw secret 노출 위험 없음.
- `~/.anvyc-secrets/` 영역은 v0.2 에서 도입하지 않는다 (V1 결정). SOPS-in-anvyc/ 단일 모델로 충분.

---

## 32. `project show` JSON schema (v0.8.0, AI agent integration)

### 32.1 배경

[improvement-plan-ai-agent.md](./docs/archive/improvement-plan-ai-agent.md) Wave 7. AI agent
(Claude Code / Cursor / ChatGPT) 가 cwd 의 모든 connection 정보 (AWS profile /
GitHub remote / Pulumi project / dev_env / tool versions) 를 단일 JSON 으로 받기
위한 정식 schema. `anvyc project show --json` 출력의 외부 호환 보장.

### 32.2 Top-level

| key | type | nullable | 설명 |
|---|---|---|---|
| `path` | string | no | 입력 path 의 resolve 된 절대 경로 |
| `aws_profile` | string | yes | `.envrc` 의 `export AWS_PROFILE=X` 값 (편의 single-field) |
| `gh_account` | string | yes | `.envrc` 의 `export GH_CONFIG_DIR=X` 경로에서 도출한 gh 계정 (§32.4a) |
| `claude_account` | string | yes | `.envrc` 의 `export CLAUDE_CONFIG_DIR=X` 경로에서 도출한 Claude Code 계정 (§32.4b) |
| `github` | array | yes | parse 된 git remote 목록 (없으면 null) |
| `pulumi` | object | yes | Pulumi project info (Pulumi.yaml 없으면 null) |
| `dev_env` | object | no | `.envrc` 의 모든 `export KEY=VALUE` — 빈 객체 가능 |
| `tool_versions` | object | no | python/node/asdf 종합 — 빈 객체 가능 |

### 32.3 github 항목 (array of object)

| key | type | 설명 |
|---|---|---|
| `name` | string | "origin", "upstream", ... |
| `url` | string | raw URL (SSH 또는 HTTPS) |
| `host` | string | `github.com`, `github.com-<alias>`, `gitlab.com`, ... |
| `owner` | string | URL 의 owner segment |
| `repo` | string | URL 의 repo segment (`.git` 제외) |
| `ssh_alias` | string\|null | `github.com-<alias>` 의 alias suffix |
| `protocol` | enum | `"ssh"` \| `"https"` |

### 32.4 pulumi 객체

| key | type | 설명 |
|---|---|---|
| `project_name` | string | Pulumi.yaml 의 `name` |
| `runtime` | string\|null | `"python"`, `"nodejs"`, ... (dict 형식이면 `name` 만) |
| `description` | string\|null | Pulumi.yaml 의 `description` |
| `backend` | string\|null | Pulumi.yaml 의 `backend.url` — state backend (§32.4c). 키 부재 → null |
| `stacks` | array | `Pulumi.<stack>.yaml` 파일들의 stack 이름 (alphabetical) |
| `yaml_path` | string | Pulumi.yaml 의 절대 경로 |

### 32.4a gh_account 도출 (v0.11.0)

per-project gh routing convention: `.envrc` 가
`export GH_CONFIG_DIR="$HOME/.config/gh-<account>"` 를 export 하면 `gh` CLI 가
project 별 올바른 GitHub 계정을 사용한다 (`gh` 의 single global active account
우회). `gh_account` 는 이 routing 의 계정 이름이다.

- 도출: `GH_CONFIG_DIR` 경로 값의 basename 에서 `gh-` prefix 제거.
  - `$HOME/.config/gh-16bitdo` → `16bitdo`
  - `$HOME/.config/gh-secondary` → `secondary`
- `AWS_PROFILE` 은 값 자체가 식별자라 그대로 쓰지만, `GH_CONFIG_DIR` 은 경로
  값이므로 basename 추출 한 단계를 더 거친다.
- `GH_CONFIG_DIR` 부재 / basename 이 `gh-<name>` 형식 아님 → `null`.
- 경로 값 자체는 secret 이 아니므로 `dev_env` 에 그대로 남고, 편의 single-field
  `gh_account` 는 도출된 계정만 노출 (`aws_profile` 과 동일 패턴).

### 32.4b claude_account 도출 (v0.12.0)

per-project Claude Code routing convention: `.envrc` 가
`export CLAUDE_CONFIG_DIR="$HOME/.claude-<account>"` 를 export 하면 Claude Code
가 project 별 올바른 계정(config + auth 토큰)을 사용한다 (`CLAUDE_CONFIG_DIR`
은 `GH_CONFIG_DIR` 의 직접 analog — Claude Code 가 네이티브로 읽는 env var).
`claude_account` 는 이 routing 의 계정 이름이다.

- 도출: `CLAUDE_CONFIG_DIR` 경로 값의 basename 에서 `.claude-` / `claude-` prefix 제거.
  - `$HOME/.claude-16bitdo` → `16bitdo`
  - `$HOME/.claude-edward` → `edward`
- `gh_account` 와 동일하게 경로 값이므로 basename 추출 한 단계를 더 거친다.
- `CLAUDE_CONFIG_DIR` 부재 / basename 이 `.claude-<name>` 형식 아님 (기본
  `$HOME/.claude` 포함) → `null`.
- 경로 값 자체는 secret 이 아니므로 `dev_env` 에 그대로 남고, 편의 single-field
  `claude_account` 는 도출된 계정만 노출.

### 32.4c pulumi.backend 도출 (v0.12.0)

per-project Pulumi routing: `Pulumi.yaml` 의 `backend.url` 이 Pulumi state backend
(state 저장 위치 + org/account) 를 결정한다. AWS profile / gh account 같은 단일
username 이 아니라 **backend** 개념이라 필드명을 `pulumi.backend` 로 둔다.

- 도출: `Pulumi.yaml` 의 `backend` 키가 `{url: <str>}` 형식이면 그 URL.
  - `s3://my-state-bucket`, `gs://...`, `azblob://...`, `https://api.pulumi.com`,
    `file://~/state` 등
- `backend` 키 부재 = Pulumi Cloud default — anvyc 은 **명시 선언만 추적**하며
  default 는 추론하지 않는다 (`null`).
- `.envrc` 의 `PULUMI_BACKEND_URL` 은 env override 로, `dev_env` 에 그대로 수집된다
  (비-secret). `PULUMI_ACCESS_TOKEN` 은 secret → D11c redaction (`pulumi_token`
  패턴) 으로 자동 마스킹, 값은 추적하지 않는다.
- 두 신호의 정합성은 doctor `pulumi_backend_routing` / `project-pulumi-backend-mapping`
  check 가 검증 (§33.3).

### 32.5 dev_env redaction (D11c)

- 각 (KEY, VALUE) 페어에 대해 가상 line `KEY=VALUE` 를 생성하고 anvyc 의
  `security.patterns.PATTERNS` 의 어떤 regex 라도 매칭되면 VALUE 를
  `***REDACTED***` 로 치환.
- `op://<vault>/<item>/<field>` (1Password Secret Reference) 는 placeholder
  signal 이므로 redaction 면제.
- `--reveal-secrets` flag 지정 시 raw 값 노출. 단, agent / log 에 secret
  유출 위험 — 사용자 책임 영역.

### 32.6 사용 예 (AI agent JSON)

```json
{
  "path": "/Users/edward/dev/proj",
  "aws_profile": "company-dev",
  "gh_account": "16bitdo",
  "claude_account": "16bitdo",
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
    "description": null,
    "backend": "s3://acme-pulumi-state",
    "stacks": ["dev", "prd"],
    "yaml_path": "/Users/edward/dev/proj/Pulumi.yaml"
  },
  "dev_env": {
    "AWS_PROFILE": "company-dev",
    "GH_CONFIG_DIR": "$HOME/.config/gh-16bitdo",
    "CLAUDE_CONFIG_DIR": "$HOME/.claude-16bitdo",
    "PULUMI_BACKEND_URL": "s3://acme-pulumi-state",
    "NODE_ENV": "development",
    "GITHUB_TOKEN": "***REDACTED***"
  },
  "tool_versions": {"python": "3.13", "node": "20.10.0"}
}
```

### 32.7 schema 안정성

- v0.8.0 부터 본 schema 는 **public API** — 외부 도구 호환을 위해 minor 변경
  (key 추가) 만 허용, breaking 변경은 major (v1.0+) 에서만.
- 신규 hoster / runtime / pattern 추가는 본 schema 의 enum 확장 (backward-compat).

---

## 33. project list / project doctor schema (v0.8.1)

### 33.1 `project list` output

`anvyc project list --json` — array of `ProjectInfo` (DESIGN §32 와 동일 schema).
순서: path alphabetical. 발견 0건 시 빈 array `[]`.

discovery 규칙:
- root candidates: `--root` 반복 옵션 (미지정 시 `project_roots` config 또는 표준 루트)
- marker: `.git` 또는 `Pulumi.yaml` 보유 디렉터리 (depth ≤ 2)
- symlink 디렉터리는 alias 가능성으로 skip
- marker 발견 디렉터리의 sub-dir 은 별도 project 가 아니라 동일 project 의 일부

### 33.2 `project doctor` output

`anvyc project doctor --json`:

```json
{
  "path": "/absolute/path",
  "results": [
    {"check_name": "...", "severity": "...", "message": "...",
     "location": null, "line": null, "suggestion": null}
  ]
}
```

`results` 는 doctor `--json` 의 result entry 와 동일 6 field (check_name, severity,
message, location, line, suggestion). `path` 는 입력 path 의 resolve 된 절대 경로.

### 33.3 project doctor check 명세 (8 check)

| check_name | trigger | severity (issue 시) |
|---|---|---|
| `aws_profile_defined` | `.envrc` 의 AWS_PROFILE 있을 때만 | WARNING |
| `github_remote_parseable` | `.git/config` 있을 때만 | (parseable 한 것만 info 에 들어가므로 항상 INFO) |
| `gh_account_routing` | origin remote 가 GitHub ssh alias 쓸 때만 | WARNING |
| `claude_account_dir_exists` | `.envrc` 의 CLAUDE_CONFIG_DIR 있을 때만 | WARNING |
| `pulumi_stacks_valid` | `Pulumi.yaml` 있을 때만 | WARNING |
| `pulumi_backend_routing` | `Pulumi.yaml` 의 backend 또는 `.envrc` PULUMI_BACKEND_URL 있을 때만 | WARNING |
| `dev_env_secret_safety` | `.envrc` 의 export 변수 있을 때만 | **CRITICAL** |
| `tool_versions_installed` | `.python-version`/`.nvmrc`/`.tool-versions` 있을 때만 | WARNING |

→ check 의 source 가 없으면 silent skip (결과 0건). bare path 는 `{"results": []}`.

`gh_account_routing` (v0.11.0): origin remote URL 이 `github.com-<alias>` ssh
alias 를 쓰면, `.envrc` 의 `GH_CONFIG_DIR` 에서 도출한 gh 계정 (§32.4a) 이
그 alias 와 일치하는지 검증. `GH_CONFIG_DIR` 부재 / 계정 불일치 → WARNING,
일치 → INFO. plain `github.com` origin (alias 없음) 은 검증 대상 아님 (silent).
global `project-gh-account-mapping` check (§27.1.1) 의 path-aware 버전.

`claude_account_dir_exists` (v0.12.0): `.envrc` 가 `CLAUDE_CONFIG_DIR` 을
선언하면, 그 경로가 가리키는 config 디렉터리가 실제 존재하는지 검증한다.
존재 → INFO, 부재 → WARNING. cross-check 할 "remote" 가 없으므로 gh 와 달리
**1-way (디렉터리 존재 확인)** 만 한다. `CLAUDE_CONFIG_DIR` 미선언 → 검증 대상
아님 (silent). global `project-claude-account-mapping` check 의 path-aware 버전.

`pulumi_backend_routing` (v0.12.0): `Pulumi.yaml` 의 `backend.url` 과 `.envrc` 의
`PULUMI_BACKEND_URL` 이 둘 다 선언되면 일치하는지 검증한다 (**2-way 정합성** —
gh 수준). 비교 전 trailing slash 제거 + `file://` 의 `~` 확장으로 정규화. 둘 다
일치 / 한쪽만 선언 → INFO, 불일치 → WARNING. backend·PULUMI_BACKEND_URL 둘 다
미선언 (Pulumi Cloud default) → 검증 대상 아님 (silent). global
`project-pulumi-backend-mapping` check 의 path-aware 버전.

이 check 들은 기존 `anvyc doctor` 와 별개 — `project doctor` 는 path-aware.

### 33.4 --strict 모드

`--strict` 시 `report.has_blocking()` 이 True 면 exit 1. blocking severity:
WARNING, WARNING_FOREIGN, WARNING_DANGLING, CRITICAL.

INFO / INFO_ALIASED 는 strict 모드에서도 exit 0.

### 33.5 secret 다루기

- `project doctor` 는 `collect_project_info(redact_secrets=False)` 로 raw 값을
  메모리에서 사용 (secret 패턴 검증 위해).
- raw secret 은 report 의 message 에 노출되지 않음 — KEY 명만 (`GITHUB_TOKEN`).
- JSON 출력의 어떤 field 에도 raw secret 미포함.

---

## 34. MCP server architecture (v0.9.0, P6)

### 34.1 배경

[improvement-plan-ai-agent.md](./docs/archive/improvement-plan-ai-agent.md) Wave 9. AI agent
(Claude Code / Cursor) 가 anvyc 의 5 read-only tool 을 Model Context Protocol
(stdio transport) 로 직접 호출. subprocess 호출 + stdout parse 우회.

### 34.2 격리 — optional extra (D20)

MCP SDK 의 transitive dep (`pydantic-core` Rust extension 등) 이 무겁고
Homebrew sandbox install 과 충돌 우려.

| 설치 영역 | 의존 |
|---|---|
| core anvyc | typer / rich / pathspec / pyyaml (4) |
| `anvyc[mcp]` | core + mcp (+ pydantic, anyio, httpx, jsonschema 등) |

Homebrew Formula (`packaging/homebrew/Formula/anvyc.rb`) 는 core 만 build.
MCP 사용자는 `uv tool install 'anvyc[mcp]'` 별도 path.

### 34.3 모듈 구조

```
src/anvyc/
├── mcp/
│   ├── __init__.py        # 모듈 docstring
│   └── server.py          # MCP server (5 tool dispatch + stdio)
└── cli.py                 # @app.command("serve")
```

`anvyc serve --mcp` → `mcp.server.run()` → asyncio.run(_main()) → stdio_server.

### 34.4 노출 tool 명세 (5 read-only, D21)

| tool | dispatch target | input schema | output |
|---|---|---|---|
| `project_show` | `core.project_info.collect_project_info` | `{path?, reveal_secrets?}` | ProjectInfo (§32) |
| `project_list` | `core.project_discovery.discover_projects` + collect | `{roots?, reveal_secrets?}` | array ProjectInfo (§33.1) |
| `project_doctor` | `core.project_doctor.run_project_doctor` | `{path?}` | `{path, results}` (§33.2) |
| `doctor` | `core.doctor.run_doctor` | `{only?, skip?}` | `{results}` |
| `tools_list` | `cli._collect_tools_rows` | `{}` | array `{tool, enabled, detected, files, secrets}` |

### 34.5 write 영역 의도적 제외

`backup` / `apply` / `restore` / `scan-secrets` 등 file system 을 변경하는
명령은 tool 로 노출 안 함. AI agent 가 자율적으로 destructive 실행하면 위험
— 사용자가 CLI 로 명시 실행 유지.

### 34.6 redaction (D11c default 동일)

- `project_show` / `project_list` 의 `reveal_secrets=False` default
- `project_doctor` 는 raw 검증 위해 내부 `redact_secrets=False` 사용
  하지만 결과 message 에는 KEY 명만 (raw 미포함)

### 34.7 error handling

- `_dispatch` 의 `ValueError("unknown tool")` 은 caller 에 raise
- `call_tool` wrapper 가 모든 Exception 잡아 `{"error": str}` TextContent 반환
- 실패해도 server 는 살아있고 다음 tool 호출 가능

### 34.8 stdio transport 의 한계

- 단일 client (Claude Code 또는 Cursor 1개 process 만 connect)
- 모든 통신은 단일 process 의 stdin/stdout (multi-client SSE 는 향후)
- log 출력은 stderr (또는 file) — stdout 은 protocol 만

### 34.9 schema 안정성

- v0.10.0 부터 5 tool 의 이름 + `inputSchema` + 출력 schema 는 **public API**
  - v0.9.0 의 `anvyc_*` prefix 는 cleanup deferred 였음 (v0.10.0 에서 제거)
- minor 변경 (key 추가 / 새 tool 추가) 만 backward-compat
- breaking 변경 (key 제거 / 이름 변경 / 타입 변경) 은 major (v1.0+) 에서만

## 35. Snapshot / Rollback 설계 (CP-4)

> **본 axis 본문은 [docs/design-axes/cp-04-snapshot.md](./docs/design-axes/cp-04-snapshot.md)
> 로 분리됐습니다.**

Control Plane v2 의 첫 axis. autopilot 의 실수 (예: 브랜치 30 파일 수정) 를
명시적 marker → 복원 가능하게 한다. `git stash` + meta schema v1
(`schema_version: 1`) + `refs/anvyc-snapshots/<id>` anchor 로 GC 방지.
`anvyc snapshot {create|list|diff|restore}` 4-layer safety (dry-run 기본 /
`--force` + confirm / auto pre-restore snapshot / conflict 시 회복 채널 안내).

상세 (schema v1 / 명령 contract / git stash anchor 의미 / capture 구현
`stash push -u` + 즉시 `pop --index` / restore 안전 절차 6단계) →
[CP-4 본문](./docs/design-axes/cp-04-snapshot.md).

## 36. Credentials Lifecycle 설계 (CP-5)

> **본 axis 본문은 [docs/design-axes/cp-05-creds.md](./docs/design-axes/cp-05-creds.md)
> 로 분리됐습니다.**

Control Plane v2 의 마지막 axis. GitHub PAT / AWS session / Claude OAuth
토큰 만료를 사전 감지 + 회전 절차를 native re-auth + 1Password CLI 로 연결.
`CredentialsReport schema v1` + `anvyc creds {status|rotate}` + doctor
`creds-expiry-within-7d` check (CP-3 scheduler 자동 합류). rotate 는
[CP-4 §7](./docs/design-axes/cp-04-snapshot.md) 의 4-layer 안전 패턴 미러.

상세 (schema v1 / 3 kind detection 전략 / CP-3 scheduler 시너지 / rotate
안전 절차) → [CP-5 본문](./docs/design-axes/cp-05-creds.md).

---

## 37. Cross-Machine State Sync 설계 (CP-6)

> **본 axis 본문은 [docs/design-axes/cp-06-sync.md](./docs/design-axes/cp-06-sync.md)
> 로 분리됐습니다.**

Control Plane v3 의 첫 axis. 여러 머신 간 control plane mutable state
(CP-4 snapshot meta + CP-3 health JSON + CP-5 creds expiry timestamp)
동기화. `SyncTargetManifest schema v1` + `anvyc sync {status|push|pull}` +
`sync conflict {list|resolve}` (per-entry sha256 명시 해결). auto-policy /
3-way merge 영구 out-of-scope — 사용자 prompt 가 권위.

상세 (schema v1 / diff 알고리즘 / remote target layout / push-pull 안전
절차 / conflict resolution 정책) → [CP-6 본문](./docs/design-axes/cp-06-sync.md).

---

## 38. Cost observability 설계 (CP-13)

> **본 axis 본문은 [docs/design-axes/cp-13-cost.md](./docs/design-axes/cp-13-cost.md)
> 로 분리됐습니다.**

CP-13 의 구조 SoT. 결정 SoT 는 [`role-based-ruleset` ADR
v6-cp13-cost-observability.md](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/adr/v6-cp13-cost-observability.md)
(Accepted v1.1, 2026-05-27). AI agent 의 실행 비용 (Anthropic + AWS +
GitHub) 을 동일 `CostReport schema v1` 로 통합. USD 저장 / KRW 표시
(`fx_rate_basis` 캡처). admin API (ii) channel 은 v0.2 deferred (공식 endpoint
미공개). 6h rolling window state 권위 위치 =
`~/.config/cc-inspect/cost-window.json` (ccinspector owner).

상세 (schema v1 / adapter Protocol / cache layout / doctor 5 check / 보안
경계 / 변경 이력 8 entries) → [CP-13 본문](./docs/design-axes/cp-13-cost.md).

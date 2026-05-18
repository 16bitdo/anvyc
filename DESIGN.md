# DESIGN.md — anvyc 개발환경 설정 동기화 도구 설계서

> 문서 버전: v0.2
> 작성일: 2026-05-17
> 개정일: 2026-05-18 (v0.2 — 손상 섹션 복원 및 문맥 정합성 확보)
> 프로젝트 가칭: `anvyc`
> 목적: 여러 장치에서 Claude Code, Cursor IDE, AWS CLI, GitHub CLI, Pulumi, iTerm2 등 로컬 개발환경 설정을 안전하고 일관되게 동기화한다.

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
├── CONTEXT.md
├── pyproject.toml
├── src/
│   └── anvyc/
│       ├── __init__.py
│       ├── cli.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── inventory.py
│       │   ├── backup.py
│       │   ├── diff.py
│       │   ├── apply.py
│       │   ├── restore.py
│       │   └── metadata.py
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
│       │   └── pulumi.py
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

### 14.2 포함 대상

| 항목 | 정책 |
|---|---|
| Profiles | 포함 가능 (이름, 폰트, 색 등 시각/입력 관련) |
| Key mappings | 포함 가능 |
| Color presets | 포함 가능 |
| Touch bar settings | 포함 가능 |
| Hotkey window 설정 | 신중히 포함 |

### 14.3 제외 대상

| 항목 | 이유 |
|---|---|
| Window arrangement | 장비별 화면 크기와 충돌 |
| Recent sessions | 불필요한 이력 |
| Local path | 장비별 경로 |
| UI state | 장비별 상태 |
| Dynamic runtime data | 장비별 휘발성 데이터 |

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
      - "~/Documents/anvyc"
      - "~/Documents/another-project"
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

## 17. AWS / GitHub CLI / Pulumi Adapter 설계

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
| 문서 | README/DESIGN/CONTEXT 최신화 |
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

### 27.2 모듈 구조

```
src/anvyc/
├── checks/                  # 재사용 Check 컴포넌트
│   ├── __init__.py
│   ├── base.py              # Severity, CheckResult, CheckContext
│   └── cross_user.py        # §27.3 구현
└── core/
    └── doctor.py            # check 등록/실행 orchestrator
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

## 29. Post-PoC 로드맵 (2026-05-18 기준)

§21 의 1~3주차 원안은 일부 완료. 본 섹션이 v0.1.0 MVP 까지의 갱신된 작업 계획이다.

### 29.1 완료된 영역

| 영역 | 완료 내역 |
|---|---|
| CLI | doctor, init, backup, list, status, diff |
| Adapter | shell, git |
| Doctor checks | cross-user, venv-hidden-flag |
| Core | backup orchestrator, secret scanner, status, diff |

### 29.2 Phase 분류

| Phase | 범위 | 우선순위 | 추정 |
|---|---|---|---|
| 1 | apply / restore (round-trip) | HIGH | 4~6h |
| 2 | 어댑터 6개 (aws/gh/pulumi/claude/iterm2/cursor) | HIGH | 5~7h |
| 3 | Git 동기화 (.anvyc → remote, pre-commit hook) | MEDIUM (v0.2 후보) | 3~4h |
| 4 | Doctor 보강 (#17 iTerm2 plist, adapter validate 통합, --fix) | MEDIUM | 2~3h |
| 5 | Encryption (~/.anvyc-secrets/, age, 1Password) | LOW (post-MVP) | 3~4h |
| 6 | 테스트 + 패키징 + v0.1.0 릴리즈 | 필수 (MVP 직전) | 4~6h |

### 29.3 의존성

```
P1 → P2 (apply 기본 구현이 있어야 새 어댑터가 즉시 backup+apply 양쪽 동작)
P2 → P6
P3, P4, P5 — P1 이후 어디서든 병렬
```

### 29.4 v0.1.0 MVP 최단 경로

**필수**: Phase 1 + Phase 2 (cursor/claude/iterm2 포함) + Phase 6
**v0.2 연기 가능**: Phase 3, 4, 5

근거: `.anvyc/` 자체는 Dropbox/iCloud/수동 SCP 로도 이전 가능. secret 기본 제외 정책으로 encryption 없이도 안전성 확보. Doctor 추가 check 은 신뢰도용.

**총 추정 (필수 경로)**: 13~19 시간 = 2~3일.

### 29.5 권장 진행 순서

```
Day 1  P1.1 → P1.7  apply/restore 라운드 트립 완성
Day 1  P2.1 ~ P2.3  aws/gh/pulumi
Day 2  P2.4         claude
Day 2  P2.5         iterm2 (plistlib)
Day 2  P2.6         cursor (#6~#11)
Day 3  P6.1 ~ P6.5  unit/integration test + pipx + v0.1.0 tag
```

각 phase 끝에 commit + push.

### 29.6 열린 결정

| # | 항목 | 후보 |
|---|---|---|
| Q1 | Phase 3 (Git sync) 를 v0.1.0 에 포함할지 | 포함 / v0.2 |
| Q2 | iterm2 safe subset 키 목록 확정 시점 | §14.2 그대로 / 사용자 환경 기준 재조정 |
| Q3 | Cursor projects 모드 default roots 기본값 | empty / 자동 감지 후 제안 |
| Q4 | v0.1.0 에서 secret encryption 제공 범위 | 없음 / age 기본 통합 |

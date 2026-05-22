# anvyc

> **anvyc**는 여러 장치(주로 macOS)에서 개발 도구 설정 정보와 인증 정보를 **안전하게 백업, 비교, 복원, 동기화**하는 CLI 도구다.

상세 설계는 [DESIGN.md](./DESIGN.md), 진행 상태와 결정 사항은 [CONTEXT.md](./CONTEXT.md)를 참고한다.

---

## 1. 한 줄 설명

```text
chezmoi의 안전 원칙을 참고한, 개발환경 특화 config sync tool.
shell / git / AWS / GitHub CLI / Pulumi / iTerm2 / Cursor / Claude Code 설정을 한 번에.
```

---

## 2. 왜 만들었나

- `.zshrc`, Cursor settings, iTerm2 plist, AWS config 등 **설정 위치가 제각각**이다.
- hostname, OS, email 등 **장비별 값이 달라** 단순 복사가 위험하다.
- credentials/token이 **dotfiles에 섞여 Git에 올라가는 사고**가 잦다.
- 단순 복사 방식은 **diff/검증/백업 절차가 부재**하다.

anvyc는 이 문제들을 **도구별 safe adapter** + **secret 기본 제외** + **apply 전 diff/dry-run** + **restore 전 local backup**으로 풀어낸다.

---

## 3. 핵심 원칙

1. **Secret 기본 제외** — `~/.aws/credentials`, `~/.pulumi/credentials.json`, SSH key, `.env`, Claude tokens 등은 수집하지 않는다.
2. **Apply 전 diff & dry-run** — 어떤 변경이 일어나는지 항상 먼저 확인한다.
3. **Restore 전 local backup** — 덮어쓰기 전 현재 상태를 자동으로 보관한다.
4. **도구별 safe adapter** — 범용 파일 복사 대신 도구 특성에 맞춘 안전한 추출/적용 로직.
5. **Git-friendly, secret-hostile** — Git push 전 pre-commit hook으로 secret을 재차 차단한다.

---

## 4. 지원 도구

| 도구 | 기본 포함 | 기본 제외 |
|---|---|---|
| Shell (zsh) | `.zshrc`, `.zprofile` | shell history |
| Git | `.gitconfig`, `.gitignore_global` | `.git-credentials` |
| AWS CLI | `~/.aws/config` | `~/.aws/credentials`, SSO cache |
| GitHub CLI | `config.yml` | `hosts.yml` (token) |
| Cursor IDE | settings/keybindings/snippets/rules/skills/mcp.json | workspaceStorage, History, globalStorage |
| Claude Code | settings.json, hooks, plugins | sessions, tokens, cache, logs |
| iTerm2 | profiles, key mappings, color presets | window state, recent sessions, local path |
| Pulumi | `config.json` | `credentials.json` |
| **dev_env** (v0.7.0+) | `.envrc`, `.tool-versions`, `.python-version`, `.nvmrc` (project root scan, default disabled) | `node_modules/`, `.venv/`, `.git/`, `__pycache__/` |

---

## 5. 설치

### 5.0 one-liner 설치 (v0.7.1+)

```bash
curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh | bash

# 특정 버전:
ANVYC_VERSION=v0.7.1 bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)

# 설치 도구 강제 (uv | pipx | auto):
ANVYC_METHOD=pipx bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)
```

- GitHub Release wheel + `SHA256SUMS` 자동 검증
- `uv tool` 또는 `pipx` 자동 감지 (없으면 명시 안내)

### 5.1 Homebrew tap (v0.7.1+)

```bash
brew tap 16bitdo/anvyc
brew install anvyc
anvyc --version
```

Formula source-of-truth: [packaging/homebrew/Formula/anvyc.rb](./packaging/homebrew/Formula/anvyc.rb).
Tap repo: [16bitdo/homebrew-anvyc](https://github.com/16bitdo/homebrew-anvyc). 
갱신 절차: [docs/homebrew-publishing.md](./docs/homebrew-publishing.md).

### 5.2 GitHub Release 의 wheel 직접 설치

```bash
# uv tool (권장)
uv tool install https://github.com/16bitdo/anvyc/releases/download/v0.6.3/anvyc-0.6.3-py3-none-any.whl

# 또는 pipx
pipx install https://github.com/16bitdo/anvyc/releases/download/v0.6.3/anvyc-0.6.3-py3-none-any.whl

anvyc --version
```

### 5.3 git remote 에서 부트스트랩 (v0.6.2+)

머신 A 에서 `.anvyc/` 를 private git repo 로 push 해두고, 새 머신 B 에서:

```bash
anvyc init --from-git git@github.com:<you>/anvyc-config.git
anvyc doctor
anvyc apply --dry-run
anvyc apply
```

`--from-git` 은 target `.anvyc/` 이 이미 있으면 fail-fast — 덮어쓰지 않는다.

### 5.5 MCP server (AI agent integration, v0.9.0+)

Claude Code / Cursor 등 MCP 호환 agent 에서 anvyc 의 read-only 5 tool 호출:

```bash
uv tool install --upgrade 'anvyc[mcp]'
```

`~/.claude/mcp.json` (Claude Code) 또는 `~/.cursor/mcp.json` (Cursor):

```json
{
  "mcpServers": {
    "anvyc": {
      "command": "anvyc",
      "args": ["serve", "--mcp"]
    }
  }
}
```

상세 설정 + 사용 예: [docs/mcp-integration.md](./docs/mcp-integration.md).

### 5.6 개발 설치 (contributor)

```bash
git clone git@github.com:16bitdo/anvyc.git
cd anvyc
bash scripts/dev-install.sh
```

`scripts/dev-install.sh` 는 venv 생성·editable 설치·dev wrapper
(`~/.local/bin/anvyc`) 설치·검증을 한 번에 처리하며 재실행해도 안전합니다.
디렉터리 이전이나 Python 업그레이드 후에도 이 스크립트만 재실행하면 복구됩니다.

상세 가이드: [CONTRIBUTING.md](./CONTRIBUTING.md)

> **macOS + Python 3.13.13+ 참고**: editable install 의 `.pth` 가 macOS
> `UF_HIDDEN` flag 때문에 `ModuleNotFoundError: No module named 'anvyc.cli'` 로
> 깨질 수 있습니다 — `dev-install.sh` 가 설치하는 dev wrapper 는 `.pth` 대신
> `PYTHONPATH` 로 `src/` 를 주입해 `python -m anvyc` 로 실행하므로 이 트랩을
> 아예 거치지 않습니다. 원인·수동 대응은
> [docs/troubleshooting-macos.md](./docs/troubleshooting-macos.md) 참고. 일반
> 사용자 (`uv tool install` / `pipx`) 는 영향 없음.

---

## 6. 빠른 시작

```bash
# 1) 초기화 — .anvyc/, anvyc.yaml 생성
anvyc init

# 2) 환경 점검 — 설치된 도구, 위험 경로, 권한 확인
anvyc doctor

# 3) 백업 — 현재 환경 설정을 .anvyc/backups/<timestamp>/ 에 저장
anvyc backup

# 4) 상태 확인
anvyc status

# 5) 다른 장비에서 복원
anvyc diff
anvyc apply --dry-run
anvyc apply
```

---

## 7. 디렉터리 구조

```text
anvyc/
├── README.md
├── DESIGN.md
├── CONTEXT.md
├── pyproject.toml
├── src/anvyc/
│   ├── cli.py
│   ├── core/        # inventory, backup, diff, apply, restore, metadata
│   ├── adapters/    # shell, git, aws, gh, cursor, claude, iterm2, pulumi
│   ├── security/    # scanner, patterns, policy
│   ├── storage/     # local, git, encryption
│   └── utils/
└── tests/{unit,integration,fixtures}
```

런타임 상태는 사용자 환경의 `.anvyc/` 와 `~/.anvyc-secrets/` 에 저장된다.

---

## 8. 명령어 요약

```bash
anvyc init                     # 프로젝트/설정 초기화
anvyc init --interactive       # 대화형 wizard (v0.7.1+)
anvyc init --from-git <url>    # git remote 에서 .anvyc/ clone (v0.6.2+)
anvyc doctor                   # 환경 진단 (14 check)
anvyc backup                   # 현재 환경 백업
anvyc status                   # target vs backup 차이 요약
anvyc diff                     # unified diff 출력
anvyc apply [--dry-run]        # source 설정 적용 (전 local backup 자동)
anvyc restore <backup-id>      # 특정 backup으로 복원
anvyc list                     # 백업 목록
anvyc scan-secrets             # secret 패턴 스캔

anvyc config edit              # $EDITOR 로 anvyc.yaml 편집 + schema 검증 (v0.6.3+)
anvyc config show [--effective] [--json]   # raw 또는 default 적용된 yaml/json (v0.6.3+/v0.8.0)
anvyc tools list [--json]      # 9 도구의 enabled / detect / file-count (v0.6.3+/v0.8.0)

anvyc project show [--path P] [--json] [--reveal-secrets]
                               # cwd 의 AWS/GitHub/Pulumi/dev_env 통합 view (v0.8.0+)
anvyc project list [--root R...] [--json]
                               # root 아래 모든 project matrix (v0.8.1+)
anvyc project doctor [--path P] [--json] [--strict]
                               # cwd connection 정합성 8 check (v0.8.1+)
anvyc prompt [--path P] [--json]
                               # cwd 계정 라우팅을 shell prompt 용 한 줄로 (v0.13.0+)

anvyc serve --mcp              # MCP server (Claude Code/Cursor 직접 호출, v0.9.0+)

anvyc git {init|status|commit|push}
anvyc sops {encrypt|decrypt|rotate-keys}
```

---

## 9. 보안 정책 요약

| 등급 | 예시 | 동작 |
|---|---|---|
| Critical | private key, AWS secret key | 백업/적용 즉시 중단 |
| High | GitHub token, Pulumi token | 백업/적용 즉시 중단 |
| Medium | `.env`, `password=` | 경고, `--force` 시 진행 |
| Low | email, username, op:// 와 같은 라인의 패턴 매칭 | 정보 로그만 |

`secret-scan`은 `backup` / `apply` / `git push` 모든 시점에 실행된다.

### 9.1 1Password Secret Reference (v0.1.0)

raw secret 대신 [1Password Secret Reference](https://developer.1password.com/docs/cli/secret-references/) `op://<vault>/<item>/<field>` 를 사용한다. reference 자체는 비-secret 이므로 backup/Git commit 안전.

```bash
# .zshrc 예
export AWS_ACCESS_KEY_ID="op://Personal/AWS/access_key_id"
export GITHUB_TOKEN="op://Personal/GitHub/token"
```

**사용 흐름**:

```bash
# 1) 1Password CLI 설치 + 로그인
brew install 1password-cli      # macOS
op signin

# 2) 민감 값을 1Password 에 등록 (또는 기존 항목 사용)
op item create --category=login --title='AWS' \
    access_key_id=AKIA... secret_access_key=...

# 3) dotfile 에서 raw secret 을 op:// reference 로 치환

# 4) backup — reference 는 그대로 들어감
anvyc backup

# 5) 다른 머신에서 apply 후 1Password 로그인만 하면 동일 환경
op signin           # 새 머신에서
anvyc apply
```

**scanner 의 false-positive 강등**: 같은 라인에 `op://` 가 있으면 다른 secret 패턴 매칭이 `low` 로 강등된다 (placeholder 신호로 간주). 따라서 위 `.zshrc` 예시는 backup 시 차단되지 않는다.

**doctor 의 reference 검증**: `anvyc doctor --only op-references-valid` 가 발견된 모든 `op://` URI 를 `op read` 로 resolve 시도한다. 실패 시 WARNING. `op` CLI 미설치/미인증 시 안전 skip.

### 9.2 SOPS encryption-at-rest (v0.2)

다수 secret 묶음 (`.env`, `.toml`, 바이너리 키 등) 은 [SOPS](https://github.com/getsops/sops) 로 암호화하여 백업한다. age 키 backend 기본 지원.

```bash
# 1) sops + age 설치
brew install sops age

# 2) age key 생성 (한 번만)
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
# Public key: age1abc... ← anvyc.yaml 에 추가

# 3) anvyc.yaml 설정
cat >> .anvyc/anvyc.yaml <<EOF
security:
  sops:
    enabled: true
    age_recipients:
      - "age1abc...edward-mac"
    age_identity_file: "~/.config/sops/age/keys.txt"

tools:
  pulumi:
    enabled: true
    files: ["~/.pulumi/config.json"]
    secret_files: ["~/.pulumi/credentials.json"]
EOF

# 4) backup — secret_files 는 자동으로 SOPS 암호화
anvyc backup
# → backup_dir/pulumi/sops/credentials.json.sops.json (encrypted)

# 5) 다른 머신에서 — 같은 age private key 가 있어야 복호화
anvyc apply   # SOPS 자동 복호화 후 target 에 평문 저장
```

**1Password 와 공존 가능**:
- 단일 변수 raw secret → `op://` reference (§9.1)
- 다수 secret 묶음 (`.env` 등) → SOPS `secret_files`

**doctor 점검**: `anvyc doctor --only sops-keys-available` 가 sops/age binary 와 age identity file 부재를 자동 안내.

**scanner 통합**: SOPS 로 암호화된 파일 (`.sops.json` 또는 `sops:` metadata 보유) 은 secret scan 통과 — 암호화된 상태에서 base64 가 secret 패턴에 매치되는 false positive 차단.

---

## 9.3 `anvyc doctor --json` schema (v0.5.3)

CI / 다른 도구 통합용. 출력은 valid JSON 으로 안정적이며 회귀 테스트로 보장된다.

```bash
anvyc doctor --json                          # 전체
anvyc doctor --only cross-user --json        # 특정 check 만
anvyc doctor --skip cursor-projects-suggest --json
```

### Top-level

| 필드 | 타입 | 설명 |
|---|---|---|
| `results` | `list[Result]` | 발견된 모든 finding |
| `summary` | `dict[severity, int]` | 6 severity 각각의 카운트 (0 카운트도 포함) |

### Result 객체

| 필드 | 타입 | 비고 |
|---|---|---|
| `check_name` | `str` | 발행한 check (예: `cross-user`, `cursor-symlink-integrity`) |
| `severity` | `str` | `info` / `info-aliased` / `warning` / `warning-foreign` / `warning-dangling` / `critical` |
| `message` | `str` | 사람-가독 요약 |
| `location` | `str \| null` | 절대 경로 또는 null |
| `line` | `int \| null` | 텍스트 매칭의 라인 번호 (해당 시) |
| `suggestion` | `str \| null` | 조치 권유 (해당 시) |

### Summary 객체

```json
{
  "info": 11,
  "info-aliased": 0,
  "warning": 1,
  "warning-foreign": 21,
  "warning-dangling": 0,
  "critical": 0
}
```

### Exit code

| 코드 | 의미 |
|---|---|
| `0` | clean 또는 blocking 없는 결과 (--strict 없을 때) |
| `1` | --strict 일 때 blocking severity (warning*/critical) 발견 |
| `2` | argparse 등 사용 오류 |

### 활용 예 (jq)

```bash
# critical 만 추출
anvyc doctor --json | jq '.results[] | select(.severity == "critical")'

# 특정 location 의 finding 수
anvyc doctor --json | jq '[.results[] | select(.location | contains(".cursor"))] | length'

# CI 게이트: blocking 발견 시 exit 1
anvyc doctor --strict --json > /dev/null
```

---

## 10. 기술 스택

| 항목 | 선택 |
|---|---|
| 언어 | Python 3.11+ |
| CLI | Typer |
| 출력 | Rich |
| 설정 검증 | pydantic |
| 경로 패턴 | pathspec |
| 테스트 | pytest |
| plist 처리 | plistlib (stdlib) |
| 암호화 (선택) | age 또는 cryptography |
| 패키징 | pipx / uv |

---

## 11. 다수 AWS profile 관리 (multi-account workflow)

anvyc 는 **정적 설정 sync 도구**다. runtime profile switching 은 표준 도구
([direnv](https://direnv.net/), [aws-vault](https://github.com/99designs/aws-vault)) 에 맡기고
anvyc 는 그 설정을 백업·동기화하는 역할에 집중한다.

### 11.1 권장 패턴: direnv + .envrc (프로젝트별 1개 profile)

```bash
# 1) direnv 설치 + zsh hook
brew install direnv
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc

# 2) 프로젝트 디렉터리에 .envrc 작성
cat > ~/dev/my-dev-project/.envrc <<'EOF'
export AWS_PROFILE=my-dev
EOF

# 3) 새 .envrc 신뢰 (보안)
cd ~/dev/my-dev-project
direnv allow

# 4) 이후로는 cd 시 AWS_PROFILE 자동 설정
cd ~/dev/my-dev-project   # → AWS_PROFILE=my-dev 자동 export
cd ~/                            # → AWS_PROFILE 자동 unset
```

### 11.2 PR 별 임시 전환 (1~3 profile 교체)

```bash
# ~/.zshrc 에 helper function:
awsp() { export AWS_PROFILE="$1"; aws sts get-caller-identity; }

# PR 작업 중:
awsp my-dev      # 개발
awsp my-audit    # 로그 확인
awsp my-prd      # 운영 readonly
unset AWS_PROFILE  # 원복
```

또는 [aws-vault](https://github.com/99designs/aws-vault) (MFA 강제 + 격리):

```bash
aws-vault exec my-prd -- terraform plan
```

### 11.3 anvyc 가 추적하는 것

```yaml
# anvyc.yaml
tools:
  aws:
    enabled: true
    files: ["~/.aws/config"]        # 모든 profile 정의 백업
    # ~/.aws/credentials 는 secret 으로 기본 제외
    # SOPS 통합 시 secret_files 로:
    # secret_files: ["~/.aws/credentials"]

  # 향후 v0.7+ (dev_env 어댑터, 계획 중):
  # dev_env:
  #   project_roots: ["~/dev"]
  #   patterns: [".envrc", ".tool-versions", ".python-version", ".nvmrc"]
```

### 11.4 anvyc 의 scope (multi-account 영역)

| anvyc 가 해야 할 | anvyc 가 안 해야 할 |
|---|---|
| ✓ `~/.aws/config` profile 정의 sync | ✗ runtime profile switching |
| ✓ `.envrc` 파일 추적 (v0.7+ 계획) | ✗ credential 자체 관리 |
| ✓ profile mapping 검증 (doctor check, v0.6.x 계획) | ✗ shell session state 추적 |
| ✓ 변경 안전망 (local-backup) | ✗ AWS API 호출 자체 |

direnv 와 aws-vault 가 더 잘 하는 영역에 anvyc 가 들어가면 도구 경계 모호.
anvyc 는 **정적 설정 동기화 + 검증 + 권장 워크플로 가이드** 역할.

### 11.5 multi-account doctor checks (v0.6.1 구현됨)

| Check | 동작 | 상태 |
|---|---|---|
| `project-aws-profile-mapping` | `project_roots` 아래 `.envrc` 의 `AWS_PROFILE` 값 ↔ `~/.aws/config` 정합성 검증 | ✓ v0.6.1 |
| `aws-profile-status` | 현재 active `AWS_PROFILE` env var ↔ 정의 검증 | ✓ v0.6.1 |
| `multi-account-detected` | ssh / aws / cursor alias 의 multi-account 환경 자동 안내 (INFO) | ✓ v0.6.1 |
| `unused-aws-profiles` | `.aws/config` 에만 있고 어디서도 안 쓰는 profile (INFO) | v0.7+ 계획 |

```bash
# 개별 실행
anvyc doctor --only project-aws-profile-mapping
anvyc doctor --only aws-profile-status
anvyc doctor --only multi-account-detected
```

자세한 UX 개선 계획은 [docs/archive/improvement-plan-ux-review.md](./docs/archive/improvement-plan-ux-review.md) 참고 (아카이브).

### 11.6 다수 GitHub 계정 관리 (per-project gh routing, v0.11.0+)

AWS profile 과 같은 문제가 GitHub 계정에도 있다. `gh` CLI 는 **single global
active account** 만 가지므로, 여러 계정 (개인 / org 별 봇 계정 등) 을 오가면
잘못된 계정으로 동작하거나 false warning 이 발생한다. AWS 의 `.envrc` +
`AWS_PROFILE` 패턴과 동일하게, project 별 `.envrc` 에 `GH_CONFIG_DIR` 을
선언해 direnv 가 계정을 라우팅하게 한다.

```bash
# 1) 계정별 gh config 디렉터리 준비 (convention: ~/.config/gh-<account>)
GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"  gh auth login   # 개인 계정
GH_CONFIG_DIR="$HOME/.config/gh-heisgone" gh auth login   # org 봇 계정

# 2) 프로젝트 .envrc 에 라우팅 선언 (origin ssh alias 와 일치시킬 것)
cat >> ~/dev/my-personal-repo/.envrc <<'EOF'
export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"
EOF

# 3) 새 .envrc 신뢰
cd ~/dev/my-personal-repo
direnv allow

# 4) 이후 cd 시 gh 가 올바른 계정 자동 사용
cd ~/dev/my-personal-repo   # → gh 가 gh-16bitdo config 사용
```

권장: `GH_CONFIG_DIR` 의 계정 이름을 git `origin` 의 ssh alias
(`git@github.com-<alias>:...`) 와 동일하게 맞춘다. anvyc 의 doctor check 가
이 일치를 검증한다.

| Check | 동작 | 상태 |
|---|---|---|
| `project-gh-account-mapping` | `project_roots` 아래 `.envrc` 의 `GH_CONFIG_DIR` gh 계정 ↔ GitHub `origin` ssh alias 정합성 검증 (global) | ✓ v0.11.0 |
| `gh_account_routing` | cwd 의 `GH_CONFIG_DIR` ↔ origin ssh alias 정합성 (`anvyc project doctor` 의 per-cwd check) | ✓ v0.11.0 |

```bash
# 개별 실행
anvyc doctor --only project-gh-account-mapping
anvyc project doctor              # cwd 에 gh_account_routing 포함 8 check
```

`anvyc project show --json` 의 `gh_account` 필드로 project 의 라우팅 계정을
machine-readable 하게 확인할 수 있다 (DESIGN §32.4a). AWS 와 마찬가지로
anvyc 는 **정적 설정 동기화 + 검증** 역할이며, 계정 인증 자체는 `gh` 가 관리한다.

### 11.7 다수 Claude Code 계정 관리 (per-project Claude routing, v0.12.0+)

Claude Code 도 단일 계정 config 를 쓰므로, 개인 / 업무 계정을 오가면 잘못된
계정으로 동작할 수 있다. `CLAUDE_CONFIG_DIR` 은 Claude Code 가 네이티브로 읽는
env var (`GH_CONFIG_DIR` 의 직접 analog) 이므로, `.envrc` 에 선언하면 direnv 가
project 별 계정(config + auth 토큰)을 라우팅한다.

```bash
# 1) 계정별 config 디렉터리 준비 (convention: ~/.claude-<account>)
CLAUDE_CONFIG_DIR="$HOME/.claude-16bitdo" claude   # 개인 계정 로그인
CLAUDE_CONFIG_DIR="$HOME/.claude-work"    claude   # 업무 계정 로그인

# 2) 프로젝트 .envrc 에 라우팅 선언
cat >> ~/dev/my-personal-repo/.envrc <<'EOF'
export CLAUDE_CONFIG_DIR="$HOME/.claude-16bitdo"
EOF

# 3) 새 .envrc 신뢰
cd ~/dev/my-personal-repo
direnv allow
```

| Check | 동작 | 상태 |
|---|---|---|
| `project-claude-account-mapping` | `project_roots` 아래 `.envrc` 의 `CLAUDE_CONFIG_DIR` 가 가리키는 config 디렉터리 존재 검증 (global) | ✓ v0.12.0 |
| `claude_account_dir_exists` | cwd 의 `CLAUDE_CONFIG_DIR` config 디렉터리 존재 (`anvyc project doctor` 의 per-cwd check) | ✓ v0.12.0 |

```bash
# 개별 실행
anvyc doctor --only project-claude-account-mapping
anvyc project doctor              # cwd 에 claude_account_dir_exists 포함 8 check
```

`anvyc project show --json` 의 `claude_account` 필드로 라우팅 계정을 확인할 수
있다 (DESIGN §32.4b). gh 와 달리 cross-check 할 remote 가 없어 검증은 **디렉터리
존재 확인 (1-way)** 만 한다 — 핵심 가치는 AI agent / 사용자가 "이 프로젝트가 어느
Claude 계정으로 라우팅되는지" 를 알 수 있는 것이다.

### 11.8 다수 Pulumi backend 관리 (per-project Pulumi routing, v0.12.0+)

Pulumi 의 "계정"은 AWS profile / gh 계정 같은 단일 username 이 아니라 **backend**
(state 저장 위치 + org/account) 개념이다. project 별로 다른 backend 를 쓰면
`Pulumi.yaml` 의 `backend.url` 로 선언하고, 필요 시 `.envrc` 의
`PULUMI_BACKEND_URL` 로 override 한다.

```yaml
# Pulumi.yaml — state backend 선언 (커밋되는 SoT)
name: my-infra
runtime: python
backend:
  url: s3://acme-pulumi-state
```

```bash
# (선택) .envrc 로 backend env override — Pulumi.yaml 과 일치시킬 것
cat >> ~/dev/my-infra/.envrc <<'EOF'
export PULUMI_BACKEND_URL="s3://acme-pulumi-state"
EOF
direnv allow
```

| Check | 동작 | 상태 |
|---|---|---|
| `project-pulumi-backend-mapping` | `project_roots` 아래 `Pulumi.yaml` backend ↔ `.envrc` `PULUMI_BACKEND_URL` 정합성 검증 (global) | ✓ v0.12.0 |
| `pulumi_backend_routing` | cwd 의 `Pulumi.yaml` backend ↔ `.envrc` `PULUMI_BACKEND_URL` 정합성 (`anvyc project doctor` 의 per-cwd check) | ✓ v0.12.0 |

```bash
# 개별 실행
anvyc doctor --only project-pulumi-backend-mapping
anvyc project doctor              # cwd 에 pulumi_backend_routing 포함 8 check
```

`anvyc project show --json` 의 `pulumi.backend` 필드로 backend 를 확인할 수 있다
(DESIGN §32.4c). `backend` 키를 명시하지 않으면 Pulumi Cloud default 이며 anvyc 은
명시 선언만 추적한다. `PULUMI_ACCESS_TOKEN` 은 secret 이라 `dev_env` 에서 자동
마스킹되고, anvyc 은 값을 추적하지 않는다.

### 11.9 shell prompt 에 라우팅 표시 (`anvyc prompt`, v0.13.0+)

`anvyc prompt` 는 현재 디렉터리의 계정 라우팅(§11.5~11.8)을 shell prompt 용
한 줄로 출력한다 — `project show` 를 매번 치지 않고 prompt 에서 바로 확인.

```bash
$ anvyc prompt
aws:company-dev gh:16bitdo claude:edward
```

설정된 필드만 공백 구분 `key:value` 로 출력하고 없으면 빈 출력이다. starship
custom command / powerlevel10k 세그먼트 연동 방법은
[docs/shell-prompt.md](./docs/shell-prompt.md) 참고.

---

## 12. 호스트별 overlay (v0.6.4+)

머신마다 다른 도구 enabled/files 설정을 별도 yaml 분기 없이 적용할 수 있다.

```
.anvyc/
├── anvyc.yaml                          # base — 공통 설정
└── anvyc.<hostname>.yaml               # overlay — 머신별 설정 (선택)
```

- hostname = `socket.gethostname().split(".")[0]` (FQDN 안전)
  - 예: `host-a.local` → `anvyc.host-a.yaml`
- `ANVYC_HOSTNAME` env 로 override 가능 (테스트/머신 이동 시 유용)

### 예: 공통 설정 + macOS-A 머신만 git 비활성화

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
# .anvyc/anvyc.macOS-A.yaml (macOS-A 머신 한정 — 합쳐서 적용)
tools:
  git:
    enabled: false
```

### Merge 규칙

| 타입 | 동작 |
|---|---|
| dict | recursive deep merge (overlay 우선) |
| list | overlay 가 base 대체 (concat 아님 — 안전성/명시성) |
| scalar | overlay 우선 |

### 확인

```bash
anvyc config show --effective    # merged result + overlay_source 표시
anvyc tools list                 # overlay 반영된 enabled/files count
```

overlay 미존재 시 base 동작 그대로 — backward compatible.

---

## 13. 로드맵

- **v0.1.0~v0.5.3** ✓ Released — 8 adapter / 9 CLI / 7 doctor check / SOPS / 1Password / Git sync
- **v0.6.0** ✓ — OSS 공개 준비 + multi-AWS-profile 가이드 (§11)
- **v0.6.1** ✓ — multi-account doctor checks (10 check 총합)
- **v0.6.2** ✓ — `anvyc init --from-git` + Homebrew Formula 초안 + GitHub Release 자동화
- **v0.6.3** ✓ — `anvyc config edit/show` + `anvyc tools list` + 영어 에러 메시지 표준화
- **v0.6.4** ✓ — 호스트별 yaml overlay (§12)
- **v0.7.0** ✓ — `dev_env` 어댑터 (.envrc/.tool-versions/.nvmrc 추적) + `unused-aws-profiles` doctor check
- **v0.7.1** ✓ — `anvyc init --interactive` wizard + `install.sh` one-liner
- **v0.7.2** ✓ — pydantic 의존 제거 (Homebrew install fix)
- **v0.8.0** ✓ — `anvyc project show` (AI agent multi-project view) + JSON output 확장 ([plan](./docs/archive/improvement-plan-ai-agent.md))
- **v0.8.1** ✓ — `anvyc project list` + `anvyc project doctor` (cross-project matrix + 정합성 5 check)
- **v0.9.0** ✓ — MCP server (`anvyc serve --mcp`, Claude Code/Cursor 직접 호출)
- **v0.10.0** ✓ — MCP tool naming cleanup (`anvyc_` prefix 제거, breaking)
- **v0.11.0** — per-project gh 계정 라우팅 인식 + 프로젝트 루트 SoT 단일화 (`~/dev` 이전) — 별도 태깅 없이 v0.12.0 으로 통합 배포
- **v0.12.0** ✓ — per-project Claude Code·Pulumi backend 계정 라우팅 인식 ([plan](./docs/archive/improvement-plan-account-routing.md))
- **v0.13.0** (현재) — shell prompt 통합 — `anvyc prompt` 세그먼트 명령 + starship/p10k config 어댑터
- **v1.0** — API stable, PyPI 배포

자세한 내용은 [CONTEXT.md](./CONTEXT.md), [RELEASE_NOTES.md](./RELEASE_NOTES.md), [docs/archive/improvement-plan-ux-review.md](./docs/archive/improvement-plan-ux-review.md) 참고.

---

## 14. 기여

[CONTRIBUTING.md](./CONTRIBUTING.md) 참고.

## 15. 보안

취약점 신고는 [SECURITY.md](./SECURITY.md) 의 비공개 채널로 부탁드립니다.

## 16. 라이선스

[MIT License](./LICENSE) © 2026 edward (16bitdo)

# anvyc

> **anvyc**는 여러 장치(주로 macOS)에서 개발 도구 설정 정보와 인증 정보를 **안전하게 백업, 비교, 복원, 동기화**하는 CLI 도구다.

상세 설계는 [DESIGN.md](./DESIGN.md)를 참고한다.

## 목차

- [1. 한 줄 설명](#1-한-줄-설명) · [2. 왜 만들었나](#2-왜-만들었나) · [3. 핵심 원칙](#3-핵심-원칙) · [4. 지원 도구](#4-지원-도구)
- [5. 설치](#5-설치) · [6. 빠른 시작](#6-빠른-시작) · [7. 디렉터리 구조](#7-디렉터리-구조) · [8. 명령어 요약](#8-명령어-요약)
- [9. 보안 정책 요약](#9-보안-정책-요약) · [10. 기술 스택](#10-기술-스택)
- [11. 다수 계정 관리](#11-다수-계정-관리) · [12. 호스트별 overlay](#12-호스트별-overlay-v064)
- [13. AI agent control-plane (CP-1·4·5·6·12·13)](#13-ai-agent-control-plane-v0140)
- [14. 로드맵](#14-로드맵) · [15. 기여 / 보안 / 라이선스](#15-기여--보안--라이선스)

심화 문서 (별도 파일):

| 문서 | 내용 |
|---|---|
| [DESIGN.md](./DESIGN.md) | 설계 본문 (38 섹션, axis 본문은 docs/design-axes/ 로 분리) |
| [docs/multi-account.md](./docs/multi-account.md) | AWS / GitHub / Claude / Pulumi per-project 계정 라우팅 가이드 |
| [docs/security-policy.md](./docs/security-policy.md) | 1Password Secret Reference + SOPS encryption-at-rest |
| [docs/doctor-json-schema.md](./docs/doctor-json-schema.md) | `anvyc doctor --json` 안정 schema (CI 통합용) |
| [docs/control-plane.md](./docs/control-plane.md) | AI agent control-plane axes (CP-1·4·5·6·12·13) + Cost observability |
| [docs/design-axes/](./docs/design-axes/) | 각 axis 의 schema · 명령 contract · 안전 절차 본문 |
| [docs/mcp-integration.md](./docs/mcp-integration.md) | MCP server 설정 / 8 tool 사용 예 |
| [docs/install-via-homebrew.md](./docs/install-via-homebrew.md) | Homebrew 사용자 설치 / 검증 / 제거 가이드 |
| [docs/shell-prompt.md](./docs/shell-prompt.md) | starship / p10k 세그먼트 연동 |
| [docs/troubleshooting-macos.md](./docs/troubleshooting-macos.md) | macOS-specific 트러블슈팅 |

---

## 1. 한 줄 설명

```text
여러 장치에서 개발 환경 설정을 안전하게 백업·비교·복원·동기화하는 macOS CLI.
Shell / Git / AWS / GitHub / Cursor / Claude Code / iTerm2 / Pulumi + dev_env / shell_prompt — 10 종 도구의 safe adapter.
AI agent 의 audit / snapshot / creds / sync / workctx / cost 6 종 control-plane axis 통합 (CP-1·4·5·6·12·13).
```

---

## 2. 왜 만들었나

- `.zshrc`, Cursor settings, iTerm2 plist, AWS config 등 **설정 위치가 제각각**이다.
- hostname, OS, email 등 **장비별 값이 달라** 단순 복사가 위험하다.
- credentials/token이 **dotfiles에 섞여 Git에 올라가는 사고**가 잦다.
- 단순 복사 방식은 **diff/검증/백업 절차가 부재**하다.

anvyc는 이 문제들을 **도구별 safe adapter** + **secret 기본 제외** + **apply 전 diff/dry-run** + **restore 전 local backup**으로 풀어낸다.

[chezmoi](https://chezmoi.io) 의 안전 원칙 (source/target 분리 · dry-run · age 암호화) 에서 영감을 받았다. 자세한 비교: [DESIGN.md §2 선행 사례](./DESIGN.md).

---

## 3. 핵심 원칙

1. **Secret 기본 제외** — `~/.aws/credentials`, `~/.pulumi/credentials.json`, SSH key, `.env`, Claude tokens 등은 수집하지 않는다.
2. **Apply 전 diff & dry-run** — 어떤 변경이 일어나는지 항상 먼저 확인한다.
3. **Restore 전 local backup** — 덮어쓰기 전 현재 상태를 자동으로 보관한다.
4. **도구별 safe adapter** — 범용 파일 복사 대신 도구 특성에 맞춘 안전한 추출/적용 로직.
5. **Git-friendly, secret-hostile** — Git push 전 pre-commit hook으로 secret을 재차 차단한다.

---

## 4. 지원 도구

> **AI 도구 시대의 dotfile manager** — Cursor / Claude Code 의 settings · hooks · plugins · MCP config 까지 도구별 safe adapter 로 다룬다. 범용 파일 복사 도구는 secret/세션/캐시 영역까지 통째 가져가지만, anvyc 는 도구별 특성을 인지해 **공유 가치 영역** (rules / skills / plugins / settings) 만 분리 수집한다.

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
| **shell_prompt** (v0.13.0+) | `~/.config/starship.toml`, `~/.p10k.zsh` | p10k instant-prompt 캐시 (재생성 가능, 미수집) |

---

## 5. 설치

### 5.1 one-liner 설치 (권장, v0.7.1+)

```bash
curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh | bash

# 특정 버전:
ANVYC_VERSION=v0.16.0 bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)

# 설치 도구 강제 (uv | pipx | auto):
ANVYC_METHOD=pipx bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)
```

- GitHub Release wheel + `SHA256SUMS` 자동 검증
- `uv tool` 또는 `pipx` 자동 감지 (없으면 명시 안내)

### 5.2 Homebrew tap (v0.7.1+)

```bash
brew tap 16bitdo/anvyc
brew install anvyc
anvyc --version
```

사용자 설치/검증 가이드 (사후 검증 / 트러블슈팅 / 제거 절차):
[docs/install-via-homebrew.md](./docs/install-via-homebrew.md).
Formula SoT: [packaging/homebrew/Formula/anvyc.rb](./packaging/homebrew/Formula/anvyc.rb).
Tap repo: [16bitdo/homebrew-anvyc](https://github.com/16bitdo/homebrew-anvyc).
메인테이너 릴리스 절차: [docs/homebrew-publishing.md](./docs/homebrew-publishing.md).

### 5.3 GitHub Release 의 wheel 직접 설치

```bash
# uv tool (권장)
uv tool install https://github.com/16bitdo/anvyc/releases/download/v0.16.0/anvyc-0.16.0-py3-none-any.whl

# 또는 pipx
pipx install https://github.com/16bitdo/anvyc/releases/download/v0.16.0/anvyc-0.16.0-py3-none-any.whl

anvyc --version
```

### 5.4 git remote 에서 부트스트랩 (v0.6.2+)

머신 A 에서 `.anvyc/` 를 private git repo 로 push 해두고, 새 머신 B 에서:

```bash
anvyc init --from-git git@github.com:<you>/anvyc-config.git
anvyc doctor
anvyc apply           # dry-run plan (default)
anvyc apply --apply   # 실 적용
```

`--from-git` 은 target `.anvyc/` 이 이미 있으면 fail-fast — 덮어쓰지 않는다.

### 5.5 MCP server (AI agent integration, v0.9.0+)

Claude Code / Cursor 등 MCP 호환 agent 에서 anvyc 의 read-only 8 tool 호출:
`project_show` / `project_list` / `project_doctor` / `doctor` / `tools_list` /
`activity_summary` (CP-1) / `tool_call_stats` (CP-1·8·11) / `cost_summary` (CP-13).
write 영역 (`backup` / `apply` / `restore` / `snapshot restore` / `creds rotate` /
`sync push/pull`) 은 의도적 미포함 — agent 가 destructive 실행 불가.

```bash
# 1) [mcp] extra 설치
uv tool install --upgrade 'anvyc[mcp]'

# 2) mcp.json 자동 등록 (v0.16.0+) — 기존 다른 server entry 보존, atomic write
anvyc mcp install --ide both --apply --yes

# 3) IDE 재시작 (Cmd+Q 후 재실행)

# 등록 상태 확인
anvyc mcp status
```

`anvyc mcp install` 은 `CLAUDE_CONFIG_DIR` env var 인지 + 기존 mcp.json 의
다른 server entry 보존 + dry-run default + `.bak` 자동 생성.

Manual 설정 (custom wrapper path 사용 시) 도 가능 — `~/.claude/mcp.json` 또는
`~/.cursor/mcp.json` 에 직접 JSON 작성. 상세: [docs/mcp-integration.md](./docs/mcp-integration.md).

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
> 깨질 수 있습니다 — dev wrapper 는 `.pth` 대신 `PYTHONPATH` 로 `src/` 를
> 주입해 `python -m anvyc` 로 실행하므로 이 트랩을 회피합니다. 원인·수동
> 대응은 [docs/troubleshooting-macos.md](./docs/troubleshooting-macos.md)
> 참고. 일반 사용자 (`uv tool install` / `pipx`) 는 영향 없음.

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
anvyc apply           # dry-run plan (default, v0.16.0+)
anvyc apply --apply   # 실 적용
```

선택 — shell 자동완성을 활성화하면 sub-command/flag tab 보완을 받을 수 있다:

```bash
anvyc --install-completion zsh   # bash / fish 도 동일
```

---

## 7. 디렉터리 구조

```text
anvyc/
├── README.md
├── DESIGN.md
├── CONTEXT.md         # AI agent 작업 인계 — 결정/가정/진행 상태
├── RELEASE_NOTES.md
├── pyproject.toml
├── src/anvyc/
│   ├── __main__.py    # python -m anvyc 진입점 (v0.13.0+)
│   ├── cli.py
│   ├── templates.py
│   ├── templates/     # 정적 자산 (예: aws-cost-readonly.json IAM policy, CP-13 PR-13C)
│   ├── core/          # inventory, backup, diff, apply, restore, metadata,
│   │   │              # project_info, project_roots, snapshot, creds, sync,
│   │   │              # activity, audit_log, workctx
│   │   └── cost/      # cost observability (CP-13) — api, compute, cache,
│   │                  # ledger, budgets, fx, adapters/, pricing/
│   ├── adapters/      # shell, git, aws, gh, cursor, claude, iterm2,
│   │                  # pulumi, dev_env, shell_prompt (10 도구)
│   ├── agents/        # multi-agent activity adapter (CP-7) — claude_code,
│   │                  # cursor, codex (Protocol + 3 어댑터)
│   ├── checks/        # 20 doctor check (cross_user, project_*_account,
│   │                  # venv_hidden, creds_expiry, hook_integrity,
│   │                  # mcp_extra_importable, work_cwd_track,
│   │                  # cost_aws_explorer_iam, cost_github_pat_scope, ...)
│   ├── mcp/           # MCP server (anvyc serve --mcp, v0.9.0+, [mcp] extra)
│   ├── security/      # scanner, patterns, policy
│   ├── storage/       # local, git, encryption
│   └── utils/         # paths, hashing, logging, gh_hosts, git_remote, ...
└── tests/{unit,integration,fixtures}
```

런타임 상태는 사용자 환경의 다음 위치에 저장된다:
- `.anvyc/` — 프로젝트 루트의 backup / snapshot / sync state
- `~/.anvyc-secrets/` — 분리된 secret 영역 (1Password ref / SOPS)
- `~/.config/anvyc/cost/` — CP-13 cost cache (raw daily / aggregate / fx / pricing)
- `~/.claude*/.work-cwd-cache` — CP-12 work-cwd cache (schema v1)
- `~/.config/cc-inspect/cost-window.json` — CP-13 6h rolling window (ccinspector owner, DESIGN §38.5)

---

## 8. 명령어 요약

```bash
# --- 핵심 backup / apply / restore ---
anvyc init                     # 프로젝트/설정 초기화
anvyc init --interactive       # 대화형 wizard (v0.7.1+)
anvyc init --from-git <url>    # git remote 에서 .anvyc/ clone (v0.6.2+)
anvyc doctor                   # 환경 진단 (20 check, CP-13 까지)
anvyc backup                   # 현재 환경 백업
anvyc status                   # target vs backup 차이 요약
anvyc diff                     # unified diff 출력
anvyc apply [--apply]          # default dry-run plan; --apply 시 실 적용 (전 local backup 자동, v0.16.0+)
anvyc restore <backup-id>      # 특정 backup으로 복원
anvyc list                     # 백업 목록
anvyc scan-secrets             # secret 패턴 스캔

# --- 설정 / 도구 / 프로젝트 view ---
anvyc config edit              # $EDITOR 로 anvyc.yaml 편집 + schema 검증 (v0.6.3+)
anvyc config show [--effective] [--json]   # raw 또는 default 적용된 yaml/json (v0.6.3+/v0.8.0)
anvyc tools list [--json]      # 10 도구의 enabled / detect / file-count (v0.6.3+/v0.13.0)

anvyc project show [--path P] [--json] [--reveal-secrets]
                               # cwd 의 AWS/GitHub/Pulumi/dev_env 통합 view (v0.8.0+)
anvyc project list [--root R...] [--json]
                               # root 아래 모든 project matrix (v0.8.1+)
anvyc project doctor [--path P] [--json] [--strict]
                               # cwd connection 정합성 8 check (v0.8.1+)
anvyc prompt [--path P] [--json]
                               # cwd 계정 라우팅을 shell prompt 용 한 줄로 (v0.13.0+)

# --- AI agent control-plane (CP-1·4·5·6·12·13) ---
anvyc activity [--limit N] [--agent <name>] [--json]
                               # AI agent session 별 통계 (CP-1, v0.14.0+)
anvyc snapshot {create|list|diff|restore}
                               # 작업 회복 — git stash + meta schema v1 (CP-4, v0.14.0+)
anvyc creds {status|rotate}    # AWS SSO / GitHub PAT / Claude OAuth 만료 + 재인증 (CP-5, v0.14.0+)
anvyc sync {status|push|pull}
anvyc sync conflict {list|resolve}
                               # cross-machine state sync — control-plane 자산 머신 간 동기화 (CP-6, v0.14.0+)
anvyc workctx {switch|clear|show}
                               # agent 의 work-cwd explicit override (CP-12, v0.15.0+)
anvyc cost {collect|summary|ledger|cleanup}
                               # cost observability — Anthropic (i) / AWS Cost Explorer / GitHub Billing
                               # 통합 합산 + KRW 표시 + EOM forecast + budget 평가 (CP-13, in-flight)
                               # (cleanup = cache GC; `gc` alias 도 지원)

# --- MCP / Git / SOPS ---
anvyc serve --mcp              # MCP server (8 read-only tool, Claude Code/Cursor 직접 호출, v0.9.0+)
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

`secret-scan` 은 `backup` / `apply` / `git push` 모든 시점에 실행된다.

### 9.1 두 가지 secret 분리 채널

| 채널 | 적합 | 안전 자산 |
|---|---|---|
| **1Password Secret Reference** (v0.1.0) | 단일 변수 raw secret | `op://<vault>/<item>/<field>` reference. 같은 라인에 `op://` 가 있으면 scanner false-positive 자동 강등. doctor `op-references-valid` check. |
| **SOPS encryption-at-rest** (v0.2) | `.env` 같은 다수 secret 묶음 | age 키 backend. `secret_files` 가 backup 시 자동 암호화 (`.sops.json`). doctor `sops-keys-available` check. |

두 채널 공존 가능. 설치 절차 / 사용 흐름 / scanner 통합 등 상세는
**[docs/security-policy.md](./docs/security-policy.md)** 참조.

### 9.2 `anvyc doctor --json` schema

CI / 다른 도구 통합용 안정 schema (v0.5.3+). 회귀 테스트로 보장.

```bash
anvyc doctor --json                          # 전체
anvyc doctor --only cross-user --json        # 특정 check 만
anvyc doctor --strict --json > /dev/null     # CI 게이트: blocking 발견 시 exit 1
```

필드 / 타입 / exit code / jq 활용 예 →
**[docs/doctor-json-schema.md](./docs/doctor-json-schema.md)**.

---

## 10. 기술 스택

| 항목 | 선택 |
|---|---|
| 언어 | Python 3.11+ |
| CLI | Typer |
| 출력 | Rich |
| YAML 파서 | PyYAML |
| 경로 패턴 | pathspec |
| 테스트 | pytest (+ pytest-cov) |
| Lint / Type | ruff / mypy (strict, `platform=darwin` 고정) |
| plist 처리 | plistlib (stdlib) |
| 패키징 | uv tool / pipx / Homebrew |
| 암호화 (선택, `[encryption]`) | cryptography |
| MCP server (선택, `[mcp]`) | mcp ≥ 1.0 |
| Cost / AWS (선택, `[cost-aws]`) | boto3 — Cost Explorer adapter |
| Cost / GitHub (선택, `[cost-github]`) | httpx — Enhanced Billing Platform |

pydantic 의존은 v0.7.2 에서 제거됐다 (Homebrew install 호환). 설정 검증은
stdlib (`dataclasses` + 수동 schema 검사) 로 처리한다.

---

## 11. 다수 계정 관리

AWS profile / GitHub / Claude Code / Pulumi 의 per-project 계정 라우팅을
`.envrc` (direnv) 로 선언하고 anvyc 의 doctor check 로 정합성을 검증한다.

```bash
# AWS
export AWS_PROFILE=my-dev
# GitHub
export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"
# Claude
export CLAUDE_CONFIG_DIR="$HOME/.claude-edward"
# Pulumi
export PULUMI_BACKEND_URL="s3://acme-pulumi-state"
```

shell prompt 통합 (v0.13.0+):

```bash
$ anvyc prompt
aws:company-dev gh:16bitdo claude:edward
```

다음 4 도구 × 5+ doctor check 의 전체 설정 절차 / 정합성 검증은
**[docs/multi-account.md](./docs/multi-account.md)** 참조.

| 도구 | env var | doctor check | 도입 |
|---|---|---|---|
| AWS | `AWS_PROFILE` (direnv) | `project-aws-profile-mapping` 외 3 | v0.6.1+ |
| GitHub | `GH_CONFIG_DIR` | `project-gh-account-mapping`, `gh_account_routing` | v0.11.0+ |
| Claude Code | `CLAUDE_CONFIG_DIR` | `project-claude-account-mapping`, `claude_account_dir_exists` | v0.12.0+ |
| Pulumi | `PULUMI_BACKEND_URL` + `Pulumi.yaml backend.url` | `project-pulumi-backend-mapping`, `pulumi_backend_routing` | v0.12.0+ |

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

## 13. AI agent control-plane (v0.14.0+)

anvyc 는 `role-based-ruleset` × `ccinspector` 와 함께 **AI agent autopilot 의 L2
Environment layer** 책임을 맡는다. 각 axis 는 `schema_version: 1` 단일 키로
통합되며 CP-3 scheduler 의 `anvyc doctor --strict --json` 호출에 자동 합류한다.

| Axis | 명령 | 도입 |
|---|---|---|
| **CP-1** audit | `anvyc activity` + MCP `activity_summary` / `tool_call_stats` | v0.14.0 |
| **CP-4** snapshot | `anvyc snapshot {create\|list\|diff\|restore}` | v0.14.0 |
| **CP-5** creds | `anvyc creds {status\|rotate}` + `creds-expiry-within-7d` check | v0.14.0 |
| **CP-6** sync | `anvyc sync {status\|push\|pull}` + `conflict {list\|resolve}` | v0.14.0 |
| **CP-12** work-cwd | `anvyc workctx {switch\|clear\|show}` + `work-cwd-track-wired` check | v0.15.0 |
| **CP-13** cost | `anvyc cost {collect\|summary\|ledger\|gc}` + MCP `cost_summary` | in-flight |

axis 요약 + Cost observability 빠른 사용 / doctor check / cache layout →
**[docs/control-plane.md](./docs/control-plane.md)**.
각 axis 의 상세 schema · 명령 contract · 안전 절차 →
**[docs/design-axes/](./docs/design-axes/)**.

---

## 14. 로드맵

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
- **v0.13.0** ✓ — shell prompt 통합 — `anvyc prompt` 세그먼트 명령 + starship/p10k config 어댑터
- **v0.14.0** ✓ — Control Plane v1+v2 합류 — CP-1 activity audit (`anvyc activity` + MCP `activity_summary` / `tool_call_stats`), CP-4 snapshot/restore (`anvyc snapshot`, schema v1, 4-layer safety), CP-5 credentials lifecycle (`anvyc creds` + `creds-expiry-within-7d` doctor check)
- **v0.14.x (CP-6)** ✓ — cross-machine state sync (`anvyc sync {status|push|pull}` + `sync conflict {list|resolve}`, schema v1, 4-layer safety)
- **v0.15.0** ✓ — Control Plane v6 — CP-12 agent work-cwd tracking (`anvyc workctx` CLI + `work-cwd-track-wired` doctor check, cache schema v1)
- **v0.15.1** ✓ — `__version__` 동적 lookup refactor (display drift 차단, pyproject 가 SoT)
- **v0.15.2** ✓ — MCP integration silent-failure hardening (`mcp-extra-importable` doctor check + dev-install.sh 기본 `[mcp]` extra + `print_error()`/`safe_msg()` 헬퍼)
- **v0.16.0** ✓ — Cost observability MVP (CP-13, 8 PR) + UX 친화도 개선 (3 PR — `anvyc mcp install` 자동 등록 / `anvyc apply` default dry-run breaking / `--help` 5-panel 카테고리화 + shell completion + wizard 10 도구) + docs 슬림화 (4 PR — README/DESIGN/RELEASE_NOTES 분리 + 결번 정정 + check 목록 갱신). cost adapter 3종 (`anvyc cost {collect|summary|ledger|gc}` + MCP `cost_summary` + 2 doctor check). 자세한 변경은 [RELEASE_NOTES.md](./RELEASE_NOTES.md) 의 v0.16.0 entry.
- **v0.16.x post-release polish** (untagged, 2026-05-28) — UX 4 관점 리뷰 후속 5 PR: test HOME isolation 메타 fix ([#101](https://github.com/16bitdo/anvyc/pull/101)), `--json` help 정합화 + shell completion 안내 + `cost cleanup` alias ([#102](https://github.com/16bitdo/anvyc/pull/102)), init wizard 의 cursor 3-layer (mask_mcp_tokens / globalStorage_allowlist / projects.enabled) prompt ([#103](https://github.com/16bitdo/anvyc/pull/103)), `anvyc mcp install --absolute-path` + `--claude-config-dirs` multi-account batch ([#104](https://github.com/16bitdo/anvyc/pull/104)), examples ↔ templates drift sync ([#105](https://github.com/16bitdo/anvyc/pull/105)).
- **v1.0** — API stable, PyPI 배포

자세한 내용은 [RELEASE_NOTES.md](./RELEASE_NOTES.md), [docs/archive/improvement-plan-ux-review.md](./docs/archive/improvement-plan-ux-review.md) 참고.

---

## 15. 기여 / 보안 / 라이선스

- 기여 가이드: [CONTRIBUTING.md](./CONTRIBUTING.md). 기여자 간 상호작용은 [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) ([Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) 기반) 를 따릅니다.
- 취약점 신고: [SECURITY.md](./SECURITY.md) 의 비공개 채널.
- 라이선스: [MIT License](./LICENSE) © 2026 edward (16bitdo)

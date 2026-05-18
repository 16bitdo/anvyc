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

## 4. 지원 도구 (MVP)

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

---

## 5. 설치 (예정)

> v0.1.0 릴리즈 후 사용 가능. MVP 개발 중에는 로컬 editable 설치로 사용한다.

### 5.1 사용자 설치 (예정)

```bash
pipx install anvyc
# 또는
uv tool install anvyc
```

### 5.2 개발 설치

```bash
git clone <repo-url> anvyc
cd anvyc
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
anvyc --help
```

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
anvyc doctor                   # 환경 진단
anvyc backup                   # 현재 환경 백업
anvyc status                   # target vs backup 차이 요약
anvyc diff                     # unified diff 출력
anvyc apply [--dry-run]        # source 설정 적용 (전 local backup 자동)
anvyc restore <backup-id>      # 특정 backup으로 복원
anvyc list                     # 백업 목록
anvyc scan-secrets             # secret 패턴 스캔
anvyc git {init|status|commit|push}
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

## 11. 로드맵

- **1주차 PoC**: CLI skeleton + shell/git/aws adapter + secret scanner v0
- **2주차 MVP**: cursor/claude/iterm2 adapter + diff/apply/restore + pre-commit hook
- **3주차 정비**: 테스트 보강 + 실제 Mac 2대 검증 + pipx 패키징 + v0.1.0 릴리즈

자세한 내용은 [CONTEXT.md §5 Roadmap](./CONTEXT.md)를 참고한다.

---

## 12. 라이선스

향후 결정. (후보: MIT, Apache-2.0)

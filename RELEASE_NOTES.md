# anvyc 릴리즈 노트

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

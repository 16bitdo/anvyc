# anvyc 릴리즈 노트

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

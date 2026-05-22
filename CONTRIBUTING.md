# Contributing to anvyc

기여를 환영합니다. anvyc 는 macOS 개발자 환경 설정을 안전하게 백업·동기화하는
CLI 도구이며, 사용자 친화성과 보안 안전망을 핵심 가치로 합니다.

## 1. 기여 가능 영역

- **버그 리포트** — 재현 단계 + 환경 정보 (`anvyc doctor --json` 출력 첨부 권장)
- **기능 제안** — Issue 로 의도와 사용 사례를 먼저 논의
- **PR (코드)** — 작은 변경부터 환영. 큰 변경은 Issue 로 사전 합의 권장
- **문서 개선** — README, DESIGN 의 오타·명확성 개선
- **새 어댑터** — 도구별 adapter 패턴 (예: vscode, helix, neovim)

## 2. 개발 환경 셋업

### 2.1 의존성

- macOS (1차 지원), Python 3.11+
- 빌드/패키징: [uv](https://github.com/astral-sh/uv) (또는 pip + build)
- 선택 의존성:
  - [SOPS](https://github.com/getsops/sops) + [age](https://github.com/FiloSottile/age) — secret encryption 테스트
  - [1Password CLI (`op`)](https://developer.1password.com/docs/cli/) — `op://` reference 검증
  - [direnv](https://direnv.net/) — 프로젝트별 env 자동화 (README §11 참고)

### 2.2 셋업

```bash
git clone git@github.com:16bitdo/anvyc.git
cd anvyc
bash scripts/dev-install.sh
```

`scripts/dev-install.sh` 가 venv·editable 설치·dev wrapper 를 멱등하게
처리합니다. 인터프리터를 고정하려면 `ANVYC_PYTHON=python3.13 bash scripts/dev-install.sh`,
extras 를 늘리려면 `ANVYC_EXTRAS="dev,encryption,mcp" bash scripts/dev-install.sh`.

<details><summary>수동 설치 (스크립트 미사용 시)</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,encryption]"
anvyc --version
```

> ⚠ **macOS Python 3.13 venv 트랩**: `.`-prefix 디렉터리(`.venv`)에 `UF_HIDDEN`
> 플래그가 자동으로 붙어 Python 3.13 의 `site.py` 가 `.pth` 를 스킵합니다.
> editable install 직후 `import anvyc` 가 실패하면:
>
> ```bash
> chflags -R nohidden .venv
> ```
>
> `anvyc doctor --only venv-hidden-flag` 가 이 문제를 자동 감지합니다. 이 수동
> 경로는 dev wrapper 를 설치하지 않습니다 — `.pth` 트랩을 거치지 않는
> `dev-install.sh` 사용을 권장합니다.

</details>

### 2.3 선택: SOPS + age 설치 (encryption 테스트 통과)

```bash
brew install sops age
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
# Public key 를 anvyc.yaml security.sops.age_recipients 에 등록
```

미설치 시 SOPS 관련 테스트는 자동 skip.

## 3. 테스트 실행

```bash
pytest -q tests                          # 전체 (≈ 64+ cases)
pytest -q tests/unit                     # unit only
pytest -q tests/integration              # integration only
pytest -q tests/integration/test_sops_*.py  # SOPS 영역
```

### 3.1 회귀 안전망

- `tests/unit/test_smoke.py` — import / cli 로드
- `tests/unit/test_scanner.py` — secret 패턴 + op:// downgrade
- `tests/unit/test_cross_user_classify.py` — cross-user 분류 로직
- `tests/integration/test_backup_status_diff.py` — backup/status/diff 라운드 트립
- `tests/integration/test_apply_restore.py` — apply/restore 라운드 트립
- `tests/integration/test_cursor_layer_c.py` — Cursor Layer C + symlink
- `tests/integration/test_git_workflow.py` — Git init + pre-commit hook
- `tests/integration/test_sops_roundtrip.py` — SOPS encrypt/decrypt
- `tests/integration/test_sops_cli.py` — `anvyc sops` 단독 CLI
- `tests/integration/test_iterm2_status.py` — iTerm2 target_hash 정합
- `tests/integration/test_doctor_json.py` — doctor --json schema

## 4. PR 가이드

### 4.1 Branch 명명

- `feat/<short-desc>` — 새 기능
- `fix/<short-desc>` — 버그 수정
- `docs/<short-desc>` — 문서만
- `chore/<short-desc>` — 빌드/툴체인/메타 변경
- `test/<short-desc>` — 테스트 보강

### 4.2 Commit 메시지

[Conventional Commits](https://www.conventionalcommits.org/) 스타일:

```
<type>: <짧은 요약, 명령형 어조>

<본문 — 무엇/왜>

<footer (선택)>
```

`<type>`: `feat`, `fix`, `docs`, `chore`, `test`, `refactor`, `perf`

### 4.3 PR 체크리스트

- [ ] `pytest -q tests` 전체 통과
- [ ] 새 기능은 unit + integration test 동반
- [ ] 새 기능은 README / DESIGN.md 갱신 (해당 시)
- [ ] secret 누출 없음 (`anvyc scan-secrets` 또는 grep)
- [ ] 큰 변경은 사전 Issue 합의

### 4.4 Style

```bash
ruff check src tests               # 린트
ruff format src tests              # 자동 포맷 (선택)
mypy src                            # 타입 체크 (best-effort)
```

## 5. Issue 가이드

### 5.1 Bug Report

다음을 포함해 주세요:

- anvyc 버전: `anvyc --version`
- OS: macOS 버전 (`sw_vers -productVersion`)
- 재현 단계 (최소 reproducer)
- 기대 동작 vs 실제 동작
- doctor 출력: `anvyc doctor --json` (민감 경로 제거 후)

### 5.2 Feature Request

- 사용 사례 + 현재 회피 방법
- 기존 어댑터/check 와의 관계
- (선택) 구현 아이디어

## 6. 보안

- 취약점 발견 시 **Public Issue 가 아닌** [SECURITY.md](./SECURITY.md) 의
  안내에 따라 비공개 채널로 보고해 주세요.
- 테스트 fixture 의 secret 은 모두 **명백한 합성값** (`AKIA1234567890ABCDEF` 등) 입니다.
  실제 token/credential 을 commit 에 포함하지 마세요.
- 로컬 commit 시 secret 누출 방지를 위해 [pre-commit](https://pre-commit.com) +
  [gitleaks](https://github.com/gitleaks/gitleaks) hook 을 설치합니다:
  ```bash
  brew install pre-commit gitleaks
  pre-commit install
  ```
  `.pre-commit-config.yaml` + `.gitleaks.toml` (project allowlist) 는 저장소에
  포함되어 있어 자동 적용됩니다.

## 7. 행동 강령

기여자 간 상호 존중. 기술 외 토론은 Issue 보다 적절한 채널에서.

## 8. 라이선스

기여하신 코드는 [MIT License](./LICENSE) 하에 배포됩니다.

---

질문은 Issue 로 자유롭게 부탁드립니다. 작은 PR 부터 환영합니다.

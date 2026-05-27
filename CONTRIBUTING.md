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

### 2.4 Git hooks (자동)

`scripts/dev-install.sh` 가 마지막 단계로 `scripts/install-git-hooks.sh` 를
자동 호출해 `.git/hooks/pre-push` 를 설치합니다 (멱등).

- **pre-push**: `pytest -m "not integration"` 으로 unit fast-fail gate (약
  15 초). 실패 시 push 차단 — CI 의 `Pytest (unit, fast-fail gate)` step
  과 동일 명령이므로 결과 일관. 의도적 우회: `git push --no-verify`.
- **SoT**: `scripts/hooks/pre-push.sh` (git 추적). 수동 재설치:
  `bash scripts/install-git-hooks.sh`.
- `.venv/bin/pytest` 가 없으면 hook 은 graceful skip — 셋업 직후 첫 push 가
  실패하지 않습니다.

기존 `.git/hooks/pre-commit` (secret/개인화 파일 차단) 은 별도 도메인의
hook 으로 이 installer 가 손대지 않습니다.

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
mypy src/anvyc/ tests/             # 타입 체크 (strict — CI / pre-commit 과 동일 범위)
```

`mypy` 범위는 CI 의 `Lint and type-check` job 과 동일하게 `src/anvyc/ tests/`
입니다. pre-commit hook 도 같은 범위로 실행되므로 push 전 잡힙니다.

### 4.5 CLI 사용자 출력 (console.print 가이드)

`cli.py` 의 사용자-facing 출력은 [Rich](https://github.com/Textualize/rich)
콘솔을 통과합니다. Rich 는 `[red]`, `[bold]` 같은 markup 태그를 해석하기 때문에,
**외부 값**(예외 메시지·subprocess 출력·diff 라인 등) 을 그대로 보간하면
값 안의 `[xxx]` 표기가 silent strip 됩니다.

실제 사례: `pip install 'anvyc[mcp]'` 안내가 `pip install 'anvyc'` 로 표시돼
사용자가 잘못된 명령을 실행하던 버그 (`#71`).

**규칙**

| 상황 | 사용 |
|---|---|
| 에러 메시지 (예외 또는 외부값 포함) | `print_error(message)` |
| 색상 + 외부값 보간 (예: diff 라인 색상) | `console.print(f"[color]{safe_msg(value)}[/]")` |
| 색상 + 리터럴/안전한 값만 (path, int 등) | `console.print(f"[color]{path}[/]")` — 그대로 OK |

```python
from anvyc.utils.errors import print_error, safe_msg

# 에러:
try:
    risky_op()
except FooError as e:
    print_error(e)                                    # "[red]error[/] <escaped str(e)>"
    raise typer.Exit(code=1) from e

# 색상 + 외부값 보간:
console.print(f"[red]{safe_msg(diff_line)}[/]")

# 절대 작성 금지 (markup strip 위험):
console.print(f"[red]error[/] {e}")                   # ✗
console.print(f"[red]{e}[/]")                         # ✗
console.print(f"[green]{subprocess_output}[/]")       # ✗
```

브래킷 보존이 중요한 이유: pip extra 표기(`[mcp]`), 로그 prefix(`[INFO]`),
정규식 character class 등 합법적인 메시지에 brace 가 포함될 수 있습니다.

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

기여자 간 상호 존중. 기술 외 토론은 Issue 보다 적절한 채널에서. 본 프로젝트는 [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) 을 기반으로 한 [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) 를 채택합니다. 위반 신고는 `16bitdo@gmail.com` (제목 prefix `[anvyc-conduct]`) 로 비공개로 보내주세요.

## 8. 라이선스

기여하신 코드는 [MIT License](./LICENSE) 하에 배포됩니다.

---

질문은 Issue 로 자유롭게 부탁드립니다. 작은 PR 부터 환영합니다.

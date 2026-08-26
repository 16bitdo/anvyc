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

- **pre-push**: 보호 브랜치 가드(anvyc-pr-guard) → `ruff` → `mypy src/anvyc/ tests/`
  → `pytest -m "not integration"` 순서로 실행하는 fast-fail gate. 앞 단계 실패 시
  즉시 차단합니다. CI 의 `Lint and type-check` · `Pytest (unit, fast-fail gate)` step
  과 동일 명령이라 결과가 일관됩니다. 의도적 우회: `git push --no-verify`.
- **SoT**: `scripts/hooks/pre-push.sh` (git 추적). 수동 재설치:
  `bash scripts/install-git-hooks.sh`.
- `.venv/bin/pytest` 가 없으면 hook 은 graceful skip — 셋업 직후 첫 push 가
  실패하지 않습니다.

`.git/hooks/pre-commit` 은 이 installer 가 손대지 않습니다 — 그 자리는
**pre-commit framework** (`.pre-commit-config.yaml`) 가 씁니다. `pre-commit install`
로 켜지며 gitleaks(내용 기반 시크릿) · ruff · mypy(CI 와 동일 범위) ·
**personal-config-guard**(경로 기반 개인화 파일 차단) 를 실행합니다.

- **personal-config-guard**: tracked `scripts/hooks/pre-commit` 을 local 훅으로
  호출합니다 — 정규식·마커 로직을 config 에 복제하지 않습니다. `--no-verify` 우회와
  훅 미설치 환경은 `.github/workflows/personal-config-guard.yml` 이 server-side 로
  재검사하며, 거기서도 **같은 스크립트를 재호출**해 SoT 를 하나로 유지합니다.
  배선 자체는 `tests/unit/test_personal_config_guard_wiring.py` 가 구속합니다.

### 2.5 로컬 소스를 tool 로 설치한 경우 — 갱신 절차

`dev-install.sh`(editable) 대신 **로컬 디렉터리를 tool venv 로 non-editable 설치**해
쓰는 환경이 있습니다.

```bash
uv tool install "$HOME/dev/anvyc[mcp,tui]"
```

이 형태는 설치 시점의 소스를 **복사**합니다 — editable 이 아니므로 이후 `git pull` 로
소스가 바뀌어도 반영되지 않습니다. 갱신은 재설치로만 됩니다.

**`--force` 만으로는 조용히 실패합니다.** uv 캐시에 같은 version 의 빌드 아티팩트가
남아 있으면 그것을 재사용하는데, 로컬 소스는 커밋이 바뀌어도 `pyproject.toml` 의
version 이 그대로면 같은 키가 됩니다. 그래서 `--force` 는 재설치를 수행하고 **rc=0 으로
끝나지만 낡은 빌드가 그대로 다시 깔립니다.** 로그도 정상이라 알아채기 어렵습니다.

```bash
# 갱신 — 캐시 우회가 필수
uv tool install --force --reinstall --refresh --python 3.14 "$HOME/dev/anvyc[mcp,tui]"
```

**검증은 버전 문자열이 아니라 "기대하는 심볼" 로 합니다.** 로컬 소스 설치에서 version 은
커밋을 구분하지 못합니다.

```bash
anvyc worktree --help                    # 최근 추가된 커맨드가 보이는가
P=$(echo ~/.local/share/uv/tools/anvyc/lib/python*/site-packages/anvyc)
ls "$P/core/worktree.py"                 # 최근 추가된 모듈이 있는가
```

> **2026-08-26 실사고.** 소스에는 `anvyc worktree add` 와 doctor 의
> `worktree_rule_links` 검사가 있었으나(2026-08-25 `a281b21`, PR #204) 설치본
> (2026-08-17 빌드)에는 없었습니다. 양쪽 다 `--version` 이 `v0.21.0` 이라 낙후가
> 가려졌고, `--force` 만 붙인 첫 재설치는 rc=0 으로 끝났는데 `core/worktree.py` 가
> 여전히 없었습니다. `--reinstall --refresh` 를 붙여서야 반영됐습니다.
>
> uv 캐시에서 직접 확인된 근거 — 같은 버전의 dist-info 가 둘 공존했습니다:
>
> ```
> 2026-08-17 07:00  archive-v0/…/anvyc-0.21.0.dist-info   ← --force 가 재사용한 것
> 2026-08-26 20:18  archive-v0/…/anvyc-0.21.0.dist-info   ← --refresh 로 새로 빌드된 것
> ```
>
> 이 함정을 없애려면 기능 머지 시 version 을 올리거나 `--version` 에 커밋 SHA 를
> 병기하는 편이 낫습니다(별도 트랙).

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
ruff check src tests               # 린트 — CI·pre-commit 이 강제
mypy src/anvyc/ tests/             # 타입 체크 (strict — CI / pre-commit 과 동일 범위)
```

`mypy` 범위는 CI 의 `Lint and type-check` job 과 동일하게 `src/anvyc/ tests/`
입니다. pre-commit hook 도 같은 범위로 실행되므로 push 전 잡힙니다.

#### `ruff format` 은 쓰지 않습니다

강제 대상은 **`ruff check`(린트) 와 `mypy`** 뿐입니다. `ruff format` 은 CI
(`.github/workflows/ci.yml`)에도 pre-commit(`.pre-commit-config.yaml`)에도 없고,
**PR 에서 실행하지 마세요.**

- **전 트리 포맷**은 253 파일 · 4219 줄을 바꿉니다(2026-08-16 측정). 이 저장소는
  결정의 근거를 코드 주석과 커밋 이력에 남기는 방식으로 굴러가는데, 그 규모의 재포맷은
  `git blame` 을 통째로 덮어 "이 줄이 왜 이렇게 됐는가" 를 추적 불가능하게 만듭니다.
- **일부 파일만 포맷**해도 문제입니다. 변경과 무관한 스타일 diff 가 섞여 리뷰어가 실질
  변경을 찾기 어려워집니다 — 실제로 2026-08-16 에 4 파일을 고치며 `ruff format` 을 함께
  돌렸다가 diff 가 70 줄에서 132 줄로 부풀어, 되돌리고 다시 커밋했습니다.

로컬에서 포맷터를 쓰고 싶다면 커밋에 포함시키지 마세요. 스타일이 거슬리는 부분은
그 파일을 **실제로 고치는 PR** 에서 함께 정리하는 편이 낫습니다.

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

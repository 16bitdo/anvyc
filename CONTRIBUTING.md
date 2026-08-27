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
- **외부 managed-block 은 보존됩니다.** 설치된 훅에 anvyc 소유가 아닌 블록이 있으면
  (`# >>> <name> … >>>` ~ `# <<< <name> <<<`) 교체 전에 떼어내 SoT 뒤에 다시 붙입니다
  (`scripts/preserve_managed_blocks.py`). role-based-ruleset 의 `claude-md-freshness`
  가 그 예입니다 — 예전에는 재설치가 그 블록을 조용히 지워 CLAUDE.md stale 게이트가
  push 에서 빠졌습니다(2026-08-27). 짝이 맞지 않는 마커는 깨진 훅을 만들지 않도록
  보존하지 않고, 무엇을 버렸는지 stderr 에 알립니다.

`.git/hooks/pre-commit` 은 이 installer 가 손대지 않습니다 — 그 자리는
**pre-commit framework** (`.pre-commit-config.yaml`) 가 씁니다. `pre-commit install`
로 켜지며 gitleaks(내용 기반 시크릿) · ruff · mypy(CI 와 동일 범위) ·
**personal-config-guard**(경로 기반 개인화 파일 차단) 를 실행합니다.

- **personal-config-guard**: tracked `scripts/hooks/pre-commit` 을 local 훅으로
  호출합니다 — 정규식·마커 로직을 config 에 복제하지 않습니다. `--no-verify` 우회와
  훅 미설치 환경은 `.github/workflows/personal-config-guard.yml` 이 server-side 로
  재검사하며, 거기서도 **같은 스크립트를 재호출**해 SoT 를 하나로 유지합니다.
  배선 자체는 `tests/unit/test_personal_config_guard_wiring.py` 가 구속합니다.

### 2.5 이미 설치된 환경 갱신하기

**먼저 설치 방식을 판별합니다 — 갱신 절차가 정반대입니다.**

```bash
head -1 "$(command -v anvyc)"
#  #!/usr/bin/env bash                            → A. dev wrapper (editable)
#  #!/…/.local/share/uv/tools/anvyc/bin/python3   → B. uv tool 설치본
```

판별을 건너뛰면 A 환경에서 B 의 절차를 실행하는 사고가 납니다 — `uv tool install` 은
`~/.local/bin/anvyc` 를 자기 런처로 덮어써 **dev wrapper 를 없앱니다.** "pull 즉시 반영"
이던 환경이 "매번 재설치" 로 퇴행하는데, 명령 자체는 정상 종료합니다.

#### A. dev wrapper (editable) — `git pull` 이 곧 갱신

`dev-install.sh` 로 셋업한 환경입니다. wrapper 가 repo 의 `src/` 를 `PYTHONPATH` 로
직접 실행하므로 **소스가 곧 실행본**입니다. 재설치 없이 pull 만으로 반영됩니다.

`dev-install.sh` 재실행이 필요한 경우는 다음입니다 (멱등이라 확신이 안 서면 그냥
돌려도 안전합니다 — venv 는 인터프리터가 맞으면 재사용됩니다):

- `pyproject.toml` 의 **의존성이 바뀐** pull 을 받았을 때 — 새 패키지가 venv 에 없습니다.
- `pyproject.toml` 의 **version 이 올랐을 때** — `--version` 표시는 `.venv` 의 dist-info
  를 읽으므로 재설치 전까지 옛 버전으로 보입니다. **코드는 이미 최신입니다** — 표시만
  낡은 것이라 낙후로 오진하지 마세요.
- `scripts/anvyc-wrapper.sh` **정본이 바뀌었을 때** — 설치된 wrapper 는 사본입니다.
- `scripts/hooks/pre-push.sh` **정본이 바뀌었을 때** — 함께 갱신됩니다.

```bash
bash scripts/dev-install.sh   # venv 재사용 · editable 재설치 · wrapper/hook 은 변경 시에만 교체
```

#### B. uv tool 설치본 — 재설치로만 갱신

**로컬 디렉터리를 tool venv 로 non-editable 설치**해 쓰는 환경입니다.

```bash
uv tool install "$HOME/dev/anvyc[mcp,tui]"
```

> 릴리스(PyPI·whl)로 설치한 일반 사용자는 이 절차가 아닙니다 — `uv tool install
> --upgrade 'anvyc[mcp]'` 로 끝납니다([README](./README.md)). 아래 캐시 함정은
> version 이 그대로인 **로컬 소스** 설치에만 생깁니다.

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

#### 갱신 검증

`--version` 은 소스 커밋을 병기합니다 (v0.21.0+, #206). version 문자열만으로는 커밋을
구분할 수 없습니다 — 릴리스 배치 버저닝이라 한 version 이 여러 커밋을 덮습니다.

**커밋을 어디서 읽는지가 설치 형태마다 다릅니다.** 괄호 안의 ` source` 가 그 구분입니다.

```bash
# A — dev wrapper: 런타임 git 이 답한다 (항상 현재값)
anvyc --version                                   # anvyc v0.21.0 (5ea9534 source)
git -C "$HOME/dev/anvyc" rev-parse --short HEAD   # 5ea9534   ← 항상 일치

# B — uv tool 설치본: 빌드 시 각인된 값 (설치 시점에 고정)
anvyc --version                                   # anvyc v0.21.0 (6176216)
git -C "$HOME/dev/anvyc" rev-parse --short HEAD   # 6176216   ← 일치해야 갱신 완료
```

**A (dev wrapper)** — 실행 중인 코드가 곧 워킹트리이므로 `--version` 이 **런타임에**
`git rev-parse HEAD` 를 읽어 ` source` 를 병기합니다. 따라서 **A 에서는 SHA 가 HEAD 와
항상 일치**하고, 불일치는 낙후가 아니라 버그입니다. editable 설치는 `_build_info.py` 를
만들지 않습니다 — 설치 시점에 얼어붙은 값이 `git pull` 직후 거짓이 되기 때문입니다.
git 조회 비용은 `--version` 경로에서만 냅니다(다른 명령의 시작 시간은 그대로입니다).

**B (uv tool 설치본)** — 각인된 SHA 가 곧 설치된 소스의 커밋입니다. 위 두 값이
**일치해야 갱신 완료**이고, 불일치는 낙후입니다.

공통으로:

- `(… source)` 는 **A(소스 실행)** 입니다 — 그 SHA 는 "지금 실행 중인 커밋"입니다.
  `source` 가 없으면 **B(설치본)** 이고, 그 SHA 는 "빌드된 시점의 커밋"입니다.
- 괄호가 **아예 없으면**(`anvyc v0.21.0`) #206 이전 빌드입니다 — 그 자체가 낙후 신호입니다.
- `+dirty` 는 커밋되지 않은 변경이 섞여 있다는 뜻입니다 (`5ea9534+dirty source`).
- 릴리스(태그) 빌드는 version 이 곧 식별자이므로 SHA 를 붙이지 않습니다.

> **2026-08-26 실사고 — #206 이 해소한 문제.** 소스에는 `anvyc worktree add` 와 doctor 의
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
> 빌드 시 소스 커밋을 각인하는 #206 으로 `--version` 이 커밋을 구분하게 되어, 이제는
> 같은 함정이 발생해도 즉시 드러납니다.

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

# 설치 방식을 아는 extras 설치 안내 설계

- **날짜**: 2026-10-07
- **상태**: 설계 승인됨 (스펙 검토 대기)
- **프로젝트**: anvyc (L2-environment)
- **관련**: `core/extras.py`(`EXTRAS_REGISTRY` · `install_hint`), `checks/{mcp_extra_importable,tui_extra,cost_aws_explorer_iam,cost_github_pat_scope}.py`, `core/cost/adapters/base.py`(`CostAdapterDepMissingError`), `mcp/server.py`, `cli.py`(`extras` · `serve`), `__init__.py`(`_source_repo`), `scripts/dev-install.sh`, `scripts/gen_extras.py`, README §5.7, PR #228(문서·install.sh `ANVYC_EXTRAS`)

## 1. 배경 / 문제

anvyc 는 **PyPI 에 없다** — pypi.org simple·JSON, test.pypi.org 모두 404 이고 어느 워크플로에도 publish 단계가 없다. PyPI 배포는 v1.0 으로 보류돼 있다(DESIGN §29.2). 그런데 코드가 출력하는 pyextra 설치 안내는 전부 이름 기반이다.

| 출력 지점 | 현재 문구 |
|---|---|
| `checks/mcp_extra_importable.py` | `pip install 'anvyc[mcp]' (uv: uv tool install 'anvyc[mcp]' · dev: …)` |
| `checks/tui_extra.py` | `pip install 'anvyc[tui]' (또는 uv tool install 'anvyc[tui]') …` |
| `checks/cost_aws_explorer_iam.py` | `pip install 'anvyc[cost-aws]' …` |
| `checks/cost_github_pat_scope.py` | `pip install 'anvyc[cost-github]' …` |
| `core/cost/adapters/base.py` | `install with: pip install 'anvyc[{group}]'` |
| `mcp/server.py` (ImportError) | `pip install 'anvyc[mcp]' or uv tool install 'anvyc[mcp]'` |
| `core/extras.py` `ExtraReq.install_cmd` (`anvyc extras`·README 표) | `pip install 'anvyc[…]'` 5종 |

`install_hint(name)` 이라는 단일 SoT 가 이미 있지만(바이너리 도구는 이것을 쓴다) pyextra 6곳은 우회해 문자열을 박았다. 두 check 의 주석은 "pipx/uv/brew/venv 어디서든 복붙 가능하도록 plain install" 이라고 근거를 적었는데, **그 전제가 실측으로 틀렸다**(2026-10-07, 격리 sandbox):

| 맥락 | `pip install 'anvyc[mcp]'` 류의 결과 |
|---|---|
| 새 환경 | rc=1 — no matching distribution |
| pip venv + 설치본, **그 환경의 pip** | extras 추가 (동작) |
| uv tool · pipx · Homebrew 설치본 | PATH 의 `pip` 은 다른 환경 — 설치본에는 아무 일도 없다 |
| pipx `install --force 'anvyc[mcp]'` | rc=1 |
| 이름 선점 시뮬레이션(가짜 `anvyc` 99.0.0) | 새 설치·`--upgrade` 형은 **가짜를 설치·교체** |

또 **extras 는 누적되지 않는다** — uv tool·pipx 의 재설치는 요구 문자열의 extras 로 환경을 맞추므로, 요청한 extra 하나만 적은 안내를 따르면 다른 extras 의 의존이 제거된다(install.sh E2E: extras 없이 재실행하자 "Uninstalled 30 packages"). 안내가 `cost-aws` 하나만 적으면 그것을 따른 사용자의 MCP 가 깨진다.

## 2. 목표 / Non-goals

**목표**:
- 런타임 pyextra 안내가 **현재 설치 방식에서 실제로 동작하는 명령**이다. 어떤 안내도 PyPI 에서 이름으로 찾지 않는다.
- 안내 명령이 **이미 설치된 extras 를 보존**한다.
- pyextra 안내는 모두 `install_hint()` 한 경로를 지난다 — 하드코딩 6곳 제거.
- README 생성 표는 환경과 무관한 정적 문구(권장 경로 명령)를 유지한다.

**Non-goals (YAGNI)**:
- 바이너리(CLI) 도구 안내(`brew install sops` 등) — 무변경.
- 자동 설치 — anvyc 는 안내만 하고 설치기를 실행하지 않는다.
- Homebrew formula 에 extras 지원 추가 — 범위 밖. Homebrew 설치본은 install.sh 로 옮기도록 안내만 한다.
- PyPI 배포·이름 확보 — 별도 결정.
- pipx 의 로컬 디렉터리 설치 특수 처리 — 문서화된 경로가 아니다. pipx 는 install.sh 형으로 안내한다.
- `anvyc mcp status`·MCP 등록 경로 문제 — 별건.

## 3. 결정 (승인됨)

**접근 A — 설치 방식 판별 + 그 방식의 정확한 명령.** 정적 안내(B: README §5.7 링크만)는 틀리지 않지만 복붙 명령이 아니고, install.sh 고정(C)은 Homebrew·venv 에서 두 번째 설치본을 만들고 버전을 최신으로 바꾼다.

판별 신호(전부 2026-10-07 실측):

| 순서 | 방식 | 신호 |
|---|---|---|
| 1 | `dev` | `anvyc._source_repo()` — 패키지가 git worktree 안. wrapper 와 `.venv/bin/anvyc` 직접 실행 모두 |
| 2 | `uv-tool-source` | `sys.prefix/uv-receipt.toml` 의 anvyc 요구에 `directory` 키 (CONTRIBUTING §2.5 B) |
| 3 | `uv-tool` | 같은 receipt 의 `url` 또는 `path` 키 (Release URL·install.sh 설치본) |
| 4 | `pipx` | `sys.prefix/pipx_metadata.json` |
| 5 | `homebrew` | `sys.prefix` 경로에 `Cellar/anvyc` 구간 |
| 6 | `venv` | `sys.prefix != sys.base_prefix` |
| 7 | `unknown` | 그 외 |

방식별 명령(§6 에 정확한 문자열):

| 방식 | 명령 |
|---|---|
| `dev` | `ANVYC_EXTRAS=<합집합> bash <repo>/scripts/dev-install.sh` |
| `uv-tool` | `ANVYC_VERSION=v<현재> ANVYC_EXTRAS=<합집합> bash <(curl -sSL <install.sh>)` — 같은 버전·SHA256 검증 |
| `uv-tool-source` | `uv tool install --force --reinstall --refresh '<dir>[<합집합>]'` (CONTRIBUTING B) |
| `pipx` | `ANVYC_METHOD=pipx ANVYC_VERSION=v<현재> ANVYC_EXTRAS=<합집합> bash <(curl -sSL <install.sh>)` |
| `homebrew` | "extras 미지원" 문구 + install.sh 명령 + README §5.7 |
| `venv` | `<python> -m pip install 'anvyc[<합집합>] @ <현재 버전 Release wheel URL>'` |
| `unknown` | install.sh 명령 + README §5.7 |

## 4. 아키텍처

**신규 `src/anvyc/core/install_method.py`** — stdlib 만 쓴다(`mcp` 미설치 ImportError 경로에서도 import 된다).

```python
InstallMethod = Literal["dev", "uv-tool-source", "uv-tool", "pipx", "homebrew", "venv", "unknown"]

@dataclass(frozen=True)
class InstallContext:
    method: InstallMethod
    python: str               # sys.executable — venv 명령용
    source_dir: Path | None   # dev: repo 루트, uv-tool-source: receipt 의 directory

def detect(*, prefix=None, base_prefix=None, source_repo=_AUTO, executable=None) -> InstallContext
    # 인자는 테스트 주입용. 기본값은 sys.prefix / sys.base_prefix / anvyc._source_repo() / sys.executable.
    # 어떤 예외도 밖으로 내지 않는다 — 판별 실패는 "unknown".

def extras_install_command(extras, *, ctx=None, version=None) -> str
    # extras: 이미 합치고 레지스트리 순서로 정렬한 pip extra 키(mcp, tui, cost-aws …).
    # 합집합·정렬은 core/extras.py 가 한다 — install_method 는 레지스트리를 모른다(core/extras 가
    # install_method 를 import 하므로 반대 방향 import 는 순환). dev 일 때만 기본값을 앞에 붙이고
    # 중복을 지운다. version 기본값은 anvyc.__version__.

DEV_INSTALL_DEFAULT_EXTRAS = ("dev", "mcp", "tui")   # scripts/dev-install.sh 기본값과 drift 테스트로 묶는다
INSTALL_SH_URL = "https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh"
README_INSTALL_URL = "https://github.com/16bitdo/anvyc#57-업그레이드와-extras-추가-설치-방식별"
```

**`core/extras.py` 변경**:
- `installed_pip_extras() -> tuple[str, ...]` — probe dist 가 설치된 pyextra 의 `pip_extra` 키(레지스트리 순서).
- `_order_extras(keys) -> list[str]` — 레지스트리 순서, 그 밖의 키는 정렬해 뒤에.
- `install_hint(name)` — 바이너리는 무변경. pyextra 는 `install_hint_for_extra(req.pip_extra)`.
- `install_hint_for_extra(pip_extra)` — `extras_install_command(_order_extras({pip_extra, *installed_pip_extras()}))`. 비용 어댑터 오류가 직접 쓴다. 미지 키도 같은 규칙으로 명령을 만든다.
- pyextra 5종의 정적 `install_cmd` = `ANVYC_EXTRAS=<key> bash <(curl -sSL <install.sh>)` — README 표 전용. 런타임 출력은 쓰지 않는다.
- `collect_extras_status()` 의 `install_cmd` — pyextra 는 런타임 명령(`extras_install_command`), 바이너리는 지금과 같은 정적 값.

**호출부**:
- 4개 check 의 `suggestion` = `install_hint(<name>)` + 기존 꼬리 문구(예: "설치 후 `anvyc cost collect --source aws` 가능"). 틀린 근거 주석은 실측 근거로 교체.
- `CostAdapterDepMissingError` 메시지 = `install_hint_for_extra(group)`.
- `mcp/server.py` 의 ImportError 메시지 = `install_hint("mcp")` (except 블록 안에서 import).
- `cli.py serve` · `mcp/__init__.py` docstring — 이름 기반 명령을 지우고 `anvyc extras` / README §5.7 을 가리킨다.
- `cli.py` 의 Rich escape 주석(현재 `pip install 'anvyc[cost-aws]'` 를 대괄호 예시로 든다) — 예시를 바꾼다. 아래 drift 가드가 주석까지 본다.

**복붙 가능성 — 긴 명령이 줄바꿈되지 않게**:
- 새 안내는 120~180자다. `utils/errors.print_error` 는 `soft_wrap` 없이 출력해 비-TTY 80열에서 강제 개행한다 — 복사한 명령이 중간에서 끊긴다. `soft_wrap=True` 로 바꾼다(doctor 렌더링이 이미 같은 이유로 쓰는 설정).
- `anvyc extras` 표의 설치 명령 칸은 긴 명령을 접는다(`overflow="fold"`). 표 아래에 미설치 행의 명령을 한 줄씩(`soft_wrap=True`) 출력한다 — 표는 개요, 그 아래 줄이 복붙용.

**여러 extras 를 한 번에 — 합산 명령** (최종 리뷰 반영 — 처음 이 스펙은 이것을 Non-goal 로 두었다):
- 행별·check 별 안내는 각자 *표시 시점*의 설치 상태로 계산돼 서로를 모른다. uv tool·pipx·install.sh 설치본은 재설치가 환경을 요구 extras 에 맞추므로, `mcp` 안내와 `cost-aws` 안내를 차례로 실행하면 두 번째 재설치가 첫 번째가 깐 `mcp` 를 지운다. "행별 명령은 순차 실행해도 맞다" 는 처음 가정은 틀렸다.
- `install_hint_for_extras(keys)` 가 요청 키 전부 + 설치된 extras 의 합집합으로 명령 하나를 만든다. `install_hint_for_extra(k)` 는 `install_hint_for_extras([k])` 다.
- `anvyc extras` — 미설치 pyextra 가 2개 이상이면 행별 명령 아래에 `# 여러 개를 한 번에` 와 합산 명령 한 줄을 더 낸다. 머리말이 "행별 명령은 서로를 대체한다" 고 알린다.
- `anvyc doctor`(요약·verbose) — 표시된 blocking 결과의 suggestion 가운데 서로 다른 extras 안내가 2건 이상이면 끝에 `extras 설치 안내 N건 — 하나씩 실행하면 서로를 지운다 … 한 번에:` 와 합산 명령을 낸다. 건수는 키가 아니라 suggestion 으로 센다 — `dev` 는 기본 extras(`dev,mcp,tui`) 안의 키들이 같은 명령을 내므로 키로 세면 같은 명령 하나를 2건으로 센다.

**한 줄 통째 복붙 — 덧붙임은 셸 주석**:
- 안내 줄은 통째로 붙여 넣어도 bash 문법이 맞아야 한다. 명령 뒤 괄호 설명 `(…)` 는 bash 가 `syntax error near unexpected token '('` 로 거부한다 — 덧붙임은 `  # …` 셸 주석으로 붙인다. 대상: Homebrew·unknown 안내(§6), doctor 의 cost check 2종 suggestion(`# 설치 후 … 가능`).
- 바이너리 도구 안내의 `(또는 <url>)` 는 Non-goal(무변경)이다.

## 5. 데이터 흐름

```
check / 오류 경로 / anvyc extras
  → install_hint(name) ─ binary → 정적 install_cmd (무변경)
                       └ pyextra → install_hint_for_extra(key) = install_hint_for_extras([key])
                                   installed_pip_extras()          → 이미 설치된 extras
                                   _order_extras(...)              → 합집합·레지스트리 순서
                                   extras_install_command(...)     → detect() → 방식별 템플릿 → 문자열
여러 개: anvyc extras · doctor 꼬리말 → install_hint_for_extras(keys) — 합산 명령 하나
README 표: scripts/gen_extras.py → render_extras_markdown() → 정적 install_cmd (환경 무관, 무변경 경로)
```

합집합 순서는 결정적이다: (`dev` 일 때만) `DEV_INSTALL_DEFAULT_EXTRAS` → 레지스트리 순서(mcp, tui, cost-aws, cost-github, encryption) → 그 밖의 요청 키 정렬. 중복은 첫 위치만 남긴다.

## 6. 동작 정의 (수용 기준)

예시 조건: 현재 버전 `0.23.0`, 설치된 extras `{mcp}`, 요청 `cost-aws`. `<SH>` = `INSTALL_SH_URL`.

| 방식 | 기대 문자열 |
|---|---|
| `dev` (repo `/r/anvyc`) | `ANVYC_EXTRAS=dev,mcp,tui,cost-aws bash /r/anvyc/scripts/dev-install.sh` |
| `uv-tool` | `ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,cost-aws bash <(curl -sSL <SH>)` |
| `uv-tool-source` (dir `/s/anvyc`) | `uv tool install --force --reinstall --refresh '/s/anvyc[mcp,cost-aws]'` |
| `pipx` | `ANVYC_METHOD=pipx ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,cost-aws bash <(curl -sSL <SH>)` |
| `homebrew` | `ANVYC_EXTRAS=mcp,cost-aws bash <(curl -sSL <SH>)  # Homebrew 설치본은 extras 를 지원하지 않는다 — install.sh 로 옮긴다. 설치 방식별: <README_INSTALL_URL>` |
| `venv` (python `/v/bin/python`) | `/v/bin/python -m pip install 'anvyc[mcp,cost-aws] @ https://github.com/16bitdo/anvyc/releases/download/v0.23.0/anvyc-0.23.0-py3-none-any.whl'` |
| `unknown` | `ANVYC_EXTRAS=mcp,cost-aws bash <(curl -sSL <SH>)  # 설치 방식별: <README_INSTALL_URL>` |

추가 규칙:
- 버전이 `^\d+\.\d+\.\d+$` 가 아니면(예: `0.0.0+unknown`) `ANVYC_VERSION=` 를 붙이지 않는다. `venv` 는 Release URL 을 만들 수 없으므로 `unknown` 문구로 내려간다.
- 경로·인터프리터는 `shlex.quote` — 공백 경로도 복붙된다. `'<dir>[…]'` 는 zsh 글롭(`[`)을 피하려고 항상 따옴표가 붙는다.
- 생성된 어떤 명령에도 `@` 없는 `anvyc[` 이름 기반 요구가 나오지 않는다.
- 어떤 방식의 안내든 줄 전체가 `bash -n` 을 통과한다(설명은 셸 주석).
- `src/` 전체(주석·docstring 포함)에 `pip install 'anvyc[` · `uv tool install 'anvyc[` · `pipx install … 'anvyc[` 꼴이 ` @ ` 없이 나타나지 않는다 — 설명이 필요하면 명령 꼴이 아닌 말로 쓴다("PyPI 에서 이름으로 찾는 설치").

## 7. 에러 처리 / 엣지

- `detect()` 는 receipt TOML·pipx JSON 파싱 실패, 권한 오류 등 어떤 예외도 삼키고 다음 신호로 넘어간다 — 안내 문구가 doctor 를 죽이면 안 된다.
- `installed_pip_extras()` 는 probe dist 로 판정하므로 과대 추정할 수 있다(`httpx`·`cryptography` 는 mcp 의 전이 의존). 과대 포함은 이미 있는 의존을 다시 요청할 뿐 무해하고, 과소 포함만 extras 를 지운다 — 그래서 probe 기반을 택한다.
- `dev` 의 pip 는 extras 를 지우지 않지만(`pip install -e` 는 제거하지 않는다), venv 재생성 시를 위해 기본값을 포함한다.
- uv tool 설치본에는 `uv` 가 반드시 있으므로 install.sh 의 auto 가 uv 를 고른다. pipx 는 uv 도 있을 수 있어 `ANVYC_METHOD=pipx` 를 명시한다.
- `bash <(…)` 는 bash·zsh 용이다. fish 등은 범위 밖(README 와 동일).

## 8. 테스트 (TDD)

- `detect()` — tmp prefix 에 마커를 두고 7개 방식 각각(receipt `directory`/`url`/`path`, pipx JSON, `Cellar/anvyc` 경로, venv, unknown) + 깨진 receipt 는 다음 신호로.
- `extras_install_command()` — §6 표의 정확한 문자열, 합집합·중복 제거·순서, 버전 미고정, 공백 경로 quoting, 미지 extra.
- `install_hint` / `install_hint_for_extra` — pyextra 가 판별 결과를 따르는지(`detect` monkeypatch), 바이너리 무변경.
- 호출부 — 4개 check suggestion · `CostAdapterDepMissingError` · MCP ImportError 메시지가 `install_hint()` 결과를 담는지. 기존 테스트(`test_extras_registry` 의 "pip install" 단언, `test_serve_mcp_error_message`)를 새 계약으로 갱신.
- drift 가드 — `DEV_INSTALL_DEFAULT_EXTRAS` ↔ `scripts/dev-install.sh` 의 `EXTRAS="${ANVYC_EXTRAS:-…}"`; **`src/` 전체(주석 포함)에 §6 의 이름 기반 설치 꼴이 없다**(파일 텍스트 검색 — 가드가 먼저 실패하는 것을 RED 로 확인).
- README — 표 재생성, `test_gen_extras` 통과.
- 복붙 가능성 — `print_error` 가 좁은 콘솔(width 40)에서도 긴 메시지에 개행을 넣지 않는다; `anvyc extras` 가 미설치 행의 명령 전문을 표 아래 한 줄로 낸다; 7개 방식의 안내와 cost check suggestion 줄 전체가 `bash -n` 을 통과한다.
- 합산 명령 — `install_hint_for_extras` 가 요청 키 + 설치된 extras 를 합친다; `anvyc extras` 는 미설치 pyextra 2개 이상일 때만 합산 줄을 낸다; doctor 요약·verbose 는 서로 다른 extras 안내 2건 이상일 때만 꼬리말을 내고, `dev` 의 같은 명령 2건은 1건으로 센다.
- E2E(격리 sandbox) — 브랜치 wheel 을 uv tool·pipx·venv 로 설치하고 dev 소스에서도 실행. mcp 없는 상태에서 `anvyc doctor --only mcp-extra-importable` 이 출력하는 명령을 **그대로 실행**해 mcp 설치 + 기존 extras 보존을 확인한다(명령은 v0.23.0 Release 를 가리킨다).

## 9. 문서 / 영향

- README — 동반 도구 표 재생성(pyextra 5행이 install.sh 형), 표 아래 노트를 "런타임 안내는 설치 방식을 따른다(`anvyc extras`)" 로 갱신.
- `docs/mcp-integration.md` — 인용한 실제 오류 문구가 바뀐다. 방식별로 달라지므로 예시와 함께 갱신.
- DESIGN — §27 근처 extras SoT 서술(현재 "`pip install 'anvyc[…]'` 의 단일 SoT")을 설치 방식 판별로 갱신.
- `anvyc extras --json` 의 `install_cmd` 값이 환경에 따라 달라진다 — 필드 이름은 그대로, 외부 소비자 없음(anvyx·ccinspector·rbr 검색 0건).
- RELEASE_NOTES — 다음 릴리스에서.

## 10. 단계 / 브랜치

브랜치 `feat/install-method-extras-hints`, PR 1개.

1. 스펙(이 문서) → 구현 계획(`docs/superpowers/plans/2026-10-07-install-method-aware-extras-hints.md`)
2. `core/install_method.py` — `detect` · `extras_install_command` (TDD)
3. `core/extras.py` 연결 — `installed_pip_extras` · `install_hint` · `install_hint_for_extra` · 정적 `install_cmd` (최종 리뷰 후 `install_hint_for_extras` · `missing_pip_extras` 추가)
4. 호출부 6곳 + docstring, 기존 테스트 갱신, drift 가드
5. README 재생성 · 문서 · DESIGN
6. E2E 4종 + 전체 게이트

# 설치 방식을 아는 extras 설치 안내 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 코드가 출력하는 pyextra 설치 안내(doctor 4종·MCP 오류·cost 어댑터 오류·`anvyc extras`)를 지금 실행 중인 anvyc 의 설치 방식에서 실제로 동작하고 이미 설치된 extras 를 보존하는 명령으로 바꾼다.

**Architecture:** 새 `core/install_method.py` 가 설치 방식을 판별(`detect`)하고 방식별 명령을 만든다(`extras_install_command`). `core/extras.py` 가 합집합·레지스트리 정렬을 맡아 `install_hint()` → `install_hint_for_extra()` 한 경로로 모든 pyextra 안내를 만든다. 하드코딩 6곳은 그 함수를 부르고, 긴 명령이 줄바꿈되지 않도록 `print_error` 와 `anvyc extras` 를 고친다.

**Tech Stack:** Python 3.11+ (stdlib `tomllib`·`shlex`), Typer, Rich, pytest, ruff, mypy(strict)

**Spec:** `docs/superpowers/specs/2026-10-07-install-method-aware-extras-hints-design.md`

## Global Constraints

- `core/install_method.py` 는 stdlib 만 import 한다 — `mcp` 미설치 ImportError 경로에서도 import 된다. `core/extras` 를 import 하지 않는다(순환).
- `INSTALL_SH_URL = "https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh"`
- `RELEASE_WHEEL_URL = "https://github.com/16bitdo/anvyc/releases/download/v{v}/anvyc-{v}-py3-none-any.whl"`
- `README_INSTALL_URL = "https://github.com/16bitdo/anvyc#57-업그레이드와-extras-추가-설치-방식별"`
- `DEV_INSTALL_DEFAULT_EXTRAS = ("dev", "mcp", "tui")` — `scripts/dev-install.sh` 의 `EXTRAS="${ANVYC_EXTRAS:-dev,mcp,tui}"` 와 같다.
- 방식별 명령 문자열은 spec §6 표와 글자 단위로 같다.
- `detect()` 는 어떤 예외도 밖으로 내지 않는다.
- `src/` 전체(주석·docstring 포함)에 `pip install 'anvyc[` · `uv tool install 'anvyc[` · `pipx install … 'anvyc[` 꼴이 ` @ ` 없이 나타나지 않는다.
- ruff `line-length = 100`, mypy `strict = true` (src + tests). 주석·docstring 은 한국어, 저장소 문체.
- 테스트 실행은 항상 `env -u FORCE_COLOR .venv/bin/pytest …` — 샌드박스의 `FORCE_COLOR=3` 이 색 민감 테스트를 거짓 실패시킨다.
- 커밋은 pre-commit 훅(gitleaks·guard·ruff·mypy)을 통과해야 한다. `--no-verify` 금지.

## Review Focus

- **공백이 든 경로**(repo·python·receipt directory) — 명령이 따옴표로 감싸져 복붙된다. → Task 2 `test_paths_with_spaces_are_quoted`.
- **깨졌거나 남의 `uv-receipt.toml`**(잘못된 TOML·`requirements` 가 리스트 아님·anvyc 요구 없음·읽기 권한 없음) — 예외 없이 다음 신호로. → Task 1 `test_broken_or_foreign_receipt_falls_through`, `test_detect_never_raises_on_unreadable_receipt`.
- **릴리스가 아닌 버전**(`0.0.0+unknown`, `0.24.0.dev1`) — `ANVYC_VERSION` 고정 없이, venv 는 install.sh 안내로. → Task 2 `test_non_release_version_is_not_pinned`.
- **Homebrew 의 opt 심볼릭 링크 prefix**(`/opt/homebrew/opt/anvyc/libexec`) — resolve 후 `Cellar/anvyc` 로 인식, 다른 formula 의 Cellar 는 Homebrew-anvyc 가 아니다. → Task 1 `test_homebrew_via_opt_symlink`, `test_other_cellar_formula_is_not_homebrew_anvyc`.
- **좁은·비-TTY 콘솔**(CliRunner 80열, width 40) — 긴 명령에 강제 개행이 없다. → Task 4 `test_print_error_never_hard_wraps_a_long_command`, `test_missing_rows_print_full_command_on_one_line`.

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `src/anvyc/core/install_method.py` | 설치 방식 판별 + 방식별 명령 문자열 | 신규 |
| `src/anvyc/core/extras.py` | 레지스트리·합집합·정렬·`install_hint` 경로 | 수정 |
| `src/anvyc/utils/errors.py` | `print_error` 줄바꿈 금지 | 수정 |
| `src/anvyc/cli.py` | `anvyc extras` 명령 전문 줄, 주석·docstring | 수정 |
| `src/anvyc/checks/{mcp_extra_importable,tui_extra,cost_aws_explorer_iam,cost_github_pat_scope}.py` | suggestion → `install_hint` | 수정 |
| `src/anvyc/core/cost/adapters/base.py` | `CostAdapterDepMissingError` 메시지 | 수정 |
| `src/anvyc/mcp/server.py`, `src/anvyc/mcp/__init__.py` | ImportError 메시지, docstring | 수정 |
| `tests/unit/test_install_method.py` | 판별·명령 | 신규 |
| `tests/unit/test_extras_install_hints.py` | extras 연결 | 신규 |
| `tests/unit/test_no_pypi_name_install_hints.py` | src 가드 | 신규 |
| 기존 테스트 7개 | 새 계약으로 단언 갱신 | 수정 |
| `README.md`, `docs/mcp-integration.md`, `DESIGN.md` | 생성 표·노트·오류 인용·§11.2 | 수정 |

---

### Task 1: 설치 방식 판별 — `detect()`

**Files:**
- Create: `src/anvyc/core/install_method.py`
- Test: `tests/unit/test_install_method.py`

**Interfaces:**
- Consumes: `anvyc._source_repo() -> Path | None` (기존, `src/anvyc/__init__.py`)
- Produces:
  - `InstallMethod = Literal["dev", "uv-tool-source", "uv-tool", "pipx", "homebrew", "venv", "unknown"]`
  - `@dataclass(frozen=True) class InstallContext: method: InstallMethod; python: str; source_dir: Path | None = None`
  - `detect(*, prefix: Path | None = None, base_prefix: Path | None = None, source_repo: Path | None | _Auto = _AUTO, executable: str | None = None) -> InstallContext`
  - 상수 `INSTALL_SH_URL`, `RELEASE_WHEEL_URL`, `README_INSTALL_URL`, `DEV_INSTALL_DEFAULT_EXTRAS`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_install_method.py`:

```python
"""core/install_method — 설치 방식 판별과 extras 설치 명령.

spec: docs/superpowers/specs/2026-10-07-install-method-aware-extras-hints-design.md
판별 신호는 2026-10-07 실측(uv receipt 의 url/path/directory, pipx_metadata.json,
Homebrew 의 Cellar/anvyc prefix)을 따른다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core import install_method as im
from anvyc.core.install_method import InstallContext, detect


def _receipt(prefix: Path, body: str) -> None:
    prefix.mkdir(parents=True, exist_ok=True)
    (prefix / "uv-receipt.toml").write_text(body, encoding="utf-8")


def _detect(prefix: Path, *, base: Path | None = None) -> InstallContext:
    return detect(
        prefix=prefix,
        base_prefix=base if base is not None else Path("/base"),
        source_repo=None,
        executable="/py",
    )


def test_dev_when_source_repo(tmp_path: Path) -> None:
    ctx = detect(
        prefix=tmp_path, base_prefix=tmp_path, source_repo=Path("/r/anvyc"), executable="/py"
    )
    assert ctx == InstallContext("dev", "/py", Path("/r/anvyc"))


def test_running_from_this_checkout_is_dev() -> None:
    assert detect().method == "dev"


def test_uv_tool_source_from_receipt_directory(tmp_path: Path) -> None:
    _receipt(
        tmp_path,
        '[tool]\nrequirements = [{ name = "anvyc", extras = ["mcp"], directory = "/s/anvyc" }]\n',
    )
    assert _detect(tmp_path) == InstallContext("uv-tool-source", "/py", Path("/s/anvyc"))


@pytest.mark.parametrize("key", ["url", "path"])
def test_uv_tool_from_receipt_url_or_path(tmp_path: Path, key: str) -> None:
    _receipt(
        tmp_path,
        f'[tool]\nrequirements = [{{ name = "anvyc", {key} = "/x/anvyc-0.23.0-py3-none-any.whl" }}]\n',
    )
    assert _detect(tmp_path) == InstallContext("uv-tool", "/py")


@pytest.mark.parametrize(
    "body",
    [
        "not = [valid",
        '[tool]\nrequirements = "oops"\n',
        '[tool]\nrequirements = [{ name = "other" }]\n',
    ],
    ids=["invalid-toml", "not-a-list", "no-anvyc"],
)
def test_broken_or_foreign_receipt_falls_through(tmp_path: Path, body: str) -> None:
    _receipt(tmp_path, body)
    assert _detect(tmp_path).method == "venv"  # 다음 신호(prefix ≠ base)로 — 예외 없음


def test_detect_never_raises_on_unreadable_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt(tmp_path, "[tool]\nrequirements = []\n")

    def boom(*_args: object, **_kwargs: object) -> object:
        raise PermissionError("denied")

    monkeypatch.setattr(im.tomllib, "load", boom)
    assert _detect(tmp_path).method == "venv"


def test_pipx_metadata(tmp_path: Path) -> None:
    tmp_path.joinpath("pipx_metadata.json").write_text("{}", encoding="utf-8")
    assert _detect(tmp_path).method == "pipx"


def test_homebrew_cellar_prefix(tmp_path: Path) -> None:
    prefix = tmp_path / "Cellar" / "anvyc" / "0.23.0" / "libexec"
    prefix.mkdir(parents=True)
    assert _detect(prefix).method == "homebrew"


def test_homebrew_via_opt_symlink(tmp_path: Path) -> None:
    real = tmp_path / "Cellar" / "anvyc" / "0.23.0"
    (real / "libexec").mkdir(parents=True)
    opt = tmp_path / "opt"
    opt.mkdir()
    (opt / "anvyc").symlink_to(real)
    assert _detect(opt / "anvyc" / "libexec").method == "homebrew"


def test_other_cellar_formula_is_not_homebrew_anvyc(tmp_path: Path) -> None:
    prefix = tmp_path / "Cellar" / "python@3.13" / "3.13.16"
    prefix.mkdir(parents=True)
    assert _detect(prefix).method == "venv"


def test_venv_when_prefix_differs(tmp_path: Path) -> None:
    assert _detect(tmp_path).method == "venv"


def test_unknown_when_prefix_is_base(tmp_path: Path) -> None:
    assert _detect(tmp_path, base=tmp_path).method == "unknown"
```

- [ ] **Step 2: 실패 확인**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_install_method.py -q -p no:cacheprovider`
Expected: 수집 단계 ERROR — `ModuleNotFoundError: No module named 'anvyc.core.install_method'`

- [ ] **Step 3: 최소 구현**

`src/anvyc/core/install_method.py`:

```python
"""설치 방식 판별 + extras 설치 명령 — 런타임 안내가 '그 설치본에서 동작하는 명령' 이 되도록.

anvyc 는 PyPI 에 없다(v1.0 보류). PyPI 에서 이름으로 찾는 설치 안내는 새 환경에서 실패하고,
uv tool·pipx·Homebrew 설치본에서는 PATH 의 pip 가 다른 환경이라 설치본에 닿지 않는다
(2026-10-07 실측). 이 모듈은 지금 실행 중인 anvyc 가 어떻게 설치됐는지 판별하고 그 방식의
명령을 만든다.

stdlib 만 쓴다 — `mcp` 미설치 ImportError 경로(anvyc.mcp.server)에서도 import 된다.
레지스트리(core/extras)는 모른다: core/extras 가 이 모듈을 import 하므로 반대 방향은 순환이다.
"""

from __future__ import annotations

import enum
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

InstallMethod = Literal["dev", "uv-tool-source", "uv-tool", "pipx", "homebrew", "venv", "unknown"]

INSTALL_SH_URL: Final = "https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh"
RELEASE_WHEEL_URL: Final = (
    "https://github.com/16bitdo/anvyc/releases/download/v{v}/anvyc-{v}-py3-none-any.whl"
)
README_INSTALL_URL: Final = (
    "https://github.com/16bitdo/anvyc#57-업그레이드와-extras-추가-설치-방식별"
)
# scripts/dev-install.sh 의 `EXTRAS="${ANVYC_EXTRAS:-…}"` 와 같아야 한다(테스트가 묶는다).
DEV_INSTALL_DEFAULT_EXTRAS: Final[tuple[str, ...]] = ("dev", "mcp", "tui")


@dataclass(frozen=True)
class InstallContext:
    """판별 결과. `python` 은 venv 명령용, `source_dir` 는 dev·uv-tool-source 의 소스 경로."""

    method: InstallMethod
    python: str
    source_dir: Path | None = None


class _Auto(enum.Enum):
    TOKEN = 0


_AUTO: Final = _Auto.TOKEN


def detect(
    *,
    prefix: Path | None = None,
    base_prefix: Path | None = None,
    source_repo: Path | None | _Auto = _AUTO,
    executable: str | None = None,
) -> InstallContext:
    """지금 실행 중인 anvyc 의 설치 방식. 인자는 테스트 주입용이고 기본값은 런타임 값이다.

    어떤 예외도 밖으로 내지 않는다 — 판별은 안내 문구를 위한 것이라, 실패가 doctor 를
    죽이면 안 된다. 신호를 못 읽으면 다음 신호로 넘어간다.
    """
    python = executable if executable is not None else sys.executable
    repo: Path | None
    if isinstance(source_repo, _Auto):
        repo = _source_repo_or_none()
    else:
        repo = source_repo
    if repo is not None:
        return InstallContext("dev", python, repo)

    pfx = prefix if prefix is not None else Path(sys.prefix)
    base = base_prefix if base_prefix is not None else Path(sys.base_prefix)

    req = _uv_receipt_requirement(pfx)
    if req is not None:
        directory = req.get("directory")
        if isinstance(directory, str) and directory:
            return InstallContext("uv-tool-source", python, Path(directory))
        return InstallContext("uv-tool", python)
    if _is_file(pfx / "pipx_metadata.json"):
        return InstallContext("pipx", python)
    if _is_homebrew(pfx):
        return InstallContext("homebrew", python)
    if _resolved(pfx) != _resolved(base):
        return InstallContext("venv", python)
    return InstallContext("unknown", python)


def _source_repo_or_none() -> Path | None:
    try:
        import anvyc

        return anvyc._source_repo()
    except Exception:  # noqa: BLE001 — 판별은 안내용이라 실패해도 다음 신호로 간다
        return None


def _uv_receipt_requirement(prefix: Path) -> dict[str, object] | None:
    """uv tool 설치본이면 receipt 의 anvyc 요구(dict), 아니면 None.

    실측 형식: `[tool] requirements = [{ name = "anvyc", extras = [...],
    url|path|directory = "..." }]` — url 은 Release URL, path 는 install.sh 가 쓴 임시 wheel,
    directory 는 로컬 소스(CONTRIBUTING §2.5 B).
    """
    try:
        with (prefix / "uv-receipt.toml").open("rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError):  # 파일 없음·권한·TOMLDecodeError(ValueError 하위)
        return None
    tool = data.get("tool")
    reqs = tool.get("requirements") if isinstance(tool, dict) else None
    if not isinstance(reqs, list):
        return None
    for req in reqs:
        if isinstance(req, dict) and req.get("name") == "anvyc":
            return req
    return None


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _is_homebrew(prefix: Path) -> bool:
    """Homebrew formula 의 libexec venv — resolve 하면 `…/Cellar/anvyc/<ver>/libexec`."""
    parts = _resolved(prefix).parts
    return any(
        part == "Cellar" and i + 1 < len(parts) and parts[i + 1] == "anvyc"
        for i, part in enumerate(parts)
    )
```

- [ ] **Step 4: 통과 확인**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_install_method.py -q -p no:cacheprovider`
Expected: 16 passed

Run: `.venv/bin/ruff check src/anvyc/core/install_method.py tests/unit/test_install_method.py && .venv/bin/mypy src/anvyc/core/install_method.py tests/unit/test_install_method.py`
Expected: `All checks passed!` / `Success: no issues found`

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/install_method.py tests/unit/test_install_method.py
git commit -m "feat(install-method): 실행 중인 anvyc 의 설치 방식을 판별한다"
```

---

### Task 2: 방식별 명령 — `extras_install_command()`

**Files:**
- Modify: `src/anvyc/core/install_method.py` (Task 1 파일 끝에 추가)
- Test: `tests/unit/test_install_method.py` (끝에 추가)

**Interfaces:**
- Consumes: Task 1 의 `InstallContext`, `detect`, 상수들
- Produces: `extras_install_command(extras: Sequence[str], *, ctx: InstallContext | None = None, version: str | None = None) -> str` — `extras` 는 호출자가 합치고 정렬한 pip extra 키. `ctx` 기본값은 `detect()`, `version` 기본값은 `anvyc.__version__`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_install_method.py` 의 import 블록을 다음으로 바꾼다:

```python
from __future__ import annotations

import re
from pathlib import Path

import pytest

from anvyc.core import install_method as im
from anvyc.core.install_method import (
    InstallContext,
    InstallMethod,
    detect,
    extras_install_command,
)
```

파일 끝에 추가:

```python
_SH = "bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)"
_README = "https://github.com/16bitdo/anvyc#57-업그레이드와-extras-추가-설치-방식별"
_WHEEL = (
    "https://github.com/16bitdo/anvyc/releases/download/v0.23.0/anvyc-0.23.0-py3-none-any.whl"
)


@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        (
            InstallContext("dev", "/py", Path("/r/anvyc")),
            "ANVYC_EXTRAS=dev,mcp,tui,cost-aws bash /r/anvyc/scripts/dev-install.sh",
        ),
        (
            InstallContext("uv-tool", "/py"),
            f"ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,cost-aws {_SH}",
        ),
        (
            InstallContext("uv-tool-source", "/py", Path("/s/anvyc")),
            "uv tool install --force --reinstall --refresh '/s/anvyc[mcp,cost-aws]'",
        ),
        (
            InstallContext("pipx", "/py"),
            f"ANVYC_METHOD=pipx ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,cost-aws {_SH}",
        ),
        (
            InstallContext("homebrew", "/py"),
            "Homebrew 설치본은 extras 를 지원하지 않습니다 — install.sh 로 옮기세요: "
            f"ANVYC_EXTRAS=mcp,cost-aws {_SH} (설치 방식별: {_README})",
        ),
        (
            InstallContext("venv", "/v/bin/python"),
            f"/v/bin/python -m pip install 'anvyc[mcp,cost-aws] @ {_WHEEL}'",
        ),
        (
            InstallContext("unknown", "/py"),
            f"ANVYC_EXTRAS=mcp,cost-aws {_SH} (설치 방식별: {_README})",
        ),
    ],
    ids=["dev", "uv-tool", "uv-tool-source", "pipx", "homebrew", "venv", "unknown"],
)
def test_command_per_method(ctx: InstallContext, expected: str) -> None:
    assert extras_install_command(["mcp", "cost-aws"], ctx=ctx, version="0.23.0") == expected


@pytest.mark.parametrize("version", ["0.0.0+unknown", "0.24.0.dev1"])
def test_non_release_version_is_not_pinned(version: str) -> None:
    uv = extras_install_command(["mcp"], ctx=InstallContext("uv-tool", "/py"), version=version)
    assert uv == f"ANVYC_EXTRAS=mcp {_SH}"
    venv = extras_install_command(["mcp"], ctx=InstallContext("venv", "/py"), version=version)
    assert venv == f"ANVYC_EXTRAS=mcp {_SH} (설치 방식별: {_README})"


def test_paths_with_spaces_are_quoted() -> None:
    dev = extras_install_command(
        ["mcp"], ctx=InstallContext("dev", "/py", Path("/My Repos/anvyc")), version="0.23.0"
    )
    assert dev == "ANVYC_EXTRAS=dev,mcp,tui bash '/My Repos/anvyc/scripts/dev-install.sh'"
    venv = extras_install_command(
        ["mcp"], ctx=InstallContext("venv", "/My Envs/v/bin/python"), version="0.23.0"
    )
    assert venv == f"'/My Envs/v/bin/python' -m pip install 'anvyc[mcp] @ {_WHEEL}'"
    src = extras_install_command(
        ["mcp"], ctx=InstallContext("uv-tool-source", "/py", Path("/My Src/anvyc")), version="0.23.0"
    )
    assert src == "uv tool install --force --reinstall --refresh '/My Src/anvyc[mcp]'"


def test_duplicates_removed_order_kept() -> None:
    cmd = extras_install_command(
        ["mcp", "tui", "mcp"], ctx=InstallContext("uv-tool", "/py"), version="0.23.0"
    )
    assert cmd == f"ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,tui {_SH}"


def test_default_context_and_version_come_from_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(im, "detect", lambda: InstallContext("uv-tool", "/py"))
    monkeypatch.setattr("anvyc.__version__", "9.8.7")
    assert extras_install_command(["mcp"]) == f"ANVYC_VERSION=v9.8.7 ANVYC_EXTRAS=mcp {_SH}"


def test_dev_install_default_extras_match_script() -> None:
    script = (Path(__file__).resolve().parents[2] / "scripts" / "dev-install.sh").read_text(
        encoding="utf-8"
    )
    m = re.search(r'EXTRAS="\$\{ANVYC_EXTRAS:-([a-z0-9,-]+)\}"', script)
    assert m, "dev-install.sh 의 EXTRAS 기본값 줄을 찾지 못했다"
    assert tuple(m[1].split(",")) == im.DEV_INSTALL_DEFAULT_EXTRAS


_METHODS: tuple[InstallMethod, ...] = (
    "dev",
    "uv-tool",
    "uv-tool-source",
    "pipx",
    "homebrew",
    "venv",
    "unknown",
)


@pytest.mark.parametrize("method", _METHODS)
def test_no_generated_command_resolves_the_name_on_pypi(method: InstallMethod) -> None:
    ctx = InstallContext(method, "/py", Path("/s/anvyc"))
    cmd = extras_install_command(["mcp"], ctx=ctx, version="0.23.0")
    assert not re.search(r"(?<![\w/.-])anvyc\[[^\]]*\](?!\s*@)", cmd), cmd
```

- [ ] **Step 2: 실패 확인**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_install_method.py -q -p no:cacheprovider`
Expected: 수집 단계 ERROR — `ImportError: cannot import name 'extras_install_command'`

- [ ] **Step 3: 최소 구현**

`src/anvyc/core/install_method.py` 의 import 블록을 다음으로 바꾼다:

```python
from __future__ import annotations

import enum
import re
import shlex
import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
```

파일 끝에 추가:

```python
_RELEASE_VERSION: Final = re.compile(r"\d+\.\d+\.\d+")


def extras_install_command(
    extras: Sequence[str],
    *,
    ctx: InstallContext | None = None,
    version: str | None = None,
) -> str:
    """extras 를 현재 설치 방식으로 설치하는 명령 한 줄.

    `extras` 는 호출자(core/extras)가 이미 설치된 것과 합치고 레지스트리 순서로 정렬한 pip
    extra 키다 — uv tool·pipx 재설치는 요구 문자열의 extras 로 환경을 맞추므로 빠진 extras 의
    의존이 제거된다(install.sh E2E 실측). 명령은 PyPI 에서 이름으로 찾지 않는다.
    """
    ctx = ctx if ctx is not None else detect()
    if version is None:
        import anvyc

        version = anvyc.__version__
    release = version if _RELEASE_VERSION.fullmatch(version) else None

    if ctx.method == "dev" and ctx.source_dir is not None:
        keys = ",".join(_dedup([*DEV_INSTALL_DEFAULT_EXTRAS, *extras]))
        script = shlex.quote(str(ctx.source_dir / "scripts" / "dev-install.sh"))
        return f"ANVYC_EXTRAS={keys} bash {script}"

    csv = ",".join(_dedup(extras))
    if ctx.method == "uv-tool-source" and ctx.source_dir is not None:
        spec = shlex.quote(f"{ctx.source_dir}[{csv}]")
        return f"uv tool install --force --reinstall --refresh {spec}"
    if ctx.method == "uv-tool":
        return _install_sh(csv, version=release)
    if ctx.method == "pipx":
        return _install_sh(csv, version=release, method="pipx")
    if ctx.method == "homebrew":
        return (
            "Homebrew 설치본은 extras 를 지원하지 않습니다 — install.sh 로 옮기세요: "
            f"{_install_sh(csv, version=None)} (설치 방식별: {README_INSTALL_URL})"
        )
    if ctx.method == "venv" and release is not None:
        spec = shlex.quote(f"anvyc[{csv}] @ {RELEASE_WHEEL_URL.format(v=release)}")
        return f"{shlex.quote(ctx.python)} -m pip install {spec}"
    return f"{_install_sh(csv, version=None)} (설치 방식별: {README_INSTALL_URL})"


def _install_sh(csv: str, *, version: str | None, method: str | None = None) -> str:
    env = [f"ANVYC_METHOD={method}"] if method else []
    if version:
        env.append(f"ANVYC_VERSION=v{version}")
    env.append(f"ANVYC_EXTRAS={csv}")
    return f"{' '.join(env)} bash <(curl -sSL {INSTALL_SH_URL})"


def _dedup(keys: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_install_method.py -q -p no:cacheprovider`
Expected: 36 passed

Run: `.venv/bin/ruff check src/anvyc/core/install_method.py tests/unit/test_install_method.py && .venv/bin/mypy src/anvyc/core/install_method.py tests/unit/test_install_method.py`
Expected: 통과

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/install_method.py tests/unit/test_install_method.py
git commit -m "feat(install-method): 설치 방식별 extras 설치 명령 — 이름 해석 없이, 기존 extras 보존"
```

---

### Task 3: `core/extras.py` 연결 + README 표 재생성

**Files:**
- Modify: `src/anvyc/core/extras.py` (import 블록, pyextra 5종 `install_cmd`, `install_hint`, `collect_extras_status`, 신규 함수 3개)
- Modify: `tests/unit/test_extras_registry.py:42-48` (pyextra 불변식)
- Modify: `tests/unit/test_extras_command.py:42-43` (`test_extras_table_renders` 의 `"anvyc["` 단언 제거 — 개발 설치의 pyextra 명령엔 대괄호가 없다. 대괄호 보존은 Task 4 의 새 테스트가 잡는다)
- Create: `tests/unit/test_extras_install_hints.py`
- Modify: `README.md` (동반 도구 표 — 생성기로, 표 아래 노트 — 손으로)

**Interfaces:**
- Consumes: `extras_install_command`, `INSTALL_SH_URL`, `InstallContext`, `detect` (Task 1·2)
- Produces:
  - `installed_pip_extras() -> tuple[str, ...]`
  - `_order_extras(keys: Iterable[str]) -> list[str]`
  - `install_hint_for_extra(pip_extra: str) -> str`
  - `install_hint(name: str) -> str` — pyextra 는 `install_hint_for_extra(req.pip_extra)`
  - `collect_extras_status()` 행의 `install_cmd` — pyextra 는 런타임 명령

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_extras_install_hints.py`:

```python
"""core/extras ↔ core/install_method 연결 — pyextra 안내가 설치 방식을 따르고 extras 를 보존."""

from __future__ import annotations

import pytest

import anvyc
from anvyc.core import extras as ex
from anvyc.core import install_method as im
from anvyc.core.install_method import INSTALL_SH_URL, InstallContext

_SH = f"bash <(curl -sSL {INSTALL_SH_URL})"


@pytest.fixture
def uv_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(im, "detect", lambda: InstallContext("uv-tool", "/py"))
    monkeypatch.setattr(anvyc, "__version__", "1.2.3")


def test_installed_pip_extras_follow_registry_order(monkeypatch: pytest.MonkeyPatch) -> None:
    present = {"boto3", "mcp"}
    monkeypatch.setattr(ex, "_pyextra_version", lambda req: "1" if req.name in present else None)
    assert ex.installed_pip_extras() == ("mcp", "cost-aws")


def test_order_extras_registry_first_then_unknown_sorted() -> None:
    assert ex._order_extras({"zzz", "cost-aws", "mcp", "aaa"}) == ["mcp", "cost-aws", "aaa", "zzz"]


def test_hint_keeps_installed_extras(monkeypatch: pytest.MonkeyPatch, uv_tool: None) -> None:
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ("mcp", "tui"))
    assert ex.install_hint_for_extra("cost-aws") == (
        f"ANVYC_VERSION=v1.2.3 ANVYC_EXTRAS=mcp,tui,cost-aws {_SH}"
    )


def test_install_hint_routes_pyextra_by_name(
    monkeypatch: pytest.MonkeyPatch, uv_tool: None
) -> None:
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ())
    assert ex.install_hint("boto3") == f"ANVYC_VERSION=v1.2.3 ANVYC_EXTRAS=cost-aws {_SH}"
    assert ex.install_hint("boto3") == ex.install_hint_for_extra("cost-aws")


def test_unknown_extra_key_still_gets_a_command(
    monkeypatch: pytest.MonkeyPatch, uv_tool: None
) -> None:
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ("mcp",))
    assert ex.install_hint_for_extra("future-x") == (
        f"ANVYC_VERSION=v1.2.3 ANVYC_EXTRAS=mcp,future-x {_SH}"
    )


def test_binary_hint_unchanged() -> None:
    assert ex.install_hint("sops").startswith("brew install sops")


def test_collect_status_pyextra_command_is_runtime_hint(
    monkeypatch: pytest.MonkeyPatch, uv_tool: None
) -> None:
    monkeypatch.setattr(ex, "installed_pip_extras", lambda: ())
    for row in ex.collect_extras_status():
        if row["kind"] == "pyextra":
            assert row["install_cmd"] == ex.install_hint_for_extra(row["pip_extra"])
        else:
            req = ex.find(row["name"])
            assert req is not None
            assert row["install_cmd"] == req.install_cmd
```

`tests/unit/test_extras_registry.py` 의 import 블록에 `from anvyc.core.install_method import INSTALL_SH_URL` 를 추가하고 `test_kind_specific_invariants` 를 바꾼다:

```python
@pytest.mark.parametrize("req", _ALL, ids=lambda r: r.name)
def test_kind_specific_invariants(req: ExtraReq) -> None:
    if req.kind == "pyextra":
        assert req.pip_extra, f"{req.name}: pyextra 는 pip_extra 필수"
        # README 표용 정적 명령 = install.sh 설치본 기준. 런타임 안내는 install_hint 가 만든다.
        expected = f"ANVYC_EXTRAS={req.pip_extra} bash <(curl -sSL {INSTALL_SH_URL})"
        assert req.install_cmd == expected, f"{req.name}: pyextra install_cmd 이상"
    else:  # binary
        assert req.pip_extra is None, f"{req.name}: binary 는 pip_extra 없어야 함"
```

`tests/unit/test_extras_command.py` 의 `test_extras_table_renders` 에서 마지막 두 줄을 지운다:

```python
    # install_cmd 의 'anvyc[...]' 대괄호가 rich 마크업으로 삼켜지지 않고 보존돼야 한다.
    assert "anvyc[" in out
```

(pyextra 의 `install_cmd` 가 런타임 명령이 되면 개발 설치에서는 dev-install 명령이라 대괄호가 없다. 대괄호 보존 회귀는 Task 4 의 `test_missing_rows_print_full_command_on_one_line` 가 대괄호 든 명령으로 잡는다.)

- [ ] **Step 2: 실패 확인**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_extras_install_hints.py tests/unit/test_extras_registry.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'anvyc.core.extras' has no attribute 'installed_pip_extras'` 등, `test_kind_specific_invariants` 의 pyextra 5건 실패

- [ ] **Step 3: 구현**

`src/anvyc/core/extras.py` import 블록:

```python
from __future__ import annotations

import importlib.metadata as _md
import platform
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from anvyc.core.install_method import INSTALL_SH_URL, extras_install_command
```

`EXTRAS_REGISTRY` 정의 바로 위에 추가:

```python
def _install_sh_cmd(pip_extra: str) -> str:
    """README 표용 정적 명령 — install.sh 설치본 기준(권장 경로). 런타임 안내는 install_hint."""
    return f"ANVYC_EXTRAS={pip_extra} bash <(curl -sSL {INSTALL_SH_URL})"
```

pyextra 5종의 `install_cmd=` 줄을 각각 바꾼다:

```python
        install_cmd=_install_sh_cmd("mcp"),
```
```python
        install_cmd=_install_sh_cmd("tui"),
```
```python
        install_cmd=_install_sh_cmd("cost-aws"),
```
```python
        install_cmd=_install_sh_cmd("cost-github"),
```
```python
        install_cmd=_install_sh_cmd("encryption"),
```

`install_hint` 를 바꾸고 그 아래에 새 함수를 추가한다:

```python
def install_hint(name: str) -> str:
    """안내 문구용 설치 힌트. 미지 name 은 빈 문자열.

    바이너리는 정적 문구 — "brew install sops (또는 <url>)". pyextra 는 지금 실행 중인
    설치본의 방식에 맞춘 명령이다(install_hint_for_extra) — anvyc 는 PyPI 에 없어서 이름으로
    찾는 설치는 새 환경에서 실패하고, PATH 의 pip 는 uv tool·pipx·Homebrew 설치본과 다른
    환경이다(2026-10-07 실측).
    """
    req = _BY_NAME.get(name)
    if req is None:
        return ""
    if req.kind == "pyextra" and req.pip_extra:
        return install_hint_for_extra(req.pip_extra)
    if req.install_url:
        return f"{req.install_cmd}  (또는 {req.install_url})"
    return req.install_cmd


def install_hint_for_extra(pip_extra: str) -> str:
    """pip extra 키 하나를 현재 설치 방식으로 더하는 명령 — 이미 설치된 extras 를 보존한다."""
    return extras_install_command(_order_extras({pip_extra, *installed_pip_extras()}))


def installed_pip_extras() -> tuple[str, ...]:
    """probe dist 가 설치된 pyextra 의 pip extra 키(레지스트리 순서).

    probe 는 전이 의존으로도 깔린다(httpx·cryptography 는 mcp 가 끌어온다) — 과대 추정은
    이미 있는 의존을 한 번 더 적을 뿐 무해하다. 과소 추정은 재설치가 그 extras 를 지우므로
    그쪽을 피하는 판정이다.
    """
    out: list[str] = []
    for req in EXTRAS_REGISTRY:
        if req.kind == "pyextra" and req.pip_extra and _pyextra_version(req) is not None:
            out.append(req.pip_extra)
    return tuple(out)


def _order_extras(keys: Iterable[str]) -> list[str]:
    """레지스트리 순서, 그 밖의 키는 정렬해 뒤에 — 안내 문자열이 결정적이게."""
    wanted = set(keys)
    order: list[str] = []
    for req in EXTRAS_REGISTRY:
        if req.pip_extra is not None and req.pip_extra in wanted:
            order.append(req.pip_extra)
    return order + sorted(wanted.difference(order))
```

`collect_extras_status()` 의 `"install_cmd": req.install_cmd,` 줄을 바꾼다:

```python
                "install_cmd": (
                    install_hint_for_extra(req.pip_extra)
                    if req.kind == "pyextra" and req.pip_extra
                    else req.install_cmd
                ),
```

README 표 재생성:

Run: `env -u FORCE_COLOR .venv/bin/python scripts/gen_extras.py && env -u FORCE_COLOR .venv/bin/python scripts/gen_extras.py --check`
Expected: 두 번째 명령이 `README 동반 도구 표: SoT 와 일치 ✓`

`README.md` 의 표 아래 노트(현재 "`pip extra` 행의 `pip install` 은 **anvyc 가 이미 설치된 그 환경의 pip** 로 …" 두 줄)를 바꾼다:

```markdown
> `pip extra` 행의 명령은 install.sh 설치본 기준이다. 지금 쓰는 설치 방식(개발 설치·uv tool·
> pipx·Homebrew·venv)에 맞춘 명령은 `anvyc extras` 와 `anvyc doctor` 가 이미 설치된 extras 까지
> 반영해 보여 준다 — anvyc 는 PyPI 에 없다. 설치 방식별 정리는 [§5.7](#57-업그레이드와-extras-추가-설치-방식별).
```

- [ ] **Step 4: 통과 확인**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_extras_install_hints.py tests/unit/test_extras_registry.py tests/unit/test_gen_extras.py tests/unit/test_extras_command.py -q -p no:cacheprovider`
Expected: 전부 통과

Run: `.venv/bin/ruff check src/anvyc/core/extras.py tests/unit/test_extras_install_hints.py tests/unit/test_extras_registry.py && .venv/bin/mypy src/anvyc/core/extras.py tests/unit/test_extras_install_hints.py`
Expected: 통과

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/core/extras.py tests/unit/test_extras_install_hints.py tests/unit/test_extras_registry.py tests/unit/test_extras_command.py README.md
git commit -m "feat(extras): pyextra 안내를 설치 방식 판별로 — install_hint 한 경로, 기존 extras 보존"
```

---

### Task 4: 복붙 가능성 — 긴 명령이 줄바꿈되지 않게

**Files:**
- Modify: `src/anvyc/utils/errors.py:52` (`print_error`)
- Modify: `src/anvyc/cli.py` (`extras` 명령의 미설치 안내 블록)
- Modify: `tests/unit/test_errors_print_error.py` (끝에 추가)
- Modify: `tests/unit/test_extras_command.py` (끝에 새 테스트)

**Interfaces:**
- Consumes: Task 3 의 `collect_extras_status()` 행(`install_cmd` 가 런타임 명령)
- Produces: `print_error(message, *, console=None)` — 출력에 `soft_wrap=True`. `anvyc extras` — 미설치 행마다 `  # <label>` 과 `  <install_cmd>` 두 줄(soft_wrap).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_errors_print_error.py` 끝에 추가:

```python
def test_print_error_never_hard_wraps_a_long_command() -> None:
    """긴 설치 명령이 좁은 비-TTY 콘솔에서도 한 줄로 남아야 복붙된다."""
    buf = io.StringIO()
    c = Console(file=buf, force_terminal=False, no_color=True, width=40)
    cmd = (
        "ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,cost-aws bash <(curl -sSL "
        "https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)"
    )
    print_error(f"requires the [mcp] extra. Install: {cmd}", console=c)
    out = buf.getvalue()
    assert cmd in out
    assert out.count("\n") == 1
```

`tests/unit/test_extras_command.py` 끝에 추가:

```python
def test_missing_rows_print_full_command_on_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """표 칸은 긴 명령을 접는다 — 미설치 행의 명령 전문은 표 아래 한 줄로 나와야 복붙된다.

    대괄호가 든 명령으로 Rich markup strip 회귀(PR #71)도 함께 잡는다.
    """
    cmd = (
        "/v/bin/python -m pip install 'anvyc[mcp,cost-aws] @ "
        "https://github.com/16bitdo/anvyc/releases/download/v0.23.0/anvyc-0.23.0-py3-none-any.whl'"
    )
    row = {
        "name": "mcp",
        "kind": "pyextra",
        "label": "mcp (MCP SDK)",
        "purpose": "MCP server 모드",
        "installed": False,
        "version": None,
        "install_cmd": cmd,
        "install_url": None,
        "pip_extra": "mcp",
        "required": False,
        "platform": None,
        "relevant": True,
    }
    monkeypatch.setattr(cli, "collect_extras_status", lambda: [row])
    result = CliRunner().invoke(app, ["extras"])
    assert result.exit_code == 0, result.output
    out = _ANSI.sub("", result.output)
    assert any(line.strip() == cmd for line in out.splitlines()), out
```

- [ ] **Step 2: 실패 확인**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_errors_print_error.py tests/unit/test_extras_command.py -q -p no:cacheprovider`
Expected: 2 failed — `test_print_error_never_hard_wraps_a_long_command`(명령이 40열에서 줄바꿈), `test_missing_rows_print_full_command_on_one_line`(명령 전문 줄 없음)

- [ ] **Step 3: 구현**

`src/anvyc/utils/errors.py` 의 `print_error` 본문 마지막 줄:

```python
    c = console or _get_console()
    # soft_wrap: 비-TTY 80열 fallback 의 강제 개행을 막는다 — 오류에 실린 설치 명령이 중간에서
    # 끊기면 복붙이 실패한다(doctor 렌더링과 같은 이유).
    c.print(f"[red]error[/] {safe_msg(message)}", soft_wrap=True)
```

`src/anvyc/cli.py` 의 `extras` 명령에서 미설치 안내 블록을 바꾼다. 현재:

```python
        absent = [r for r in rows if r["relevant"] and not r["installed"]]
        if absent:
            console.print(
                f"\n[yellow]{len(absent)}개 미설치[/] — 위 '설치 명령' 으로 필요한 기능만 추가하세요."
            )
        else:
            console.print("\n[green]모든 동반 도구 설치됨[/]")
```

변경 후:

```python
        absent = [r for r in rows if r["relevant"] and not r["installed"]]
        if absent:
            console.print(
                f"\n[yellow]{len(absent)}개 미설치[/] — 필요한 기능의 명령만 골라 실행하세요 "
                "(현재 설치 방식 기준, 이미 설치된 extras 유지):"
            )
            # 표 칸은 긴 명령을 접는다 — 복붙용 전문은 여기서 한 줄로(soft_wrap).
            for r in absent:
                console.print(f"  [dim]# {escape(r['label'])}[/]")
                console.print(f"  {escape(r['install_cmd'])}", soft_wrap=True)
        else:
            console.print("\n[green]모든 동반 도구 설치됨[/]")
```

- [ ] **Step 4: 통과 확인**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_errors_print_error.py tests/unit/test_extras_command.py tests/unit/test_extras_install_hints.py tests/unit/test_extras_registry.py tests/unit/test_gen_extras.py -q -p no:cacheprovider`
Expected: 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add src/anvyc/utils/errors.py src/anvyc/cli.py tests/unit/test_errors_print_error.py tests/unit/test_extras_command.py
git commit -m "fix(cli): 긴 설치 명령이 줄바꿈되지 않게 — print_error soft_wrap, anvyc extras 명령 전문 줄"
```

---

### Task 5: 호출부 6곳 통일 + src 가드

**Files:**
- Create: `tests/unit/test_no_pypi_name_install_hints.py`
- Modify: `src/anvyc/checks/mcp_extra_importable.py:33-37`
- Modify: `src/anvyc/checks/tui_extra.py:31-34`
- Modify: `src/anvyc/checks/cost_aws_explorer_iam.py:14-16, 80-86`
- Modify: `src/anvyc/checks/cost_github_pat_scope.py:12, 130-135`
- Modify: `src/anvyc/core/cost/adapters/base.py:45-49`
- Modify: `src/anvyc/mcp/server.py:31-35`, `src/anvyc/mcp/__init__.py:3`
- Modify: `src/anvyc/cli.py` (`_render_finding_group` docstring 의 escape 예시, `serve` docstring)
- Modify tests: `tests/unit/test_mcp_extra_importable_check.py:33-35`, `tests/unit/test_tui_extra_importable_check.py:30`, `tests/unit/test_cost_aws_explorer_iam_check.py:57`, `tests/unit/test_cost_github_pat_scope_check.py:56`, `tests/unit/test_serve_mcp_error_message.py`, `tests/unit/test_cost_adapter_aws.py` (끝에 추가)

**Interfaces:**
- Consumes: `install_hint(name)`, `install_hint_for_extra(pip_extra)` (Task 3), `InstallContext`, `detect` (Task 1)
- Produces: 없음 (호출부 변경)

- [ ] **Step 1: 가드 테스트 작성**

`tests/unit/test_no_pypi_name_install_hints.py`:

```python
"""src 에 PyPI 이름 기반 설치 안내가 없다.

anvyc 는 PyPI 에 없다(2026-10-07: simple·JSON·TestPyPI 모두 404). 이름으로 찾는 설치 안내는 새
환경에서 실패하고, 누군가 그 이름을 올리면 그 패키지를 설치한다. 주석·docstring 도 본다 —
설명이 필요하면 명령 꼴이 아닌 말로 쓴다.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "anvyc"
# 설치 명령 뒤 60자 안에 경로가 아닌 `anvyc[…]` 가 오고 ` @ ` 로 이어지지 않는 꼴.
_NAME_BASED = re.compile(
    r"(?:pip install|uv tool install|pipx install)\b.{0,60}?(?<![\w/.-])anvyc\[[^\]]*\](?!\s*@)"
)


def test_no_name_based_install_hint_in_src() -> None:
    hits: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        # 줄을 이어 붙여 본다 — 명령과 extras 가 다음 줄로 넘어간 docstring 도 잡는다.
        text = re.sub(r"\s*\n\s*", " ", path.read_text(encoding="utf-8"))
        hits.extend(f"{path.relative_to(_SRC.parent)}: {m.group(0)}" for m in _NAME_BASED.finditer(text))
    assert hits == [], "PyPI 이름 기반 설치 안내:\n" + "\n".join(hits)
```

- [ ] **Step 2: 가드가 실패하는지 확인 (RED)**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_no_pypi_name_install_hints.py -q -p no:cacheprovider`
Expected: FAIL — 목록에 `checks/mcp_extra_importable.py`, `checks/tui_extra.py`, `checks/cost_aws_explorer_iam.py`, `checks/cost_github_pat_scope.py`, `core/cost/adapters/base.py`, `mcp/server.py`, `mcp/__init__.py`, `cli.py` 가 나온다.

- [ ] **Step 3: 기존 테스트를 새 계약으로 바꾼다 (RED)**

`tests/unit/test_mcp_extra_importable_check.py` — import 에 `from anvyc.core.extras import install_hint` 추가, 마지막 단언 3줄(주석 2 + `assert "anvyc[mcp]" in r.suggestion`)을 바꾼다:

```python
    # 설치 방식별 명령(core/install_method) — 이름 기반 `pip install` 이 아니다.
    assert r.suggestion == install_hint("mcp")
```

`tests/unit/test_tui_extra_importable_check.py` — import 추가, `assert "anvyc[tui]" in r.suggestion` 를:

```python
    assert r.suggestion == install_hint("textual")
```

`tests/unit/test_cost_aws_explorer_iam_check.py` — import 에 `from anvyc.core.extras import install_hint` 추가, `assert "anvyc[cost-aws]" in res[0].suggestion` 를:

```python
    assert install_hint("boto3") in res[0].suggestion
```

`tests/unit/test_cost_github_pat_scope_check.py` — import 추가, `assert "anvyc[cost-github]" in res[0].suggestion` 를:

```python
    assert install_hint("httpx") in res[0].suggestion
```

`tests/unit/test_serve_mcp_error_message.py` 의 테스트 함수를 다음으로 바꾼다(모듈 docstring 은 유지):

```python
from __future__ import annotations

import sys

import pytest
from typer.testing import CliRunner

import anvyc
from anvyc.cli import app
from anvyc.core import install_method as im
from anvyc.core.extras import install_hint
from anvyc.core.install_method import InstallContext


def test_serve_mcp_missing_extra_prints_install_command_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mcp 미설치 시 '[mcp] extra' 와 설치 명령 전문이 그대로(대괄호·한 줄) 나와야 한다."""
    for mod in ("mcp", "mcp.server", "mcp.server.stdio", "mcp.types"):
        monkeypatch.setitem(sys.modules, mod, None)
    monkeypatch.delitem(sys.modules, "anvyc.mcp.server", raising=False)
    # 대괄호가 든 안내(venv 형)로 고정 — Rich markup strip 회귀(PR #71)를 계속 잡는다.
    monkeypatch.setattr(im, "detect", lambda: InstallContext("venv", "/v/bin/python"))
    monkeypatch.setattr(anvyc, "__version__", "0.23.0")
    hint = install_hint("mcp")
    assert "'anvyc[" in hint and " @ https://" in hint

    result = CliRunner().invoke(app, ["serve", "--mcp"])

    assert result.exit_code == 1
    assert "[mcp] extra" in result.output, f"missing '[mcp] extra' in: {result.output!r}"
    assert hint in result.output, f"missing install command in: {result.output!r}"
```

`tests/unit/test_cost_adapter_aws.py` 끝에 추가:

```python
def test_dep_missing_error_names_the_install_command() -> None:
    from anvyc.core.extras import install_hint_for_extra

    err = CostAdapterDepMissingError("aws", "cost-aws")
    assert f"install with: {install_hint_for_extra('cost-aws')}" in str(err)
    assert (err.source, err.group) == ("aws", "cost-aws")
```

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_mcp_extra_importable_check.py tests/unit/test_tui_extra_importable_check.py tests/unit/test_cost_aws_explorer_iam_check.py tests/unit/test_cost_github_pat_scope_check.py tests/unit/test_serve_mcp_error_message.py tests/unit/test_cost_adapter_aws.py -q -p no:cacheprovider`
Expected: 6 failed (호출부가 아직 하드코딩)

- [ ] **Step 4: 호출부 구현**

`src/anvyc/checks/mcp_extra_importable.py` — import 에 `from anvyc.core.extras import install_hint` 추가, `suggestion=(…)` 블록을:

```python
                # 설치 방식별 명령 — anvyc 는 PyPI 에 없고 PATH 의 pip 는 uv tool·pipx·
                # Homebrew 설치본과 다른 환경이다(2026-10-07 실측). 명령이 곧 suggestion 이다.
                suggestion=install_hint("mcp"),
```

`src/anvyc/checks/tui_extra.py` — import 추가, `suggestion=(…)` 블록을:

```python
                suggestion=install_hint("textual"),
```

`src/anvyc/checks/cost_aws_explorer_iam.py` — import 에 `from anvyc.core.extras import install_hint` 추가. docstring 의 두 줄

```
  * boto3 미설치 → WARNING (graceful skip, suggestion 으로 `pip install
    'anvyc[cost-aws]'` 안내)
```

을

```
  * boto3 미설치 → WARNING (graceful skip, suggestion 으로 설치 방식별 명령 —
    `install_hint("boto3")`)
```

로, `suggestion=(…)` 블록(틀린 근거 주석 3줄 포함)을:

```python
                    suggestion=(
                        # 설치 방식별 명령 — PATH 의 pip 는 uv tool·pipx·Homebrew 설치본과
                        # 다른 환경이고 anvyc 는 PyPI 에 없다(2026-10-07 실측).
                        f"{install_hint('boto3')}  "
                        "(설치 후 `anvyc cost collect --source aws` 가능)"
                    ),
```

`src/anvyc/checks/cost_github_pat_scope.py` — import 추가. docstring 줄

```
  * httpx 미설치 → WARNING (graceful skip — `pip install 'anvyc[cost-github]'`)
```

을

```
  * httpx 미설치 → WARNING (graceful skip — 설치 방식별 명령, `install_hint("httpx")`)
```

로, `suggestion=(…)` 블록을:

```python
                    suggestion=(
                        # 설치 방식별 명령 — cost_aws_explorer_iam 와 같은 근거.
                        f"{install_hint('httpx')}  "
                        "(설치 후 `anvyc cost collect --source github` 가능)"
                    ),
```

`src/anvyc/core/cost/adapters/base.py` 의 `CostAdapterDepMissingError.__init__`:

```python
    def __init__(self, source: str, group: str) -> None:
        # 지연 import — 어댑터 모듈 로드가 extras 레지스트리·설치 방식 판별을 끌어오지 않게.
        from anvyc.core.extras import install_hint_for_extra

        super().__init__(
            f"cost adapter {source!r} requires optional dep group {group!r}; "
            f"install with: {install_hint_for_extra(group)}"
        )
        self.source = source
        self.group = group
```

`src/anvyc/mcp/server.py` 의 except 블록:

```python
except ImportError as e:  # pragma: no cover - import-time error path
    # 설치 방식별 명령 — core.extras 는 mcp 없이도 import 된다.
    from anvyc.core.extras import install_hint

    raise SystemExit(
        f"anvyc MCP server requires the [mcp] extra. Install: {install_hint('mcp')}"
    ) from e
```

`src/anvyc/mcp/__init__.py` 3번째 줄:

```
Optional install: `[mcp]` extra — 설치 방식별 명령은 `anvyc extras` (README §5.7).
```

`src/anvyc/cli.py` — `_render_finding_group` docstring 의

```
    escape(): message/suggestion/location 은 데이터(예: `pip install 'anvyc[cost-aws]'`)
```

를

```
    escape(): message/suggestion/location 은 데이터(예: `'anvyc[cost-aws] @ https://…'`)
```

로, `serve` docstring 의

```
    requires: `pip install 'anvyc[mcp]'` 또는 `uv tool install 'anvyc[mcp]'`.
```

를

```
    requires: `[mcp]` extra — 설치 방식별 명령은 `anvyc extras` (README §5.7).
```

로 바꾼다.

- [ ] **Step 5: 통과 확인**

Run: `env -u FORCE_COLOR .venv/bin/pytest tests/unit/test_no_pypi_name_install_hints.py tests/unit/test_mcp_extra_importable_check.py tests/unit/test_tui_extra_importable_check.py tests/unit/test_cost_aws_explorer_iam_check.py tests/unit/test_cost_github_pat_scope_check.py tests/unit/test_serve_mcp_error_message.py tests/unit/test_cost_adapter_aws.py tests/unit/test_cost_adapter_github.py -q -p no:cacheprovider`
Expected: 전부 통과

Run: `env -u FORCE_COLOR .venv/bin/pytest -m "not integration" -q -p no:cacheprovider`
Expected: 전부 통과(1 skipped — fresh worktree venv 의 boto3)

Run: `.venv/bin/ruff check src tests && .venv/bin/mypy src/anvyc tests`
Expected: 통과

- [ ] **Step 6: 커밋**

```bash
git add src/anvyc/checks/mcp_extra_importable.py src/anvyc/checks/tui_extra.py src/anvyc/checks/cost_aws_explorer_iam.py src/anvyc/checks/cost_github_pat_scope.py src/anvyc/core/cost/adapters/base.py src/anvyc/mcp/server.py src/anvyc/mcp/__init__.py src/anvyc/cli.py tests/unit/test_no_pypi_name_install_hints.py tests/unit/test_mcp_extra_importable_check.py tests/unit/test_tui_extra_importable_check.py tests/unit/test_cost_aws_explorer_iam_check.py tests/unit/test_cost_github_pat_scope_check.py tests/unit/test_serve_mcp_error_message.py tests/unit/test_cost_adapter_aws.py
git commit -m "fix(hints): doctor·MCP·cost 오류의 설치 안내를 install_hint 로 — PyPI 이름 기반 문자열 제거 + 가드"
```

---

### Task 6: 문서 — mcp-integration 오류 인용 · DESIGN §11.2

**Files:**
- Modify: `docs/mcp-integration.md` (§1 의 오류 인용 블록과 그 아래 문단)
- Modify: `DESIGN.md` (§11.2)

**Interfaces:**
- Consumes: Task 1~5 의 동작
- Produces: 없음

- [ ] **Step 1: `docs/mcp-integration.md` 갱신**

현재 블록:

````markdown
```
error: anvyc MCP server requires the [mcp] extra. Install: pip install 'anvyc[mcp]'
```

이 안내의 `pip install` 은 anvyc 가 설치된 **그 환경의 pip** 를 전제한다 — 설치 방식별로는
위의 명령을 쓴다.
````

변경 후:

````markdown
```
error: anvyc MCP server requires the [mcp] extra. Install: <지금 설치 방식에 맞춘 명령>
```

명령은 실행 중인 anvyc 의 설치 방식(개발 설치·uv tool·pipx·Homebrew·venv)을 판별해 만들고,
이미 설치된 extras 를 함께 적는다(재설치가 빠진 extras 를 지우므로). 예 — install.sh 로 설치한
v0.23.0:

```
error: anvyc MCP server requires the [mcp] extra. Install: ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)
```

`anvyc extras` · `anvyc doctor` 의 안내도 같은 규칙이다.
````

- [ ] **Step 2: `DESIGN.md` §11.2 갱신**

현재 문장:

```
anvyc 의 일부 기능은 PATH 의 **외부 CLI 바이너리**(sops/age/op/aws-vault/gh/…) 또는
**pip extras**(boto3/httpx/textual/mcp/cryptography)가 있어야 동작한다. 이 의존성 메타와
설치 안내(`brew install …` / `pip install 'anvyc[…]'`)의 단일 SoT 는
`src/anvyc/core/extras.py` 의 `EXTRAS_REGISTRY` 다 (AdapterMeta(§11.1)와 동형 패턴).
```

변경 후:

```
anvyc 의 일부 기능은 PATH 의 **외부 CLI 바이너리**(sops/age/op/aws-vault/gh/…) 또는
**pip extras**(boto3/httpx/textual/mcp/cryptography)가 있어야 동작한다. 이 의존성 메타와
설치 안내의 단일 SoT 는 `src/anvyc/core/extras.py` 의 `EXTRAS_REGISTRY` 다
(AdapterMeta(§11.1)와 동형 패턴).
```

같은 절의 "헬퍼 `is_available(name)` / `install_hint(name)` …" 문단 바로 앞에 추가:

```
pyextra 의 런타임 안내는 설치 방식을 따른다 — `core/install_method.py` 가 실행 중인 anvyc 의
설치 방식(dev·uv tool·uv tool 로컬 소스·pipx·Homebrew·venv)을 판별하고(`detect`), 이미 설치된
extras 를 합친 목록으로 그 방식의 명령을 만든다(`extras_install_command`). 경로는
`install_hint` → `install_hint_for_extra` 하나다. anvyc 는 PyPI 에 없어 이름으로 찾는 설치는 새
환경에서 실패하고 이름 선점에 노출되므로 쓰지 않는다(`test_no_pypi_name_install_hints` 가 src 전체를
막는다). 정적 `install_cmd` 는 README 표용 install.sh 형이다. spec:
`docs/superpowers/specs/2026-10-07-install-method-aware-extras-hints-design.md`.
```

같은 문단 끝의 정합성 테스트 목록 `test_gen_extras`(README↔SoT 동기)로 강제한다.` 를:

```
`test_gen_extras`(README↔SoT 동기), `test_install_method`(판별·방식별 명령),
`test_extras_install_hints`(합집합·경로), `test_no_pypi_name_install_hints`(src 가드)로 강제한다.
```

- [ ] **Step 3: 확인**

Run: `grep -n "pip install 'anvyc\[" docs/mcp-integration.md DESIGN.md`
Expected: 출력 없음 (mcp-integration 의 오류 인용과 DESIGN §11.2 의 `pip install 'anvyc[…]'` 가 사라졌다)

- [ ] **Step 4: 커밋**

```bash
git add docs/mcp-integration.md DESIGN.md
git commit -m "docs: MCP 오류 인용과 DESIGN §11.2 를 설치 방식 판별 안내로"
```

---

### Task 7: E2E · 게이트 · PR

**Files:**
- Create (scratchpad, 커밋 안 함): `/private/tmp/claude-501/-Users-edward-dev-anvyc/b36ba525-8031-465c-a1a1-e126df82d27f/scratchpad/e2e-extras-hints.sh`

**Interfaces:**
- Consumes: 전체 브랜치
- Produces: PR

- [ ] **Step 1: E2E 스크립트 작성 — 격리 sandbox, 생성된 안내 명령을 그대로 실행**

`/private/tmp/claude-501/-Users-edward-dev-anvyc/b36ba525-8031-465c-a1a1-e126df82d27f/scratchpad/e2e-extras-hints.sh`:

```bash
#!/usr/bin/env bash
# 브랜치 wheel 을 uv tool·pipx·venv 로 설치(이미 tui 가 있는 상태)하고, mcp 가 없을 때 doctor 가
# 내는 안내 명령을 그대로 실행해 mcp 설치 + tui 보존을 확인한다. 실제 ~/.local/bin·uv tool·pipx 무접촉.
set -uo pipefail
WT=/Users/edward/worktrees/anvyc-extras-hints
S="$(cd "$(dirname "$0")" && pwd)/e2e-hints-$(date +%s)"
mkdir -p "$S"/{dist,tools,bin,cache,px,pb,shim}
export UV_CACHE_DIR="$S/cache" UV_NO_PROGRESS=1 NO_COLOR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
unset FORCE_COLOR
B=$(shasum -a 256 "$HOME/.local/bin/anvyc" | cut -d' ' -f1)
(cd "$WT" && uv build --wheel -q --out-dir "$S/dist")
WHL=$(ls "$S"/dist/anvyc-*.whl)
printf '#!/usr/bin/env bash\nsub="$1"; shift\nexec uvx pipx "$sub" --backend pip "$@"\n' > "$S/shim/pipx"
chmod +x "$S/shim/pipx"

hint_of() {  # $1=anvyc 실행 파일 → doctor 가 낸 mcp 안내
  "$1" doctor --only mcp-extra-importable --json 2>/dev/null \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["results"]; print(r[0]["suggestion"] if r else "")'
}
check() {  # $1=python $2=라벨
  printf '    %s → mcp=%s tui=%s\n' "$2" \
    "$("$1" -c 'import mcp' >/dev/null 2>&1 && echo 있음 || echo 없음)" \
    "$("$1" -c 'import textual' >/dev/null 2>&1 && echo 있음 || echo 없음)"
}

echo "== uv tool"
export UV_TOOL_DIR="$S/tools" UV_TOOL_BIN_DIR="$S/bin"
uv tool install -q "anvyc[tui] @ file://$WHL"
H=$(hint_of "$S/bin/anvyc"); echo "  hint: ${H//$S/<sbx>}"
check "$S/tools/anvyc/bin/python" "before"
bash -c "$H" >/dev/null 2>&1; echo "  run rc=$?"
check "$S/tools/anvyc/bin/python" "after"

echo "== pipx"
export PIPX_HOME="$S/px" PIPX_BIN_DIR="$S/pb" PIPX_MAN_DIR="$S/pm" PATH="$S/shim:$PATH"
pipx install --force "anvyc[tui] @ file://$WHL" >/dev/null 2>&1
H=$(hint_of "$S/pb/anvyc"); echo "  hint: ${H//$S/<sbx>}"
check "$S/px/venvs/anvyc/bin/python" "before"
bash -c "$H" >/dev/null 2>&1; echo "  run rc=$?"
check "$S/px/venvs/anvyc/bin/python" "after"

echo "== venv"
/opt/homebrew/opt/python@3.13/bin/python3.13 -m venv "$S/venv"
"$S/venv/bin/pip" install -q "anvyc[tui] @ file://$WHL"
H=$(hint_of "$S/venv/bin/anvyc"); echo "  hint: ${H//$S/<sbx>}"
check "$S/venv/bin/python" "before"
bash -c "$H" >/dev/null 2>&1; echo "  run rc=$?"
check "$S/venv/bin/python" "after"

echo "== dev (이 worktree — 멱등 재실행)"
H=$("$WT/.venv/bin/python" -c 'from anvyc.core.extras import install_hint; print(install_hint("mcp"))')
echo "  hint: ${H//$HOME/~}"
bash -c "$H" >/dev/null 2>&1; echo "  run rc=$?"

echo "가드: dev wrapper 불변 = $([ "$B" = "$(shasum -a 256 "$HOME/.local/bin/anvyc" | cut -d' ' -f1)" ] && echo yes || echo NO)"
```

- [ ] **Step 2: 실행**

Run: `bash /private/tmp/claude-501/-Users-edward-dev-anvyc/b36ba525-8031-465c-a1a1-e126df82d27f/scratchpad/e2e-extras-hints.sh`
Expected:
- uv tool hint `ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,tui bash <(curl …)` → run rc=0, after `mcp=있음 tui=있음`
- pipx hint `ANVYC_METHOD=pipx ANVYC_VERSION=v0.23.0 ANVYC_EXTRAS=mcp,tui bash <(curl …)` → rc=0, after `mcp=있음 tui=있음`
- venv hint `<sbx>/venv/bin/python -m pip install 'anvyc[mcp,tui] @ https://…/v0.23.0/…whl'` → rc=0, after `mcp=있음 tui=있음`
- dev hint `ANVYC_EXTRAS=dev,mcp,tui,… bash ~/worktrees/anvyc-extras-hints/scripts/dev-install.sh` → rc=0
- `가드: dev wrapper 불변 = yes`

(Homebrew 는 실설치가 의존 업그레이드·cleanup 부수효과를 내므로 E2E 에서 제외 — 단위 테스트로 덮는다.)

- [ ] **Step 3: 전체 게이트 + push**

Run: `env -u FORCE_COLOR git push -u origin feat/install-method-extras-hints`
Expected: pre-push 게이트 `✓ lint + type + unit gate 통과`, 원격에 브랜치 생성. `git ls-remote origin refs/heads/feat/install-method-extras-hints` 의 SHA 가 `git rev-parse HEAD` 와 같다.

- [ ] **Step 4: PR 생성**

`gh pr create --base main --head feat/install-method-extras-hints` — 제목 `feat(extras): 설치 안내가 설치 방식을 따른다 — PyPI 이름 기반 안내 제거`, 본문에 spec·plan 경로, 방식별 명령 표(spec §6), 검증(TDD·가드 RED·E2E 4종 결과·게이트 수치), 범위 밖(Homebrew E2E·PyPI). CI(`gh pr checks`)가 head SHA 기준 통과하는지 `gh run list --branch feat/install-method-extras-hints` 로 확인.

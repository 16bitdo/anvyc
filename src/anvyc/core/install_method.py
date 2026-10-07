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
import re
import shlex
import sys
import tomllib
from collections.abc import Iterable, Sequence
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
    repo = _source_repo_or_none() if isinstance(source_repo, _Auto) else source_repo
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
        # 안내는 명령 + 셸 주석 꼴 — 줄을 통째로 붙여 넣어도 문법이 맞는다(괄호 안내는 syntax error).
        return (
            f"{_install_sh(csv, version=None)}  # Homebrew 설치본은 extras 를 지원하지 않는다 — "
            f"install.sh 로 옮긴다. 설치 방식별: {README_INSTALL_URL}"
        )
    if ctx.method == "venv" and release is not None:
        spec = shlex.quote(f"anvyc[{csv}] @ {RELEASE_WHEEL_URL.format(v=release)}")
        return f"{shlex.quote(ctx.python)} -m pip install {spec}"
    return f"{_install_sh(csv, version=None)}  # 설치 방식별: {README_INSTALL_URL}"


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

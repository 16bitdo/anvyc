"""integration test 공용 helper.

`.venv/bin/anvyc` 를 subprocess 로 호출하는 integration test 들의 중복 `_anvyc`
정의를 통합한다. macOS 에서 editable install 의 `.pth` 가 UF_HIDDEN flag 로
hidden 되면 Python 3.13 site.py 가 그것을 skip → anvyc import 가 깨지므로
(docs/troubleshooting-macos.md), 매 호출 직전 self-heal 한다.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path


def heal_editable_pth() -> None:
    """macOS UF_HIDDEN 으로 hidden 된 .venv 의 editable `.pth` 를 복구한다.

    Python 3.13 site.py 는 hidden `.pth` 를 skip → editable install 의
    anvyc import 가 ModuleNotFoundError 로 깨진다. macOS 외 플랫폼이거나
    실패 시 no-op.

    chflags 는 이후 새 subprocess(새 인터프리터)의 site.py 를 복구한다.
    하지만 이미 실행 중인 인터프리터(pytest 자신)는 site.py 의 `.pth`
    처리가 끝났으므로 editable shim 이 가리키는 경로를 sys.path 에 직접
    보정한다.
    """
    if sys.platform != "darwin":
        return
    venv = Path(sys.executable).parent.parent
    for site_packages in (venv / "lib").glob("python*/site-packages"):
        for pth_file in site_packages.glob("*.pth"):
            with contextlib.suppress(OSError):
                os.chflags(pth_file, 0)
            _restore_pth_to_syspath(pth_file)


def _restore_pth_to_syspath(pth_file: Path) -> None:
    """editable `.pth` 가 가리키는 디렉터리를 현 인터프리터 sys.path 에 보정."""
    with contextlib.suppress(OSError):
        for raw in pth_file.read_text(encoding="utf-8").splitlines():
            entry = raw.strip()
            if (
                entry
                and not entry.startswith(("#", "import "))
                and entry not in sys.path
                and Path(entry).is_dir()
            ):
                sys.path.insert(0, entry)


def run_anvyc(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_str: str = "",
) -> subprocess.CompletedProcess[str]:
    """`.venv/bin/anvyc <args>` 를 subprocess 로 실행한다.

    호출 직전 editable `.pth` 를 self-heal (macOS UF_HIDDEN 회피).

    Args:
        args: anvyc CLI 인자.
        cwd: 작업 디렉터리.
        env: 추가 환경변수 (현재 환경에 merge). None 이면 그대로 상속.
        input_str: stdin 으로 전달할 문자열 (interactive wizard 등).
    """
    heal_editable_pth()
    cmd = [str(Path(sys.executable).parent / "anvyc"), *args]
    full_env: dict[str, str] | None = None
    if env is not None:
        full_env = {**os.environ, **env}
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=full_env,
        input=input_str or None,
        capture_output=True,
        text=True,
    )

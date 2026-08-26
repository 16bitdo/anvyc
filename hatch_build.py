"""빌드 시 소스 커밋을 새긴다 — version 만으로는 커밋을 구분할 수 없다.

anvyc 는 **릴리스 배치 버저닝**이다. version 은 `chore(release)` 커밋에서 올리고
태그 push 가 릴리스를 만든다. 그래서 한 version 이 여러 커밋을 덮는다 — 2026-08-26
기준 `v0.21.0` 이 미릴리스 4커밋(PR #201~#204)을 덮고 있었다.

로컬 디렉터리를 tool venv 로 설치해 쓰면(`uv tool install "$HOME/dev/anvyc[...]"`)
"지금 깔린 게 어느 커밋인가" 를 답할 방법이 없다. 실제로 그 때문에 소스에 있는
기능(`anvyc worktree add`)이 설치본에 없는데도 양쪽 `--version` 이 똑같아 낙후를
못 알아챘다. 이 훅은 그 질문에 답할 값을 빌드 산출물에 남긴다.

**git 이 없거나 실패하면 아무것도 쓰지 않는다.** 그러면 런타임은 기존과 동일하게
version 만 출력한다 — 새 실패 경로를 만들지 않는다. sdist → wheel 경로처럼 git 이
없는 빌드에서는 sdist 에 이미 들어 있는 `_build_info.py` 를 **덮지 않는다**(원래
빌드의 provenance 가 보존된다).

태그에 정확히 올라선 빌드(= 릴리스)는 `RELEASE = True` 로 표시한다. 그 경우
version 자체가 식별자이므로 런타임은 커밋을 병기하지 않는다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ImportError:  # 빌드 밖(테스트 등) — hatchling 은 빌드 전용 의존이다.
    # 이 파일의 값은 collect/render 라는 **순수 함수**에 있고, 그것들은 빌드 백엔드를
    # 필요로 하지 않는다. 실제 빌드에서는 hatchling 이 반드시 존재하므로 이 fallback 이
    # 빌드 경로의 결함을 가리지 않는다.
    BuildHookInterface = object

TARGET = Path("src") / "anvyc" / "_build_info.py"
_GIT_TIMEOUT_S = 5


def _git(root: Path, *args: str) -> str | None:
    """git 출력. 실패·부재·타임아웃이면 None — 예외를 빌드로 흘리지 않는다."""
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def collect(root: Path) -> dict[str, Any] | None:
    """빌드 대상의 git 정체. 판정 불가면 None (호출부가 파일을 건드리지 않는다)."""
    commit = _git(root, "rev-parse", "--short", "HEAD")
    if not commit:
        return None
    # `--exact-match` 는 HEAD 가 태그 그 자체일 때만 성공한다 = 릴리스 빌드.
    release = _git(root, "describe", "--exact-match", "--tags", "HEAD") is not None
    # porcelain 이 비어 있지 않으면 워킹트리에 미커밋 변경이 있다.
    status = _git(root, "status", "--porcelain")
    dirty = bool(status)  # None(조회 실패)도 False — 없는 사실을 있다고 하지 않는다
    return {"commit": commit, "release": release, "dirty": dirty}


def render(info: dict[str, Any]) -> str:
    return (
        "# 자동 생성 — hatch_build.py 가 빌드 시 기록한다. 수정하거나 커밋하지 말 것.\n"
        f'COMMIT = "{info["commit"]}"\n'
        f"RELEASE = {info['release']!r}\n"
        f"DIRTY = {info['dirty']!r}\n"
    )


class CustomBuildHook(BuildHookInterface):  # type: ignore[misc]  # base 가 Any(빌드 전용 의존)
    """sdist·wheel 양쪽 빌드 직전에 `_build_info.py` 를 갱신한다."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        info = collect(root)
        if info is None:
            return  # git 부재/실패 — 기존 파일이 있으면 그대로 보존한다
        (root / TARGET).write_text(render(info), encoding="utf-8")

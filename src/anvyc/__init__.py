"""anvyc — 개발환경 설정 동기화 CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 런타임 import 비용 0 — Path 는 타입 위치에서만 쓴다.
    from pathlib import Path

# 동적 version lookup — pyproject.toml 이 SoT. release PR 에서 __init__.py
# hardcode 갱신 누락으로 발생한 v0.14.0 → v0.15.0 의 display drift 영구 차단
# (v0.15.1 patch refactor).
#
# 우선순위:
#   1. importlib.metadata.version("anvyc")  — 설치된 패키지 (wheel / pip install)
#   2. pyproject.toml 직접 파싱           — editable install (uv pip install -e .)
#                                          이 dist-info 안 만드는 케이스 fallback
#   3. "0.0.0+unknown"                    — 둘 다 fail (source-only 실행 등)


def _read_version() -> str:
    try:
        from importlib.metadata import version as _pkg_version

        return _pkg_version("anvyc")
    except Exception:  # noqa: BLE001 — PackageNotFoundError 외 import 실패 등 광범위 fallback
        pass
    try:
        import tomllib  # Python 3.11+
        from pathlib import Path

        proj = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        if proj.is_file():
            with proj.open("rb") as f:
                data = tomllib.load(f)
            v = data.get("project", {}).get("version")
            if isinstance(v, str) and v:
                return v
    except Exception:  # noqa: BLE001 — tomllib 미존재 / 파일 손상 등
        pass
    return "0.0.0+unknown"


def _read_build_commit() -> str | None:
    """빌드 시 새겨진 소스 커밋. 릴리스(태그) 빌드이거나 정보가 없으면 None.

    version 만으로는 커밋을 구분할 수 없다 — 릴리스 배치 버저닝이라 한 version 이
    여러 커밋을 덮는다. 로컬 소스로 설치한 환경에서 "지금 깔린 게 어느 커밋인가" 를
    답하려면 이 값이 필요하다 (2026-08-26: 소스에 있는 기능이 설치본에 없는데도
    양쪽 --version 이 같아 낙후를 못 알아챘다).

    `_build_info` 는 hatch_build.py 가 빌드 시 생성하며 git 이 없으면 아예 없다 —
    그때는 None 이라 출력이 기존과 동일해진다.
    """
    try:
        # import_module 로 받는다 — `from anvyc import _build_info` 는 정적 해석 대상이라
        # 생성물 유무에 따라 type: ignore 필요 여부가 갈린다(환경 의존 lint).
        import importlib

        _build_info = importlib.import_module("anvyc._build_info")
    except Exception:  # noqa: BLE001 — 미생성(git 부재 빌드)이 정상 경로다
        return None
    if getattr(_build_info, "RELEASE", False):
        return None  # 태그 빌드 — version 자체가 식별자다
    commit = getattr(_build_info, "COMMIT", "")
    if not isinstance(commit, str) or not commit:
        return None
    return f"{commit}+dirty" if getattr(_build_info, "DIRTY", False) else commit


def _git(repo: Path, *args: str) -> str | None:
    """repo 에서 git 실행. 부재·실패·타임아웃이면 None — 예외를 호출부로 흘리지 않는다."""
    # 함수 안에서 import 한다 — 이 경로는 `--version` 에서만 밟는다. 모듈 로드 시
    # subprocess 를 끌어오면 모든 명령이 표시 전용 기능의 비용을 낸다.
    import subprocess

    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _git_head_stamp(repo: Path) -> str | None:
    """repo 의 HEAD 단축 커밋(+dirty). 판정 불가면 None."""
    commit = _git(repo, "rev-parse", "--short", "HEAD")
    if not commit:
        return None
    # porcelain 이 비어 있지 않으면 미커밋 변경이 있다 — 실행 중인 코드 ≠ 그 커밋.
    return f"{commit}+dirty" if _git(repo, "status", "--porcelain") else commit


def _source_repo() -> Path | None:
    """패키지가 git worktree 안에 있으면 그 루트, 아니면 None(= 설치본).

    `.git` 은 디렉터리일 수도 **파일**일 수도 있다(linked worktree) — `exists()` 가
    둘 다 받는다. `anvyc worktree add` 로 만든 트리에서도 소스 실행으로 인식된다.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    return repo if (repo / ".git").exists() else None


__version__ = _read_version()
__build_commit__ = _read_build_commit()


def build_commit() -> str | None:
    """**지금 실행 중인** 코드의 커밋. 판정 불가면 None.

    `__build_commit__` 은 *설치 시점* 에 새겨진 값이라 dev wrapper 처럼 live source 를
    실행하는 환경에서는 `git pull` 직후 거짓이 된다 (2026-08-27). 소스 트리에서는
    런타임 git 을 권위 소스로 삼고 ` source` 를 병기해, 그 값이 '항상 현재값'임을
    설치본의 '빌드 시점 고정값'과 구분한다.

    비용은 이 함수를 부를 때만 낸다 — `__build_commit__` 은 무변경(subprocess 0회)이라
    모듈 로드가 느려지지 않는다.

    fallback 은 얼어붙은 `__build_commit__` 이 아니라 `_read_build_commit()` 재호출이다
    — 이 함수의 계약은 '호출 시점의 상태를 읽는다' 이고, 상수를 돌려주면 그 계약이
    깨진다(프로덕션에선 결과가 같지만 테스트로 확인할 수 없게 된다).
    """
    repo = _source_repo()
    if repo is not None:
        stamp = _git_head_stamp(repo)
        if stamp is not None:
            return f"{stamp} source"
    return _read_build_commit()

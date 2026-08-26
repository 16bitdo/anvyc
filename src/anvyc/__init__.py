"""anvyc — 개발환경 설정 동기화 CLI."""

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


__version__ = _read_version()
__build_commit__ = _read_build_commit()

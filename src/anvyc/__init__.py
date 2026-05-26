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


__version__ = _read_version()

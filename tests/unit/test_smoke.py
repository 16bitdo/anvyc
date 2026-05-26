"""스켈레톤 임포트 smoke test — CI 최소 안전망."""
from __future__ import annotations

import re


def test_package_imports() -> None:
    import anvyc

    # v0.15.1 patch — __version__ 은 동적 lookup (pyproject.toml SoT, importlib.metadata
    # 또는 tomllib fallback). hardcode 비교 대신 valid semver 정규식 검증으로 향후
    # release 마다 본 test 갱신 의무 제거.
    assert re.match(r"^\d+\.\d+\.\d+", anvyc.__version__), (
        f"unexpected __version__: {anvyc.__version__!r}"
    )


def test_cli_app_loads() -> None:
    from anvyc.cli import app

    assert app is not None


def test_patterns_loaded() -> None:
    from anvyc.security.patterns import PATTERNS

    names = {p.name for p in PATTERNS}
    assert {"aws_access_key", "github_token", "private_key"} <= names


def test_dunder_main_entrypoint() -> None:
    """`python -m anvyc` 진입점 (__main__.py) 동작 — dev wrapper 의 실행 경로."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "anvyc", "--version"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "anvyc v" in proc.stdout

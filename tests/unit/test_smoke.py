"""스켈레톤 임포트 smoke test — CI 최소 안전망."""
from __future__ import annotations


def test_package_imports() -> None:
    import anvyc

    assert anvyc.__version__ == "0.12.0"


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

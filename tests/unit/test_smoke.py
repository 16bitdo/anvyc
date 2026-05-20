"""스켈레톤 임포트 smoke test — CI 최소 안전망."""
from __future__ import annotations


def test_package_imports() -> None:
    import anvyc

    assert anvyc.__version__ == "0.11.0"


def test_cli_app_loads() -> None:
    from anvyc.cli import app

    assert app is not None


def test_patterns_loaded() -> None:
    from anvyc.security.patterns import PATTERNS

    names = {p.name for p in PATTERNS}
    assert {"aws_access_key", "github_token", "private_key"} <= names

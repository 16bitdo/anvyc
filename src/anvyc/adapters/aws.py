"""AWS adapter — `~/.aws/config`만 백업한다. credentials/SSO cache는 기본 제외."""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile


class AwsAdapter:
    name = "aws"

    def detect(self) -> bool:
        return Path("~/.aws/config").expanduser().exists()

    def collect(self) -> list[ManagedFile]:
        raise NotImplementedError

    def exclude(self) -> list[str]:
        return [
            "~/.aws/credentials",
            "~/.aws/sso/cache",
            "~/.aws/cli/cache",
        ]

    def validate(self) -> list[CheckResult]:
        raise NotImplementedError

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError

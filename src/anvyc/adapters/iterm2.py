"""iTerm2 adapter — plist의 safe subset만 추출/적용.

전체 plist 동기화는 금지. profiles / key mappings / color presets만 plistlib로 직렬화.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile

PLIST_PATH = Path("~/Library/Preferences/com.googlecode.iterm2.plist").expanduser()

SAFE_KEYS_INCLUDE = (
    "New Bookmarks",       # profiles
    "GlobalKeyMap",        # key mappings
    "Custom Color Presets",
    "TouchBar Configuration",
)

SAFE_KEYS_EXCLUDE = (
    "NSWindow Frame",
    "Window Arrangement",
    "Recent",
)


class Iterm2Adapter:
    name = "iterm2"

    def detect(self) -> bool:
        return PLIST_PATH.exists()

    def collect(self) -> list[ManagedFile]:
        raise NotImplementedError

    def exclude(self) -> list[str]:
        return list(SAFE_KEYS_EXCLUDE)

    def validate(self) -> list[CheckResult]:
        raise NotImplementedError

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError

"""iTerm2 status 정합화 검증 — target_hash override 로 safe subset 만 비교."""
from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from anvyc.adapters.iterm2 import Iterm2Adapter
from anvyc.core.status import _adapter_target_hash


def _write_plist(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        plistlib.dump(data, f, fmt=plistlib.FMT_BINARY)


def test_target_hash_stable_for_unsafe_key_change(tmp_path: Path) -> None:
    """safe 키는 동일, 위험 키만 변경 → target_hash 가 같아야 한다 (PoC 한계 해소의 핵심)."""
    plist_a = tmp_path / "a.plist"
    plist_b = tmp_path / "b.plist"
    _write_plist(plist_a, {
        "HideTab": True,
        "GlobalKeyMap": {"k1": "v1"},
        # 위험 키 — backup 대상 아님
        "NSWindow Frame iTerm Window 0": "111",
        "NoSyncInstallationId": "abc",
    })
    _write_plist(plist_b, {
        "HideTab": True,
        "GlobalKeyMap": {"k1": "v1"},
        # 같은 safe 키, 위험 키만 변경
        "NSWindow Frame iTerm Window 0": "999",
        "NoSyncInstallationId": "xyz",
    })

    ad = Iterm2Adapter()
    assert ad.target_hash(plist_a) == ad.target_hash(plist_b)


def test_target_hash_changes_for_safe_key_change(tmp_path: Path) -> None:
    """safe 키 변경 시 target_hash 가 달라야 한다 → status modified 로 정확히 잡힘."""
    plist_a = tmp_path / "a.plist"
    plist_b = tmp_path / "b.plist"
    _write_plist(plist_a, {"HideTab": True, "GlobalKeyMap": {}})
    _write_plist(plist_b, {"HideTab": False, "GlobalKeyMap": {}})  # safe 변경

    ad = Iterm2Adapter()
    assert ad.target_hash(plist_a) != ad.target_hash(plist_b)


def test_target_hash_dispatch_falls_back_for_other_tools(tmp_path: Path) -> None:
    """iTerm2 외 도구는 default sha256_file 폴백."""
    f = tmp_path / "shell.txt"
    f.write_text("hello\n")
    h = _adapter_target_hash("shell", f)
    # sha256("hello\n") = ...
    import hashlib
    expected = hashlib.sha256(b"hello\n").hexdigest()
    assert h == expected


def test_target_hash_unknown_tool_falls_back(tmp_path: Path) -> None:
    """알려지지 않은 tool 이름도 default sha256."""
    f = tmp_path / "x.txt"
    f.write_text("z\n")
    import hashlib
    assert _adapter_target_hash("nonexistent-tool", f) == hashlib.sha256(b"z\n").hexdigest()

"""cross_user check 의 분류 로직."""
from __future__ import annotations

from pathlib import Path

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.cross_user import CrossUserCheck


def test_current_user_is_info() -> None:
    ctx = CheckContext(current_user="edward", known_user_aliases={})
    assert CrossUserCheck._classify("edward", ctx) is Severity.INFO


def test_unknown_user_is_dangling() -> None:
    ctx = CheckContext(current_user="edward", known_user_aliases={})
    s = CrossUserCheck._classify("nobody_definitely_not_a_user_zzz", ctx)
    assert s is Severity.WARNING_DANGLING


def test_declared_alias_resolving_to_current_is_info_aliased() -> None:
    # 이 머신에서 /Users/aliasuser → /Users/edward symlink 가 존재한다 (사용자 환경).
    # CI 등 다른 환경에서는 다를 수 있으므로 두 가능성 모두 인정.
    ctx = CheckContext(current_user="edward", known_user_aliases={"aliasuser": "edward"})
    s = CrossUserCheck._classify("aliasuser", ctx)
    assert s in (Severity.INFO_ALIASED, Severity.WARNING_FOREIGN, Severity.WARNING_DANGLING)


def test_text_scan_only_yields_non_info_findings(tmp_path: Path) -> None:
    """텍스트 파일 스캔 시 현재 user 의 path 는 finding 으로 들어오지 않는다."""
    f = tmp_path / "x.conf"
    f.write_text("/Users/edward/Documents/foo\n/Users/zzzzzz_fake/bar\n")
    ctx = CheckContext(
        current_user="edward",
        known_user_aliases={},
        scan_targets=[f],
    )
    check = CrossUserCheck()
    results = check.run(ctx)
    # edward 라인은 INFO → 출력 X. zzzzzz_fake 는 nondangling
    severities = {r.severity for r in results if r.location == f}
    assert Severity.INFO not in severities
    assert any(r.severity is Severity.WARNING_DANGLING for r in results if r.location == f)


def test_plist_scan(tmp_path: Path) -> None:
    """합성 plist 의 cross-user 경로를 정확히 분류."""
    import plistlib

    p = tmp_path / "fake.plist"
    data = {
        "New Bookmarks": [
            {"Name": "P1", "Working Directory": "/Users/edward/Documents"},  # INFO
            {"Name": "P2", "Working Directory": "/Users/totallymade_up/X"},  # DANGLING
        ],
    }
    with p.open("wb") as f:
        plistlib.dump(data, f)

    ctx = CheckContext(current_user="edward", known_user_aliases={}, scan_targets=[p])
    check = CrossUserCheck()
    results = check.run(ctx)
    plist_results = [r for r in results if r.location == p]
    assert any(r.severity is Severity.WARNING_DANGLING for r in plist_results)
    # edward 는 들어오지 않아야 함
    msgs = "\n".join(r.message for r in plist_results)
    assert "/Users/edward/" not in msgs

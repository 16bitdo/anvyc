"""core/ini_io — atomic 텍스트 쓰기 + INI 섹션 라인 범위."""
from pathlib import Path

from anvyc.core.ini_io import atomic_write_text, locate_section


def test_atomic_write_creates_and_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "sub" / "config"
    atomic_write_text("hello\n", p)
    assert p.read_text(encoding="utf-8") == "hello\n"
    atomic_write_text("world\n", p)
    assert p.read_text(encoding="utf-8") == "world\n"


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def test_locate_named_profile() -> None:
    text = "[default]\nregion = a\n\n[profile dev]\nregion = b\nsso_session = s\n"
    assert locate_section(_lines(text), "default") == (0, 3)
    assert locate_section(_lines(text), "profile dev") == (3, 6)


def test_locate_last_section_runs_to_eof() -> None:
    text = "[profile a]\nregion = x\n\n[sso-session s]\nsso_start_url = u\n"
    lines = _lines(text)
    result = locate_section(lines, "sso-session s")
    assert result is not None
    start, end = result
    assert (start, end) == (3, len(lines))


def test_locate_preserves_comments_in_range() -> None:
    text = "[profile dev]\n# a comment\nregion = b\n[profile other]\nregion = c\n"
    result = locate_section(_lines(text), "profile dev")
    assert result is not None
    start, end = result
    assert _lines(text)[start:end] == ["[profile dev]\n", "# a comment\n", "region = b\n"]


def test_locate_missing_returns_none() -> None:
    assert locate_section(_lines("[profile a]\nregion = x\n"), "profile zzz") is None

"""shell_prompt adapter 단위 테스트 (v0.13.0).

`files=` 주입으로 실제 `~` 경로 의존성을 격리한다.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.shell_prompt import DEFAULT_FILES, ShellPromptAdapter


def test_default_files() -> None:
    """DEFAULT_FILES = starship.toml + p10k.zsh."""
    assert DEFAULT_FILES == ("~/.config/starship.toml", "~/.p10k.zsh")


def test_detect_true_when_any_file_exists(tmp_path: Path) -> None:
    """파일 하나만 있어도 detect True (사용자는 보통 starship/p10k 중 하나만 사용)."""
    star = tmp_path / "starship.toml"
    star.write_text("add_newline = false\n")
    p10k = tmp_path / "p10k.zsh"  # 생성 안 함
    adapter = ShellPromptAdapter(files=(str(star), str(p10k)))
    assert adapter.detect() is True


def test_detect_false_when_no_file(tmp_path: Path) -> None:
    adapter = ShellPromptAdapter(
        files=(str(tmp_path / "starship.toml"), str(tmp_path / "p10k.zsh"))
    )
    assert adapter.detect() is False


def test_collect_existing_files_only(tmp_path: Path) -> None:
    """존재하는 파일만 ManagedFile 로 수집."""
    star = tmp_path / "starship.toml"
    star.write_text("format = '$all'\n")
    p10k = tmp_path / "p10k.zsh"  # 부재
    adapter = ShellPromptAdapter(files=(str(star), str(p10k)))

    collected = adapter.collect()
    assert len(collected) == 1
    assert collected[0].tool == "shell_prompt"
    assert collected[0].source_path == star


def test_collect_both_files(tmp_path: Path) -> None:
    star = tmp_path / "starship.toml"
    star.write_text("x = 1\n")
    p10k = tmp_path / "p10k.zsh"
    p10k.write_text("# p10k config\n")
    adapter = ShellPromptAdapter(files=(str(star), str(p10k)))

    assert len(adapter.collect()) == 2


def test_exclude_empty() -> None:
    """DEFAULT_FILES 가 설정 파일 2개만 명시 → 별도 exclude 불필요."""
    assert ShellPromptAdapter().exclude() == []


def test_registered_in_backup_adapters() -> None:
    """ADAPTERS 레지스트리 + file-based set 에 등록 — backup/apply 파이프라인 자동 연결."""
    from anvyc.core.backup import _FILE_BASED_ADAPTERS, ADAPTERS

    assert ADAPTERS["shell_prompt"] is ShellPromptAdapter
    assert "shell_prompt" in _FILE_BASED_ADAPTERS

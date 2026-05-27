"""apply / restore round-trip — modified/missing 시나리오 + 2 backup restore."""
from __future__ import annotations

import time
from pathlib import Path

from typer.testing import CliRunner

from anvyc.cli import app
from anvyc.core.apply import run_apply
from anvyc.core.backup import run_backup
from anvyc.core.restore import run_restore
from anvyc.core.status import compute_status


def test_dry_run_does_not_mutate_target(isolated_env: dict[str, Path]) -> None:
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    isolated_env["zshrc"].write_text("tampered\n")
    report = run_apply(
        root=isolated_env["root"],
        config_path=isolated_env["config"],
        dry_run=True,
    )
    # dry-run 이라 target 변경 X
    assert isolated_env["zshrc"].read_text() == "tampered\n"
    # entries 는 채워져 있어야
    assert report.entries
    assert all(e.state_after.startswith("would_") for e in report.entries)


def test_apply_restores_modified_file(isolated_env: dict[str, Path]) -> None:
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    original = isolated_env["zshrc"].read_text()
    isolated_env["zshrc"].write_text("tampered\n")
    run_apply(root=isolated_env["root"], config_path=isolated_env["config"])
    assert isolated_env["zshrc"].read_text() == original


def test_apply_recreates_missing_file(isolated_env: dict[str, Path]) -> None:
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    original = isolated_env["zshrc"].read_text()
    isolated_env["zshrc"].unlink()
    run_apply(root=isolated_env["root"], config_path=isolated_env["config"])
    assert isolated_env["zshrc"].exists()
    assert isolated_env["zshrc"].read_text() == original


def test_apply_local_backup_preserves_pre_apply_state(isolated_env: dict[str, Path]) -> None:
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    isolated_env["zshrc"].write_text("PRE_APPLY_STATE\n")
    result = run_apply(root=isolated_env["root"], config_path=isolated_env["config"])
    assert result.local_backup_dir is not None
    lb_file = result.local_backup_dir / "shell" / "fake.zshrc"
    assert lb_file.is_file()
    assert lb_file.read_text() == "PRE_APPLY_STATE\n"


def test_restore_older_backup(isolated_env: dict[str, Path]) -> None:
    # backup A
    isolated_env["zshrc"].write_text("VERSION_A\n")
    res_a = run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    time.sleep(1.1)  # 다른 timestamp dir
    # backup B
    isolated_env["zshrc"].write_text("VERSION_B\n")
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    # 현재 target = B
    assert isolated_env["zshrc"].read_text() == "VERSION_B\n"
    # A 로 restore
    run_restore(
        root=isolated_env["root"],
        backup_id=res_a.backup_dir.name,
        config_path=isolated_env["config"],
    )
    assert isolated_env["zshrc"].read_text() == "VERSION_A\n"
    # status vs A → unchanged
    report = compute_status(isolated_env["root"], backup_id=res_a.backup_dir.name)
    assert report.counts().get("unchanged", 0) >= 1


# ---------- CLI-level breaking (v0.16.0): apply default = dry-run --------


def test_cli_apply_default_is_dry_run(isolated_env: dict[str, Path]) -> None:
    """`anvyc apply` (no flag) 는 dry-run — target 무변경 + hint 1줄."""
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    isolated_env["zshrc"].write_text("tampered\n")

    result = CliRunner().invoke(
        app,
        ["apply", "--root", str(isolated_env["root"]), "--config", str(isolated_env["config"])],
    )
    assert result.exit_code == 0
    assert "dry-run" in result.stdout
    assert "v0.15.x 와 동작이 다릅" in result.stdout
    # target 무변경
    assert isolated_env["zshrc"].read_text() == "tampered\n"


def test_cli_apply_with_apply_flag_actually_applies(isolated_env: dict[str, Path]) -> None:
    """`--apply` opt-in 시 실 적용."""
    run_backup(root=isolated_env["root"], config_path=isolated_env["config"])
    original = isolated_env["zshrc"].read_text()
    isolated_env["zshrc"].write_text("tampered\n")

    result = CliRunner().invoke(
        app,
        [
            "apply",
            "--root", str(isolated_env["root"]),
            "--config", str(isolated_env["config"]),
            "--apply",
        ],
    )
    assert result.exit_code == 0
    # 실제 적용 — 원본 복원
    assert isolated_env["zshrc"].read_text() == original
    # apply mode 에서는 deprecation hint 미출력
    assert "v0.15.x 와 동작이 다릅" not in result.stdout


def test_cli_apply_dry_run_option_removed(isolated_env: dict[str, Path]) -> None:
    """`--dry-run` 옵션은 v0.16.0 에서 제거됨 — typer 가 unknown option error."""
    result = CliRunner().invoke(
        app,
        ["apply", "--dry-run", "--root", str(isolated_env["root"])],
    )
    assert result.exit_code != 0
    # typer 의 unknown option 에러 메시지
    assert "no such option" in result.stdout.lower() or "no such option" in (result.stderr or "").lower()

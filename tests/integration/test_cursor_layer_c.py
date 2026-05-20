"""Cursor Layer C (project-local opt-in) + symlink round-trip."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

from anvyc.core.apply import run_apply
from anvyc.core.backup import run_backup


def _make_layer_c_yaml(root: Path, anvyc_dir: Path, project_root: Path) -> Path:
    cfg = anvyc_dir / "anvyc.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            version: 1
            storage:
              root: ".anvyc"
            security:
              secret_scan: true
              block_on_secret: false
            tools:
              shell:    {{enabled: false}}
              git:      {{enabled: false}}
              aws:      {{enabled: false}}
              gh:       {{enabled: false}}
              claude:   {{enabled: false}}
              iterm2:   {{enabled: false}}
              pulumi:   {{enabled: false}}
              cursor:
                enabled: true
                global:  {{include: []}}
                ide:     {{include: []}}
                projects:
                  enabled: true
                  roots: ["{project_root}"]
                  patterns: [".cursor/rules", ".cursor/mcp.json", ".cursorrules"]
            """
        )
    )
    return cfg


def test_layer_c_backup_includes_files_and_symlink(tmp_path, project_with_cursor) -> None:
    anvyc_dir = tmp_path / ".anvyc-test"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = _make_layer_c_yaml(tmp_path, anvyc_dir, project_with_cursor["root"])

    result = run_backup(root=anvyc_dir, config_path=cfg, only=["cursor"])
    # 4 plain (00-base.md, 01-second.md, mcp.json, .cursorrules) + 1 symlink (zz-link.md)
    paths = [str(mf.target_path) for mf in result.inventory.files]
    assert any(".cursor/rules/00-base.md" in p for p in paths)
    assert any(".cursor/rules/01-second.md" in p for p in paths)
    assert any(".cursorrules" in p for p in paths)
    # symlink metadata
    syms = [mf for mf in result.inventory.files if mf.symlink_target is not None]
    assert len(syms) == 1
    assert syms[0].symlink_target.endswith("external/external-rule.md")


def test_layer_c_apply_restores_files_and_symlink(tmp_path, project_with_cursor) -> None:
    anvyc_dir = tmp_path / ".anvyc-test"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = _make_layer_c_yaml(tmp_path, anvyc_dir, project_with_cursor["root"])

    # baseline backup
    run_backup(root=anvyc_dir, config_path=cfg, only=["cursor"])

    # tamper target
    proj = project_with_cursor["root"]
    (proj / ".cursor/rules/00-base.md").write_text("TAMPERED\n")
    (proj / ".cursor/rules/zz-link.md").unlink()  # symlink 제거

    # apply
    run_apply(root=anvyc_dir, config_path=cfg, only=["cursor"])

    # restored?
    assert (proj / ".cursor/rules/00-base.md").read_text() == "# base rule\n"
    link = proj / ".cursor/rules/zz-link.md"
    assert link.is_symlink()
    assert os.readlink(link).endswith("external/external-rule.md")


def test_layer_c_symlink_unchanged_state(tmp_path, project_with_cursor) -> None:
    """이미 올바른 symlink 가 있으면 state_before=unchanged."""
    anvyc_dir = tmp_path / ".anvyc-test"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = _make_layer_c_yaml(tmp_path, anvyc_dir, project_with_cursor["root"])
    run_backup(root=anvyc_dir, config_path=cfg, only=["cursor"])

    report = run_apply(root=anvyc_dir, config_path=cfg, only=["cursor"], dry_run=True)
    # cfg 가 global/ide include 를 [] 로 비웠으므로 Layer C entry 만 backup 된다.
    # 모든 entry 가 would_skip (unchanged) 이어야 한다.
    bad = [
        (str(e.target_path), e.state_before)
        for e in report.entries
        if e.state_before != "unchanged"
    ]
    assert not bad, f"unexpected: {bad}"

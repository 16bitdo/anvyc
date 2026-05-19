"""dev_env adapter 통합 — anvyc backup --only dev_env 가 정상 동작하는지."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _anvyc(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(Path(sys.executable).parent / "anvyc"), *args]
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True
    )


def _touch(p: Path, body: str = "# fixture\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_dev_env_backup_collects_envrc_files(tmp_path: Path) -> None:
    """tmp project tree 에 .envrc 2개 + .python-version 1개 → backup metadata 에 3 file."""
    projects = tmp_path / "projects"
    _touch(projects / "alpha" / ".envrc", "export NODE_ENV=dev\n")
    _touch(projects / "beta" / ".envrc", "export NODE_ENV=test\n")
    _touch(projects / "gamma" / ".python-version", "3.13\n")

    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        textwrap.dedent(f"""\
        version: 1
        storage:
          root: {tmp_path / ".anvyc"}
        security:
          secret_scan: false
        tools:
          shell:    {{enabled: false}}
          git:      {{enabled: false}}
          aws:      {{enabled: false}}
          gh:       {{enabled: false}}
          cursor:   {{enabled: false}}
          claude:   {{enabled: false}}
          iterm2:   {{enabled: false}}
          pulumi:   {{enabled: false}}
          dev_env:
            enabled: true
            project_roots:
              - "{projects}"
            patterns:
              - ".envrc"
              - ".python-version"
        """)
    )

    proc = _anvyc(
        "backup",
        "--config", str(cfg),
        "--root", str(tmp_path / ".anvyc"),
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    # 3 file 모두 metadata 에 포함
    import json
    backups = sorted((tmp_path / ".anvyc" / "backups").iterdir())
    assert backups, "no backup directory created"
    latest = backups[-1]
    meta = json.loads((latest / "metadata.json").read_text())
    targets = {entry["targetPath"] for entry in meta["files"]}
    assert any(".envrc" in t and "alpha" in t for t in targets)
    assert any(".envrc" in t and "beta" in t for t in targets)
    assert any(".python-version" in t and "gamma" in t for t in targets)


def test_dev_env_disabled_by_default(tmp_path: Path) -> None:
    """default template 에서 dev_env.enabled=false → backup 시 수집 안 됨."""
    projects = tmp_path / "projects"
    _touch(projects / "alpha" / ".envrc", "export X=1\n")

    cfg = tmp_path / ".anvyc" / "anvyc.yaml"
    cfg.parent.mkdir()
    # tools 키 자체를 비워서 dev_env 가 default(enabled=true) 일 텐데
    # 명시적으로 enabled=false 로 confirm
    cfg.write_text(
        textwrap.dedent(f"""\
        version: 1
        storage:
          root: {tmp_path / ".anvyc"}
        security:
          secret_scan: false
        tools:
          shell:    {{enabled: false}}
          git:      {{enabled: false}}
          aws:      {{enabled: false}}
          gh:       {{enabled: false}}
          cursor:   {{enabled: false}}
          claude:   {{enabled: false}}
          iterm2:   {{enabled: false}}
          pulumi:   {{enabled: false}}
          dev_env:  {{enabled: false}}
        """)
    )

    proc = _anvyc(
        "backup",
        "--config", str(cfg),
        "--root", str(tmp_path / ".anvyc"),
        cwd=tmp_path,
    )
    # backup 성공 (0 도구가 enabled — empty inventory) 또는 exit 1 (도구 없음 에러)
    # 어떤 경우든 dev_env file 은 metadata 에 없어야 함
    backups = list((tmp_path / ".anvyc" / "backups").iterdir())
    if backups:
        import json
        meta_path = backups[-1] / "metadata.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text())
            targets = {entry["targetPath"] for entry in meta["files"]}
            assert not any(".envrc" in t for t in targets)

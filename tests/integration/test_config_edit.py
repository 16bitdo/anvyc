"""anvyc config edit 통합 테스트.

monkeypatch.setenv("EDITOR", ...) 로 외부 에디터 호출 격리.
실 vi/vim 실행 없음.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _anvyc(*args: str, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(Path(sys.executable).parent / "anvyc"), *args]
    full_env = {**__import__("os").environ}
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=full_env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def anvyc_yaml_fixture(tmp_path: Path) -> Path:
    """최소 anvyc.yaml 을 cwd 하위에 배치."""
    anvyc_dir = tmp_path / ".anvyc"
    anvyc_dir.mkdir()
    cfg = anvyc_dir / "anvyc.yaml"
    cfg.write_text(
        "version: 1\nstorage:\n  root: '.anvyc'\ntools:\n  shell:\n    enabled: true\n"
    )
    return cfg


def test_config_edit_no_op_editor(
    tmp_path: Path, anvyc_yaml_fixture: Path
) -> None:
    """EDITOR=true (no-op) → 변경 없음, exit 0, .bak 생성."""
    original = anvyc_yaml_fixture.read_text()
    proc = _anvyc(
        "config", "edit",
        "--config", str(anvyc_yaml_fixture),
        env={"EDITOR": "true"},
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "ok" in proc.stdout
    assert anvyc_yaml_fixture.read_text() == original
    # .bak 생성 확인
    baks = list(anvyc_yaml_fixture.parent.glob("anvyc.yaml.bak.*"))
    assert len(baks) == 1
    assert baks[0].read_text() == original


def test_config_edit_with_append(
    tmp_path: Path, anvyc_yaml_fixture: Path
) -> None:
    """EDITOR 가 yaml 끝에 comment 추가 → schema 검증 통과."""
    original = anvyc_yaml_fixture.read_text()
    editor = "sh -c 'printf \"# appended\\n\" >> \"$1\"' --"
    proc = _anvyc(
        "config", "edit",
        "--config", str(anvyc_yaml_fixture),
        env={"EDITOR": editor},
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    after = anvyc_yaml_fixture.read_text()
    assert "appended" in after
    assert after != original
    # .bak 가 원본 보존
    baks = list(anvyc_yaml_fixture.parent.glob("anvyc.yaml.bak.*"))
    assert baks[0].read_text() == original


def test_config_edit_invalid_yaml_restores_backup(
    tmp_path: Path, anvyc_yaml_fixture: Path
) -> None:
    """EDITOR 가 invalid yaml 작성 → exit 1, 원본 복구, .bak 보존."""
    original = anvyc_yaml_fixture.read_text()
    # YAML 의 mapping value 구분 콜론 뒤에 또 콜론 — invalid
    editor = "sh -c 'printf \": : : invalid\\n\" > \"$1\"' --"
    proc = _anvyc(
        "config", "edit",
        "--config", str(anvyc_yaml_fixture),
        env={"EDITOR": editor},
        cwd=tmp_path,
    )
    assert proc.returncode == 1
    assert "schema 검증 실패" in proc.stdout or "schema" in proc.stdout
    # 원본 복구
    assert anvyc_yaml_fixture.read_text() == original


def test_config_edit_missing_file_fails(tmp_path: Path) -> None:
    """anvyc.yaml 부재 → exit 1 + anvyc init 안내."""
    missing = tmp_path / "not-exist.yaml"
    proc = _anvyc(
        "config", "edit",
        "--config", str(missing),
        env={"EDITOR": "true"},
        cwd=tmp_path,
    )
    assert proc.returncode == 1
    assert "부재" in proc.stdout
    assert "anvyc init" in proc.stdout

"""tests 공용 pytest fixture.

대부분의 통합 테스트는 격리된 .anvyc 디렉터리 + 합성 source 파일들을 필요로 한다.
이 conftest 가 그 셋업을 단일 fixture 로 제공한다.
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from tests.integration._helpers import heal_editable_pth

# test 모듈 collection (anvyc import) 전에 editable .pth 를 self-heal —
# macOS UF_HIDDEN flag 가 Python 3.13 site.py 의 .pth 처리를 막는 문제 회피.
heal_editable_pth()


@pytest.fixture(autouse=True)
def _heal_venv_pth() -> None:
    """매 테스트 직전 editable .pth self-heal (지역 import / subprocess 보호)."""
    heal_editable_pth()


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, Path]:
    """격리된 anvyc 환경.

    Returns dict:
      base:      tmp_path
      root:      tmp_path / ".anvyc"
      config:    tmp_path / ".anvyc/anvyc.yaml"
      zshrc:     tmp_path / "fake.zshrc"
      zprofile:  tmp_path / "fake.zprofile"
    """
    root = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (root / sub).mkdir(parents=True)

    zshrc = tmp_path / "fake.zshrc"
    zshrc.write_text("alias x=1\n")
    zprofile = tmp_path / "fake.zprofile"
    zprofile.write_text("export PATH=/usr/bin\n")

    config = root / "anvyc.yaml"
    config.write_text(
        textwrap.dedent(
            f"""\
            version: 1
            storage:
              root: ".anvyc"
            security:
              secret_scan: true
              block_on_secret: false
            tools:
              shell:
                enabled: true
                files:
                  - "{zshrc}"
                  - "{zprofile}"
              git:    {{enabled: false}}
              aws:    {{enabled: false}}
              gh:     {{enabled: false}}
              claude: {{enabled: false}}
              iterm2: {{enabled: false}}
              pulumi: {{enabled: false}}
              cursor: {{enabled: false}}
            """
        )
    )

    return {
        "base": tmp_path,
        "root": root,
        "config": config,
        "zshrc": zshrc,
        "zprofile": zprofile,
    }


@pytest.fixture
def project_with_cursor(tmp_path: Path) -> dict[str, Path]:
    """Cursor Layer C 검증용: .cursor/rules 가 있는 합성 프로젝트 root."""
    proj = tmp_path / "fake-proj"
    (proj / ".cursor/rules").mkdir(parents=True)
    (proj / ".cursor/rules/00-base.md").write_text("# base rule\n")
    (proj / ".cursor/rules/01-second.md").write_text("# second rule\n")
    (proj / ".cursor/mcp.json").write_text('{"mcpServers": {}}\n')
    (proj / ".cursorrules").write_text("legacy single-file rule\n")

    # external symlink target
    ext = tmp_path / "external"
    ext.mkdir()
    (ext / "external-rule.md").write_text("# external\n")
    os.symlink(ext / "external-rule.md", proj / ".cursor/rules/zz-link.md")

    return {"root": proj, "external": ext}

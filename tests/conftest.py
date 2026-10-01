"""tests 공용 pytest fixture.

대부분의 통합 테스트는 격리된 .anvyc 디렉터리 + 합성 source 파일들을 필요로 한다.
이 conftest 가 그 셋업을 단일 fixture 로 제공한다.
"""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.integration._helpers import heal_editable_pth


def _drop_repo_local_git_env() -> None:
    """git 저장소-지역 환경변수를 이 pytest 프로세스에서 지운다 — 테스트의 git 명령이 자기 저장소만 보게.

    linked worktree 에서 git 이 띄운 pytest(훅·`rebase -x`·`bisect run`·`!` alias)는 그 worktree 의 절대
    `GIT_DIR`(pre-commit 이면 `GIT_INDEX_FILE` 도)을 물려받는다. 그대로 두면 픽스처의 `git -C <tmp> …` 가
    그 저장소의 공용 config·브랜치·인덱스에 쓴다(2026-10-01 사고 — #222 는 pre-push 게이트 경로만 막았다).

    git 이 없으면 그냥 돌아간다 — 부를 git 이 없으니 샐 곳도 없다. git 이 있는데 목록을 못 얻으면 예외를 그대로
    올린다: 조용히 넘어가면 위험이 열린 채로 스위트가 돈다.
    회귀 테스트: tests/unit/test_conftest_git_env_isolation.py
    """
    try:
        names = subprocess.run(
            ["git", "rev-parse", "--local-env-vars"],
            capture_output=True, text=True, check=True,
        ).stdout.split()
    except FileNotFoundError:
        return
    for name in names:
        os.environ.pop(name, None)


# 어떤 픽스처·collection 보다 먼저 — 모든 scope 의 픽스처와 import 시점 코드가 정리된 환경을 본다.
_drop_repo_local_git_env()

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

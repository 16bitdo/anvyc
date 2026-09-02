"""claude-md-freshness doctor check 단위테스트."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from anvyc.checks import claude_md_freshness as mod
from anvyc.checks.base import CheckContext, Severity


def _ctx() -> CheckContext:
    return CheckContext()


def test_skip_when_rbr_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_rbr_script", lambda: Path("/no/such/rbr/generate_claude_md.py"))
    assert mod.ClaudeMdFreshnessCheck().run(_ctx()) == []


def test_fresh_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "generate_claude_md.py"
    script.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(mod, "_rbr_script", lambda: script)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "[check] OK", ""))
    # 스캔 대상을 비워 미커밋 관측과 분리한다. 이 테스트는 subprocess.run 을 전역
    # patch 하므로, 비우지 않으면 git 호출까지 그 stub(rc=0)을 받아 실제 fleet 의
    # 모든 repo 가 tracked+미커밋으로 오판된다.
    monkeypatch.setattr(mod, "_projects", list)
    assert mod.ClaudeMdFreshnessCheck().run(_ctx()) == []


def test_stale_returns_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "generate_claude_md.py"
    script.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(mod, "_rbr_script", lambda: script)
    out = "[check] 2 stale generated CLAUDE.md (8 checked):\n  - anvyc: /x/CLAUDE.md  — ...\n  - ctxport: /y/CLAUDE.md  — ...\n"
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, out, ""))
    results = mod.ClaudeMdFreshnessCheck().run(_ctx())
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "stale" in results[0].message


# ── 미커밋 생성물 탐지 (fresh + tracked + 미커밋) ────────────────────────────
#
# stale 은 "재생성하라"가 답이라 기존 WARNING 이 담당한다. 여기서 보는 것은 그
# 다음 구간 — 재생성은 됐는데 커밋이 안 된 상태다. 재생성 직후 잠깐 열렸다
# 커밋하면 닫히는 창이라 주기 관측으로는 잘 안 잡힌다.

_MARKER = "<!-- auto-generated from .cursor/rules/ by generate_claude_md.py -->\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path, name: str) -> Path:
    """CLAUDE.md 가 커밋된 git repo 를 만든다."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "CLAUDE.md").write_text(_MARKER + "본문 v1\n", encoding="utf-8")
    _git(repo, "add", "CLAUDE.md")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, projects: list[Path]) -> None:
    """rbr --check 를 fresh(rc=0)로 고정하고 스캔 대상을 지정한다."""
    script = tmp_path / "generate_claude_md.py"
    script.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(mod, "_rbr_script", lambda: script)
    monkeypatch.setattr(mod, "_check_stale", lambda _s: (0, "[check] OK"))
    monkeypatch.setattr(mod, "_projects", lambda: projects)


def test_uncommitted_generated_reports_info(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _repo(tmp_path, "proj")
    (repo / "CLAUDE.md").write_text(_MARKER + "본문 v2\n", encoding="utf-8")  # 재생성만
    _fresh(monkeypatch, tmp_path, [repo])

    results = mod.ClaudeMdFreshnessCheck().run(_ctx())
    assert len(results) == 1
    # INFO — is_blocking 이면 재생성 직후 창이 anvyx C6 pre-run gate 를 막는다.
    assert results[0].severity == Severity.INFO
    assert not results[0].severity.is_blocking
    assert "proj" in results[0].message


def test_committed_generated_silent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = _repo(tmp_path, "proj")  # 재생성 없음 = 커밋 상태 그대로
    _fresh(monkeypatch, tmp_path, [repo])
    assert mod.ClaudeMdFreshnessCheck().run(_ctx()) == []


def test_untracked_claude_md_silent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """gitignored/untracked 는 커밋 자체가 대상이 아니다 — anvyc·rbr 이 그 경우다."""
    repo = tmp_path / "ignored"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / ".gitignore").write_text("CLAUDE.md\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text(_MARKER + "본문\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "init")
    _fresh(monkeypatch, tmp_path, [repo])
    assert mod.ClaudeMdFreshnessCheck().run(_ctx()) == []


def test_manual_claude_md_silent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """사람이 쓴 CLAUDE.md 는 생성물이 아니다 — 마커가 유일한 판별 근거."""
    repo = tmp_path / "manual"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "CLAUDE.md").write_text("# 손으로 쓴 지침\n", encoding="utf-8")
    _git(repo, "add", "CLAUDE.md")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / "CLAUDE.md").write_text("# 손으로 쓴 지침 (수정)\n", encoding="utf-8")
    _fresh(monkeypatch, tmp_path, [repo])
    assert mod.ClaudeMdFreshnessCheck().run(_ctx()) == []


def test_stale_does_not_report_uncommitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """stale 이면 답이 '재생성하라'다 — 미커밋 보고는 그 위에 얹혀 소음이 된다."""
    repo = _repo(tmp_path, "proj")
    (repo / "CLAUDE.md").write_text(_MARKER + "본문 v2\n", encoding="utf-8")
    script = tmp_path / "generate_claude_md.py"
    script.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(mod, "_rbr_script", lambda: script)
    out = "[check] 1 stale generated CLAUDE.md (8 checked):\n  - proj: /x/CLAUDE.md  — ...\n"
    monkeypatch.setattr(mod, "_check_stale", lambda _s: (1, out))
    monkeypatch.setattr(mod, "_projects", lambda: [repo])

    results = mod.ClaudeMdFreshnessCheck().run(_ctx())
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "stale" in results[0].message


def test_stale_suggestion_includes_deploy_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """단독 --apply 는 .cursor/rules 가 뒤처졌을 때 룰을 인덱스에서 drop 한다(회귀).

    rbr 이 --check 실패 시 안내하는 안전 순서가 2단계다 — 재배포 후 재생성.
    """
    script = tmp_path / "generate_claude_md.py"
    script.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(mod, "_rbr_script", lambda: script)
    out = "[check] 1 stale generated CLAUDE.md (8 checked):\n  - proj: /x/CLAUDE.md  — ...\n"
    monkeypatch.setattr(mod, "_check_stale", lambda _s: (1, out))
    monkeypatch.setattr(mod, "_projects", lambda: [])

    sug = mod.ClaudeMdFreshnessCheck().run(_ctx())[0].suggestion
    assert sug is not None
    assert "deploy_cursor_rules.py" in sug
    assert sug.index("deploy_cursor_rules.py") < sug.index("generate_claude_md.py")

"""codex-bundle-drift doctor check 단위테스트.

L2 read-only: 각 프로젝트의 `.agents/rbr/manifest.json`(rbr agent bundle --surface codex 가 쓴다)을
읽어 (a) source.commit 이 role-based-ruleset HEAD 보다 뒤처졌는지, (b) manifest 가 소유한 파일의
sha256 이 바뀌었거나 사라졌는지 관측한다. manifest 가 한 곳도 없으면 침묵(이 머신에 Codex 번들이 없음).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from anvyc.checks import codex_bundle_drift as mod
from anvyc.checks.base import CheckContext, Severity

START = "<!-- rbr:codex:start -->"
END = "<!-- rbr:codex:end -->"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _deploy(project: Path, *, commit: str, dirty: bool = False) -> None:
    """rbr agent bundle 이 쓰는 모양을 최소로 흉내 낸다."""
    (project / ".agents/rbr/rules").mkdir(parents=True)
    rule = project / ".agents/rbr/rules/20-aws.mdc"
    rule.write_bytes(b"---\nalwaysApply: false\n---\nbody\n")
    block = f"{START}\n# Role-based ruleset: devops-engineer\n{END}\n"
    (project / "AGENTS.md").write_text("# mine\n\n" + block, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "surface": "codex",
        "role": "devops-engineer",
        "source": {"commit": commit, "dirty": dirty},
        "files": {
            "AGENTS.md": _sha(block.encode()),
            ".agents/rbr/rules/20-aws.mdc": _sha(rule.read_bytes()),
        },
    }
    (project / ".agents/rbr/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    projects: list[Path],
    *,
    head: str | None,
    behind: dict[str, int | None],
) -> None:
    monkeypatch.setattr(mod, "_projects", lambda: projects)
    monkeypatch.setattr(mod, "_rbr_head", lambda: head)
    monkeypatch.setattr(mod, "_behind", lambda commit: behind.get(commit))


def test_no_manifest_anywhere_is_silent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "p"
    p.mkdir()
    _patch(monkeypatch, [p], head="abc1234", behind={})
    assert mod.CodexBundleDriftCheck().run(CheckContext()) == []


def test_fresh_bundle_is_silent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "p"
    p.mkdir()
    _deploy(p, commit="abc1234")
    _patch(monkeypatch, [p], head="abc1234", behind={"abc1234": 0})
    assert mod.CodexBundleDriftCheck().run(CheckContext()) == []


def test_stale_source_commit_warns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "p"
    p.mkdir()
    _deploy(p, commit="old0000")
    _patch(monkeypatch, [p], head="new1111", behind={"old0000": 7})
    results = mod.CodexBundleDriftCheck().run(CheckContext())
    assert len(results) == 1
    r = results[0]
    assert r.severity == Severity.WARNING
    assert "7" in r.message and "old0000" in r.message
    assert r.location == p
    assert r.suggestion is not None and "--role devops-engineer" in r.suggestion


def test_edited_or_missing_owned_file_warns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "p"
    p.mkdir()
    _deploy(p, commit="abc1234")
    (p / ".agents/rbr/rules/20-aws.mdc").write_bytes(b"edited")
    _patch(monkeypatch, [p], head="abc1234", behind={"abc1234": 0})
    results = mod.CodexBundleDriftCheck().run(CheckContext())
    assert len(results) == 1 and results[0].severity == Severity.WARNING
    assert "20-aws.mdc" in results[0].message


def test_edited_agents_block_warns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "p"
    p.mkdir()
    _deploy(p, commit="abc1234")
    agents = p / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8").replace("devops-engineer", "edited"), encoding="utf-8")
    _patch(monkeypatch, [p], head="abc1234", behind={"abc1234": 0})
    results = mod.CodexBundleDriftCheck().run(CheckContext())
    assert len(results) == 1 and "AGENTS.md" in results[0].message


def test_user_text_outside_block_does_not_warn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "p"
    p.mkdir()
    _deploy(p, commit="abc1234")
    agents = p / "AGENTS.md"
    agents.write_text("# mine, edited freely\n\n" + agents.read_text(encoding="utf-8").split("\n\n", 1)[1], encoding="utf-8")
    _patch(monkeypatch, [p], head="abc1234", behind={"abc1234": 0})
    assert mod.CodexBundleDriftCheck().run(CheckContext()) == []


def test_invalid_manifest_warns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "p"
    (p / ".agents/rbr").mkdir(parents=True)
    (p / ".agents/rbr/manifest.json").write_text("{not json", encoding="utf-8")
    _patch(monkeypatch, [p], head="abc1234", behind={})
    results = mod.CodexBundleDriftCheck().run(CheckContext())
    assert len(results) == 1 and results[0].severity == Severity.WARNING


def test_unknown_commit_is_reported_not_counted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """rbr clone 에 없는 commit(다른 머신 배포 등) → 뒤처짐 수를 모른다고 말하고 WARNING."""
    p = tmp_path / "p"
    p.mkdir()
    _deploy(p, commit="zzz9999")
    _patch(monkeypatch, [p], head="abc1234", behind={"zzz9999": None})
    results = mod.CodexBundleDriftCheck().run(CheckContext())
    assert len(results) == 1 and "zzz9999" in results[0].message


def test_rbr_head_unknown_skips_commit_compare_but_still_checks_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    p = tmp_path / "p"
    p.mkdir()
    _deploy(p, commit="abc1234")
    (p / ".agents/rbr/rules/20-aws.mdc").unlink()
    _patch(monkeypatch, [p], head=None, behind={})
    results = mod.CodexBundleDriftCheck().run(CheckContext())
    assert len(results) == 1 and "20-aws.mdc" in results[0].message

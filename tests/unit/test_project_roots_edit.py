"""core.project_roots_edit — roots 변경 순수 로직 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS
from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS as _DEF
from anvyc.core.project_roots_edit import (
    _current_explicit_roots,
    _load_raw,
    _write_roots,
    add_roots,
    clear_roots,
    load_roots_model,
    normalize_root,
    remove_roots,
)


def test_normalize_keeps_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("~/dev") == "~/dev"


def test_normalize_contracts_home_abs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("/Users/tester/work") == "~/work"
    assert normalize_root("/Users/tester") == "~"


def test_normalize_strips_trailing_slash_and_space(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("  ~/dev/  ") == "~/dev"


def test_normalize_keeps_non_home_abs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    assert normalize_root("/opt/projects") == "/opt/projects"


def test_normalize_empty_returns_empty() -> None:
    assert normalize_root("   ") == ""


# ---------------------------------------------------------------------------
# Task 3: _load_raw + _current_explicit_roots
# ---------------------------------------------------------------------------


def test_load_raw_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _load_raw(tmp_path / "nope.yaml") == {}


def test_current_roots_explicit(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/work\n  - ~/side\n")
    roots, was_explicit = _current_explicit_roots(_load_raw(cfg))
    assert roots == ["~/work", "~/side"]
    assert was_explicit is True


def test_current_roots_materializes_default(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")  # project_roots 없음
    roots, was_explicit = _current_explicit_roots(_load_raw(cfg))
    assert roots == list(DEFAULT_PROJECT_ROOTS)
    assert was_explicit is False


def test_current_roots_empty_list_materializes(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots: []\n")
    roots, was_explicit = _current_explicit_roots(_load_raw(cfg))
    assert roots == list(DEFAULT_PROJECT_ROOTS)
    assert was_explicit is False


# ---------------------------------------------------------------------------
# Task 4: RootsEditResult + _write_roots
# ---------------------------------------------------------------------------


def test_write_roots_backup_and_revalidate(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    backup = _write_roots({"project_roots": ["~/dev", "~/work"]}, cfg, make_backup=True)
    assert backup is not None and backup.name == "anvyc.yaml.bak"
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["project_roots"] == ["~/dev", "~/work"]
    # 백업엔 변경 전 내용 보존 (단일 .bak — 매 변경 덮어씀, tools_select 선례)
    assert _y.safe_load(backup.read_text())["project_roots"] == ["~/dev"]


def test_write_roots_restores_on_revalidate_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")

    def _boom(_path: Path) -> object:
        raise ValueError("schema invalid")

    monkeypatch.setattr("anvyc.core.config.load_anvyc_config", _boom)
    with pytest.raises(ValueError):
        _write_roots({"project_roots": ["~/x"]}, cfg, make_backup=True)
    # 원본 복구
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["project_roots"] == ["~/dev"]


# ---------------------------------------------------------------------------
# Task 5: add_roots
# ---------------------------------------------------------------------------


def test_add_materializes_then_appends(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")  # 명시 없음
    work = tmp_path / "work"
    work.mkdir()
    res = add_roots(cfg, [str(work)])
    assert res.materialized is True
    assert res.effective_after == [*list(_DEF), normalize_for(work)]
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["project_roots"][-1] == normalize_for(work)


def test_add_dedupes_existing(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    res = add_roots(cfg, ["~/dev"])
    assert res.added == [] and res.skipped == ["~/dev"]
    assert res.written is False


def test_add_warns_missing_dir_but_adds(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    res = add_roots(cfg, ["~/definitely-not-here-xyz"])
    assert res.added == ["~/definitely-not-here-xyz"]
    assert any("미존재" in w for w in res.warnings)
    assert res.written is True


def normalize_for(p: Path) -> str:
    """테스트 헬퍼 — tmp_path 는 $HOME 밖이므로 절대경로 그대로."""
    return normalize_root(str(p))


# ---------------------------------------------------------------------------
# Task 6: remove_roots
# ---------------------------------------------------------------------------


def test_remove_existing(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n  - ~/work\n")
    res = remove_roots(cfg, ["~/work"])
    assert res.removed == ["~/work"] and res.written is True
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["project_roots"] == ["~/dev"]


def test_remove_to_empty_clears_key(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    res = remove_roots(cfg, ["~/dev"])
    assert res.cleared_to_default is True
    import yaml as _y
    assert "project_roots" not in (_y.safe_load(cfg.read_text()) or {})


def test_remove_not_in_list_reported(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    res = remove_roots(cfg, ["~/nope"])
    assert res.skipped == ["~/nope"] and res.removed == []
    assert res.written is False


def test_remove_from_materialized_defaults(tmp_path: Path) -> None:
    """project_roots 미설정(default) 상태에서 default 멤버 rm → materialize 후 기록 (spec §7)."""
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")  # project_roots 없음
    res = remove_roots(cfg, ["~/Code"])
    assert res.materialized is True
    assert res.removed == ["~/Code"] and res.written is True
    import yaml as _y
    written = _y.safe_load(cfg.read_text())["project_roots"]
    assert "~/Code" not in written and "~/dev" in written


def test_remove_matches_hand_edited_trailing_slash(tmp_path: Path) -> None:
    """저장값 정규화 — hand-edit 된 후행 슬래시 root 도 rm 이 매칭한다."""
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/work/\n  - ~/dev\n")  # 후행 슬래시(hand-edit)
    res = remove_roots(cfg, ["~/work"])
    assert res.removed == ["~/work"] and res.skipped == []
    import yaml as _y
    assert _y.safe_load(cfg.read_text())["project_roots"] == ["~/dev"]


# ---------------------------------------------------------------------------
# Task 7: clear_roots
# ---------------------------------------------------------------------------


def test_clear_removes_key(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n  - ~/work\n")
    res = clear_roots(cfg)
    assert res.cleared_to_default is True and res.written is True
    assert res.removed == ["~/dev", "~/work"]
    import yaml as _y
    assert "project_roots" not in (_y.safe_load(cfg.read_text()) or {})


def test_clear_already_default_noop(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    res = clear_roots(cfg)
    assert res.written is False and res.cleared_to_default is False


# ---------------------------------------------------------------------------
# Task 8: load_roots_model (RootEntry / RootsModel)
# ---------------------------------------------------------------------------


def test_load_model_explicit_with_existence_and_count(tmp_path: Path) -> None:
    root = tmp_path / "dev"
    (root / "proj").mkdir(parents=True)
    (root / "proj" / ".git").mkdir()
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text(f"project_roots:\n  - {root}\n  - ~/nonexistent-xyz\n")
    model = load_roots_model(cfg)
    assert model.explicit is True
    by_path = {e.path: e for e in model.entries}
    dev = by_path[normalize_for(root)]
    assert dev.source == "explicit" and dev.exists is True and dev.projects == 1
    missing = by_path["~/nonexistent-xyz"]
    assert missing.exists is False and missing.projects == 0


def test_load_model_default_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # HOME 격리(autouse conftest 가 HOME 을 격리하지 않음) → defaults 미존재 → 실제 FS 스캔 회피.
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    model = load_roots_model(cfg)
    assert model.explicit is False
    assert all(e.source == "default" for e in model.entries)
    assert all(e.projects == 0 for e in model.entries)  # 빈 HOME → discover 0 (헤르메틱)
    assert [e.path for e in model.entries] == list(_DEF)

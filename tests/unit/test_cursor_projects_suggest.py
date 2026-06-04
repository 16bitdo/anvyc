# tests/unit/test_cursor_projects_suggest.py
from pathlib import Path

import pytest

from anvyc.checks.cursor_projects_suggest import CursorProjectsSuggestCheck
from anvyc.core.config import AnvycConfig


def test_cursor_suggest_honors_roots_and_excludes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    container = tmp_path / "dev"
    (container / "p1" / ".cursor").mkdir(parents=True)
    (container / "p2" / ".cursor").mkdir(parents=True)
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(container),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: ())
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: (str(container / "p2"),))
    # 등록 roots 비움(중복 제안 회피 로직): load_anvyc_config 를 빈 config 로
    monkeypatch.setattr("anvyc.core.config.load_anvyc_config", lambda *a, **k: AnvycConfig())
    from anvyc.checks.base import CheckContext

    results = CursorProjectsSuggestCheck().run(CheckContext())
    msg = " ".join(r.message for r in results)
    assert "p1" in msg and "p2" not in msg  # p2 는 exclude

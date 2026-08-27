"""빌드 커밋 스탬프 — hatch_build.collect/render 와 런타임 판독.

계기 — 2026-08-26: 소스에는 `anvyc worktree add` 와 doctor 의 `worktree_rule_links`
검사가 있었는데(`a281b21`, PR #204) 로컬 소스로 설치한 tool venv 에는 없었다. 양쪽
`--version` 이 똑같이 `v0.21.0` 이라 낙후가 드러나지 않았다. 릴리스 배치 버저닝이라
한 version 이 여러 커밋을 덮기 때문이다 — version 은 커밋의 식별자가 아니다.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import cast

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import hatch_build  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("v1\n", encoding="utf-8")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "init")
    return root


# --------------------------------------------------------------------------- #
# collect — 빌드 대상의 git 정체
# --------------------------------------------------------------------------- #


def test_collect_reads_commit_on_clean_repo(tmp_path: Path) -> None:
    info = hatch_build.collect(_repo(tmp_path))
    assert info is not None
    assert info["commit"]
    assert info["dirty"] is False
    assert info["release"] is False  # 태그 없음


def test_collect_marks_dirty_working_tree(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "f.txt").write_text("v2\n", encoding="utf-8")

    info = hatch_build.collect(root)
    assert info is not None
    assert info["dirty"] is True


def test_collect_marks_release_when_head_is_exactly_a_tag(tmp_path: Path) -> None:
    """태그에 정확히 올라선 빌드는 릴리스다 — 그때는 version 이 곧 식별자다."""
    root = _repo(tmp_path)
    _git(root, "tag", "v9.9.9")

    info = hatch_build.collect(root)
    assert info is not None
    assert info["release"] is True


def test_collect_returns_none_outside_git(tmp_path: Path) -> None:
    """git 이 없으면 판정 불가 — 호출부가 기존 파일을 덮지 않게 None 을 돌려준다."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert hatch_build.collect(plain) is None


def test_should_stamp_skips_editable_builds() -> None:
    """editable 설치는 스탬프하지 않는다 — 산출물이 아니라 **live source** 를 실행한다.

    editable 로 깔면 코드는 repo 의 src/ 에서 그대로 돈다. 그런데 스탬프는 설치 시점에
    얼어붙으므로 `git pull` 직후 거짓이 된다. 소스 트리는 런타임 git 이 답하므로
    (`build_commit`) 여기서는 오해 소지 있는 파일을 애초에 만들지 않는다.
    """
    assert hatch_build.should_stamp("editable") is False


def test_should_stamp_allows_real_wheel_builds() -> None:
    assert hatch_build.should_stamp("standard") is True


def test_render_emits_importable_module() -> None:
    src = hatch_build.render({"commit": "abc1234", "release": False, "dirty": True})
    ns: dict[str, object] = {}
    exec(compile(src, "_build_info.py", "exec"), ns)  # noqa: S102 — 생성물 형식 검증
    assert ns["COMMIT"] == "abc1234"
    assert ns["RELEASE"] is False
    assert ns["DIRTY"] is True


# --------------------------------------------------------------------------- #
# 런타임 판독 — _read_build_commit
# --------------------------------------------------------------------------- #


def _with_build_info(monkeypatch: pytest.MonkeyPatch, **attrs: object) -> None:
    """가짜 `_build_info` 를 심는다.

    `sys.modules` 만 바꾸면 부족하다 — `from anvyc import _build_info` 는 **패키지
    속성을 먼저** 보므로, 실제 `_build_info.py` 가 빌드로 생성돼 이미 import 된
    세션에서는 진짜 모듈이 이긴다(전체 스위트에서만 재현되는 격리 결함이었다).
    속성과 `sys.modules` 를 함께 덮는다.
    """
    anvyc = importlib.import_module("anvyc")
    mod = types.ModuleType("anvyc._build_info")
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setattr(anvyc, "_build_info", mod, raising=False)
    monkeypatch.setitem(sys.modules, "anvyc._build_info", mod)


def _without_build_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """git 없는 빌드 재현 — 속성도 없고 import 도 실패해야 한다."""
    anvyc = importlib.import_module("anvyc")
    monkeypatch.delattr(anvyc, "_build_info", raising=False)
    monkeypatch.setitem(sys.modules, "anvyc._build_info", None)  # import 시 ImportError


def _read() -> str | None:
    anvyc = importlib.import_module("anvyc")
    return cast("str | None", anvyc._read_build_commit())


def test_read_build_commit_returns_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_build_info(monkeypatch, COMMIT="abc1234", RELEASE=False, DIRTY=False)
    assert _read() == "abc1234"


def test_read_build_commit_marks_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_build_info(monkeypatch, COMMIT="abc1234", RELEASE=False, DIRTY=True)
    assert _read() == "abc1234+dirty"


def test_read_build_commit_silent_on_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """릴리스 빌드는 커밋을 병기하지 않는다 — 출력이 기존과 같아야 한다."""
    _with_build_info(monkeypatch, COMMIT="abc1234", RELEASE=True, DIRTY=False)
    assert _read() is None


def test_read_build_commit_none_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """git 없는 빌드는 _build_info 를 만들지 않는다 — 그때 출력은 기존과 동일하다."""
    _without_build_info(monkeypatch)
    assert _read() is None


def test_read_build_commit_none_on_empty_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_build_info(monkeypatch, COMMIT="", RELEASE=False, DIRTY=False)
    assert _read() is None


# --------------------------------------------------------------------------- #
# 런타임 판독 — build_commit (소스 트리 실행)
# --------------------------------------------------------------------------- #
# 계기 — 2026-08-27: dev wrapper(`~/.local/bin/anvyc`)는 repo 의 src/ 를 PYTHONPATH 로
# 주입해 **live source** 를 실행한다. 그런데 `_build_info.py` 는 **설치 시점** 커밋을
# 새긴다. `git pull` 한 순간 둘이 갈라져, 실행되지도 않는 커밋을 `--version` 이 자신
# 있게 출력한다 — "커밋 미표시"보다 "틀린 커밋 표시"가 더 위험하다.


def _stamp(repo: Path) -> str | None:
    anvyc = importlib.import_module("anvyc")
    return cast("str | None", anvyc._git_head_stamp(repo))


def _build_commit() -> str | None:
    anvyc = importlib.import_module("anvyc")
    return cast("str | None", anvyc.build_commit())


def _head(repo: Path) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _as_source_tree(monkeypatch: pytest.MonkeyPatch, repo: Path | None) -> None:
    """소스 트리 실행 여부를 주입 — 실제 anvyc 저장소 위치에 테스트를 묶지 않는다."""
    anvyc = importlib.import_module("anvyc")
    monkeypatch.setattr(anvyc, "_source_repo", lambda: repo)


def test_git_head_stamp_reads_commit_on_clean_repo(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert _stamp(repo) == _head(repo)


def test_git_head_stamp_marks_dirty_working_tree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "f.txt").write_text("v2\n", encoding="utf-8")
    assert _stamp(repo) == f"{_head(repo)}+dirty"


def test_git_head_stamp_none_outside_git(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _stamp(plain) is None


def test_source_repo_detects_linked_worktree(tmp_path: Path) -> None:
    """`anvyc worktree add` 로 만든 트리는 `.git` 이 **파일**이다 — 그래도 소스 트리다."""
    repo = _repo(tmp_path)
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "topic", str(wt))
    assert (wt / ".git").is_file()
    assert _stamp(wt) == _head(wt)


def test_build_commit_marks_source_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    _as_source_tree(monkeypatch, repo)
    assert _build_commit() == f"{_head(repo)} source"


def test_build_commit_ignores_stale_build_info_in_source_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """핵심 회귀 — 설치 시점에 새겨진 낡은 커밋이 live source 를 이겨선 안 된다."""
    repo = _repo(tmp_path)
    _with_build_info(monkeypatch, COMMIT="0000000", RELEASE=False, DIRTY=False)
    _as_source_tree(monkeypatch, repo)
    got = _build_commit()
    assert got == f"{_head(repo)} source"
    assert "0000000" not in (got or "")


def test_build_commit_falls_back_to_build_info_when_not_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """wheel 설치본(.git 없음)은 기존 경로 그대로 — 빌드 스탬프를 쓴다."""
    _with_build_info(monkeypatch, COMMIT="abc1234", RELEASE=False, DIRTY=False)
    _as_source_tree(monkeypatch, None)
    assert _build_commit() == "abc1234"


def test_build_commit_falls_back_when_git_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """소스 트리로 보이지만 git 조회가 실패하면 빌드 스탬프로 물러선다."""
    plain = tmp_path / "no-git"
    plain.mkdir()
    _with_build_info(monkeypatch, COMMIT="abc1234", RELEASE=False, DIRTY=False)
    _as_source_tree(monkeypatch, plain)
    assert _build_commit() == "abc1234"


def test_git_lookup_is_deferred_to_build_commit_call() -> None:
    """import 는 git 을 부르지 않는다 — 표시 전용 기능이 모든 명령에 세금을 매기면 안 된다.

    측정(2026-08-27): `import anvyc, anvyc.cli` ≈ 85ms, git 2회 ≈ 15ms. 모듈 로드
    시점에 넣으면 CLI 시작이 ~18% 느려진다. 비용은 `--version` 경로에서만 낸다.
    """
    code = (
        "import subprocess\n"
        "subprocess.run = lambda *a, **k: (_ for _ in ()).throw("
        "AssertionError('import 시 subprocess 호출됨'))\n"
        "import anvyc, anvyc.cli\n"
    )
    env = {**os.environ, "PYTHONPATH": str(_ROOT / "src")}
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0, r.stderr


def test_cli_version_uses_runtime_build_commit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--version` 은 얼어붙은 `__build_commit__` 이 아니라 `build_commit()` 을 쓴다."""
    import typer

    from anvyc import cli

    monkeypatch.setattr(cli, "build_commit", lambda: "deadbee source")
    with pytest.raises(typer.Exit):
        cli._version_callback(True)
    assert "deadbee source" in capsys.readouterr().out

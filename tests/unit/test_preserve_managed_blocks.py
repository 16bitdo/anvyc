"""hook 재설치 시 외부 managed-block 보존 — scripts/preserve_managed_blocks.py.

계기 — 2026-08-27: `dev-install.sh` 가 부르는 `install-git-hooks.sh` 는 `.git/hooks/pre-push`
를 tracked SoT 로 **통째 교체**했다. 그 바람에 role-based-ruleset 이 주입해 둔
`claude-md-freshness` 블록이 조용히 사라졌고, CLAUDE.md stale 게이트가 push 에서
빠졌다. anvyc 소유 블록(`anvyc-pr-guard`)은 SoT 에 임베드해 살아남았지만, 그 해법은
anvyc 가 소유하지 않는 블록에는 쓸 수 없다 — 내용의 주인이 다른 저장소이기 때문이다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import preserve_managed_blocks as pmb  # noqa: E402

_SCRIPT = _SCRIPTS / "preserve_managed_blocks.py"

FRESHNESS = """# >>> claude-md-freshness (managed by role-based-ruleset) >>>
__rbr="${RBR_DIR:-$HOME/dev/role-based-ruleset}"
echo freshness
# <<< claude-md-freshness <<<
"""

GUARD = """# >>> anvyc-pr-guard >>>
__anvyc_protected="main"
# <<< anvyc-pr-guard <<<
"""

SOT = f"""#!/usr/bin/env bash
set -euo pipefail

{GUARD}
echo "anvyc pre-push: gate"
"""


def test_foreign_block_is_preserved() -> None:
    """SoT 에 없는 외부 블록은 살아남아야 한다 — 이번 사고의 본체."""
    result = pmb.merge_preserving_blocks(SOT + "\n" + FRESHNESS, SOT)
    assert result.preserved == ["claude-md-freshness"]
    assert FRESHNESS.strip() in result.text


def test_preserved_block_is_verbatim() -> None:
    """블록 본문은 한 바이트도 바뀌면 안 된다 — doctor 가 marker 블록을 byte 비교한다."""
    result = pmb.merge_preserving_blocks(SOT + "\n" + FRESHNESS, SOT)
    assert FRESHNESS.strip() in result.text


def test_block_owned_by_sot_is_not_duplicated() -> None:
    """SoT 가 이미 가진 이름은 재부착하지 않는다 — anvyc-pr-guard 중복 방지."""
    result = pmb.merge_preserving_blocks(SOT, SOT)
    assert result.text.count("# >>> anvyc-pr-guard >>>") == 1
    assert result.preserved == []


def test_no_blocks_returns_sot_unchanged() -> None:
    result = pmb.merge_preserving_blocks("#!/usr/bin/env bash\necho hi\n", SOT)
    assert result.text == SOT


def test_multiple_foreign_blocks_keep_source_order() -> None:
    other = "# >>> zzz-other >>>\necho other\n# <<< zzz-other <<<\n"
    result = pmb.merge_preserving_blocks(SOT + "\n" + FRESHNESS + "\n" + other, SOT)
    assert result.preserved == ["claude-md-freshness", "zzz-other"]
    assert result.text.index("claude-md-freshness") < result.text.index("zzz-other")


def test_unpaired_begin_marker_is_not_preserved_but_warns() -> None:
    """짝이 없는 마커는 보존하지 않는다 — 깨진 훅을 만드는 쪽이 더 나쁘다.

    다만 조용히 버리지도 않는다. 사라졌다는 사실이 보여야 사람이 판단할 수 있다.
    """
    broken = "# >>> truncated-block >>>\necho half\n"
    result = pmb.merge_preserving_blocks(SOT + "\n" + broken, SOT)
    assert result.preserved == []
    assert "truncated-block" not in result.text
    assert any("truncated-block" in w for w in result.warnings)


def test_result_stays_valid_bash(tmp_path: Path) -> None:
    """보존 결과가 문법적으로 실행 가능한 스크립트여야 한다."""
    result = pmb.merge_preserving_blocks(SOT + "\n" + FRESHNESS, SOT)
    hook = tmp_path / "pre-push"
    hook.write_text(result.text, encoding="utf-8")
    subprocess.run(["bash", "-n", str(hook)], check=True)


def test_cli_merges_files_and_reports_preserved_on_stderr(tmp_path: Path) -> None:
    """install-git-hooks.sh 가 쓰는 진입점 — 병합 결과는 stdout, 알림은 stderr."""
    existing = tmp_path / "existing"
    new = tmp_path / "new"
    existing.write_text(SOT + "\n" + FRESHNESS, encoding="utf-8")
    new.write_text(SOT, encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(_SCRIPT), "--existing", str(existing), "--new", str(new)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert FRESHNESS.strip() in r.stdout
    assert "claude-md-freshness" in r.stderr  # 무엇을 보존했는지 알려준다


def test_cli_without_existing_file_emits_sot(tmp_path: Path) -> None:
    """첫 설치 — 기존 훅이 없으면 SoT 를 그대로 낸다."""
    new = tmp_path / "new"
    new.write_text(SOT, encoding="utf-8")

    r = subprocess.run(
        [
            sys.executable, str(_SCRIPT),
            "--existing", str(tmp_path / "absent"),
            "--new", str(new),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == SOT


@pytest.mark.parametrize("missing", ["--existing", "--new"])
def test_cli_requires_both_paths(missing: str) -> None:
    r = subprocess.run(
        [sys.executable, str(_SCRIPT), missing, "x"], capture_output=True, text=True
    )
    assert r.returncode != 0


# --------------------------------------------------------------------------- #
# install-git-hooks.sh 배선 — 사고가 실제로 난 지점
# --------------------------------------------------------------------------- #


def _fake_repo(tmp_path: Path, existing_hook: str) -> Path:
    """scripts/ 를 복사한 tmp git repo. install-git-hooks.sh 는 자기 위치로 REPO_ROOT 를 잡는다."""
    import shutil

    repo = tmp_path / "r"
    (repo / "scripts" / "hooks").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name in ("install-git-hooks.sh", "preserve_managed_blocks.py"):
        shutil.copy(_SCRIPTS / name, repo / "scripts" / name)
    (repo / "scripts" / "hooks" / "pre-push.sh").write_text(SOT, encoding="utf-8")
    (repo / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
    (repo / ".git" / "hooks" / "pre-push").write_text(existing_hook, encoding="utf-8")
    return repo


def _install(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "install-git-hooks.sh")],
        capture_output=True, text=True,
    )


def test_install_script_preserves_foreign_block(tmp_path: Path) -> None:
    """2026-08-27 사고 재현 — SoT 재설치가 claude-md-freshness 를 삼키면 안 된다."""
    repo = _fake_repo(tmp_path, SOT + "\n" + FRESHNESS)
    r = _install(repo)
    assert r.returncode == 0, r.stderr
    assert FRESHNESS.strip() in (repo / ".git" / "hooks" / "pre-push").read_text()


def _backups(repo: Path) -> int:
    return len(list((repo / ".git" / "hooks").glob("pre-push.bak-*")))


def test_install_script_is_idempotent(tmp_path: Path) -> None:
    """재실행이 내용을 바꾸지도, 백업을 쌓지도 않는다."""
    repo = _fake_repo(tmp_path, SOT + "\n" + FRESHNESS)
    assert _install(repo).returncode == 0
    first = (repo / ".git" / "hooks" / "pre-push").read_text()
    after_first = _backups(repo)

    r = _install(repo)
    assert r.returncode == 0, r.stderr
    assert (repo / ".git" / "hooks" / "pre-push").read_text() == first
    assert _backups(repo) == after_first


def test_install_script_skips_when_already_merged(tmp_path: Path) -> None:
    """이미 SoT+보존블록 상태면 교체하지 않는다 — 백업조차 만들지 않는다.

    기존 동작은 SoT 와 byte 비교만 해서, 외부 블록이 붙어 있으면 매번 '다르다' 로
    판정해 교체+백업을 반복했다. 비교 대상이 병합 결과로 바뀌면서 사라진 낭비다.
    """
    repo = _fake_repo(tmp_path, SOT + "\n" + FRESHNESS)
    assert _install(repo).returncode == 0
    assert _backups(repo) == 0


def test_install_script_backs_up_before_replacing_different_hook(tmp_path: Path) -> None:
    """내용이 실제로 다르면 교체 전에 백업한다 — 되돌릴 길을 남긴다."""
    repo = _fake_repo(tmp_path, "#!/usr/bin/env bash\necho 완전히 다른 훅\n")
    assert _install(repo).returncode == 0
    assert _backups(repo) == 1


def test_install_script_installs_when_no_hook_exists(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path, "")
    (repo / ".git" / "hooks" / "pre-push").unlink()
    r = _install(repo)
    assert r.returncode == 0, r.stderr
    assert (repo / ".git" / "hooks" / "pre-push").read_text() == SOT

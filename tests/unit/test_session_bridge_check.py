"""tests/unit/test_session_bridge_check.py — session-bridge doctor check 회귀.

ccinspector `session-bridge` 모듈의 read-only 미러. 가짜 home(`monkeypatch Path.home`) 아래
`~/.<profile>/sessions/` 레코드 쌍 · `~/.config/cc-inspect/.session-bridge/{manifest.json,profiles}`
· `~/.<profile>/settings.json` 배선을 조립하고, pid 생존은 patch 한다(실 프로세스 무관).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch

import pytest

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.checks.session_bridge import SessionBridgeCheck
from anvyc.core.doctor import _REGISTRY

_MOD = "anvyc.checks.session_bridge"
LIB = "/opt/cc/lib/session_bridge.py"
KEY_HEX = "ab" * 32  # 64 hex — 하네스 key 파일명 `<pid>.<sha256>.key`
_ABSENT: Final = object()


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _profile(home: Path, name: str, *, wired: bool = True) -> Path:
    """`~/.<name>/sessions/` + settings.json(wired 면 SessionStart/SessionEnd 에 hook 배선)."""
    pdir = home / f".{name}"
    (pdir / "sessions").mkdir(parents=True, exist_ok=True)
    hooks: dict[str, Any] = {}
    if wired:
        cmd = f"python3 {LIB} hook"
        hooks = {
            "SessionStart": [{"hooks": [{"type": "command", "command": cmd}]}],
            "SessionEnd": [{"hooks": [{"type": "command", "command": cmd}]}],
        }
    (pdir / "settings.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    return pdir


def _record(
    home: Path, profile: str, pid: int, name: str = "s", proto: object = 1
) -> tuple[Path, Path]:
    """하네스가 쓰는 원본 레코드 쌍. proto=_ABSENT → `peerProtocol` 필드 자체가 없음."""
    d = home / f".{profile}" / "sessions"
    data: dict[str, Any] = {"pid": pid, "name": name, "sessionId": f"sid-{pid}"}
    if proto is not _ABSENT:
        data["peerProtocol"] = proto
    js = d / f"{pid}.json"
    key = d / f"{pid}.{KEY_HEX}.key"
    js.write_text(json.dumps(data), encoding="utf-8")
    key.write_text("token", encoding="utf-8")
    return js, key


def _mirror(
    home: Path,
    src_profile: str,
    dst_profile: str,
    pid: int,
    rows: list[dict[str, Any]],
    *,
    json_lag_s: float = 0.0,
) -> None:
    """브리지처럼 쌍을 dst 로 복사(mtime 보존)하고 manifest 행을 rows 에 추가.

    json_lag_s>0 → json 복사본만 원본보다 그만큼 낡게(실운영 모양: key 는 안 바뀐다).
    """
    src_dir = home / f".{src_profile}" / "sessions"
    dst_dir = home / f".{dst_profile}" / "sessions"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for fname in (f"{pid}.json", f"{pid}.{KEY_HEX}.key"):
        src, dst = src_dir / fname, dst_dir / fname
        shutil.copyfile(src, dst)
        st = src.stat()
        lag = int(json_lag_s * 1e9) if fname.endswith(".json") else 0
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns - lag))
        rows.append(
            {
                "path": str(dst),
                "src": str(src),
                "pid": pid,
                "src_profile": src_profile,
                "dst_profile": dst_profile,
            }
        )


def _state_dir(home: Path) -> Path:
    sd = home / ".config" / "cc-inspect" / ".session-bridge"
    sd.mkdir(parents=True, exist_ok=True)
    return sd


def _manifest(home: Path, rows: list[dict[str, Any]] | str) -> Path:
    p = _state_dir(home) / "manifest.json"
    body = rows if isinstance(rows, str) else json.dumps({"version": 2, "copies": rows})
    p.write_text(body, encoding="utf-8")
    return p


def _profiles_file(home: Path, names: list[str]) -> None:
    (_state_dir(home) / "profiles").write_text("\n".join(names) + "\n", encoding="utf-8")


def _run(alive: set[int]) -> list[CheckResult]:
    with patch(f"{_MOD}.pid_alive", side_effect=lambda pid: int(pid) in alive):
        return SessionBridgeCheck().run(CheckContext())


# ── 등록 ────────────────────────────────────────────────────────────


def test_registered_in_doctor_registry() -> None:
    assert "session-bridge" in _REGISTRY


# ── 활성 판정 ────────────────────────────────────────────────────────


def test_silent_when_no_profile_wires_the_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """배선이 어디에도 없음 = 모듈 off / ccinspector 미설치 머신 → N/A silent(미가시 세션이 있어도)."""
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a", wired=False)
    _profile(home, "claude-b", wired=False)
    _record(home, "claude-a", 101)
    _manifest(home, [])
    assert _run(alive={101}) == []


def test_partial_wiring_warns_naming_unwired_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sessions/ 가 있는 활성 프로필인데 배선이 없으면 그 프로필 세션의 동기화·회수가 안 돈다."""
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b", wired=False)
    _record(home, "claude-a", 101)
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows)
    _manifest(home, rows)
    res = _run(alive={101})
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "claude-b" in res[0].message and "배선" in res[0].message
    assert "claude-a" not in res[0].message
    assert res[0].suggestion is not None and "install.sh" in res[0].suggestion


def test_profiles_file_limits_active_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """state_dir/profiles 가 브리지 대상 집합 — 그 밖의 `.claude-*` 는 미가시·미배선 판정에서 제외."""
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    _profile(home, "claude-c", wired=False)  # 대상 밖: 배선 없고 복사본도 없음
    _profiles_file(home, ["claude-a", "claude-b"])
    _record(home, "claude-a", 101)
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows)
    _manifest(home, rows)
    assert _run(alive={101}) == []


# ── 가시성 ───────────────────────────────────────────────────────────


def test_silent_when_every_live_session_is_visible_everywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    _record(home, "claude-a", 101, name="alpha")
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows)
    _manifest(home, rows)
    assert _run(alive={101}) == []


def test_warns_per_live_session_missing_in_a_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path, monkeypatch)
    for p in ("claude-a", "claude-b", "claude-c"):
        _profile(home, p)
    js, _ = _record(home, "claude-a", 101, name="alpha")
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows)  # c 에는 없음
    _manifest(home, rows)
    res = _run(alive={101})
    assert len(res) == 1
    r = res[0]
    assert r.severity is Severity.WARNING
    assert "alpha" in r.message and "101" in r.message and "claude-c" in r.message
    assert "claude-b" not in r.message  # 보이는 프로필은 나열하지 않는다
    assert r.location == js
    assert r.suggestion is not None and f"python3 {LIB} sync" in r.suggestion


def test_half_pair_in_other_profile_counts_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """json 만 있고 key 가 없으면 SendMessage 인증이 안 된다 — 쌍이 완전해야 가시."""
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    _record(home, "claude-a", 101)
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows)
    (home / ".claude-b" / "sessions" / f"101.{KEY_HEX}.key").unlink()
    _manifest(home, rows)
    res = _run(alive={101})
    assert [r.severity for r in res] == [Severity.WARNING]
    assert "claude-b" in res[0].message


def test_dead_session_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """죽은 pid 의 원본은 다음 reconcile 이 치운다 — 미가시로 보고하지 않는다."""
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    _record(home, "claude-a", 101)
    _manifest(home, [])
    assert _run(alive=set()) == []


def test_copy_is_not_treated_as_an_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """b 의 복사본(manifest 소유)은 원본이 아니다 — a 원본이 c 에 없을 때 b 몫으로 이중 보고 금지."""
    home = _home(tmp_path, monkeypatch)
    for p in ("claude-a", "claude-b", "claude-c"):
        _profile(home, p)
    _record(home, "claude-a", 101)
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows)
    _manifest(home, rows)
    res = _run(alive={101})
    assert len(res) == 1
    assert "claude-a" in res[0].message  # 원본 프로필 기준 1건뿐


def test_missing_manifest_means_no_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """manifest 부재 = sync 가 한 번도 안 돎 → 원본은 전부 원본, 미가시는 그대로 보고."""
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    _record(home, "claude-a", 101)
    res = _run(alive={101})
    assert [r.severity for r in res] == [Severity.WARNING]
    assert "claude-b" in res[0].message


# ── manifest / 형식 가드 ─────────────────────────────────────────────


def test_manifest_unparseable_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    _record(home, "claude-a", 101)
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows)
    mp = _manifest(home, "{not json")
    res = _run(alive={101})
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "manifest" in res[0].message
    assert res[0].location == mp


def test_copies_without_any_record_pair_warns_format_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """복사본은 있는데 인식되는 원본 쌍이 0 — 하네스 레코드 형식 변경 의심(lib status --check 와 같은 guard)."""
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    (home / ".claude-a" / "sessions" / "101.v2.json").write_text("{}", encoding="utf-8")
    rows = [
        {"path": str(home / ".claude-b" / "sessions" / "101.v2.json"),
         "src": str(home / ".claude-a" / "sessions" / "101.v2.json"),
         "pid": 101, "src_profile": "claude-a", "dst_profile": "claude-b"},
    ]
    _manifest(home, rows)
    res = _run(alive={101})
    assert [r.severity for r in res] == [Severity.WARNING]
    assert "형식" in res[0].message


# ── peerProtocol ─────────────────────────────────────────────────────


def test_peer_protocol_other_than_1_warns_aggregated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    _record(home, "claude-a", 101, proto=2)
    _record(home, "claude-a", 102, proto=2)
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows)
    _mirror(home, "claude-a", "claude-b", 102, rows)
    _manifest(home, rows)
    res = _run(alive={101, 102})
    assert len(res) == 1  # 값별 집계 — 세션당 1줄이 아니다
    assert res[0].severity is Severity.WARNING
    assert "peerProtocol" in res[0].message and "2 건" in res[0].message


def test_peer_protocol_absent_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    _record(home, "claude-a", 101, proto=_ABSENT)
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows)
    _manifest(home, rows)
    res = _run(alive={101})
    assert [r.severity for r in res] == [Severity.WARNING]
    assert "peerProtocol" in res[0].message and "없음" in res[0].message


# ── 복사본 신선도 ─────────────────────────────────────────────────────


def test_stale_copies_are_one_info_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5분 넘게 낡은 복사본은 INFO 1줄 집계(건수·최대 지연) — WARNING 이 아니다(상시 발생)."""
    home = _home(tmp_path, monkeypatch)
    _profile(home, "claude-a")
    _profile(home, "claude-b")
    _record(home, "claude-a", 101)
    _record(home, "claude-a", 102)
    rows: list[dict[str, Any]] = []
    _mirror(home, "claude-a", "claude-b", 101, rows, json_lag_s=600)
    _mirror(home, "claude-a", "claude-b", 102, rows, json_lag_s=60)  # 임계 미만
    _manifest(home, rows)
    res = _run(alive={101, 102})
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "1 건" in res[0].message and "10분" in res[0].message
    assert res[0].suggestion is not None and "sync" in res[0].suggestion

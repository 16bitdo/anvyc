"""anvyc doctor --json 출력 schema 정합성 검증.

외부 도구(CI, jq, 다른 스크립트) 가 JSON 을 안전하게 파싱할 수 있도록
schema 변경 시 본 테스트가 회귀를 잡는다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# JSON 출력의 result entry 가 가져야 할 6 필드 (camelCase 아님 — snake)
REQUIRED_RESULT_KEYS = {
    "check_name",
    "severity",
    "message",
    "location",
    "line",
    "suggestion",
}

# summary 가 가져야 할 6 severity 라벨
EXPECTED_SEVERITIES = {
    "info",
    "info-aliased",
    "warning",
    "warning-foreign",
    "warning-dangling",
    "critical",
}


def _anvyc(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(Path(sys.executable).parent / "anvyc"), *args]
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True
    )


def test_doctor_json_parses(tmp_path: Path) -> None:
    """--json 출력이 항상 valid JSON 이어야 한다."""
    proc = _anvyc("doctor", "--json", cwd=tmp_path)
    assert proc.returncode in (0, 1), proc.stderr
    data = json.loads(proc.stdout)
    assert isinstance(data, dict)
    assert set(data.keys()) == {"results", "summary"}, data.keys()


def test_doctor_json_result_schema(tmp_path: Path) -> None:
    """모든 result entry 가 동일 schema (6 필드) 를 가져야 한다."""
    proc = _anvyc("doctor", "--json", cwd=tmp_path)
    data = json.loads(proc.stdout)
    for r in data["results"]:
        assert set(r.keys()) == REQUIRED_RESULT_KEYS, (
            f"unexpected keys: {set(r.keys()) ^ REQUIRED_RESULT_KEYS}"
        )
        # 타입 검사
        assert isinstance(r["check_name"], str)
        assert isinstance(r["severity"], str)
        assert isinstance(r["message"], str)
        assert r["location"] is None or isinstance(r["location"], str)
        assert r["line"] is None or isinstance(r["line"], int)
        assert r["suggestion"] is None or isinstance(r["suggestion"], str)


def test_doctor_json_summary_includes_all_severities(tmp_path: Path) -> None:
    """summary 는 6 severity 를 모두 (0 카운트라도) 포함해야 한다."""
    proc = _anvyc("doctor", "--json", cwd=tmp_path)
    data = json.loads(proc.stdout)
    assert set(data["summary"].keys()) == EXPECTED_SEVERITIES
    for k, v in data["summary"].items():
        assert isinstance(v, int)
        assert v >= 0


def test_doctor_json_only_filter(tmp_path: Path) -> None:
    """--only 옵션 시 results 에 다른 check 가 섞이지 않아야 한다."""
    proc = _anvyc("doctor", "--json", "--only", "venv-hidden-flag", cwd=tmp_path)
    data = json.loads(proc.stdout)
    # venv-hidden-flag 자체 check 가 발행하는 결과의 check_name 은 동일
    # adapter-validate 와 같은 wrapper check 가 아니라면 단일 check_name
    names = {r["check_name"] for r in data["results"]}
    # venv-hidden-flag 가 발견 0건일 수도 있고 1건일 수도 있음 — 0건이면 OK
    if names:
        assert names == {"venv-hidden-flag"}, names


def test_doctor_json_skip_excludes(tmp_path: Path) -> None:
    """--skip cross-user 시 cross-user 결과가 빠져야 한다."""
    proc_all = _anvyc("doctor", "--json", cwd=tmp_path)
    proc_skipped = _anvyc("doctor", "--json", "--skip", "cross-user", cwd=tmp_path)
    all_data = json.loads(proc_all.stdout)
    skipped_data = json.loads(proc_skipped.stdout)
    skipped_names = {r["check_name"] for r in skipped_data["results"]}
    assert "cross-user" not in skipped_names
    # 그 외 check 결과는 보존
    cu_all = sum(1 for r in all_data["results"] if r["check_name"] == "cross-user")
    assert len(all_data["results"]) - cu_all == len(skipped_data["results"])

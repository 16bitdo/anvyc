"""security/scanner — pattern 매칭 + op:// reference 강등."""
from __future__ import annotations

from pathlib import Path

from anvyc.security.scanner import extract_op_references, scan_file


def test_raw_aws_key_critical(tmp_path: Path) -> None:
    f = tmp_path / "config"
    f.write_text('export AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF\n')
    findings = scan_file(f)
    assert any(x.pattern == "aws_access_key" and x.severity == "critical" for x in findings)


def test_op_reference_only_no_finding(tmp_path: Path) -> None:
    f = tmp_path / "config"
    f.write_text('export AWS="op://Personal/AWS/access_key"\n')
    findings = scan_file(f)
    # op:// 만 있고 다른 secret 패턴 매칭이 없으므로 finding 0
    assert findings == []


def test_op_reference_downgrades_same_line(tmp_path: Path) -> None:
    f = tmp_path / "config"
    # 같은 라인에 raw-like + op:// 동시 출현 (예: 마이그레이션 직전)
    f.write_text('api_key=AKIA9999999999999999 # was op://Personal/X/y\n')
    findings = scan_file(f)
    # op:// signal 로 severity "low" 로 강등돼야 함
    severities = {x.severity for x in findings}
    assert "critical" not in severities
    assert "high" not in severities
    assert "low" in severities


def test_op_reference_does_not_downgrade_other_lines(tmp_path: Path) -> None:
    f = tmp_path / "config"
    f.write_text(
        'safe_line=op://Personal/X/y\n'
        'leak_line=AKIA1234567890ABCDEF\n'
    )
    findings = scan_file(f)
    leak = [x for x in findings if x.line_number == 2]
    assert any(x.severity == "critical" for x in leak)


def test_extract_op_references(tmp_path: Path) -> None:
    f = tmp_path / "config"
    f.write_text(
        'a=op://Personal/X/y\n'
        'b="op://Work/Token/value"\n'
        'c=plain text\n'
    )
    refs = extract_op_references(f)
    assert [r[1] for r in refs] == [
        "op://Personal/X/y",
        "op://Work/Token/value",
    ]
    assert refs[0][0] == 1
    assert refs[1][0] == 2


def test_scan_nonexistent_file_returns_empty(tmp_path: Path) -> None:
    assert scan_file(tmp_path / "nope") == []


def test_github_token_pattern(tmp_path: Path) -> None:
    f = tmp_path / "env"
    f.write_text("GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789\n")
    findings = scan_file(f)
    assert any(x.pattern == "github_token" and x.severity == "high" for x in findings)


def test_private_key_marker(tmp_path: Path) -> None:
    f = tmp_path / "key.pem"
    f.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nblah\n")
    findings = scan_file(f)
    assert any(x.pattern == "private_key" and x.severity == "critical" for x in findings)

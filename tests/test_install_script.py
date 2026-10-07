"""install.sh smoke test.

- bash -n syntax check (필수)
- shellcheck (설치돼 있으면, 없으면 skip)
- 설치 인자(ANVYC_EXTRAS) — 가짜 curl·uv·pipx 로 실행해 설치기가 받는 인자를 본다

실 네트워크 호출 (GitHub API) 과 실제 설치는 하지 않음 — 가짜 curl 이 wheel·SHA256SUMS 를
내려주고, 가짜 uv/pipx 는 받은 인자를 기록만 한다.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).parent.parent / "install.sh"

_FAKE_WHEEL = "fake-wheel-bytes"
_VERSION = "v9.9.9"
_WHEEL = "anvyc-9.9.9-py3-none-any.whl"


def _write_exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_install(
    tmp_path: Path,
    *,
    method: str = "uv",
    extras: str | None = None,
    tmp_dir: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str] | None, list[str]]:
    """install.sh 를 네트워크·실제 설치 없이 실행한다.

    반환: (프로세스, 설치기가 받은 인자 — 호출되지 않았으면 None, curl 이 받은 URL 목록).
    인자는 한 줄에 하나씩 기록해 공백이 든 인자도 경계를 잃지 않게 한다.
    `tmp_dir` 를 주면 가짜 mktemp 가 그 경로를 내준다 — TMPDIR 로는 못 만든다(macOS 의
    `mktemp -d` 는 TMPDIR 를 무시한다, 2026-10-07 실측).
    """
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    curl_log = tmp_path / "curl.log"
    installer_log = tmp_path / "installer.log"
    sha = hashlib.sha256(_FAKE_WHEEL.encode()).hexdigest()
    _write_exe(
        fakebin / "curl",
        f"""#!/usr/bin/env bash
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
printf '%s\\n' "$url" >> "{curl_log}"
case "$url" in
  *.whl) printf '%s' '{_FAKE_WHEEL}' > "$out" ;;
  */SHA256SUMS) printf '%s  %s\\n' '{sha}' '{_WHEEL}' > "$out" ;;
  *) exit 22 ;;
esac
""",
    )
    _write_exe(
        fakebin / method,
        f"""#!/usr/bin/env bash
for a in "$@"; do printf '%s\\n' "$a"; done > "{installer_log}"
""",
    )
    if tmp_dir is not None:
        _write_exe(
            fakebin / "mktemp",
            f"""#!/usr/bin/env bash
mkdir -p '{tmp_dir}' && printf '%s\\n' '{tmp_dir}'
""",
        )
    env = {
        "PATH": f"{fakebin}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "ANVYC_VERSION": _VERSION,
        "ANVYC_METHOD": method,
    }
    if extras is not None:
        env["ANVYC_EXTRAS"] = extras
    proc = subprocess.run(
        ["bash", str(INSTALL_SH)], capture_output=True, text=True, env=env, timeout=60
    )
    args = installer_log.read_text().splitlines() if installer_log.exists() else None
    urls = curl_log.read_text().splitlines() if curl_log.exists() else []
    return proc, args, urls


def test_install_sh_exists() -> None:
    assert INSTALL_SH.is_file(), f"install.sh missing: {INSTALL_SH}"


def test_install_sh_is_executable() -> None:
    st = INSTALL_SH.stat()
    assert st.st_mode & 0o111, "install.sh must be executable"


def test_install_sh_bash_syntax() -> None:
    """bash -n 으로 syntax 검증."""
    proc = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_install_sh_has_strict_mode() -> None:
    """`set -euo pipefail` 강제."""
    body = INSTALL_SH.read_text()
    assert "set -euo pipefail" in body


def test_install_sh_verifies_sha256() -> None:
    """SHA256SUMS 검증 단계가 존재."""
    body = INSTALL_SH.read_text()
    assert "SHA256SUMS" in body
    assert "SHA256 mismatch" in body or "SHA256 verified" in body


@pytest.mark.skipif(
    shutil.which("shellcheck") is None,
    reason="shellcheck not installed",
)
def test_install_sh_shellcheck_passes() -> None:
    """shellcheck 가 설치돼 있으면 통과해야 함."""
    proc = subprocess.run(
        ["shellcheck", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- ANVYC_EXTRAS — anvyc 는 PyPI 에 없다. extras 를 붙인 이름 기반 명령(`'anvyc[mcp]'`)은
# 새 환경에서 실패하고, 그 이름이 선점되면 제3자 패키지를 설치한다(2026-10-07 시뮬레이션).
# 그래서 extras 는 방금 내려받아 SHA256 을 검증한 wheel 에 PEP 508 직접 참조로 붙인다.

_SPEC_RE = re.compile(r"^anvyc\[(?P<extras>[^\]]+)\] @ file:///\S+/" + re.escape(_WHEEL) + "$")


def test_install_without_extras_passes_verified_wheel_path(tmp_path: Path) -> None:
    """ANVYC_EXTRAS 가 없으면 지금처럼 검증한 wheel 경로를 그대로 넘긴다."""
    proc, args, _ = _run_install(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert args is not None and args[:3] == ["tool", "install", "--force"]
    assert len(args) == 4 and args[3].endswith("/" + _WHEEL)
    assert not args[3].startswith("anvyc[")


def test_install_with_extras_attaches_them_to_the_verified_wheel(tmp_path: Path) -> None:
    proc, args, _ = _run_install(tmp_path, extras="mcp")
    assert proc.returncode == 0, proc.stderr
    assert args is not None and args[:3] == ["tool", "install", "--force"]
    m = _SPEC_RE.match(args[3])
    assert m, args[3]
    assert m["extras"] == "mcp"


def test_install_with_several_extras(tmp_path: Path) -> None:
    proc, args, _ = _run_install(tmp_path, extras="mcp,tui,cost-aws")
    assert proc.returncode == 0, proc.stderr
    assert args is not None
    m = _SPEC_RE.match(args[-1])
    assert m, args[-1]
    assert m["extras"] == "mcp,tui,cost-aws"


def test_pipx_install_with_extras(tmp_path: Path) -> None:
    proc, args, _ = _run_install(tmp_path, method="pipx", extras="mcp")
    assert proc.returncode == 0, proc.stderr
    assert args is not None and args[:2] == ["install", "--force"]
    assert len(args) == 3 and _SPEC_RE.match(args[2]), args


@pytest.mark.parametrize(
    "bad",
    ["mcp;touch pwned", "mcp]", "MCP", "mcp tui", ",mcp", "mcp,", "mcp,,tui", "$(id)", "mcp@x"],
)
def test_invalid_extras_rejected_before_download(tmp_path: Path, bad: str) -> None:
    """값은 PEP 508 요구 문자열에 그대로 들어간다 — 내려받기 전에 거른다."""
    proc, args, urls = _run_install(tmp_path, extras=bad)
    assert proc.returncode != 0
    assert "ANVYC_EXTRAS" in proc.stderr
    assert args is None, "설치기가 호출되면 안 된다"
    assert urls == [], "검증 전에는 아무것도 내려받지 않는다"


def test_extras_file_url_encodes_spaces_in_temp_path(tmp_path: Path) -> None:
    """임시 경로에 공백이 있어도 파일 URL 은 깨지지 않는다(%20) — uv·pipx 모두 받는다(실측).

    Linux 의 mktemp 는 TMPDIR 를 따르므로 공백 경로가 실제로 생길 수 있다.
    """
    proc, args, _ = _run_install(tmp_path, extras="mcp", tmp_dir=tmp_path / "with space" / "tmp.x")
    assert proc.returncode == 0, proc.stderr
    assert args is not None
    assert "with%20space" in args[-1] and " " not in args[-1].split(" @ ", 1)[1]
    assert _SPEC_RE.match(args[-1]), args[-1]


def test_fake_mktemp_really_yields_a_spaced_path(tmp_path: Path) -> None:
    """위 테스트가 공허하지 않음을 보증 — extras 없이 돌리면 공백 경로가 그대로 설치기에 간다."""
    proc, args, _ = _run_install(tmp_path, tmp_dir=tmp_path / "with space" / "tmp.x")
    assert proc.returncode == 0, proc.stderr
    assert args is not None and "/with space/tmp.x/" + _WHEEL in args[-1]

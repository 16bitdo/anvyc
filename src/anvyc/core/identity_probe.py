"""자격의 실체 역참조 (dereference) — 선언이 아니라 실제 값을 반환한다.

기존 project/doctor check 는 선언(.envrc·ssh alias·config)끼리의 정합만 본다.
선언이 서로 일치해도 그 이름이 가리키는 자격이 실제로 그 계정인지는 확인하지
않는다(2026-08-12 사고 ③ — .envrc·gh auth status·project show 셋 다 '16bitdo'
라고 답했고 셋 다 틀렸다).

본 모듈은 선언이 아니라 실체를 반환하는 조회를 모아 둔다. GitHub/SSH/Git 신원은
이 모듈이 담당하고, AWS 실체 조회는 core/aws_probe.probe_caller_identity() 가
담당하며 doctor 의 offline 보장을 위해 본 모듈에 두지 않는다.

어떤 자격도 변경하지 않는다(read-only 불변식).

모든 함수는 실패 시 None 을 반환한다 — 네트워크·미설치·타임아웃은 "모름"이지
"불일치"가 아니다. 호출자는 None 을 불일치로 해석해선 안 된다.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_TIMEOUT = 15
_SSH_GREETING_RE = re.compile(r"Hi ([A-Za-z0-9][A-Za-z0-9-]*)!")
_IDENT_EMAIL_RE = re.compile(r"<([^>]*)>")


def gh_login(gh_config_dir: str | Path) -> str | None:
    """`GH_CONFIG_DIR` 프로필의 토큰이 실제로 귀속된 GitHub login.

    `gh auth status` 가 보고하는 라벨이 아니라 API 가 돌려주는 실체다.
    """
    env = {**os.environ, "GH_CONFIG_DIR": str(Path(gh_config_dir).expanduser())}
    try:
        proc = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, check=False, timeout=_TIMEOUT, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def ssh_login(ssh_alias: str) -> str | None:
    """`ssh -T git@<alias>` 인사말에서 실제 인증되는 GitHub login.

    GitHub 은 shell 을 제공하지 않아 정상 인증에서도 비0 exit 이고 인사말은
    stderr 로 나온다. returncode 로 판정하지 않는다.
    """
    try:
        proc = subprocess.run(
            ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", f"git@{ssh_alias}"],
            capture_output=True, text=True, check=False, timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = _SSH_GREETING_RE.search(f"{proc.stderr or ''}\n{proc.stdout or ''}")
    return m.group(1) if m else None


def commit_email(repo_dir: str | Path) -> str | None:
    """`git var GIT_AUTHOR_IDENT` — 커밋에 실제로 박힐 신원의 이메일.

    `git config user.email` 과 다르다. 환경변수 override 까지 반영된 최종값이고,
    신원 미해결이면 비0 exit 이다(useConfigOnly fail-closed).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "var", "GIT_AUTHOR_IDENT"],
            capture_output=True, text=True, check=False, timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    m = _IDENT_EMAIL_RE.search(proc.stdout or "")
    if not m:
        return None
    return m.group(1) or None

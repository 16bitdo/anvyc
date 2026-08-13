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

from anvyc.core.project_info import derive_gh_account

_TIMEOUT = 15
_SSH_GREETING_RE = re.compile(r"Hi ([A-Za-z0-9][A-Za-z0-9-]*)!")
_IDENT_EMAIL_RE = re.compile(r"<([^>]*)>")


def _gh_account_token(account: str) -> str | None:
    """`account` 로 로그인된 gh 토큰. 없으면 None.

    `gh auth token --user <account>` 는 키체인에서 **그 계정의** 토큰을 정확히 꺼낸다
    (활성 계정과 무관). gh 가 계정을 명시적으로 고르게 하는 공식 수단이다.
    """
    try:
        proc = subprocess.run(
            ["gh", "auth", "token", "--user", account],
            capture_output=True, text=True, check=False, timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def gh_login(gh_config_dir: str | Path) -> str | None:
    """`gh_config_dir` 프로필의 토큰이 실제로 귀속된 GitHub login.

    `gh auth status` 가 보고하는 라벨이 아니라 API 가 돌려주는 실체다.

    **`GH_CONFIG_DIR` 만으로는 이 질문에 답할 수 없다.** 그 변수는 config 파일 경로만
    격리하고 활성 자격은 격리하지 않는다 — gh 는 토큰을 OS 키체인에서 hostname 만으로
    조회한다(cli/cli#10136). 그래서 `GH_CONFIG_DIR` 만 준 조회는 어느 프로필을
    가리키든 **"지금 활성인 계정"** 을 돌려준다.

    2026-08-14 실측 — 주변 `GH_TOKEN` 을 바꾸면 이 함수의 답이 통째로 뒤집혔다.
    계정이 N 개면 활성인 하나만 맞고 나머지 N-1 개가 전부 불일치로 보고됐다
    (`anvyc doctor --strict` 가 그 이유로 exit 1 → anvyx C6 게이트 차단).

    그래서 디렉터리 이름에서 계정을 역산해(`gh-heisgone` -> `heisgone`) **그 계정의
    토큰을 직접 꺼내 주입한다.** 주변 `GH_TOKEN` 은 반드시 덮어쓴다 — 상속하면
    호출 환경에 따라 답이 달라지는 결함이 그대로 남는다.

    토큰을 못 얻으면 None("모름")이다. 주변 토큰으로 폴백하지 않는다 — 폴백은
    "다른 계정의 신원을 이 프로필의 실체라고 보고" 하는 것이라 침묵보다 나쁘다.
    """
    expanded = Path(gh_config_dir).expanduser()
    account = derive_gh_account(str(expanded))
    if not account:
        # 관례(`.../gh-<account>`)를 벗어난 경로 — 어느 계정의 토큰을 써야 할지
        # 알 수 없다. 주변 토큰으로 조회하면 엉뚱한 계정을 실체로 보고하게 된다.
        return None
    token = _gh_account_token(account)
    if not token:
        return None
    env = {**os.environ, "GH_CONFIG_DIR": str(expanded), "GH_TOKEN": token}
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

# src/anvyc/core/git_guards.py
"""로컬 pre-push 가드 — 보호 브랜치 직접 push 를 차단한다.

`anvyc guard install` 이 대상 repo 의 effective hooks dir 에 marker 블록을 설치한다.
정책 스냅샷(protected/allowed)을 hook 에 임베드 → push 시점에 ruleset repo 의존 없음.
core.hooksPath 가 worktree 내부(tracked)면 clobber 금지하고 skip 한다.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from anvyc.core.branch_policy import BranchPolicy

GuardStatus = Literal[
    "installed",
    "updated",
    "skipped-foreign",
    "skipped-tracked-hooks",
    "skipped-stdin-consumer",
]

GUARD_BEGIN = "# >>> anvyc-pr-guard >>>"
GUARD_END = "# <<< anvyc-pr-guard <<<"
_SHEBANG = "#!/usr/bin/env bash\nset -euo pipefail\n"


def render_guard_block(policy: BranchPolicy) -> str:
    protected = " ".join(policy.protected_branches)
    allowed = "true" if policy.push_to_main_allowed else "false"
    return (
        f"{GUARD_BEGIN}\n"
        f"# auto-generated; managed by `anvyc guard install`. policy_source={policy.source}\n"
        f'__anvyc_protected="{protected}"\n'
        f'__anvyc_allowed="{allowed}"\n'
        'if [ "$__anvyc_allowed" != "true" ]; then\n'
        "  while read -r _lref _lsha _rref _rsha; do\n"
        "    for _b in $__anvyc_protected; do\n"
        '      if [ "$_rref" = "refs/heads/$_b" ]; then\n'
        '        echo "" >&2\n'
        "        echo \"anvyc guard: '$_b' 직접 push 차단 (push_to_main_allowed=false).\" >&2\n"
        '        echo "  작업 브랜치 + PR 로 진행하세요:" >&2\n'
        '        echo "    git switch -c feat/<topic> && git push -u origin feat/<topic> && gh pr create --fill" >&2\n'
        "        exit 1\n"
        "      fi\n"
        "    done\n"
        "  done\n"
        "fi\n"
        f"{GUARD_END}\n"
    )


# pre-push 는 stdin 으로 ref 목록을 받고, 가드 블록은 `while read` 로 그것을 소비한다.
# 이미 stdin 을 읽는 훅에 가드를 끼워 넣으면 어느 위치든 한쪽이 굶는다 — 앞에 넣으면
# 본문이 ref 를 못 받고, 뒤에 넣으면 가드가 못 받아 **조용히** 통과시킨다.
# 주석 줄(`#` 이 앞선 경우)은 제외한다.
_STDIN_CONSUMER_RE = re.compile(
    r"^[^#\n]*(?:\bwhile\b[^\n]*\bread\b|\bread\s+-r?\b|\$\(\s*cat\s*\))",
    re.MULTILINE,
)


def _reads_stdin(text: str) -> bool:
    return _STDIN_CONSUMER_RE.search(text) is not None


def _insert_after_preamble(text: str, block: str) -> str:
    """shebang + 이어지는 `set …`/빈 줄 **직후** 에 block 을 끼운다.

    맨 앞에 넣으면 shebang 이 밀려 스크립트가 아니게 되고, 맨 뒤에 넣으면 본문이 먼저
    stdin 을 소비했을 때 가드가 무력해진다. anvyc SoT 훅과 같은 배치를 재현한다.
    주석은 preamble 로 보지 않는다 — 외부 managed-block 의 시작이 주석이기 때문이다.
    """
    lines = text.splitlines(keepends=True)
    i = 0
    if lines and lines[0].startswith("#!"):
        i = 1
        while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("set ")):
            i += 1
    head = "".join(lines[:i])
    if head and not head.endswith("\n"):
        head += "\n"
    return head + block + "\n" + "".join(lines[i:])


def effective_hooks_dir(repo_dir: Path) -> tuple[Path, bool]:
    """(hooks_dir, tracked_in_worktree) 반환.

    core.hooksPath 가 설정돼 있으면 그 경로를, 아니면 git common dir(`--git-common-dir`,
    linked worktree 도 안전)의 hooks 를 쓴다. tracked = worktree 내부이면서 .git 영역 밖
    (예: core.hooksPath=scripts/hooks) → anvyc 가 clobber 하지 않고 skip 하기 위함.
    """
    try:
        cfg = subprocess.run(
            ["git", "-C", str(repo_dir), "config", "--get", "core.hooksPath"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return repo_dir / ".git" / "hooks", False
    hp = cfg.stdout.strip() if cfg.returncode == 0 else ""
    if hp:
        hooks = Path(hp) if Path(hp).is_absolute() else (repo_dir / hp)
        try:
            rel = hooks.resolve().relative_to(repo_dir.resolve())
            tracked = rel.parts[:1] != (".git",)
        except (ValueError, OSError):
            tracked = False
        return hooks, tracked
    # custom hooksPath 없음 → common git dir 의 hooks (worktree 안전)
    try:
        cd = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        common = cd.stdout.strip() if cd.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        common = ""
    if not common:
        return repo_dir / ".git" / "hooks", False
    common_path = Path(common) if Path(common).is_absolute() else (repo_dir / common)
    return common_path / "hooks", False


@dataclass
class GuardInstallResult:
    repo: Path
    status: GuardStatus
    detail: str = ""


def install_pre_push_guard(
    repo_dir: Path, policy: BranchPolicy, *, force: bool = False
) -> GuardInstallResult:
    hooks_dir, tracked = effective_hooks_dir(repo_dir)
    if tracked:
        return GuardInstallResult(repo_dir, "skipped-tracked-hooks", str(hooks_dir))
    hook = hooks_dir / "pre-push"
    block = render_guard_block(policy)
    if not hook.exists():
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook.write_text(_SHEBANG + block)
        hook.chmod(0o755)
        return GuardInstallResult(repo_dir, "installed")
    text = hook.read_text()
    if GUARD_BEGIN in text:
        pre = text.split(GUARD_BEGIN)[0]
        post = text.split(GUARD_END, 1)[1] if GUARD_END in text else "\n"
        hook.write_text(pre + block + post)
        hook.chmod(0o755)
        return GuardInstallResult(repo_dir, "updated")
    if not force:
        return GuardInstallResult(repo_dir, "skipped-foreign", str(hook))
    if _reads_stdin(text):
        # 손대지 않는다 — 깨진 조합을 만드는 것보다 사람에게 알리는 편이 낫다.
        return GuardInstallResult(repo_dir, "skipped-stdin-consumer", str(hook))
    # 통째 교체하지 않는다. 남의 훅에는 다른 도구가 소유한 managed-block 이 들어 있을 수
    # 있고(role-based-ruleset 의 claude-md-freshness), 교체는 그것을 조용히 지운다
    # (2026-08-27 실사고 — install-git-hooks.sh 에서 같은 결함을 고쳤다).
    (hooks_dir / "pre-push.pre-anvyc").write_text(text)
    hook.write_text(_insert_after_preamble(text, block))
    hook.chmod(0o755)
    return GuardInstallResult(repo_dir, "installed", "merged; backup=pre-push.pre-anvyc")

"""git worktree 에 룰을 따라오게 한다.

문제: `git worktree add` 로 만든 트리에는 **에이전트가 읽어야 할 룰이 전부 빠진다.**
`CLAUDE.md`(룰 인덱스)·`.cursor/rules`·`.cursor/skills`·`.envrc` 는 대개 gitignore
대상이라 체크아웃되지 않기 때문이다. 정작 rule 18 은 "worktree-per-task 격리" 를
권장하므로, 권장을 따르면 그 권장을 담은 룰이 사라지는 모순이 생긴다.

해법은 **복사가 아니라 symlink** 다. 복사본은 만든 순간부터 stale 해진다 —
2026-08-25 실측에서 `CLAUDE.md` 는 하루 세 번 재생성됐고, 격리 사본이 본 저장소보다
최신이 되는 역전까지 일어났다. 룰은 격리 대상이 아니다. 격리해야 할 것은 코드이고
룰은 항상 원본과 같아야 한다 — symlink 가 정확히 그 의미다.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# 읽기 전용 참조라 원본을 그대로 가리키면 된다.
#
# `.cursor` 자체가 아니라 **하위 항목**을 링크한다. `.gitignore` 의 `.cursor/`
# (뒤 슬래시)는 디렉터리만 매칭하는데 symlink 는 파일로 취급되어 걸리지 않는다 —
# 2026-08-25 실측에서 `?? .cursor` 가 떴다. `.cursor` 를 실제 디렉터리로 두면
# 기존 ignore 규칙이 그대로 먹으므로 exclude 를 조작할 필요가 없다
# (`$GIT_DIR/info/exclude` 는 linked worktree 에서 읽히지도 않는다 — git 은
# `$GIT_COMMON_DIR` 쪽을 본다).
LINK_TARGETS: tuple[str, ...] = (".cursor/rules", ".cursor/skills", "CLAUDE.md")

# direnv 승인은 경로별 보안 경계다. 자동으로 열지 않고 안내만 한다.
NOTICE_TARGETS: tuple[str, ...] = (".envrc",)

# 절대경로가 내부에 박혀 있어 링크하면 깨진다.
SKIP_TARGETS: tuple[str, ...] = (".venv", ".direnv")


@dataclass(frozen=True)
class LinkResult:
    """대상 하나의 처리 결과."""

    name: str
    status: str  # linked | exists | absent | notice | failed
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"linked", "exists", "absent", "notice"}


def _rel_to(target: Path, start: Path) -> str:
    """worktree 위치가 바뀌어도 견디도록 상대 경로로 건다."""
    return os.path.relpath(target, start)


def link_rules(origin: Path, worktree: Path) -> list[LinkResult]:
    """원본의 룰 자산을 worktree 로 symlink 한다 (순수 파일 조작).

    이미 존재하면 건드리지 않는다 — 사람이 의도적으로 둔 파일을 덮어쓰지 않는다.
    """
    results: list[LinkResult] = []

    for name in LINK_TARGETS:
        src = origin / name
        dst = worktree / name
        if not src.exists():
            results.append(LinkResult(name, "absent", "원본에 없음"))
            continue
        if dst.exists() or dst.is_symlink():
            results.append(LinkResult(name, "exists", "이미 있음 — 건드리지 않음"))
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(_rel_to(src, dst.parent))
            results.append(LinkResult(name, "linked", str(src)))
        except OSError as exc:
            results.append(LinkResult(name, "failed", str(exc)))

    for name in NOTICE_TARGETS:
        if (origin / name).exists():
            results.append(
                LinkResult(name, "notice", "direnv 는 경로별 승인이라 자동으로 열지 않는다")
            )

    return results


def missing_rule_links(worktree: Path) -> tuple[str, ...]:
    """worktree 에 없는 룰 자산 이름. 탐지(Phase 2)가 쓴다."""
    return tuple(
        name
        for name in LINK_TARGETS
        if not (worktree / name).exists() and not (worktree / name).is_symlink()
    )


def is_worktree(path: Path) -> bool:
    """linked worktree 인가 (원본 체크아웃은 False).

    linked worktree 는 `.git` 이 디렉터리가 아니라 gitdir 를 가리키는 **파일**이다.
    """
    dot_git = path / ".git"
    return dot_git.is_file()


def main_worktree_of(path: Path) -> Path | None:
    """이 worktree 의 원본(main worktree) 경로. 판정 실패 시 None."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    # 첫 항목이 main worktree 다 (git 문서 보장).
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):].strip())
    return None

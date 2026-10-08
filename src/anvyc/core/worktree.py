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
import re
import subprocess
from collections.abc import Callable
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

# 절대경로가 내부에 박혀 있어 링크하면 깨진다. 원본에 있으면 이 worktree 에서 다시 만드는
# 방법만 알린다 — `.venv` 가 없으면 첫 커밋이 pre-commit 훅의 `.venv/bin/*` 에서 막힌다.
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


def _common_exclude_file(worktree: Path) -> Path | None:
    """저장소 공용 exclude 파일 (`$GIT_COMMON_DIR/info/exclude`).

    `$GIT_DIR/info/exclude`(worktree 전용)는 **읽히지 않는다** — git 은 항상 common
    쪽을 본다(2026-08-25 실측: worktree 전용에 써도 `?? .cursor` 가 그대로였다).

    공용 파일을 건드리는 것은 두 가지 이유로 안전하다.
    ① 커밋되지 않는 로컬 파일이라 저장소 이력에 영향이 없다.
    ② 우리가 적는 경로는 원본이 이미 `.gitignore` 로 ignore 하는 대상이다 —
       원본에서는 실제 디렉터리라 `.cursor/rules/` 같은 디렉터리 패턴에 걸리고,
       worktree 에서만 symlink 라서 그 패턴을 빠져나간다. 슬래시 없는 규칙을
       더하면 worktree 의 symlink 만 추가로 걸린다.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    common = Path(out.stdout.strip())
    if not common.is_absolute():
        common = (worktree / common).resolve()
    return common / "info" / "exclude"


def _ensure_excluded(worktree: Path, names: tuple[str, ...]) -> None:
    """symlink 가 `git status` 를 더럽히지 않게 한다.

    gitignore 의 디렉터리 패턴(뒤 슬래시)은 디렉터리만 매칭한다. symlink 는 파일로
    취급돼 걸리지 않는다. 저장소마다 패턴 깊이가 달라(`.cursor/` vs
    `.cursor/rules/`) 링크 위치를 낮추는 것만으로는 덮이지 않는다.
    """
    target = _common_exclude_file(worktree)
    if target is None:
        return
    existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
    have = {ln.strip() for ln in existing.splitlines()}
    missing = [n for n in names if n not in have]
    if not missing:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(
                "\n# anvyc worktree: 룰 symlink — gitignore 의 디렉터리 패턴에 걸리지 않는다\n"
            )
            f.write("\n".join(missing) + "\n")
    except OSError:
        return


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

    linked = tuple(r.name for r in results if r.status == "linked")
    if linked:
        _ensure_excluded(worktree, linked)

    for name in NOTICE_TARGETS:
        if (origin / name).exists():
            results.append(
                LinkResult(name, "notice", "direnv 는 경로별 승인이라 자동으로 열지 않는다")
            )

    # 원본에 없으면 침묵한다 — venv 를 쓰지 않는 저장소에 알리면 소음이다.
    for name in SKIP_TARGETS:
        if (origin / name).exists():
            results.append(LinkResult(name, "notice", _skip_notice(name, worktree)))

    return results


def _skip_notice(name: str, worktree: Path) -> str:
    """링크하지 않는 대상을 이 worktree 에서 다시 만드는 방법.

    `--origin` 으로 다른 저장소에도 쓰이므로 설치 스크립트는 그 worktree 에 있을 때만 이름을
    댄다 — 없는 명령을 알려 주면 안내가 없는 것보다 나쁘다. `scripts/dev-install.sh` 는 linked
    worktree 에서 돌려도 전역 래퍼(내용이 같으면 교체 생략)·공용 훅(`.git` 이 파일이라 설치 단계
    skip)을 건드리지 않는다(2026-10-06 sandbox·실제 worktree 실측).
    """
    head = "링크하지 않는다(내부 절대경로) — "
    if name == ".direnv":
        return head + "direnv allow 가 이 worktree 에 새로 만든다"
    if name == ".venv" and (worktree / "scripts" / "dev-install.sh").is_file():
        return head + "이 worktree 에서 bash scripts/dev-install.sh"
    if name == ".venv":
        return head + "이 worktree 에서 새로 만든다(커밋 훅·pre-push 게이트가 .venv/bin 을 찾는다)"
    return head + "이 worktree 에서 새로 만든다"


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


# ---------- 오래된 잠금 탐지 ----------------------------------------------------
#
# Claude 세션은 자기 worktree 를 `git worktree lock` 으로 잠그고, 정리 없이 끝나면 잠금이 그대로
# 남는다. 잠긴 worktree 는 `remove`·`prune` 이 거부하는데 아무 신호가 없다 — 2026-10-06
# pulseforge 에서 8/5 세션(pid 89657, 이미 종료)의 잠금이 두 달간 정리를 막았다.

# 사유 원문 예: "claude session phase3b1-web-ui (pid 89657 start Wed Aug  5 06:36:11 2026)"
_CLAUDE_LOCK_RE = re.compile(
    r"claude session (?P<session>.+?) \(pid (?P<pid>\d+) start (?P<start>[^)]+)\)"
)


@dataclass(frozen=True)
class LockedWorktree:
    """`git worktree list --porcelain` 의 잠긴 항목."""

    path: Path
    branch: str | None  # None = detached
    reason: str  # 사유 없이 잠갔으면 ""


@dataclass(frozen=True)
class ClaudeLock:
    """Claude 세션 형식의 잠금 사유를 푼 것."""

    session: str
    pid: int
    start: str  # 사유에 적힌 그대로(C 로캘 `ps -o lstart` 형식)


def main_worktree_in(porcelain: str) -> Path | None:
    """porcelain 출력의 첫 항목 = main worktree (git 문서 보장)."""
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):].strip())
    return None


def locked_worktrees(porcelain: str) -> list[LockedWorktree]:
    """잠긴 worktree 목록. `locked` 줄이 없는 항목(main 포함)은 뺀다."""
    found: list[LockedWorktree] = []
    for block in porcelain.split("\n\n"):
        path: Path | None = None
        branch: str | None = None
        reason: str | None = None
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = Path(line[len("worktree "):].strip())
            elif line.startswith("branch "):
                branch = line[len("branch "):].removeprefix("refs/heads/")
            elif line == "locked":
                reason = ""
            elif line.startswith("locked "):
                reason = line[len("locked "):]
        if path is not None and reason is not None:
            found.append(LockedWorktree(path, branch, reason))
    return found


def parse_claude_lock(reason: str) -> ClaudeLock | None:
    """Claude 세션 형식의 사유만 푼다. 사람이 의도로 건 다른 사유는 None — 판정하지 않는다."""
    m = _CLAUDE_LOCK_RE.fullmatch(reason)
    if m is None:
        return None
    return ClaudeLock(m.group("session"), int(m.group("pid")), m.group("start"))


def stale_lock_reason(lock: ClaudeLock, start_of: Callable[[int], str | None]) -> str | None:
    """잠금을 건 세션이 끝났으면 그 이유, 아직 살아 있으면 None.

    start_of(pid) 는 그 pid 의 현재 시작 시각(없으면 None). pid 만 보면 재사용된 번호를
    살아 있는 세션으로 오판한다 — 두 달이면 pid 는 얼마든지 돈다.
    """
    now = start_of(lock.pid)
    if now is None:
        return f"pid {lock.pid} 없음(세션 종료)"
    current = " ".join(now.split())
    if current != " ".join(lock.start.split()):
        return f"pid {lock.pid} 를 다른 프로세스가 쓴다(시작 {current})"
    return None


def process_start(pid: int) -> str | None:
    """pid 의 시작 시각(C 로캘 `ps -o lstart`, 공백 정규화). 프로세스가 없으면 None.

    로캘을 C 로 고정한다 — ko_KR 의 lstart 는 「2026년 10월  8일 목요일 …」이라 잠금 사유와
    비교하면 살아 있는 세션이 전부 「다른 프로세스」가 된다(2026-10-07 실측).
    """
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True, text=True, timeout=10, check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = " ".join(out.stdout.split())
    return text if out.returncode == 0 and text else None

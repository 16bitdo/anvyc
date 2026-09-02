"""claude-md-freshness check (L2 관측, read-only).

role-based-ruleset 의 generate_claude_md.py --check 를 호출해, fleet 의 생성된
CLAUDE.md 가 각 repo .cursor/rules 와 content-fresh 한지 관측한다. stale → WARNING.
anvyc 는 SoT 를 수정하지 않는다(단방향) — 재생성은 사용자/L3 몫.

fresh 일 때는 그 다음 구간을 본다 — 재생성은 됐는데 커밋이 안 된 상태(INFO).
각 프로젝트에서 룰셋의 유일한 추적 기록이 CLAUDE.md 다(.cursor/ 는 대개 gitignore
대상). 커밋이 빠지면 다음 세션이 옛 인덱스를 보고, 저장소만으로는 어느 룰셋
버전 기준으로 작업했는지 알 수 없다. 재생성 직후 잠깐 열렸다 커밋하면 닫히는
창이라 사람이 사고로 발견하게 되는 종류의 상태다.

ruleset-deploy-drift(repo 가 origin 보다 뒤 — 스탬프성 신호) 를 per-file content
정밀 신호로 보완. rbr 부재 / 비정상 exit / 오류 → silent skip(무오탐).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.project_discovery import discover_projects

# generate_claude_md.py 가 생성물 첫 줄에 남기는 마커. 사람이 쓴 CLAUDE.md 와
# 가르는 유일한 근거다 — 이름 규칙이나 경로로 추정하지 않는다.
_GENERATED_MARKER = "auto-generated from .cursor/rules/"

# 단독 --apply 는 .cursor/rules(생성기 입력)가 SoT 보다 뒤처졌을 때 누락 룰을
# 인덱스에서 drop 한다(회귀). rbr 이 --check 실패 시 안내하는 안전 순서가 2단계다.
_STALE_REMEDY = (
    "python3 ~/dev/role-based-ruleset/scripts/deploy_cursor_rules.py "
    "--role <role> --target-dir <project> --apply --yes → "
    "python3 ~/dev/role-based-ruleset/scripts/generate_claude_md.py --apply → 각 repo 커밋 "
    "(재배포를 건너뛴 단독 --apply 는 룰을 인덱스에서 drop 한다)"
)


def _rbr_script() -> Path:
    return Path.home() / "dev" / "role-based-ruleset" / "scripts" / "generate_claude_md.py"


def _check_stale(script: Path) -> tuple[int, str] | None:
    """rbr --check 실행 → (returncode, stdout). 실행 불가면 None."""
    try:
        proc = subprocess.run(
            ["python3", str(script), "--check"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode, proc.stdout


def _projects() -> list[Path]:
    """미커밋 관측 대상 프로젝트. discover_projects 위임(테스트 patch 지점)."""
    return discover_projects()


def _is_generated(claude_md: Path) -> bool:
    """첫 줄에 생성 마커가 있는가."""
    try:
        with claude_md.open(encoding="utf-8") as fh:
            return _GENERATED_MARKER in fh.readline()
    except OSError:
        return False


def _git_out(repo: Path, *args: str) -> str | None:
    """git 실행 → stdout. 비0 exit / 오류 → None (모름은 불일치가 아니다)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _uncommitted_generated(projects: list[Path]) -> list[Path]:
    """생성물 CLAUDE.md 가 tracked 인데 미커밋인 프로젝트.

    tracked 게이트가 먼저다 — gitignored/untracked repo(anvyc·rbr 등)는 커밋
    자체가 대상이 아니라 재생성이 정본이므로, 보고하면 100% 오탐이다.
    """
    found: list[Path] = []
    for repo in projects:
        claude_md = repo / "CLAUDE.md"
        if not claude_md.is_file() or not _is_generated(claude_md):
            continue
        if _git_out(repo, "ls-files", "--error-unmatch", "CLAUDE.md") is None:
            continue  # untracked / gitignored / git 아님
        status = _git_out(repo, "status", "--porcelain", "--", "CLAUDE.md")
        if status:
            found.append(repo)
    return found


class ClaudeMdFreshnessCheck:
    """L2(read-only): fleet 생성 CLAUDE.md 의 content freshness + 커밋 반영 관측."""

    name = "claude-md-freshness"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        script = _rbr_script()
        if not script.exists():
            return []
        checked = _check_stale(script)
        if checked is None:
            return []
        returncode, stdout = checked
        if returncode == 1:
            return [self._stale_result(script, stdout)]
        if returncode != 0:  # 2=인자/경로 오류 → 보고 없음(무오탐)
            return []
        # fresh — stale 이면 답이 "재생성하라"이고 미커밋 보고는 그 위에 얹혀
        # 소음이 되므로, 이 구간에서만 본다.
        return self._uncommitted_result(_uncommitted_generated(_projects()))

    def _stale_result(self, script: Path, stdout: str) -> CheckResult:
        stale = [ln.strip()[2:] for ln in stdout.splitlines() if ln.startswith("  - ")]
        n = str(len(stale)) if stale else "1+"
        return CheckResult(
            check_name=self.name,
            severity=Severity.WARNING,
            message=(
                f"생성된 CLAUDE.md {n}건이 .cursor/rules 와 불일치(stale) — "
                + "; ".join(stale[:5])
            ),
            location=script.parent.parent,
            suggestion=_STALE_REMEDY,
        )

    def _uncommitted_result(self, repos: list[Path]) -> list[CheckResult]:
        if not repos:
            return []
        names = [p.name for p in repos]
        return [
            CheckResult(
                check_name=self.name,
                # INFO — is_blocking 이면 재생성 직후의 짧은 창이 doctor --strict
                # 를 exit 1 로 만들어, 그 값을 소비하는 anvyx C6 pre-run gate 가
                # autopilot 을 막는다. 커밋 누락은 실행을 차단할 사유가 아니다.
                severity=Severity.INFO,
                message=(
                    f"재생성된 CLAUDE.md {len(names)}건이 미커밋 — "
                    + ", ".join(names[:5])
                    + (f" (+{len(names) - 5})" if len(names) > 5 else "")
                    + ". 커밋 전까지 저장소는 옛 룰 인덱스를 든 상태다"
                ),
                location=repos[0] if len(repos) == 1 else None,
                suggestion="각 repo 에서 git add CLAUDE.md && git commit",
            )
        ]

"""codex-bundle-drift check (L2 관측, read-only).

`rbr agent bundle --surface codex` 가 프로젝트에 남긴 `.agents/rbr/manifest.json` 을 읽어
(a) `source.commit` 이 role-based-ruleset clone 의 HEAD 보다 뒤처졌는지, (b) manifest 가 소유한
파일의 sha256 이 바뀌었거나 사라졌는지 관측한다. `AGENTS.md` 는 rbr managed block 만 비교한다
(그 밖의 사용자 본문은 자유). anvyc 는 재배포하지 않는다(단방향, DESIGN §7.7) — 처방은
`rbr agent bundle ... --apply`(또는 `--check` 로 재확인).

계기: 2026-10-22 에이전트 참조 구조 리뷰 — `ruleset-deploy-drift`·`claude-md-freshness` 와 rbr 의
`check_cursor_rules_drift` 모두 `.cursor`·`CLAUDE.md` 만 봐서, Codex 산출물(AGENTS managed block ·
`.agents/rbr` · 네이티브 스킬)은 낡아도 어디서도 신호가 나지 않았다. 같은 날 이 머신엔 번들이 0건이라
문서(8곳 approval_mode)와 실제가 어긋나 있었는데 그것도 보이지 않았다.

manifest 가 한 곳도 없으면 침묵한다(이 머신에 Codex 번들이 없음 — 무오탐). git 실패·commit 미존재는
"모름" 으로 보고하고 뒤처짐 수를 지어내지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.project_discovery import discover_projects

MANIFEST_REL = ".agents/rbr/manifest.json"
_START = "<!-- rbr:codex:start -->"
_END = "<!-- rbr:codex:end -->"


def _rbr_repo() -> Path:
    """role-based-ruleset 로컬 clone (관례: ~/dev/role-based-ruleset)."""
    return Path.home() / "dev" / "role-based-ruleset"


def _git(*args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(_rbr_repo()), *args],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _rbr_head() -> str | None:
    """rbr clone HEAD. 비-git / 오류 → None (commit 비교를 건너뛴다)."""
    return _git("rev-parse", "HEAD")


def _behind(commit: str) -> int | None:
    """manifest 의 source commit 이 rbr HEAD 보다 몇 커밋 뒤인지. 모르는 commit → None."""
    out = _git("rev-list", "--count", f"{commit}..HEAD")
    if out is None:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def _projects() -> list[Path]:
    """관측 대상 프로젝트. discover_projects 위임(테스트 patch 지점)."""
    return discover_projects()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _managed_block(text: str) -> str | None:
    """rbr 이 manifest 에 기록하는 것과 같은 단위 — START..END 블록 + 개행."""
    if text.count(_START) != 1 or text.count(_END) != 1:
        return None
    start, end = text.index(_START), text.index(_END)
    if end < start:
        return None
    return text[start : end + len(_END)] + "\n"


def _current_digest(project: Path, rel: str) -> str | None:
    path = project / rel
    if not path.is_file():
        return None
    if rel == "AGENTS.md":
        block = _managed_block(path.read_text(encoding="utf-8", errors="replace"))
        return None if block is None else _digest(block.encode())
    return _digest(path.read_bytes())


def inspect_bundle(project: Path, head: str | None) -> tuple[str, list[str]] | None:
    """프로젝트 1곳의 번들 상태. manifest 없음 → None. (role, 문제 목록) — 문제 없으면 빈 목록."""
    manifest_path = project / MANIFEST_REL
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest["files"]
        if not isinstance(files, dict):
            raise TypeError("files")
    except (OSError, ValueError, KeyError, TypeError):
        return "?", [f"{MANIFEST_REL} 을 읽을 수 없다(손상 또는 스키마 불일치)"]
    role = str(manifest.get("role") or "?")
    problems: list[str] = []
    source = manifest.get("source") or {}
    commit = str(source.get("commit") or "")
    if head and commit:
        n = _behind(commit)
        if n is None:
            problems.append(f"source commit {commit[:7]} 을 rbr clone 에서 찾지 못함(다른 머신 배포?)")
        elif n > 0:
            problems.append(f"source commit {commit[:7]} 이 rbr HEAD 보다 {n} 커밋 뒤")
    for rel, digest in sorted(files.items()):
        if rel == MANIFEST_REL:
            continue
        current = _current_digest(project, rel)
        if current is None:
            problems.append(f"{rel} 사라짐")
        elif current != digest:
            problems.append(f"{rel} 변경됨")
    if problems and source.get("dirty"):
        problems.append("배포 당시 SoT 가 dirty 였다(commit 만으로 재현 불가)")
    return role, problems


class CodexBundleDriftCheck:
    """L2(read-only): 프로젝트별 Codex 번들(.agents/rbr manifest)이 SoT 기준 낡았거나 손상됐는지."""

    name = "codex-bundle-drift"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        head = _rbr_head()
        results: list[CheckResult] = []
        for project in _projects():
            inspected = inspect_bundle(project, head)
            if inspected is None:
                continue
            role, problems = inspected
            if not problems:
                continue
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"Codex 번들 드리프트 — {project.name}: " + " · ".join(problems),
                    location=project,
                    suggestion=(
                        f"rbr agent bundle --surface codex --role {role} --target {project}"
                        " (dry-run 으로 변경 목록 확인) → --apply → --check 로 재확인"
                    ),
                )
            )
        return results

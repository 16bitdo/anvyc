"""Cross-user 경로 audit check.

DESIGN.md §27.3 참고.

탐지 카테고리:
  1) ~/.cursor/projects/Users-<name>-*  디렉터리 prefix
  2) ~/.cursor/** symlink target 의 /Users/<name>/ 시작
  3) 텍스트 파일 안의 /Users/<name>/ 절대 경로 (regex)
  4) iTerm2 plist 의 profile working directory (Phase 2 / 별도 task)

분류 규칙(요약):
  <name> == current_user                                                      → INFO
  <name> in known_user_aliases AND /Users/<name> 가 current home 으로 resolve → INFO_ALIASED
  /Users/<name> 가 current home 으로 resolve 되지만 alias 선언 X              → WARNING_FOREIGN (선언 제안)
  /Users/<name> 미존재                                                        → WARNING_DANGLING
  <name> 가 실재 다른 user                                                    → WARNING_FOREIGN
"""
from __future__ import annotations

import os
import plistlib
import re
from collections.abc import Iterator
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity

USER_PATH_RE = re.compile(r"/Users/([a-z][a-z0-9_.-]+)")

_TEXT_SUFFIXES = {
    ".json", ".jsonc", ".yaml", ".yml", ".md", ".conf", ".cfg",
    ".ini", ".toml", ".txt", ".sh", ".zsh", ".bash",
}
_MAX_TEXT_SIZE = 1_048_576  # 1 MiB; cross-user 대상 파일은 모두 소형


class CrossUserCheck:
    name = "cross-user"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        results: list[CheckResult] = []
        for target in ctx.scan_targets:
            results.extend(self._scan_target(target, ctx))
        results.extend(self._scan_cursor_symlinks(ctx))
        return results

    # ---------- target dispatch ----------

    def _scan_target(self, target: Path, ctx: CheckContext) -> list[CheckResult]:
        if not target.exists():
            return []
        if target.is_dir():
            if target.name == "projects" and target.parent.name == ".cursor":
                return self._decode_cursor_projects(target, ctx)
            return self._scan_dir_textfiles(target, ctx)
        if target.is_file():
            if target.suffix.lower() == ".plist":
                return self._scan_plist(target, ctx)
            return self._scan_text_file(target, ctx)
        return []

    # ---------- detector 1: ~/.cursor/projects ----------

    def _decode_cursor_projects(self, projects_dir: Path, ctx: CheckContext) -> list[CheckResult]:
        results: list[CheckResult] = []
        for entry in projects_dir.iterdir():
            if not entry.is_dir() or not entry.name.startswith("Users-"):
                continue
            rest = entry.name[len("Users-"):]
            username = rest.split("-", 1)[0]
            severity = self._classify(username, ctx)
            if severity is Severity.INFO:
                continue
            suggestion: str | None = (
                "Cursor projects 캐시는 자동 재생성되므로 백업 대상 아님. "
                "alias 선언 시 INFO_ALIASED 로 강등됨."
                if severity in (Severity.INFO_ALIASED, Severity.WARNING_FOREIGN)
                else None
            )
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=severity,
                    message=f"Cursor project cache references /Users/{username}/",
                    location=entry,
                    suggestion=suggestion,
                )
            )
        return results

    # ---------- detector 2: text content ----------

    def _scan_dir_textfiles(self, dir_path: Path, ctx: CheckContext) -> list[CheckResult]:
        results: list[CheckResult] = []
        try:
            for sub in dir_path.iterdir():
                if sub.is_file() and self._is_text_file(sub):
                    results.extend(self._scan_text_file(sub, ctx))
        except PermissionError:
            pass
        return results

    def _scan_text_file(self, path: Path, ctx: CheckContext) -> list[CheckResult]:
        results: list[CheckResult] = []
        try:
            if path.stat().st_size > _MAX_TEXT_SIZE:
                return []
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, start=1):
                    seen_in_line: set[str] = set()
                    for m in USER_PATH_RE.finditer(line):
                        username = m.group(1)
                        if username in seen_in_line:
                            continue
                        seen_in_line.add(username)
                        severity = self._classify(username, ctx)
                        if severity is Severity.INFO:
                            continue
                        results.append(
                            CheckResult(
                                check_name=self.name,
                                severity=severity,
                                message=f"/Users/{username}/ in {path}",
                                location=path,
                                line=i,
                                suggestion=(
                                    "$HOME 또는 ~/ 형식으로 정규화 권장. "
                                    "alias 선언 시 INFO_ALIASED 로 강등됨."
                                    if severity in (Severity.INFO_ALIASED, Severity.WARNING_FOREIGN)
                                    else None
                                ),
                            )
                        )
        except (OSError, PermissionError):
            pass
        return results

    # ---------- detector 2b: plist content (iTerm2 등) ----------

    def _scan_plist(self, path: Path, ctx: CheckContext) -> list[CheckResult]:
        try:
            with path.open("rb") as f:
                data = plistlib.load(f)
        except (OSError, plistlib.InvalidFileException, ValueError):
            return []
        results: list[CheckResult] = []
        seen: set[tuple[str, str]] = set()  # (username, key_path) — 중복 억제
        for key_path, value in self._walk_plist(data):
            for m in USER_PATH_RE.finditer(value):
                username = m.group(1)
                key = (username, key_path)
                if key in seen:
                    continue
                seen.add(key)
                severity = self._classify(username, ctx)
                if severity is Severity.INFO:
                    continue
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=severity,
                        message=f"/Users/{username}/ in plist key '{key_path}'",
                        location=path,
                        suggestion=(
                            "~/ 또는 $HOME 으로 정규화 권장. iTerm2 Working Directory 같은 "
                            "프로필 필드는 ~ 표기를 지원한다."
                        ),
                    )
                )
        return results

    @staticmethod
    def _walk_plist(data: object, prefix: str = "") -> Iterator[tuple[str, str]]:
        """plist 트리를 walk 하면서 (key_path, str_value) 만 yield."""
        if isinstance(data, dict):
            for k, v in data.items():
                child = f"{prefix}/{k}" if prefix else str(k)
                yield from CrossUserCheck._walk_plist(v, child)
        elif isinstance(data, list):
            for i, v in enumerate(data):
                child = f"{prefix}[{i}]"
                yield from CrossUserCheck._walk_plist(v, child)
        elif isinstance(data, str) and data:
            yield prefix, data
        # 기타 타입 (bool/int/float/datetime/bytes) 은 path 가 들어있지 않음

    # ---------- detector 3: symlink target ----------

    def _scan_cursor_symlinks(self, ctx: CheckContext) -> list[CheckResult]:
        cursor_dir = Path("~/.cursor").expanduser()
        if not cursor_dir.exists():
            return []
        results: list[CheckResult] = []
        for root, dirs, files in os.walk(cursor_dir, followlinks=False):
            depth = len(Path(root).relative_to(cursor_dir).parts)
            if depth >= 3:
                dirs[:] = []
            for entry_name in list(dirs) + list(files):
                p = Path(root) / entry_name
                if not p.is_symlink():
                    continue
                try:
                    target = os.readlink(p)
                except OSError:
                    continue
                m = USER_PATH_RE.match(target)
                if not m:
                    continue
                username = m.group(1)
                severity = self._classify(username, ctx)
                if severity is Severity.INFO:
                    continue
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=severity,
                        message=f"symlink {p} → {target}",
                        location=p,
                        suggestion=(
                            "symlink 대상이 다른 사용자 home. "
                            "Cursor adapter 의 follow_symlinks=false 정책으로 백업 대상 아님."
                        ),
                    )
                )
        return results

    # ---------- helpers ----------

    @staticmethod
    def _is_text_file(path: Path) -> bool:
        if path.suffix.lower() in _TEXT_SUFFIXES:
            return True
        # extensionless ssh config, .gitconfig 등
        return not path.suffix

    @staticmethod
    def _classify(username: str, ctx: CheckContext) -> Severity:
        if username == ctx.current_user:
            return Severity.INFO

        candidate = Path(f"/Users/{username}")
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            resolved = candidate

        resolves_to_current = str(resolved) == f"/Users/{ctx.current_user}"

        if username in ctx.known_user_aliases:
            return Severity.INFO_ALIASED if resolves_to_current else Severity.WARNING_FOREIGN

        if resolves_to_current:
            # alias 동작은 있으나 사용자가 명시 선언 X → 선언 권유
            return Severity.WARNING_FOREIGN

        if not candidate.exists():
            return Severity.WARNING_DANGLING

        return Severity.WARNING_FOREIGN

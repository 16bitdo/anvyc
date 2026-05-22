"""Claude Code adapter — `~/.claude/` 의 설정/규칙/플러그인 백업.

DESIGN.md §16 기반. 디렉터리 재귀 + pathspec gitignore-style exclude 로
sessions/tokens/cache/projects 등 민감 또는 휘발성 영역을 차단.

INCLUDES 는 TOOL_ROOT (`~/.claude/`) 기준 상대 경로. 디렉터리면 재귀 수집.
EXCLUDES 는 pathspec(gitignore) 패턴, 같은 root 기준.
"""
from __future__ import annotations

from pathlib import Path

from pathspec import PathSpec

from anvyc.adapters.base import ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile

TOOL_ROOT = Path("~/.claude").expanduser()

DEFAULT_INCLUDES: tuple[str, ...] = (
    "settings.json",
    "keybindings.json",
    "CLAUDE.md",
    "file-suggestion.sh",
    ".env.template",
    ".statusline.config",
    "hooks",
    "plugins",
    "plans",
)

# gitignore-style. relpath 가 TOOL_ROOT 기준이어야 함.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    # 세션/대화/캐시 — 개인정보·휘발성
    "sessions",
    "sessions/**",
    "tokens",
    "tokens/**",
    "cache",
    "cache/**",
    "logs",
    "logs/**",
    "conversations",
    "conversations/**",
    "history.jsonl",
    "projects",
    "projects/**",
    "session-env",
    "session-env/**",
    "shell-snapshots",
    "shell-snapshots/**",
    "file-history",
    "file-history/**",
    "ide",
    "ide/**",
    "backups",
    "backups/**",
    # 기기/세션별 runtime 상태
    ".last-cleanup",
    ".statusline-alarm-state",
    ".statusline-alarm-state.bak-*",
    "mcp-needs-auth-cache.json",
    "remote-settings.json",
    # 토큰 포함 가능성 / machine-specific
    "config.json",
    "settings.local.json",
    "settings.json.bak-*",
    # 외부 marketplace clone (재현 가능, 용량)
    "plugins/marketplaces",
    "plugins/marketplaces/**",
)


class ClaudeAdapter:
    name = "claude"

    def __init__(
        self,
        includes: tuple[str, ...] | list[str] | None = None,
        excludes: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        if includes:
            self._includes = tuple(self._normalize(includes))
        else:
            self._includes = DEFAULT_INCLUDES
        if excludes:
            # 사용자 yaml 값은 절대/`~` 형식일 수 있음 — 정규화
            self._excludes = tuple(self._normalize(excludes)) + DEFAULT_EXCLUDES
        else:
            self._excludes = DEFAULT_EXCLUDES
        self._spec = PathSpec.from_lines("gitignore", self._excludes)

    def detect(self) -> bool:
        return TOOL_ROOT.exists()

    def collect(self) -> list[ManagedFile]:
        out: list[ManagedFile] = []
        for rel in self._includes:
            p = TOOL_ROOT / rel
            if p.is_file():
                if not self._spec.match_file(rel):
                    out.append(self._make_managed(p, rel))
            elif p.is_dir():
                for f in p.rglob("*"):
                    if not f.is_file():
                        continue
                    try:
                        rel_f = str(f.relative_to(TOOL_ROOT))
                    except ValueError:
                        continue
                    if self._spec.match_file(rel_f):
                        continue
                    out.append(self._make_managed(f, rel_f))
        return out

    def exclude(self) -> list[str]:
        return list(self._excludes)

    def validate(self) -> list[CheckResult]:
        return []

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def target_hash(self, target: Path) -> str:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError

    # ---------- helpers ----------

    @staticmethod
    def _make_managed(abs_path: Path, relpath: str) -> ManagedFile:
        return ManagedFile(
            tool="claude",
            source_path=abs_path,
            target_path=Path("~/.claude") / relpath,
            mode=abs_path.stat().st_mode & 0o777,
            relpath=relpath,
        )

    @staticmethod
    def _normalize(paths: tuple[str, ...] | list[str]) -> list[str]:
        """yaml 의 절대/`~` 경로를 TOOL_ROOT 기준 상대로 변환. 외부 경로는 무시."""
        out: list[str] = []
        for p in paths:
            pp = Path(p).expanduser()
            try:
                out.append(str(pp.relative_to(TOOL_ROOT)))
            except ValueError:
                # 이미 상대 경로이거나 TOOL_ROOT 밖. pathspec 매칭용은 그대로 사용.
                out.append(p)
        return out

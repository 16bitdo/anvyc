"""Cursor IDE adapter — 3 layer 모델.

DESIGN.md §15 기반.
  Layer A (Global): ~/.cursor/ — rules/skills/mcp/plugins
  Layer B (IDE):    ~/Library/Application Support/Cursor/User/ — settings/keybindings/snippets/profiles
  Layer C (Project, opt-in): <repo>/.cursor/ — 사용자가 yaml 에 명시한 root 들

Symlinks: follow=false, ManagedFile.symlink_target 으로 metadata 만 기록.
mcp.json: v0.1.0 은 scanner 차단만 (mask_mcp_tokens 옵션 인식, 실 동작은 v0.2).
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from pathspec import PathSpec

from anvyc.adapters.base import ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile

GLOBAL_CANONICAL = "~/.cursor"
IDE_CANONICAL = "~/Library/Application Support/Cursor/User"
GLOBAL_ROOT = Path(GLOBAL_CANONICAL).expanduser()
IDE_ROOT = Path(IDE_CANONICAL).expanduser()

# Layer A — ~/.cursor/
DEFAULT_GLOBAL_INCLUDES: tuple[str, ...] = (
    "rules",
    "skills",
    "skills-cursor",
    "mcp.json",
    "plugins",
    "plans",
)

DEFAULT_GLOBAL_EXCLUDES: tuple[str, ...] = (
    # 0600 perms / 토큰 가능성
    "cli-config.json",
    "argv.json",
    "ide_state.json",
    "prompt_history.json",
    "config.json",
    # 기기/세션 캐시
    "extensions",
    "extensions/**",
    "projects",
    "projects/**",
    "workers",
    "workers/**",
    "ai-tracking",
    "ai-tracking/**",
    "chats",
    "chats/**",
    "plugins/cache",
    "plugins/cache/**",
    # marketplaces clone (재현 가능, 4M+)
    "plugins/marketplaces",
    "plugins/marketplaces/**",
    # backup 사본
    "rules.bak-*",
    "rules.bak-*/**",
    # 메타
    ".gitignore",
    ".last-cleanup",
)

# Layer B — Library/User/
DEFAULT_IDE_INCLUDES: tuple[str, ...] = (
    "settings.json",
    "keybindings.json",
    "snippets",
    "profiles",
)

DEFAULT_IDE_EXCLUDES: tuple[str, ...] = (
    "workspaceStorage",
    "workspaceStorage/**",
    "History",
    "History/**",
    "globalStorage",       # allowlist 외 전부 — 별도 처리 (_collect_global_storage)
    "globalStorage/**",
    "logs",
    "logs/**",
    "*.bak",
    "keybindings.json.*.bak",
    # profiles 내부 캐시
    "profiles/*/State",
    "profiles/*/State/**",
    "profiles/*/logs",
    "profiles/*/logs/**",
    "profiles/*/workspaceStorage",
    "profiles/*/workspaceStorage/**",
    "profiles/*/History",
    "profiles/*/History/**",
    "profiles/*/globalStorage",
    "profiles/*/globalStorage/**",
)

# globalStorage allowlist 와 무관하게 항상 제외
GLOBAL_STORAGE_ALWAYS_EXCLUDE: tuple[str, ...] = (
    "state.vscdb",
    "state.vscdb-shm",
    "state.vscdb-wal",
    "state.vscdb.backup",
    "state.vscdb.backup.*",
    "state.vscdb.options.json",
)

# Layer C — project local
DEFAULT_PROJECT_PATTERNS: tuple[str, ...] = (
    ".cursor/rules",
    ".cursor/skills",
    ".cursor/mcp.json",
    ".cursorrules",
)


class CursorAdapter:
    name = "cursor"

    def __init__(
        self,
        global_cfg: dict | None = None,
        ide_cfg: dict | None = None,
        projects_cfg: dict | None = None,
    ) -> None:
        self.global_cfg = global_cfg or {}
        self.ide_cfg = ide_cfg or {}
        self.projects_cfg = projects_cfg or {}

        self._global_includes = self._normalize_includes(
            self.global_cfg.get("include"), GLOBAL_ROOT, DEFAULT_GLOBAL_INCLUDES
        )
        self._global_spec = self._build_spec(
            self.global_cfg.get("exclude"), GLOBAL_ROOT, DEFAULT_GLOBAL_EXCLUDES
        )
        self._ide_includes = self._normalize_includes(
            self.ide_cfg.get("include"), IDE_ROOT, DEFAULT_IDE_INCLUDES
        )
        self._ide_spec = self._build_spec(
            self.ide_cfg.get("exclude"), IDE_ROOT, DEFAULT_IDE_EXCLUDES
        )
        self._gs_allow = list(self.ide_cfg.get("global_storage_allowlist") or [])
        self._gs_always_excl_spec = PathSpec.from_lines(
            "gitwildmatch", GLOBAL_STORAGE_ALWAYS_EXCLUDE
        )

    # ---------- public ----------

    def detect(self) -> bool:
        return GLOBAL_ROOT.exists() or IDE_ROOT.exists()

    def collect(self) -> list[ManagedFile]:
        out: list[ManagedFile] = []
        out.extend(
            self._collect_layer(
                GLOBAL_ROOT, GLOBAL_CANONICAL, self._global_includes, self._global_spec, "global"
            )
        )
        out.extend(
            self._collect_layer(
                IDE_ROOT, IDE_CANONICAL, self._ide_includes, self._ide_spec, "ide"
            )
        )
        if self._gs_allow:
            out.extend(self._collect_global_storage())
        if self.projects_cfg.get("enabled"):
            out.extend(self._collect_projects())
        return out

    def exclude(self) -> list[str]:
        out: list[str] = []
        out.extend(f"{GLOBAL_ROOT}/{p}" for p in DEFAULT_GLOBAL_EXCLUDES if "*" not in p)
        out.extend(f"{IDE_ROOT}/{p}" for p in DEFAULT_IDE_EXCLUDES if "*" not in p)
        return out

    def validate(self) -> list[CheckResult]:
        return []

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        # default copy 로 충분 — Layer A/B/C 파일은 모두 평면 복사. symlink 는
        # apply.py 의 _apply_symlink 가 처리하므로 여기에 도달하지 않는다.
        raise NotImplementedError

    # ---------- Layer A / B 공용 ----------

    def _collect_layer(
        self,
        root: Path,
        canonical: str,
        includes: tuple[str, ...],
        spec: PathSpec,
        ns: str,
    ) -> list[ManagedFile]:
        out: list[ManagedFile] = []
        for inc in includes:
            p = root / inc
            if p.is_symlink():
                out.append(self._make_symlink(p, root, canonical, ns))
                continue
            if p.is_file():
                rel = inc
                if spec.match_file(rel):
                    continue
                out.append(self._make_file(p, canonical, rel, ns))
            elif p.is_dir():
                for entry in self._walk(p):
                    try:
                        rel = str(entry.relative_to(root))
                    except ValueError:
                        continue
                    if spec.match_file(rel):
                        continue
                    if entry.is_symlink():
                        out.append(self._make_symlink(entry, root, canonical, ns))
                    elif entry.is_file():
                        out.append(self._make_file(entry, canonical, rel, ns))
        return out

    def _collect_global_storage(self) -> list[ManagedFile]:
        """globalStorage allowlist 가 명시된 extension 디렉터리만 포함."""
        out: list[ManagedFile] = []
        gs_root = IDE_ROOT / "globalStorage"
        if not gs_root.is_dir():
            return out
        for ext_id in self._gs_allow:
            ext_dir = gs_root / ext_id
            if not ext_dir.is_dir():
                continue
            for entry in self._walk(ext_dir):
                try:
                    rel = str(entry.relative_to(IDE_ROOT))  # "globalStorage/<ext>/..."
                except ValueError:
                    continue
                rel_under_gs = str(entry.relative_to(gs_root))  # "<ext>/..."
                if self._gs_always_excl_spec.match_file(rel_under_gs):
                    continue
                if entry.is_symlink():
                    out.append(self._make_symlink(entry, IDE_ROOT, IDE_CANONICAL, "ide"))
                elif entry.is_file():
                    out.append(self._make_file(entry, IDE_CANONICAL, rel, "ide"))
        return out

    # ---------- Layer C ----------

    def _collect_projects(self) -> list[ManagedFile]:
        out: list[ManagedFile] = []
        roots = self.projects_cfg.get("roots") or []
        patterns = self.projects_cfg.get("patterns") or list(DEFAULT_PROJECT_PATTERNS)
        for raw_root in roots:
            root_abs = Path(raw_root).expanduser()
            if not root_abs.is_dir():
                continue
            project_name = root_abs.name  # C4=(a): root last segment
            for pat in patterns:
                p = root_abs / pat
                if not p.exists() and not p.is_symlink():
                    continue
                if p.is_symlink():
                    out.append(
                        self._make_project_symlink(p, root_abs, raw_root, project_name, pat)
                    )
                    continue
                if p.is_file():
                    out.append(
                        self._make_project_file(p, raw_root, project_name, pat)
                    )
                elif p.is_dir():
                    for entry in self._walk(p):
                        try:
                            pat_rel = str(entry.relative_to(root_abs))
                        except ValueError:
                            continue
                        if entry.is_symlink():
                            out.append(
                                self._make_project_symlink(
                                    entry, root_abs, raw_root, project_name, pat_rel
                                )
                            )
                        elif entry.is_file():
                            out.append(
                                self._make_project_file(entry, raw_root, project_name, pat_rel)
                            )
        return out

    # ---------- helpers: walk + ManagedFile 생성 ----------

    @staticmethod
    def _walk(root: Path) -> Iterator[Path]:
        """root 하위를 순회. dir 은 yield X, symlink 와 file 만 yield. symlink 안으로는 들어가지 않는다."""
        stack: list[Path] = [root]
        while stack:
            d = stack.pop()
            try:
                for child in d.iterdir():
                    if child.is_symlink():
                        yield child
                    elif child.is_dir():
                        stack.append(child)
                    else:
                        yield child
            except (OSError, PermissionError):
                continue

    @staticmethod
    def _make_file(abs_path: Path, canonical: str, rel: str, ns: str) -> ManagedFile:
        return ManagedFile(
            tool="cursor",
            source_path=abs_path,
            target_path=Path(canonical) / rel,
            mode=abs_path.stat().st_mode & 0o777,
            relpath=f"{ns}/{rel}",
        )

    @staticmethod
    def _make_symlink(abs_path: Path, root: Path, canonical: str, ns: str) -> ManagedFile:
        try:
            rel = str(abs_path.relative_to(root))
        except ValueError:
            rel = abs_path.name
        try:
            target = os.readlink(abs_path)
        except OSError:
            target = ""
        return ManagedFile(
            tool="cursor",
            source_path=abs_path,
            target_path=Path(canonical) / rel,
            mode=0o777,
            relpath=f"{ns}/{rel}",
            symlink_target=target,
        )

    @staticmethod
    def _make_project_file(
        abs_path: Path, raw_root: str, project_name: str, pat_rel: str
    ) -> ManagedFile:
        return ManagedFile(
            tool="cursor",
            source_path=abs_path,
            target_path=Path(raw_root) / pat_rel,
            mode=abs_path.stat().st_mode & 0o777,
            relpath=f"projects/{project_name}/{pat_rel}",
        )

    @staticmethod
    def _make_project_symlink(
        abs_path: Path, root_abs: Path, raw_root: str, project_name: str, pat_rel: str
    ) -> ManagedFile:
        try:
            target = os.readlink(abs_path)
        except OSError:
            target = ""
        return ManagedFile(
            tool="cursor",
            source_path=abs_path,
            target_path=Path(raw_root) / pat_rel,
            mode=0o777,
            relpath=f"projects/{project_name}/{pat_rel}",
            symlink_target=target,
        )

    # ---------- config normalize ----------

    @staticmethod
    def _normalize_includes(
        raw: list[str] | tuple[str, ...] | None,
        root: Path,
        defaults: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not raw:
            return defaults
        out: list[str] = []
        for s in raw:
            p = Path(s).expanduser()
            try:
                out.append(str(p.relative_to(root)))
            except ValueError:
                out.append(s)
        return tuple(out)

    @staticmethod
    def _build_spec(
        raw: list[str] | tuple[str, ...] | None,
        root: Path,
        defaults: tuple[str, ...],
    ) -> PathSpec:
        # yaml exclude 의 절대 경로를 root 기준 상대 패턴으로 정규화
        patterns = list(defaults)
        if raw:
            for s in raw:
                p = Path(s).expanduser()
                try:
                    patterns.append(str(p.relative_to(root)))
                except ValueError:
                    patterns.append(s)
        return PathSpec.from_lines("gitwildmatch", patterns)

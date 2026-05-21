"""dev_env adapter — 프로젝트 root 의 dev-env 설정 파일 추적 (v0.7.0).

추적 패턴 (default):
- `.envrc`            — direnv (AWS_PROFILE / NODE_ENV / API_URL 등)
- `.tool-versions`    — asdf
- `.python-version`   — pyenv
- `.nvmrc`            — nvm

수집 범위는 `project_roots` (default: SoT — `~/dev` 등 표준 루트) 아래 depth ≤ 3.
node_modules / .venv 같은 빌드 산출물은 기본 제외.

target_path 는 실제 파일의 절대 경로 그대로 — apply 시 동일 경로로 복원.
머신 간 home directory layout 이 다를 경우 cross-user check 가 잡는다.
"""
from __future__ import annotations

from pathlib import Path

from pathspec import PathSpec

from anvyc.adapters.base import ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile
from anvyc.core.project_roots import DEFAULT_PROJECT_ROOTS

DEFAULT_PATTERNS: tuple[str, ...] = (
    ".envrc",
    ".tool-versions",
    ".python-version",
    ".nvmrc",
)
DEFAULT_EXCLUDE: tuple[str, ...] = (
    "**/node_modules/**",
    "**/.venv/**",
    "**/venv/**",
    "**/.git/**",
    "**/__pycache__/**",
)
_DEFAULT_MAX_DEPTH = 3


class DevEnvAdapter:
    name = "dev_env"

    def __init__(
        self,
        project_roots: tuple[str, ...] | None = None,
        patterns: tuple[str, ...] | None = None,
        excludes: tuple[str, ...] | None = None,
        max_depth: int = _DEFAULT_MAX_DEPTH,
    ) -> None:
        self._project_roots = project_roots or DEFAULT_PROJECT_ROOTS
        self._patterns = patterns or DEFAULT_PATTERNS
        self._excludes = excludes or DEFAULT_EXCLUDE
        self._max_depth = max_depth
        self._exclude_spec = PathSpec.from_lines("gitignore", self._excludes)

    def detect(self) -> bool:
        return any(Path(r).expanduser().is_dir() for r in self._project_roots)

    def collect(self) -> list[ManagedFile]:
        out: list[ManagedFile] = []
        seen: set[Path] = set()
        for root_str in self._project_roots:
            root = Path(root_str).expanduser()
            if not root.is_dir():
                continue
            for pattern in self._patterns:
                for found in root.rglob(pattern):
                    try:
                        rel = found.relative_to(root)
                    except ValueError:
                        continue
                    # depth 제한
                    if len(rel.parts) > self._max_depth:
                        continue
                    # exclude 매칭 (root 기준 relpath)
                    if self._exclude_spec.match_file(str(rel)):
                        continue
                    if not found.is_file():
                        continue
                    if found in seen:
                        continue
                    seen.add(found)
                    out.append(
                        ManagedFile(
                            tool=self.name,
                            source_path=found,
                            target_path=Path(str(found).replace(str(Path.home()), "~", 1)),
                            mode=found.stat().st_mode & 0o777,
                        )
                    )
        return sorted(out, key=lambda mf: str(mf.source_path))

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

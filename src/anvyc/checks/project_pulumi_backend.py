"""project-pulumi-backend-mapping check.

프로젝트 루트(`project_roots`) 아래 `Pulumi.yaml` 의 `backend.url` 과 같은
디렉터리 `.envrc` 의 `PULUMI_BACKEND_URL` 이 일치하는지 검증한다.

per-project Pulumi routing: `Pulumi.yaml` 의 `backend.url` 이 state backend
(org/account) 를 결정하고, `.envrc` 의 `PULUMI_BACKEND_URL` 은 env override 다.
둘 다 선언되면 일치해야 한다 (2-way 정합성).

`project-gh-account-mapping` 패턴:
- backend 선언 project 가 모두 일치 → INFO 1건 (summary)
- 불일치 → 각 project 마다 WARNING (location = Pulumi.yaml)
- backend / PULUMI_BACKEND_URL 둘 다 선언 안 한 project 만 있음 → 결과 0건 (silent)
"""

from __future__ import annotations

import re
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.project_roots import resolve_project_roots
from anvyc.utils.pulumi_project import detect_pulumi_project, normalize_backend_url

_MAX_DEPTH = 3  # <root>/<group>/<project>/Pulumi.yaml 까지

# 한 줄에 `export PULUMI_BACKEND_URL=foo` 또는 `="foo"` 매칭 (project_gh_account 패턴).
_PULUMI_BACKEND_URL_RE = re.compile(
    r"""^\s*export\s+PULUMI_BACKEND_URL\s*=\s*['"]?([^'"\s#]+)""",
    re.MULTILINE,
)


def _iter_pulumi_yaml(root: Path, max_depth: int = _MAX_DEPTH) -> list[Path]:
    """root 아래 max_depth 까지 `Pulumi.yaml` 파일 수집."""
    if not root.is_dir():
        return []
    out: list[Path] = []
    try:
        for p in root.rglob("Pulumi.yaml"):
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) > max_depth:
                continue
            if p.is_file():
                out.append(p)
    except (OSError, PermissionError):
        return []
    return sorted(out)


def _read_envrc_pulumi_backend(envrc: Path) -> str | None:
    """`.envrc` 의 첫 `export PULUMI_BACKEND_URL=X` 라인 → raw 값. 부재 → None."""
    try:
        text = envrc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _PULUMI_BACKEND_URL_RE.search(text)
    return m.group(1) if m else None


class ProjectPulumiBackendMappingCheck:
    name = "project-pulumi-backend-mapping"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        yaml_files: list[Path] = []
        seen: set[Path] = set()
        for root_str in resolve_project_roots():
            root = Path(root_str).expanduser()
            for y in _iter_pulumi_yaml(root):
                try:
                    key = y.resolve()
                except OSError:
                    key = y
                if key in seen:
                    continue
                seen.add(key)
                yaml_files.append(y)

        # backend (Pulumi.yaml) 또는 PULUMI_BACKEND_URL (.envrc) 을 선언한 project 만 대상.
        targets: list[tuple[Path, str | None, str | None]] = []
        for yaml_path in yaml_files:
            project_dir = yaml_path.parent
            info = detect_pulumi_project(project_dir)
            yaml_backend = info.backend_url if info else None
            envrc = project_dir / ".envrc"
            envrc_backend = (
                _read_envrc_pulumi_backend(envrc) if envrc.is_file() else None
            )
            if yaml_backend or envrc_backend:
                targets.append((project_dir, yaml_backend, envrc_backend))

        if not targets:
            return []

        mismatch: list[tuple[Path, str, str]] = []
        for project_dir, yaml_backend, envrc_backend in targets:
            if (
                yaml_backend
                and envrc_backend
                and normalize_backend_url(yaml_backend)
                != normalize_backend_url(envrc_backend)
            ):
                mismatch.append((project_dir, yaml_backend, envrc_backend))

        if mismatch:
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"Pulumi.yaml backend '{yaml_backend}' 가 "
                        f".envrc PULUMI_BACKEND_URL '{envrc_backend}' 와 불일치"
                    ),
                    location=project_dir / "Pulumi.yaml",
                    suggestion=(
                        "Pulumi.yaml 의 backend.url 과 .envrc 의 PULUMI_BACKEND_URL 을 "
                        "동일 backend 로 맞추세요."
                    ),
                )
                for project_dir, yaml_backend, envrc_backend in mismatch
            ]
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.INFO,
                message=(
                    f"Pulumi backend 선언 project {len(targets)}개 → "
                    "Pulumi.yaml ↔ .envrc PULUMI_BACKEND_URL 불일치 없음"
                ),
            )
        ]

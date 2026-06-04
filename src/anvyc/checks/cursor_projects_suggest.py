"""cursor-projects-suggest check.

Q3 결정 (DESIGN.md §29.6): 사용자의 candidate root 디렉터리들을 스캔해 `.cursor/`
디렉터리가 있는 프로젝트를 발견하면 INFO 로 안내한다. 자동 추가는 하지 않고,
사용자가 anvyc.yaml 의 `cursor.projects.roots` 에 직접 추가하도록 권장.

이미 roots 에 등록된 프로젝트는 결과에서 제외한다.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity

_MAX_DETAILS = 10  # 한 번에 표시할 sample 개수 — 그 이상은 summary 만


class CursorProjectsSuggestCheck:
    name = "cursor-projects-suggest"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        from anvyc.core.config import load_anvyc_config
        from anvyc.core.project_scope import iter_project_dirs

        # 이미 등록된 roots 추출 (중복 제안 회피)
        registered: set[Path] = set()
        try:
            cfg = load_anvyc_config()
            cursor_cfg = cfg.tools.get("cursor")
            if cursor_cfg is not None:
                projects = cursor_cfg.extra.get("projects") or {}
                for r in projects.get("roots") or []:
                    try:
                        registered.add(Path(r).expanduser().resolve())
                    except OSError:
                        continue
        except Exception:
            # config 로드 실패해도 check 는 계속 — registered 가 비어있을 뿐
            pass

        # candidate roots 스캔 (config-aware + excludes honoring)
        discovered: list[Path] = []
        for entry in iter_project_dirs(markers=(".cursor",), max_depth=1):
            try:
                resolved = entry.resolve()
            except OSError:
                continue
            if resolved in registered:
                continue
            discovered.append(entry)

        if not discovered:
            return []

        # 정렬: candidate 순서 유지 + 이름 기준
        discovered = sorted(set(discovered), key=lambda p: (str(p.parent), p.name))

        # 개별 INFO 발행 (top _MAX_DETAILS 까지), 그 다음 summary
        results: list[CheckResult] = []
        for project_root in discovered[:_MAX_DETAILS]:
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=f"cursor project 발견 (미등록): {project_root}",
                    location=project_root,
                    suggestion=(
                        f'anvyc.yaml 의 cursor.projects.roots 에 추가: "{project_root}"'
                    ),
                )
            )
        if len(discovered) > _MAX_DETAILS:
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"... and {len(discovered) - _MAX_DETAILS} more cursor projects "
                        f"(총 {len(discovered)}개)"
                    ),
                    suggestion=(
                        "전체 보기: anvyc doctor --only cursor-projects-suggest --verbose"
                    ),
                )
            )
        return results

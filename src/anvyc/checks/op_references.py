"""op-references-valid check.

scan_targets 안의 파일에서 발견된 op:// reference (1Password Secret Reference) 가
실제로 resolve 가능한지 확인한다.

조건:
  - `op` CLI 가 설치돼 있고
  - `op whoami` 가 성공 (signin 세션 유효)
  - 위 두 조건 미충족 시 check skip — INFO 도 발행하지 않는다 (사용자 환경 의존이 큼)

resolve 시도:
  - `op read --no-newline <uri>` 의 exit code 만 본다 (stdout 값은 버린다)
  - 실패 reference 1건당 WARNING

DESIGN.md §30 / §27 참고.
"""
from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.extras import is_available
from anvyc.security.scanner import extract_op_references

_OP_TIMEOUT_S = 6


def _op_available() -> bool:
    if not is_available("op"):
        return False
    try:
        result = subprocess.run(
            ["op", "whoami"],
            capture_output=True,
            timeout=_OP_TIMEOUT_S,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _op_resolves(uri: str) -> bool:
    try:
        result = subprocess.run(
            ["op", "read", "--no-newline", uri],
            capture_output=True,
            timeout=_OP_TIMEOUT_S,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _iter_scan_files(target: Path) -> Iterator[Path]:
    """scan_target 가 파일이면 자체, 디렉터리면 1단계 텍스트류 파일."""
    if target.is_file():
        yield target
        return
    if target.is_dir():
        try:
            for sub in target.iterdir():
                if sub.is_file():
                    yield sub
        except (OSError, PermissionError):
            return


class OpReferencesCheck:
    name = "op-references-valid"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        if not _op_available():
            return []

        # 중복 제거를 위해 (uri, path, line) 단위 캐시 + uri 단위 캐시
        seen: set[tuple[str, str, int]] = set()
        resolve_cache: dict[str, bool] = {}
        results: list[CheckResult] = []

        for target in ctx.scan_targets:
            try:
                if not target.exists():
                    continue
            except OSError:
                continue
            for path in _iter_scan_files(target):
                for line, uri in extract_op_references(path):
                    key = (uri, str(path), line)
                    if key in seen:
                        continue
                    seen.add(key)
                    if uri in resolve_cache:
                        ok = resolve_cache[uri]
                    else:
                        ok = _op_resolves(uri)
                        resolve_cache[uri] = ok
                    if ok:
                        continue
                    results.append(
                        CheckResult(
                            check_name=self.name,
                            severity=Severity.WARNING,
                            message=f"op:// reference 가 resolve 되지 않음: {uri}",
                            location=path,
                            line=line,
                            suggestion=(
                                "1Password 에 해당 vault/item/field 가 존재하는지 확인. "
                                "필요 시 `op signin` 후 재시도."
                            ),
                        )
                    )
        return results

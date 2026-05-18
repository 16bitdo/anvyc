"""venv-hidden-flag check.

macOS 에서 `.`-prefix 디렉터리(`.venv` 등)에 UF_HIDDEN file flag 가 붙으면
Python 3.13 의 site.py 가 그 안의 모든 .pth 파일을 스킵한다 →
editable install (`pip install -e .`) 의 `_editable_impl_*.pth` 가 무시되어
`import <package>` 가 ModuleNotFoundError 로 실패한다.

참고: https://github.com/python/cpython/issues/116727

해결: `chflags -R nohidden <venv-dir>` — doctor 가 안내한다.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity


class VenvHiddenFlagCheck:
    name = "venv-hidden-flag"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        if sys.platform != "darwin":
            return []
        venv_root = self._venv_root()
        if venv_root is None:
            return []

        problematic: list[Path] = []
        candidates: list[Path] = [venv_root]
        lib_dir = venv_root / "lib"
        if lib_dir.exists():
            candidates.append(lib_dir)
            candidates.extend(p for p in lib_dir.glob("python*") if p.is_dir())
        for py_dir in list(candidates):
            sp = py_dir / "site-packages"
            if sp.is_dir():
                candidates.append(sp)
                candidates.extend(sp.glob("*.pth"))

        seen: set[Path] = set()
        for c in candidates:
            try:
                rp = c.resolve(strict=False)
            except OSError:
                continue
            if rp in seen:
                continue
            seen.add(rp)
            if self._is_hidden(c):
                problematic.append(c)

        if not problematic:
            return []

        # 한 venv 안에서 여러 항목이 hidden 이면 대표 1건만 보고하고 root 수정 제안.
        head = problematic[0]
        suggestion = (
            f"chflags -R nohidden {venv_root} "
            "→ Python 3.13 의 site.py 가 .pth 를 다시 읽도록 한다."
        )
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                message=(
                    f"venv {venv_root.name} 에 macOS UF_HIDDEN flag — "
                    f".pth {len(problematic)}건 site.py 가 무시 → editable install 깨짐"
                ),
                location=head,
                suggestion=suggestion,
            )
        ]

    @staticmethod
    def _venv_root() -> Path | None:
        """현재 인터프리터가 venv 안이면 그 root 반환."""
        if getattr(sys, "real_prefix", None) is not None:
            return Path(sys.prefix)
        if sys.prefix != sys.base_prefix:
            return Path(sys.prefix)
        return None

    @staticmethod
    def _is_hidden(path: Path) -> bool:
        try:
            st = path.stat()
        except OSError:
            return False
        flags = getattr(st, "st_flags", 0)
        return bool(flags & stat.UF_HIDDEN)

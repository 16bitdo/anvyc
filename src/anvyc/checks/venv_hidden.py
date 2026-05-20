"""venv-hidden-flag check.

macOS 에서 `.`-prefix 디렉터리(`.venv` 등)에 UF_HIDDEN file flag 가 붙으면
Python 3.13 의 site.py 가 그 안의 모든 .pth 파일을 스킵한다 →
editable install (`pip install -e .`) 의 `_editable_impl_*.pth` 가 무시되어
`import <package>` 가 ModuleNotFoundError 로 실패한다.

참고: https://github.com/python/cpython/issues/116727

임시 해결: `chflags -R nohidden <venv-dir>`. 단 macOS 백그라운드 프로세스가
flag 를 주기적으로 재적용하므로 1회 chflags 로는 영구 해결이 안 된다.
영구 해결: 호출 시점마다 `chflags nohidden` 후 exec 하는 wrapper script.
상세: docs/troubleshooting-macos.md
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity

# editable install 이 site-packages 에 남기는 .pth shim 의 파일명 prefix.
# hatchling: `_editable_impl_<name>.pth`, setuptools: `__editable__.<name>-<ver>.pth`
_EDITABLE_SHIM_PREFIXES = ("_editable_impl_", "__editable__")


class VenvHiddenFlagCheck:
    name = "venv-hidden-flag"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        if sys.platform != "darwin":
            return []
        venv_root = self._venv_root()
        if venv_root is None:
            return []

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

        # editable shim 과 그 외(일반 .pth / 디렉터리) 를 분리 — message 정확도.
        editable_hidden: list[Path] = []
        other_hidden: list[Path] = []
        seen: set[Path] = set()
        for c in candidates:
            try:
                rp = c.resolve(strict=False)
            except OSError:
                continue
            if rp in seen:
                continue
            seen.add(rp)
            if not self._is_hidden(c):
                continue
            if self._is_editable_shim(c):
                editable_hidden.append(c)
            else:
                other_hidden.append(c)

        if not editable_hidden and not other_hidden:
            return []

        # 한 venv 안에서 여러 항목이 hidden 이면 대표 1건만 보고 — editable shim 우선.
        if editable_hidden:
            location = editable_hidden[0]
            message = (
                f"venv {venv_root.name} 에 macOS UF_HIDDEN flag — "
                f"editable shim .pth {len(editable_hidden)}건 site.py 가 무시 "
                "→ editable install (import) 깨짐"
            )
        else:
            location = other_hidden[0]
            message = (
                f"venv {venv_root.name} 에 macOS UF_HIDDEN flag — "
                f".pth {len(other_hidden)}건 site.py 가 무시될 수 있음"
            )

        suggestion = (
            f"chflags -R nohidden {venv_root} (임시 — macOS 백그라운드가 "
            "hidden flag 를 재적용함). 영구 해법: 호출 시 chflags nohidden 후 "
            "exec 하는 wrapper script. 상세: docs/troubleshooting-macos.md"
        )
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                message=message,
                location=location,
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

    @staticmethod
    def _is_editable_shim(path: Path) -> bool:
        """editable install 이 만든 .pth shim 인지 (hatchling/setuptools)."""
        return path.suffix == ".pth" and path.name.startswith(_EDITABLE_SHIM_PREFIXES)

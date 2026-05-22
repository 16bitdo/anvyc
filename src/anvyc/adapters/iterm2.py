"""iTerm2 adapter — plist 의 safe subset 만 추출/적용.

DESIGN.md §14 정책. 전체 plist 동기화는 금지하고, §14.2 의 22 + 12 = 34 키만 안전한
subset 으로 추출한다. 사용자의 binary plist (bplist00) 를 plistlib 으로 읽어
XML plist 로 staging 후 backup. apply 시 backup XML 을 target binary plist 에
deep-merge (덮어쓰기 X, 다른 키는 보존).
"""
from __future__ import annotations

import contextlib
import plistlib
import tempfile
from pathlib import Path
from typing import Any

from anvyc.adapters.base import ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile
from anvyc.utils.hashing import sha256_file

PLIST_CANONICAL = "~/Library/Preferences/com.googlecode.iterm2.plist"
PLIST_PATH = Path(PLIST_CANONICAL).expanduser()
STAGING_FILENAME = "iterm2-safe.plist"

# DESIGN.md §14.2 — 안전 포터블 키
SAFE_KEYS_INCLUDE: frozenset[str] = frozenset({
    # 프로필 / 식별
    "New Bookmarks",
    "Default Bookmark Guid",
    # 키바인딩 / 포인터
    "GlobalKeyMap",
    "PointerActions",
    # 색
    "Custom Color Presets",
    # 동작 prefs
    "DoubleClickPerformsSmartSelection",
    "EnableProxyIcon",
    "HideTab",
    "IRMemory",
    "PreventEscapeSequenceFromClearingHistory",
    "SavePasteHistory",
    "SplitPaneDimmingAmount",
    # 음/시각 알림
    "SoundForEsc",
    "VisualIndicatorForEsc",
    "HapticFeedbackForEsc",
    # Dim
    "DimBackgroundWindows",
    "DimInactiveSplitPanes",
    "DimOnlyText",
    # Hotkey
    "HotkeyMigratedFromSingleToMulti",
    # AI 통합
    "AIFeatureFunctionCalling",
    "AIFeatureHostedCodeInterpeter",
    "AIFeatureHostedFileSearch",
    "AIFeatureHostedWebSearch",
    "AIFeatureStreamingResponses",
    "AITermAPI",
    "AIVectorStore",
    "AIVendor",
    "AiMaxTokens",
    "AiModel",
    "AiResponseMaxTokens",
    "AitermURL",
})

# DESIGN.md §14.3 — 제외 사유 카테고리 prefix
SAFE_KEYS_EXCLUDE_PREFIXES: tuple[str, ...] = (
    "NSWindow Frame ",
    "NoSync",
    "NS",
    "Apple",
    "SU",
    "NeverWarnAbout",
)
SAFE_KEYS_EXCLUDE_EXACT: frozenset[str] = frozenset({
    "LoadPrefsFromCustomFolder",
    "PrefsCustomFolder",
    "iTerm Version",
    "URLHandlersByGuid",
})


def _extract_safe(data: dict[str, Any]) -> dict[str, Any]:
    """raw plist dict → 안전 subset dict."""
    return {k: v for k, v in data.items() if k in SAFE_KEYS_INCLUDE}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """overlay 의 키만 base 위에 덮어쓴다 (재귀 X — top-level 키 단위 교체).

    DESIGN.md §14.4 의 deep-merge 의도는 "기존 plist 의 다른 키는 건드리지 않는다"
    이지 dict 내부를 마지막 leaf 까지 병합하라는 게 아니다. 프로필 dict 의 모든
    필드는 한 덩어리로 교체되어야 일관성이 유지된다.
    """
    out = dict(base)
    for k, v in overlay.items():
        out[k] = v
    return out


class Iterm2Adapter:
    name = "iterm2"

    def __init__(self) -> None:
        self._stage_dir: Path | None = None

    def detect(self) -> bool:
        return PLIST_PATH.is_file()

    def collect(self) -> list[ManagedFile]:
        if not PLIST_PATH.is_file():
            return []
        with PLIST_PATH.open("rb") as f:
            data = plistlib.load(f)
        if not isinstance(data, dict):
            return []
        safe = _extract_safe(data)
        if not safe:
            return []

        stage_dir = self._stage()
        stage_file = stage_dir / STAGING_FILENAME
        with stage_file.open("wb") as f:
            plistlib.dump(safe, f, fmt=plistlib.FMT_XML, sort_keys=True)
        return [
            ManagedFile(
                tool=self.name,
                source_path=stage_file,
                target_path=Path(PLIST_CANONICAL),
                mode=0o644,
                relpath=STAGING_FILENAME,
            )
        ]

    def exclude(self) -> list[str]:
        # 정보성 — 실제 필터링은 _extract_safe 가 한다.
        out = list(SAFE_KEYS_EXCLUDE_EXACT)
        out.extend(f"{p}*" for p in SAFE_KEYS_EXCLUDE_PREFIXES)
        return out

    def validate(self) -> list[CheckResult]:
        return []

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def target_hash(self, target: Path) -> str:
        """target binary plist 에서 SAFE_KEYS 만 추출 후 collect() 와 동일한
        XML 직렬화 (FMT_XML, sort_keys=True) 로 sha256 계산.

        이 값은 같은 plist 가 변경되지 않은 한 backup metadata 의 sha256 과 동일하다 →
        status 가 unchanged 로 정확히 판정 가능.
        """
        if not target.is_file():
            raise FileNotFoundError(target)
        with target.open("rb") as f:
            data = plistlib.load(f)
        if not isinstance(data, dict):
            data = {}
        safe = _extract_safe(data)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".plist") as tf:
            tmp = Path(tf.name)
        try:
            with tmp.open("wb") as f:
                plistlib.dump(safe, f, fmt=plistlib.FMT_XML, sort_keys=True)
            return sha256_file(tmp)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()

    def apply(self, source: Path, target: Path) -> ApplyResult:
        """backup XML plist 의 safe subset 을 target binary plist 에 deep-merge."""
        with source.open("rb") as f:
            overlay = plistlib.load(f)
        if not isinstance(overlay, dict):
            raise RuntimeError(f"unexpected plist root type at {source}")

        if target.exists():
            with target.open("rb") as f:
                base = plistlib.load(f)
            if not isinstance(base, dict):
                base = {}
        else:
            base = {}

        merged = _deep_merge(base, overlay)

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as f:
            plistlib.dump(merged, f, fmt=plistlib.FMT_BINARY, sort_keys=True)

        return ApplyResult(
            target=target,
            changed=True,  # PoC: deep-merge 의 실제 변경 여부 비교는 후속
            backed_up=None,
            notes=[f"merged {len(overlay)} safe keys into {target.name}"],
        )

    # ---------- helpers ----------

    def _stage(self) -> Path:
        if self._stage_dir is None:
            self._stage_dir = Path(tempfile.mkdtemp(prefix="anvyc-iterm2-"))
        return self._stage_dir

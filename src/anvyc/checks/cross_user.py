"""Cross-user 경로 audit check.

DESIGN.md §27.3 참고.

탐지 카테고리:
  1) ~/.cursor/projects/Users-<name>-* 디렉터리 prefix
  2) ~/.cursor/** symlink target 의 /Users/<name>/ 시작
  3) 텍스트 파일 안의 /Users/<name>/ 절대 경로 (regex)
  4) iTerm2 plist 의 profile working directory (Phase 2)

분류 규칙:
  - <name> == current_user                                              → INFO
  - <name> in known_user_aliases AND resolves to current user home      → INFO_ALIASED
  - <name> 실재 다른 user (UID 충돌 X)                                 → WARNING_FOREIGN
  - path 미존재                                                          → WARNING_DANGLING
  - secret 영역 파일 (SSH key/AWS profile)                              → CRITICAL
"""
from __future__ import annotations

import re

from anvyc.checks.base import CheckContext, CheckResult

USER_PATH_RE = re.compile(r"/Users/([a-z][a-z0-9_.-]+)/")


class CrossUserCheck:
    name = "cross-user"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        """모든 scan_targets 를 순회하여 cross-user 흔적을 탐지한다 (MVP TODO)."""
        raise NotImplementedError

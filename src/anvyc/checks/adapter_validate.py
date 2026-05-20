"""adapter-validate doctor check.

등록된 모든 adapter 의 .validate() 결과를 doctor 리포트로 합산한다.
각 adapter 는 자신의 도메인 안전성을 점검할 수 있다 (예: cursor 의 broken symlink,
iterm2 의 Default Bookmark Guid 무결성, aws config 의 SSO 만료 등 — 향후 확장).

DESIGN.md §27.1 "도구 설치 / 경로 권한 / Secret 잔존" 카테고리 일부 + 어댑터별 상세.
"""
from __future__ import annotations

from anvyc.checks.base import CheckContext, CheckResult


class AdapterValidationCheck:
    name = "adapter-validate"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        # 지연 import — doctor.py ↔ backup.py 순환 회피
        from anvyc.core.backup import ADAPTERS

        results: list[CheckResult] = []
        for _tool_name, cls in ADAPTERS.items():
            try:
                adapter = cls()
            except Exception:
                # adapter 생성 자체 실패는 doctor 동작을 막지 않음
                continue
            try:
                if not adapter.detect():
                    continue
                results.extend(adapter.validate())
            except NotImplementedError:
                continue
            except Exception:
                # validate 자체의 예외도 흡수 — 한 adapter 의 결함이 다른 adapter
                # 점검을 막지 않게.
                continue
        return results

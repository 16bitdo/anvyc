"""사용자 프로젝트 루트 SoT (Single Source of Truth).

anvyc 가 "사용자 프로젝트 디렉터리"를 스캔하는 모든 곳(doctor 체크,
project list, dev_env 어댑터, cursor 제안)이 참조하는 단일 기본값과
config 해석 헬퍼.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anvyc.core.config import AnvycConfig

# `~/dev` 가 현행 표준 — 선두. `~/Documents` 는 전환기 잔존 프로젝트 커버용.
DEFAULT_PROJECT_ROOTS: tuple[str, ...] = (
    "~/dev",
    "~/Documents",
    "~/Projects",
    "~/code",
    "~/Code",
    "~/workspace",
    "~/src",
)


def resolve_project_roots(config: AnvycConfig | None = None) -> tuple[str, ...]:
    """anvyc.yaml 의 `doctor.project_roots` 를 읽고, 없으면 DEFAULT 로 fallback.

    config 가 None 이면 load_anvyc_config() 지연 import 후 로드. 로드/파싱
    실패 시 DEFAULT 반환. 반환은 `~` 미확장 문자열 튜플(호출부에서 expanduser).
    빈 리스트(`doctor.project_roots: []`)도 DEFAULT 로 fallback.
    """
    cfg = config
    if cfg is None:
        try:
            from anvyc.core.config import load_anvyc_config

            cfg = load_anvyc_config()
        except Exception:
            return DEFAULT_PROJECT_ROOTS

    roots = getattr(cfg.doctor, "project_roots", None)
    if not roots:
        return DEFAULT_PROJECT_ROOTS

    cleaned = tuple(str(r).strip() for r in roots if str(r).strip())
    return cleaned or DEFAULT_PROJECT_ROOTS

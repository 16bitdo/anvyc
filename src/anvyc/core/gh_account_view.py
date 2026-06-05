"""GitHub 계정 통합 뷰 — 오프라인 조립 (**네트워크 의존 0**).

`anvyc gh account` / doctor / project doctor 가 공유하는 순수 코어.
계정 탐색은 `utils/gh_hosts.py:discover_gh_accounts` 를 재사용하고,
cwd 라우팅은 `core/gh_route.py:resolve_account` 를 재사용한다.
네트워크 liveness probe 는 `core/gh_probe.py` 로 분리(이 모듈은 import 하지 않음)
→ probe_results 는 순수 데이터로만 수신.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from anvyc.core.gh_route import resolve_account
from anvyc.utils.gh_hosts import discover_gh_accounts, select_config_dir_for_user

if TYPE_CHECKING:
    # gh_probe 는 Task 2 에서 구현 — 런타임 import 금지(네트워크 의존 없음 불변)
    from anvyc.core.gh_probe import GhProbeResult


@dataclass(frozen=True)
class GhAccountView:
    """단일 GitHub 계정의 통합 뷰 (오프라인 스냅샷).

    `logged_in=True`  → `~/.config/gh*` hosts.yml 에서 탐지된 계정.
    `logged_in=False` → owner_accounts 매핑에만 존재(미로그인/미설치).
    `expiry_status`   → probe_results 제공 시 결과 반영, 미제공 시 "unknown".
    """

    account: str
    host: str
    config_dir: str | None  # str 로 직렬화 (Path 는 repr 에 토큰 노출 위험 없지만 str 통일)
    logged_in: bool
    expiry_status: str
    expires_at: str | None
    routed_owners: list[str] = field(default_factory=list)
    cwd_routed: bool = False


def collect_accounts(
    *,
    config_home: Path | None,
    owner_accounts: dict[str, str],
    cwd: Path,
    probe_results: dict[tuple[str, str], GhProbeResult] | None = None,
) -> list[GhAccountView]:
    """GitHub 계정 목록을 오프라인으로 조립해 반환한다.

    Parameters
    ----------
    config_home:
        gh config 루트 (테스트 격리용). None → DEFAULT_CONFIG_HOME (~/.config).
    owner_accounts:
        ``{owner: account}`` 매핑 (`.envrc`/routing manifest 기반).
        탐지되지 않은 account 도 뷰에 포함(logged_in=False).
    cwd:
        현재 작업 디렉터리 — git repo 의 origin SSH alias 로 cwd_routed 판정.
    probe_results:
        ``{(host, account): GhProbeResult}`` — None 이면 expiry 무시 ("unknown").
        이 모듈은 gh_probe 를 런타임 import 하지 않으며 순수 데이터만 수신.

    Returns
    -------
    list[GhAccountView]
        account 기준 오름차순 정렬.
    """
    # 1. 발견된 계정 탐색 (hosts.yml walk — 토큰 미반환)
    discovered = discover_gh_accounts(config_home)

    # account → host 매핑 (중복 시 첫 번째 host 사용)
    # NOTE: 동일 username 이 복수 host(GHES)에 존재하면 첫 host 만 보존 — Phase 1 은 GHES 미지원.
    #       멀티-host 지원 시 뷰 키를 (host, user) 로 확장 필요.
    account_host: dict[str, str] = {}
    for acct in discovered:
        if acct.user not in account_host:
            account_host[acct.user] = acct.host

    # 발견된 계정 집합
    discovered_users: set[str] = {acct.user for acct in discovered}

    # 2. owner_accounts 에서 미탐지 계정 추가 (logged_in=False)
    all_users: set[str] = discovered_users | set(owner_accounts.values())

    # 3. cwd 라우팅 (git repo origin SSH alias)
    cwd_account = resolve_account(cwd)

    # 4. owner_accounts 역인덱스: account → sorted owners
    account_owners: dict[str, list[str]] = {}
    for owner, mapped_acct in owner_accounts.items():
        account_owners.setdefault(mapped_acct, []).append(owner)
    for owners in account_owners.values():
        owners.sort()

    # 5. 뷰 조립
    views: list[GhAccountView] = []
    for user in sorted(all_users):
        logged_in = user in discovered_users
        # 매핑-only(미발견) account 는 host 미상 → "github.com" 가정 (GHES 매핑 지원 시 재검토)
        host = account_host.get(user, "github.com")

        if logged_in:
            cfg_path = select_config_dir_for_user(user, config_home=config_home)
            config_dir = str(cfg_path) if cfg_path is not None else None
        else:
            config_dir = None

        # probe 결과 조회 — TYPE_CHECKING guard 로 런타임 import 없음
        if probe_results is not None:
            pr = probe_results.get((host, user))
            expiry_status = getattr(pr, "status", "unknown") if pr is not None else "unknown"
            expires_at = getattr(pr, "expires_at", None) if pr is not None else None
        else:
            expiry_status = "unknown"
            expires_at = None

        views.append(
            GhAccountView(
                account=user,
                host=host,
                config_dir=config_dir,
                logged_in=logged_in,
                expiry_status=expiry_status,
                expires_at=expires_at,
                routed_owners=account_owners.get(user, []),
                cwd_routed=(cwd_account == user),
            )
        )

    return views

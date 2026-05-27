"""integration test 공용 fixture.

integration test 는 `.venv/bin/anvyc` 를 subprocess 로 호출한다. anvyc CLI 는
config fallback(`~/.anvyc/anvyc.yaml`), doctor checks(`~/.aws`·`~/.ssh`·
`~/.cursor`·`~/Documents`), adapter 들이 HOME 을 광범위하게 참조하므로,
HOME 을 격리하지 않으면 (1) 실 사용자 환경 상태에 따라 결과가 달라지고
(2) test 가 사용자 HOME 을 오염시킬 수 있다.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """integration test 의 HOME 을 tmp_path 로 격리한다.

    monkeypatch 가 현재 프로세스의 os.environ 을 바꾸므로, run_anvyc 가
    띄우는 subprocess(부모 env 상속/merge)도 동일하게 격리된 HOME 을 본다.
    """
    monkeypatch.setenv("HOME", str(tmp_path))


_INTEGRATION_DIR = Path(__file__).parent


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """tests/integration/ 하위 항목에 integration 마커 자동 부여.

    pytest 의 collection hook 은 conftest 위치와 무관하게 전체 collected
    items 를 인자로 받으므로, item.path 가 이 conftest 의 부모 디렉터리
    (=tests/integration) 하위에 있는지 확인해 필터링한다. 파일별
    데코레이터 부착 대신 자동 마킹 — 신규 통합 테스트도 자동 적용된다.
    CI 는 `pytest -m "not integration"` 으로 unit fast-fail 게이트를 먼저
    돌리고, 통과하면 `pytest -m integration` 단계로 넘어간다.
    """
    integration_marker = pytest.mark.integration
    for item in items:
        if _INTEGRATION_DIR in item.path.parents:
            item.add_marker(integration_marker)

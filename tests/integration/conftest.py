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

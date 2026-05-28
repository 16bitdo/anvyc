"""anvyc.yaml 의 cost section 파싱 + adapter registry 통합 (CP-13 polish)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from anvyc.core.config import CostConfig, load_anvyc_config


@pytest.fixture
def yaml_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / ".anvyc"
    d.mkdir()
    monkeypatch.setenv("ANVYC_HOSTNAME", "test-host")
    return d


def _write(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body))


def test_cost_section_absent_returns_defaults(yaml_dir: Path) -> None:
    base = yaml_dir / "anvyc.yaml"
    _write(base, "version: 1\n")
    cfg = load_anvyc_config(base)
    assert cfg.cost == CostConfig()
    assert cfg.cost.github.accounts == []


def test_cost_github_accounts_parsed(yaml_dir: Path) -> None:
    base = yaml_dir / "anvyc.yaml"
    _write(
        base,
        """\
        version: 1
        cost:
          github:
            accounts:
              - "16bitdo"
              - "heisgone@whatap"
        """,
    )
    cfg = load_anvyc_config(base)
    assert cfg.cost.github.accounts == ["16bitdo", "heisgone@whatap"]


def test_cost_github_accounts_skips_non_string(yaml_dir: Path) -> None:
    """yaml 의 잘못된 entry (number 등) 는 skip — graceful."""
    base = yaml_dir / "anvyc.yaml"
    _write(
        base,
        """\
        version: 1
        cost:
          github:
            accounts:
              - "16bitdo"
              - 42
              - "heisgone@whatap"
        """,
    )
    cfg = load_anvyc_config(base)
    assert cfg.cost.github.accounts == ["16bitdo", "heisgone@whatap"]


def test_cost_github_empty_list(yaml_dir: Path) -> None:
    base = yaml_dir / "anvyc.yaml"
    _write(
        base,
        """\
        version: 1
        cost:
          github:
            accounts: []
        """,
    )
    cfg = load_anvyc_config(base)
    assert cfg.cost.github.accounts == []


def test_cost_github_overlay_replaces_base(yaml_dir: Path) -> None:
    """anvyc.<host>.yaml overlay 의 accounts list 가 base list 대체."""
    base = yaml_dir / "anvyc.yaml"
    overlay = yaml_dir / "anvyc.test-host.yaml"
    _write(
        base,
        """\
        version: 1
        cost:
          github:
            accounts: ["16bitdo"]
        """,
    )
    _write(
        overlay,
        """\
        cost:
          github:
            accounts: ["heisgone@whatap"]
        """,
    )
    cfg = load_anvyc_config(base)
    assert cfg.overlay_source == overlay
    assert cfg.cost.github.accounts == ["heisgone@whatap"]


def test_adapter_registry_passes_accounts_override(
    yaml_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_build_registry() 가 config.cost.github.accounts 를 adapter 에 전달."""
    import importlib.util as iutil

    if iutil.find_spec("httpx") is None:
        pytest.skip("httpx not installed")

    base = yaml_dir / "anvyc.yaml"
    _write(
        base,
        """\
        version: 1
        cost:
          github:
            accounts:
              - "16bitdo"
              - "heisgone@whatap"
        """,
    )

    # load_anvyc_config 의 candidate path 가 yaml_dir/anvyc.yaml 발견하도록
    # cwd 변경 (candidate path 의 우선순위 = CWD/anvyc.yaml).
    # HOME 도 함께 isolate — `_candidate_paths` 의 `~/.anvyc/anvyc.yaml` fallback
    # 이 호스트 사용자의 실 파일을 읽지 못하도록 (CI 환경엔 없지만 dev 머신엔 있을 수 있음).
    monkeypatch.chdir(yaml_dir)
    monkeypatch.setenv("HOME", str(yaml_dir))

    from anvyc.core.cost.adapters import _build_registry  # noqa: PLC0415
    from anvyc.core.cost.adapters.github import GitHubBillingAdapter  # noqa: PLC0415

    registry = _build_registry()
    assert "github" in registry
    gh = registry["github"]
    assert isinstance(gh, GitHubBillingAdapter)
    assert gh._accounts_override == ["16bitdo", "heisgone@whatap"]

    # discover_accounts 가 override list 만 yield
    keys = sorted(a.key for a in gh.discover_accounts())
    assert keys == ["16bitdo", "heisgone@whatap"]


def test_adapter_registry_config_absent_falls_back_to_auto_discover(
    yaml_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """config 부재 시 adapter 의 accounts_override = None (자동 discover)."""
    import importlib.util as iutil

    if iutil.find_spec("httpx") is None:
        pytest.skip("httpx not installed")

    # yaml_dir 안에 anvyc.yaml 없음 — cwd 변경해도 load_anvyc_config 가 빈 cfg.
    # HOME 도 isolate — `~/.anvyc/anvyc.yaml` fallback 이 호스트 사용자의 실 파일을
    # 읽으면 `gh._accounts_override` 가 None 아닌 leak 된 값으로 채워짐 (CI 무관, dev 머신 한정).
    monkeypatch.chdir(yaml_dir)
    monkeypatch.setenv("HOME", str(yaml_dir))

    from anvyc.core.cost.adapters import _build_registry  # noqa: PLC0415
    from anvyc.core.cost.adapters.github import GitHubBillingAdapter  # noqa: PLC0415

    registry = _build_registry()
    assert "github" in registry
    gh = registry["github"]
    assert isinstance(gh, GitHubBillingAdapter)
    assert gh._accounts_override is None

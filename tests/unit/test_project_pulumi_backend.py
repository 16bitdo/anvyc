"""project-pulumi-backend-mapping check 단위 테스트.

monkeypatch 로 `resolve_project_roots` 를 격리하여 실제 사용자 환경 의존성 제거.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.checks.base import CheckContext, Severity
from anvyc.checks.project_pulumi_backend import ProjectPulumiBackendMappingCheck
from anvyc.core.config import AnvycConfig


def test_pulumi_honors_individual_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    indiv = tmp_path / "proj"
    indiv.mkdir()
    (indiv / "Pulumi.yaml").write_text("name: p\nruntime: python\nbackend:\n  url: s3://yaml-be\n")
    (indiv / ".envrc").write_text('export PULUMI_BACKEND_URL="s3://envrc-be"\n')  # mismatch
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(empty),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: (str(indiv),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    monkeypatch.setattr("anvyc.core.config.load_anvyc_config", lambda *a, **kw: AnvycConfig())
    results = ProjectPulumiBackendMappingCheck().run(CheckContext())
    # 개별 project 가 스캔되어 mismatch 경고 (yaml-be vs envrc-be 불일치)
    assert any(
        "yaml-be" in r.message and "envrc-be" in r.message
        or (r.location is not None and "proj" in str(r.location))
        for r in results
    )


def _write_pulumi(project: Path, backend: str | None = None) -> None:
    project.mkdir(parents=True, exist_ok=True)
    body = f"name: {project.name}\nruntime: python\n"
    if backend:
        body += f"backend:\n  url: {backend}\n"
    (project / "Pulumi.yaml").write_text(body)


def _write_envrc_backend(project: Path, url: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / ".envrc").write_text(f'export PULUMI_BACKEND_URL="{url}"\n')


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    r = tmp_path / "dev"
    r.mkdir()
    monkeypatch.setattr("anvyc.core.project_roots.resolve_project_roots", lambda config=None: (str(r),))
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: ())
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    monkeypatch.setattr("anvyc.core.config.load_anvyc_config", lambda *a, **kw: AnvycConfig())
    return r


def test_all_match_yields_single_info(root: Path) -> None:
    """backend 선언 project 가 모두 일치 → INFO summary 1건."""
    proj_a = root / "proj-a"
    _write_pulumi(proj_a, backend="s3://state-bucket")
    _write_envrc_backend(proj_a, "s3://state-bucket")
    proj_b = root / "proj-b"
    _write_pulumi(proj_b, backend="https://api.pulumi.com")  # Pulumi.yaml only

    res = ProjectPulumiBackendMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "2개" in res[0].message
    assert "불일치 없음" in res[0].message


def test_mismatch_yields_warning(root: Path) -> None:
    """Pulumi.yaml backend ≠ .envrc PULUMI_BACKEND_URL → WARNING (location = Pulumi.yaml)."""
    proj = root / "proj-x"
    _write_pulumi(proj, backend="s3://bucket-one")
    _write_envrc_backend(proj, "s3://bucket-two")

    res = ProjectPulumiBackendMappingCheck().run(CheckContext())

    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert "bucket-one" in res[0].message
    assert "bucket-two" in res[0].message
    assert "불일치" in res[0].message
    assert res[0].location is not None
    assert res[0].location.name == "Pulumi.yaml"
    assert res[0].suggestion is not None


def test_normalized_match_no_warning(root: Path) -> None:
    """trailing slash 차이는 정규화로 흡수 → 일치."""
    proj = root / "proj-n"
    _write_pulumi(proj, backend="s3://bucket/")
    _write_envrc_backend(proj, "s3://bucket")

    res = ProjectPulumiBackendMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO


def test_envrc_only_yields_info(root: Path) -> None:
    """Pulumi.yaml 에 backend 없고 .envrc 만 선언 → 대상이지만 불일치 아님 → INFO."""
    proj = root / "proj-e"
    _write_pulumi(proj)  # backend 없음
    _write_envrc_backend(proj, "s3://env-bucket")

    res = ProjectPulumiBackendMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "1개" in res[0].message


def test_no_backend_declared_yields_silent(root: Path) -> None:
    """backend / PULUMI_BACKEND_URL 둘 다 선언 안 함 → 결과 0건 (silent)."""
    _write_pulumi(root / "proj-plain")  # Pulumi.yaml only, backend 없음

    res = ProjectPulumiBackendMappingCheck().run(CheckContext())
    assert res == []


def test_no_pulumi_yaml_yields_silent(root: Path) -> None:
    """Pulumi.yaml 부재 → 결과 0건 (silent)."""
    (root / "proj-bare").mkdir(parents=True, exist_ok=True)
    res = ProjectPulumiBackendMappingCheck().run(CheckContext())
    assert res == []


def test_multi_root_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_project_roots 가 2개 루트를 주면 양쪽 Pulumi.yaml 모두 스캔."""
    root_a = tmp_path / "dev"
    root_b = tmp_path / "Documents"
    root_a.mkdir()
    root_b.mkdir()
    _write_pulumi(root_a / "proj-a", backend="s3://a")
    _write_pulumi(root_b / "proj-b", backend="s3://b")
    monkeypatch.setattr(
        "anvyc.core.project_roots.resolve_project_roots",
        lambda config=None: (str(root_a), str(root_b)),
    )
    monkeypatch.setattr("anvyc.core.project_roots.resolve_projects", lambda config=None: ())
    monkeypatch.setattr("anvyc.core.project_roots.resolve_excludes", lambda config=None: ())
    monkeypatch.setattr("anvyc.core.config.load_anvyc_config", lambda *a, **kw: AnvycConfig())

    res = ProjectPulumiBackendMappingCheck().run(CheckContext())
    assert len(res) == 1
    assert res[0].severity is Severity.INFO
    assert "2개" in res[0].message

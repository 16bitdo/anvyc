"""pulumi_project utility 단위 테스트 (P3, v0.8.0)."""
from __future__ import annotations

from pathlib import Path

from anvyc.utils.pulumi_project import (
    detect_pulumi_project,
    normalize_backend_url,
    to_dict,
)


def _write_yaml(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_full_project_with_stacks(tmp_path: Path) -> None:
    """Pulumi.yaml + 2 stack yaml → name/runtime/stacks 추출."""
    _write_yaml(
        tmp_path / "Pulumi.yaml",
        "name: my-proj\nruntime: python\ndescription: example\n",
    )
    _write_yaml(tmp_path / "Pulumi.dev.yaml", "config: {}\n")
    _write_yaml(tmp_path / "Pulumi.prd.yaml", "config: {}\n")

    info = detect_pulumi_project(tmp_path)
    assert info is not None
    assert info.name == "my-proj"
    assert info.runtime == "python"
    assert info.description == "example"
    assert info.stacks == ["dev", "prd"]


def test_runtime_as_dict(tmp_path: Path) -> None:
    """runtime 이 dict 형태 {name: python, options: {...}} 일 때도 name 추출."""
    _write_yaml(
        tmp_path / "Pulumi.yaml",
        "name: nest\nruntime:\n  name: python\n  options:\n    virtualenv: venv\n",
    )
    info = detect_pulumi_project(tmp_path)
    assert info is not None
    assert info.runtime == "python"


def test_no_stack_files(tmp_path: Path) -> None:
    """Pulumi.yaml 만 있고 stack yaml 없음 → stacks=[]."""
    _write_yaml(tmp_path / "Pulumi.yaml", "name: bare\nruntime: nodejs\n")
    info = detect_pulumi_project(tmp_path)
    assert info is not None
    assert info.stacks == []


def test_missing_pulumi_yaml(tmp_path: Path) -> None:
    """Pulumi.yaml 부재 → None."""
    info = detect_pulumi_project(tmp_path)
    assert info is None


def test_invalid_yaml(tmp_path: Path) -> None:
    """parse 실패 → None (graceful)."""
    _write_yaml(tmp_path / "Pulumi.yaml", ": : invalid : yaml :\n")
    info = detect_pulumi_project(tmp_path)
    assert info is None


def test_missing_name(tmp_path: Path) -> None:
    """name 키 부재 → None (Pulumi project 가 아님)."""
    _write_yaml(tmp_path / "Pulumi.yaml", "runtime: python\n")
    info = detect_pulumi_project(tmp_path)
    assert info is None


def test_to_dict_format(tmp_path: Path) -> None:
    """to_dict 출력 schema (project_name 등 key 명)."""
    _write_yaml(tmp_path / "Pulumi.yaml", "name: t\nruntime: python\n")
    info = detect_pulumi_project(tmp_path)
    d = to_dict(info)
    assert d is not None
    assert d["project_name"] == "t"
    assert d["runtime"] == "python"
    assert d["stacks"] == []
    assert d["backend"] is None
    assert "yaml_path" in d


def test_to_dict_none() -> None:
    assert to_dict(None) is None


# ---------- backend.url 파싱 (v0.12.0) -------------------------------------


def test_backend_url_parsed(tmp_path: Path) -> None:
    """Pulumi.yaml 의 backend.url → backend_url 추출."""
    _write_yaml(
        tmp_path / "Pulumi.yaml",
        "name: p\nruntime: python\nbackend:\n  url: s3://my-state-bucket\n",
    )
    info = detect_pulumi_project(tmp_path)
    assert info is not None
    assert info.backend_url == "s3://my-state-bucket"
    assert to_dict(info)["backend"] == "s3://my-state-bucket"  # type: ignore[index]


def test_backend_absent_yields_none(tmp_path: Path) -> None:
    """backend 키 부재 (Pulumi Cloud default) → backend_url None."""
    _write_yaml(tmp_path / "Pulumi.yaml", "name: p\nruntime: python\n")
    info = detect_pulumi_project(tmp_path)
    assert info is not None
    assert info.backend_url is None


def test_backend_without_url_key_yields_none(tmp_path: Path) -> None:
    """backend 가 dict 이지만 url 키 없음 → None."""
    _write_yaml(
        tmp_path / "Pulumi.yaml",
        "name: p\nruntime: python\nbackend:\n  cloudUrl: ignored\n",
    )
    info = detect_pulumi_project(tmp_path)
    assert info is not None
    assert info.backend_url is None


def test_backend_non_dict_yields_none(tmp_path: Path) -> None:
    """backend 가 dict 아님 (문자열 등) → None (graceful)."""
    _write_yaml(
        tmp_path / "Pulumi.yaml",
        "name: p\nruntime: python\nbackend: s3://oops\n",
    )
    info = detect_pulumi_project(tmp_path)
    assert info is not None
    assert info.backend_url is None


class TestNormalizeBackendUrl:
    def test_trailing_slash_stripped(self) -> None:
        assert normalize_backend_url("s3://bucket/") == "s3://bucket"
        assert normalize_backend_url("s3://bucket") == "s3://bucket"

    def test_file_tilde_expanded(self) -> None:
        result = normalize_backend_url("file://~/pulumi-state")
        assert result == "file://" + str(Path("~/pulumi-state").expanduser())

    def test_plain_url_unchanged(self) -> None:
        assert normalize_backend_url("https://api.pulumi.com") == "https://api.pulumi.com"

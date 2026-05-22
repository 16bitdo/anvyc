"""Pulumi project (<project>/Pulumi.yaml + Pulumi.<stack>.yaml) 추출 (P3, v0.8.0).

read-only utility — backup 영역과 분리. `anvyc project show` 등에서 호출.

Pulumi.yaml schema:
  name: <project-name>          # required
  runtime: <python|nodejs|go|dotnet>   # string 또는 dict {name, options}
  description: <...>            # optional
  backend:                      # optional — state backend 라우팅 (per-project)
    url: <s3://... | gs://... | https://api.pulumi.com | file://~ | ...>

Pulumi.<stack>.yaml 의 stack 이름은 파일명에서 추출. yaml 내용은 추적 안 함
(encryptionsalt / config 값 안에 secret 가능).

backend 키 부재 = Pulumi Cloud default — anvyc 은 명시 선언만 추적한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml as _yaml


@dataclass
class PulumiProjectInfo:
    yaml_path: Path
    name: str
    runtime: str | None
    description: str | None
    backend_url: str | None
    stacks: list[str]


def _extract_runtime(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        return name if isinstance(name, str) else None
    return None


def _extract_backend_url(value: object) -> str | None:
    """Pulumi.yaml 의 `backend` 키 → backend URL.

    `backend: {url: <str>}` 형식만 추적. 키 부재 / url 부재 / 형식 불일치
    → None (= Pulumi Cloud default backend, 명시 선언만 추적).
    """
    if isinstance(value, dict):
        url = value.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def normalize_backend_url(url: str) -> str:
    """backend URL 비교용 정규화 — trailing slash 제거 + `file://` 의 `~` 확장.

    `Pulumi.yaml` 의 `backend.url` 과 `.envrc` 의 `PULUMI_BACKEND_URL` 을 비교하는
    doctor check (per-cwd / global) 가 공유한다. `app.pulumi.com` ↔ `api.pulumi.com`
    같은 Pulumi Cloud alias 는 정규화하지 않는다 (best-effort — 과한 정규화는
    오탐 위험).
    """
    u = url.strip().rstrip("/")
    if u.startswith("file://"):
        rest = u[len("file://") :]
        if rest.startswith("~"):
            u = "file://" + str(Path(rest).expanduser())
    return u


def detect_pulumi_project(path: Path) -> PulumiProjectInfo | None:
    """path 안의 Pulumi.yaml 발견 시 PulumiProjectInfo 반환. 없거나 invalid → None."""
    yaml_path = path / "Pulumi.yaml"
    if not yaml_path.is_file():
        return None
    try:
        data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except (OSError, _yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    stacks: list[str] = []
    try:
        for f in path.glob("Pulumi.*.yaml"):
            if not f.is_file() or f.name == "Pulumi.yaml":
                continue
            stack = f.name[len("Pulumi."):-len(".yaml")]
            if stack:
                stacks.append(stack)
    except (OSError, PermissionError):
        pass

    return PulumiProjectInfo(
        yaml_path=yaml_path,
        name=name.strip(),
        runtime=_extract_runtime(data.get("runtime")),
        description=data.get("description") if isinstance(data.get("description"), str) else None,
        backend_url=_extract_backend_url(data.get("backend")),
        stacks=sorted(set(stacks)),
    )


def to_dict(info: PulumiProjectInfo | None) -> dict[str, Any] | None:
    if info is None:
        return None
    return {
        "project_name": info.name,
        "runtime": info.runtime,
        "description": info.description,
        "backend": info.backend_url,
        "stacks": info.stacks,
        "yaml_path": str(info.yaml_path),
    }

"""동반 도구(companion tools) 의존성 SoT — 외부 CLI 바이너리 + Python extras.

DESIGN.md §27 (doctor) / §30-31 (secrets) 참고. anvyc 의 일부 기능은 PATH 의 외부 CLI
(sops/age/op/…) 또는 pip extras (boto3/httpx/textual/mcp/…) 가 있어야 동작한다. 과거에는
`brew install …` 안내가 여러 파일에 하드코딩으로 흩어져 문구가 불일치했다(drift).

이 모듈이 그 단일 SoT 다 — `adapters.base.AdapterMeta` + `core.tools_select.collect_tool_rows`
와 동형. 정적 메타(ExtraReq) + 런타임 상태(collect_extras_status) 분리.

소비처:
  - 분산 call site (sops.py / secrets.py / checks/sops_keys.py / checks/op_references.py /
    cli.py) 가 `is_available()` · `install_hint()` 로 참조 — 안내 문구 단일화.
  - `anvyc extras` 명령 + README 생성기 (collect_extras_status / render_*).
"""

from __future__ import annotations

import importlib.metadata as _md
import platform
import shutil
from dataclasses import dataclass
from typing import Any

# ExtraReq.kind 허용값 — drift 방지 (test_extras_registry 가 강제).
EXTRA_KINDS: frozenset[str] = frozenset({"binary", "pyextra"})


@dataclass(frozen=True)
class ExtraReq:
    """동반 도구 1건의 *정적* 메타데이터 (설치 상태·버전 같은 런타임 값은 제외).

    - kind="binary": PATH 의 외부 CLI. `probe` 는 `shutil.which` 후보들.
    - kind="pyextra": pip optional-dependency. `probe` 는 import 메타데이터 dist 이름,
      `pip_extra` 는 pyproject extras 키.
    """

    name: str
    kind: str
    label: str
    purpose: str  # 이 도구가 잠금 해제하는 anvyc 기능
    probe: tuple[str, ...]
    install_cmd: str
    pip_extra: str | None = None
    install_url: str | None = None
    required: bool = False  # git 등 핵심 vs 선택
    platform: str | None = None  # "darwin" → 해당 OS 에서만 관련 (pbcopy/security)


# 단일 SoT. 순서 = `anvyc extras` / README 표 출력 순서 (binary 먼저, pyextra 다음).
EXTRAS_REGISTRY: tuple[ExtraReq, ...] = (
    ExtraReq(
        name="sops",
        kind="binary",
        label="SOPS",
        purpose="secret_files 암호화/복호화 (encryption-at-rest)",
        probe=("sops",),
        install_cmd="brew install sops",
        install_url="https://github.com/getsops/sops",
    ),
    ExtraReq(
        name="age",
        kind="binary",
        label="age",
        purpose="SOPS age backend (키 생성·암복호화)",
        probe=("age",),
        install_cmd="brew install age",
        install_url="https://github.com/FiloSottile/age",
    ),
    ExtraReq(
        name="op",
        kind="binary",
        label="1Password CLI",
        purpose="op:// Secret Reference 검증·주입",
        probe=("op",),
        install_cmd="brew install 1password-cli",
        install_url="https://developer.1password.com/docs/cli/",
    ),
    ExtraReq(
        name="aws-vault",
        kind="binary",
        label="aws-vault",
        purpose="aws-vault secret backend",
        probe=("aws-vault",),
        install_cmd="brew install aws-vault",
        install_url="https://github.com/ByteNess/aws-vault",
    ),
    ExtraReq(
        name="gh",
        kind="binary",
        label="GitHub CLI",
        purpose="GitHub cost 수집 (gh auth token)",
        probe=("gh",),
        install_cmd="brew install gh",
        install_url="https://cli.github.com",
    ),
    ExtraReq(
        name="git",
        kind="binary",
        label="Git",
        purpose="anvyc init --from-git (원격 .anvyc clone)",
        probe=("git",),
        install_cmd="xcode-select --install  (또는 brew install git)",
        required=True,
    ),
    ExtraReq(
        name="security",
        kind="binary",
        label="macOS security (keychain)",
        purpose="keychain secret backend",
        probe=("security",),
        install_cmd="(macOS 기본 제공 — 별도 설치 불필요)",
        platform="darwin",
    ),
    ExtraReq(
        name="pbcopy",
        kind="binary",
        label="pbcopy",
        purpose="secret get 클립보드 복사",
        probe=("pbcopy",),
        install_cmd="(macOS 기본 제공 — 별도 설치 불필요)",
        platform="darwin",
    ),
    ExtraReq(
        name="mcp",
        kind="pyextra",
        label="mcp (MCP SDK)",
        purpose="MCP server 모드 (anvyc serve --mcp)",
        probe=("mcp",),
        pip_extra="mcp",
        install_cmd="pip install 'anvyc[mcp]'",
    ),
    ExtraReq(
        name="textual",
        kind="pyextra",
        label="textual (TUI)",
        purpose="tools configure 체크박스 TUI",
        probe=("textual",),
        pip_extra="tui",
        install_cmd="pip install 'anvyc[tui]'",
    ),
    ExtraReq(
        name="boto3",
        kind="pyextra",
        label="boto3 (AWS)",
        purpose="AWS Cost Explorer 수집 (cost --source aws)",
        probe=("boto3",),
        pip_extra="cost-aws",
        install_cmd="pip install 'anvyc[cost-aws]'",
    ),
    ExtraReq(
        name="httpx",
        kind="pyextra",
        label="httpx (GitHub cost)",
        purpose="GitHub Billing 수집 (cost --source github)",
        probe=("httpx",),
        pip_extra="cost-github",
        install_cmd="pip install 'anvyc[cost-github]'",
    ),
    ExtraReq(
        name="cryptography",
        kind="pyextra",
        label="cryptography",
        purpose="SOPS 복호화 보조",
        probe=("cryptography",),
        pip_extra="encryption",
        install_cmd="pip install 'anvyc[encryption]'",
    ),
)

_BY_NAME: dict[str, ExtraReq] = {r.name: r for r in EXTRAS_REGISTRY}


def find(name: str) -> ExtraReq | None:
    """레지스트리에서 name 으로 ExtraReq 조회 (없으면 None)."""
    return _BY_NAME.get(name)


def _binary_installed(req: ExtraReq) -> bool:
    return any(shutil.which(b) is not None for b in req.probe)


def _pyextra_version(req: ExtraReq) -> str | None:
    for dist in req.probe:
        try:
            return _md.version(dist)
        except _md.PackageNotFoundError:
            continue
    return None


def is_available(name: str) -> bool:
    """name 도구가 설치(=사용 가능)됐는지. 미지 name 은 False.

    binary 는 `shutil.which`, pyextra 는 import 메타데이터로 판정한다. op 의 `whoami`
    같은 *인증* 검사는 포함하지 않는다 — 설치(install) 여부만 본다.
    """
    req = _BY_NAME.get(name)
    if req is None:
        return False
    if req.kind == "pyextra":
        return _pyextra_version(req) is not None
    return _binary_installed(req)


def installed_version(name: str) -> str | None:
    """pyextra 의 설치 버전 (binary 는 항상 None — 버전 추출은 도구별 상이)."""
    req = _BY_NAME.get(name)
    if req is None or req.kind != "pyextra":
        return None
    return _pyextra_version(req)


def install_hint(name: str) -> str:
    """안내 문구용 설치 힌트 — "brew install sops (또는 <url>)" 형태.

    미지 name 은 빈 문자열. 분산 call site 가 미설치 메시지의 괄호 안내로 쓴다.
    """
    req = _BY_NAME.get(name)
    if req is None:
        return ""
    if req.install_url:
        return f"{req.install_cmd}  (또는 {req.install_url})"
    return req.install_cmd


def _is_relevant(req: ExtraReq) -> bool:
    """현재 OS 에서 관련 있는 도구인지 (platform 제약 반영)."""
    if req.platform is None:
        return True
    return platform.system().lower() == req.platform.lower()


def collect_extras_status() -> list[dict[str, Any]]:
    """각 ExtraReq 의 정적 메타 + 런타임 상태(installed/version/relevant) 를 결합.

    `anvyc extras` 명령 / README 생성기 / doctor 힌트의 단일 SoT.
    """
    rows: list[dict[str, Any]] = []
    for req in EXTRAS_REGISTRY:
        rows.append(
            {
                "name": req.name,
                "kind": req.kind,
                "label": req.label,
                "purpose": req.purpose,
                "installed": is_available(req.name),
                "version": installed_version(req.name),
                "install_cmd": req.install_cmd,
                "install_url": req.install_url,
                "pip_extra": req.pip_extra,
                "required": req.required,
                "platform": req.platform,
                "relevant": _is_relevant(req),
            }
        )
    return rows

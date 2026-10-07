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
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from anvyc.core.install_method import INSTALL_SH_URL, extras_install_command

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


def _install_sh_cmd(pip_extra: str) -> str:
    """README 표용 정적 명령 — install.sh 설치본 기준(권장 경로). 런타임 안내는 install_hint."""
    return f"ANVYC_EXTRAS={pip_extra} bash <(curl -sSL {INSTALL_SH_URL})"


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
        install_cmd=_install_sh_cmd("mcp"),
    ),
    ExtraReq(
        name="textual",
        kind="pyextra",
        label="textual (TUI)",
        purpose="tools configure 체크박스 TUI",
        probe=("textual",),
        pip_extra="tui",
        install_cmd=_install_sh_cmd("tui"),
    ),
    ExtraReq(
        name="boto3",
        kind="pyextra",
        label="boto3 (AWS)",
        purpose="AWS Cost Explorer 수집 (cost --source aws)",
        probe=("boto3",),
        pip_extra="cost-aws",
        install_cmd=_install_sh_cmd("cost-aws"),
    ),
    ExtraReq(
        name="httpx",
        kind="pyextra",
        label="httpx (GitHub cost)",
        purpose="GitHub Billing 수집 (cost --source github)",
        probe=("httpx",),
        pip_extra="cost-github",
        install_cmd=_install_sh_cmd("cost-github"),
    ),
    ExtraReq(
        name="cryptography",
        kind="pyextra",
        label="cryptography",
        purpose="SOPS 복호화 보조",
        probe=("cryptography",),
        pip_extra="encryption",
        install_cmd=_install_sh_cmd("encryption"),
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
    """안내 문구용 설치 힌트. 미지 name 은 빈 문자열.

    바이너리는 정적 문구 — "brew install sops (또는 <url>)". pyextra 는 지금 실행 중인
    설치본의 방식에 맞춘 명령이다(install_hint_for_extra) — anvyc 는 PyPI 에 없어서 이름으로
    찾는 설치는 새 환경에서 실패하고, PATH 의 pip 는 uv tool·pipx·Homebrew 설치본과 다른
    환경이다(2026-10-07 실측).
    """
    req = _BY_NAME.get(name)
    if req is None:
        return ""
    if req.kind == "pyextra" and req.pip_extra:
        return install_hint_for_extra(req.pip_extra)
    if req.install_url:
        return f"{req.install_cmd}  (또는 {req.install_url})"
    return req.install_cmd


def install_hint_for_extra(pip_extra: str) -> str:
    """pip extra 키 하나를 현재 설치 방식으로 더하는 명령 — 이미 설치된 extras 를 보존한다."""
    return extras_install_command(_order_extras({pip_extra, *installed_pip_extras()}))


def installed_pip_extras() -> tuple[str, ...]:
    """probe dist 가 설치된 pyextra 의 pip extra 키(레지스트리 순서).

    probe 는 전이 의존으로도 깔린다(httpx·cryptography 는 mcp 가 끌어온다) — 과대 추정은
    이미 있는 의존을 한 번 더 적을 뿐 무해하다. 과소 추정은 재설치가 그 extras 를 지우므로
    그쪽을 피하는 판정이다.
    """
    out: list[str] = []
    for req in EXTRAS_REGISTRY:
        if req.kind == "pyextra" and req.pip_extra and _pyextra_version(req) is not None:
            out.append(req.pip_extra)
    return tuple(out)


def _order_extras(keys: Iterable[str]) -> list[str]:
    """레지스트리 순서, 그 밖의 키는 정렬해 뒤에 — 안내 문자열이 결정적이게."""
    wanted = set(keys)
    order: list[str] = []
    for req in EXTRAS_REGISTRY:
        if req.pip_extra is not None and req.pip_extra in wanted:
            order.append(req.pip_extra)
    return order + sorted(wanted.difference(order))


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
                "install_cmd": (
                    install_hint_for_extra(req.pip_extra)
                    if req.kind == "pyextra" and req.pip_extra
                    else req.install_cmd
                ),
                "install_url": req.install_url,
                "pip_extra": req.pip_extra,
                "required": req.required,
                "platform": req.platform,
                "relevant": _is_relevant(req),
            }
        )
    return rows


_KIND_LABEL = {"binary": "CLI", "pyextra": "pip extra"}


def render_extras_markdown() -> str:
    """README '동반 도구' 표를 EXTRAS_REGISTRY SoT 에서 생성 (scripts/gen_extras.py).

    런타임 설치 상태와 무관한 정적 메타만 사용 → 어느 환경에서 돌려도 동일.
    표 순서는 EXTRAS_REGISTRY 순서.
    """
    lines = [
        "| 도구 | 종류 | 잠금 해제 기능 | 설치 |",
        "|---|---|---|---|",
    ]
    for r in EXTRAS_REGISTRY:
        kind = _KIND_LABEL.get(r.kind, r.kind)
        lines.append(f"| {r.label} | {kind} | {r.purpose} | `{r.install_cmd}` |")
    return "\n".join(lines)

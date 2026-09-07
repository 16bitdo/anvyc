"""session-bridge check (L2 관측, read-only).

ccinspector `session-bridge` 모듈 — 하네스의 세션 발견 레코드 쌍(`<pid>.json` +
`<pid>.<sha256>.key`)을 다른 프로필의 `sessions/` 로 복사해 `ListAgents`/`SendMessage` 가
프로필(`CLAUDE_CONFIG_DIR`) 경계를 넘게 하는 opt-in 모듈 — 의 read-only 미러.
`module_verify`(lib 의 `status --check`)와 같은 판정을 **별 채널**로 재현해 cross-validation
한다. anvyc 는 복사본·manifest·settings 를 수정하지 않는다(단방향 의존, DESIGN §7.7) —
조치는 사용자가 lib 의 `sync` / ccinspector `install.sh` 로 한다.

활성 판정: 어느 `~/.claude*/settings.json` 에도 `session_bridge.py … hook` 배선이 없으면
silent(모듈 off / ccinspector 미설치 머신 → N/A). 대상 프로필 집합은 lib 와 같은
`~/.config/cc-inspect/.session-bridge/profiles`(설치 시 기록), 부재 시 `~/.claude*` 전부.
그중 `sessions/` 가 있는 프로필만 활성.

보고:
- 활성 프로필 일부에 배선 없음 → WARNING. 그 프로필에서 시작·종료하는 세션은 SessionStart
  동기화·SessionEnd 회수가 돌지 않는다.
- manifest 파싱 실패 → WARNING(원본/복사본 구분 불가).
- manifest 복사본은 있는데 인식되는 원본 쌍이 0 → WARNING. 하네스가 레코드 형식을 바꾸면
  브리지가 "전부 가시" 로 오판하는 바로 그 고장(lib `status --check` 와 같은 guard).
- 살아있는 원본 세션이 다른 활성 프로필에 쌍으로 없음 → 세션당 WARNING. 그 프로필의 세션에서
  `ListAgents` 에 안 보이고 `SendMessage` 가 닿지 않는다.
- 원본 레코드 `peerProtocol ≠ 1`(부재 포함) → 값별 집계 WARNING. 브리지는 protocol 1 로만
  검증됐다 — 검증되지 않은 하네스 변경.
- 복사본이 원본보다 5분 이상 낡음 → INFO 1줄 집계(건수·최대 지연). WARNING 이 아닌 이유:
  복사본은 SessionStart/End 훅에서만 갱신되는데 원본은 상태(busy/idle) 변경마다 다시 써져
  정상 운영에서도 늘 몇 건은 낡다(2026-09-07 실측: 42 건 중 6 건 >5분, 최대 10분). key 는
  바뀌지 않아 주소 지정엔 무해하고 다른 프로필의 `ListAgents` 에 이름·상태만 구식으로 보인다.
  spec 의 신선도 워처(Phase 2) 필요를 판단하는 관측 신호.

정상이면 finding 없음(✓). "N 세션 · M 프로필" 요약은 lib 의 `status` 가 보여 준다.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.checks.hook_integrity import discover_claude_settings

HOOK_MARKER = "session_bridge.py"
HOOK_EVENTS = ("SessionStart", "SessionEnd")
# 하네스 레코드 파일명 — lib 의 JSON_RE/KEY_RE 와 동일해야 같은 것을 본다.
JSON_RE = re.compile(r"^(\d+)\.json$")
KEY_RE = re.compile(r"^(\d+)\.[0-9a-f]{64}\.key$")
EXPECTED_PEER_PROTOCOL = 1
STALE_THRESHOLD_S = 300.0


def state_dir(home: Path) -> Path:
    """lib 의 기본 state dir(훅 런타임의 `CC_SESSION_BRIDGE_STATE_DIR` override 는 미반영)."""
    return home / ".config" / "cc-inspect" / ".session-bridge"


def default_lib(home: Path) -> Path:
    return home / ".config" / "cc-inspect" / "lib" / "session_bridge.py"


def sessions_dir(home: Path, profile: str) -> Path:
    return home / f".{profile}" / "sessions"


def pid_alive(pid: int) -> bool:
    """lib 의 pid_alive 미러 — 시그널 0. 권한 없음 = 존재."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wired_lib_path(settings: dict[str, Any]) -> str | None:
    """SessionStart/SessionEnd 훅 중 session_bridge.py 를 부르는 command 의 lib 경로.

    미배선 → None. 배선됐는데 경로 토큰을 못 찾으면 ''(배선은 인정, 경로는 기본값으로).
    """
    hooks_root = settings.get("hooks")
    if not isinstance(hooks_root, dict):
        return None
    for event in HOOK_EVENTS:
        groups = hooks_root.get(event)
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for h in group.get("hooks", []) or []:
                if not isinstance(h, dict):
                    continue
                cmd = h.get("command")
                if not isinstance(cmd, str) or HOOK_MARKER not in cmd:
                    continue
                return next((tok for tok in cmd.split() if tok.endswith(HOOK_MARKER)), "")
    return None


def wired_profiles(home: Path) -> dict[str, str]:
    """{profile: lib 경로('' = 미상)} — 배선된 프로필만. settings 파싱 실패는 미배선으로 본다."""
    out: dict[str, str] = {}
    for settings_path in discover_claude_settings(home):
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        lib = wired_lib_path(data)
        if lib is not None:
            out[settings_path.parent.name.lstrip(".")] = lib
    return out


def bridge_profiles(home: Path) -> list[str]:
    """대상 프로필(점 없는 이름). lib 와 같은 우선순위: state_dir/profiles → `~/.claude*` 전부."""
    try:
        lines = (state_dir(home) / "profiles").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    names = [ln.strip().lstrip(".") for ln in lines if ln.strip() and not ln.startswith("#")]
    if names:
        return names
    return [d.name.lstrip(".") for d in sorted(home.glob(".claude*")) if d.is_dir()]


def record_pairs(d: Path) -> dict[int, tuple[Path, Path]]:
    """완전한 레코드 쌍만 {pid: (json, key)} — lib 의 record_pairs 미러(반쪽 레코드는 제외)."""
    try:
        entries = list(d.iterdir())
    except OSError:
        return {}
    jsons: dict[int, Path] = {}
    keys: dict[int, Path] = {}
    for p in entries:
        m = JSON_RE.match(p.name)
        if m and p.is_file():
            jsons[int(m.group(1))] = p
            continue
        m = KEY_RE.match(p.name)
        if m and p.is_file():
            keys[int(m.group(1))] = p
    return {pid: (jsons[pid], keys[pid]) for pid in jsons if pid in keys}


def load_manifest_copies(path: Path) -> tuple[list[dict[str, Any]], bool]:
    """(copies 행, 파싱 실패 여부). 부재 → ([], False): sync 가 아직 안 돈 것이지 고장이 아니다."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], False
    except OSError:
        return [], True
    try:
        data = json.loads(raw)
    except ValueError:
        return [], True
    if not isinstance(data, dict) or not isinstance(data.get("copies"), list):
        return [], True
    return [r for r in data["copies"] if isinstance(r, dict)], False


def stale_copies(
    rows: list[dict[str, Any]], threshold_s: float = STALE_THRESHOLD_S
) -> tuple[int, float]:
    """원본보다 threshold 이상 낡은 복사본 (건수, 최대 지연 초). 한쪽이 없는 행은 건너뛴다."""
    n, worst = 0, 0.0
    for r in rows:
        src, dst = r.get("src"), r.get("path")
        if not isinstance(src, str) or not isinstance(dst, str):
            continue
        try:
            lag = os.stat(src).st_mtime - os.stat(dst).st_mtime
        except OSError:
            continue
        if lag > threshold_s:
            n += 1
            worst = max(worst, lag)
    return n, worst


def _read_record(path: Path) -> dict[str, Any] | None:
    """원본 레코드 JSON. 반쯤 써진 파일 등 파싱 실패 → None(판정 보류)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@dataclass
class _Original:
    pid: int
    profile: str
    json_path: Path
    key_name: str


class SessionBridgeCheck:
    """L2(read-only): ccinspector session-bridge 가 세션을 프로필 경계 너머로 보이게 하는지 관측."""

    name = "session-bridge"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        home = Path.home()
        wired = wired_profiles(home)
        if not wired:
            return []  # 모듈 off / ccinspector 미설치 → N/A
        lib = next((p for p in wired.values() if p), str(default_lib(home)))
        sync_cmd = f"python3 {lib} sync"
        active = [p for p in bridge_profiles(home) if sessions_dir(home, p).is_dir()]
        results: list[CheckResult] = []

        unwired = [p for p in active if p not in wired]
        if unwired:
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"session-bridge 훅이 프로필 {', '.join(unwired)} 에 배선되지 않음 — "
                        "그 프로필 세션의 SessionStart 동기화·SessionEnd 회수가 돌지 않는다"
                    ),
                    suggestion=(
                        "ccinspector install.sh 재실행 (cc-inspect.conf module_session_bridge=1, "
                        "profiles 에 해당 프로필 포함)"
                    ),
                )
            )

        manifest = state_dir(home) / "manifest.json"
        rows, broken = load_manifest_copies(manifest)
        if broken:
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message="session-bridge manifest 파싱 실패 — 원본/복사본 구분 불가",
                    location=manifest,
                    suggestion=f"내용 확인 후 {sync_cmd} (manifest 재작성)",
                )
            )
        copy_paths = {r["path"] for r in rows if isinstance(r.get("path"), str)}

        originals = [
            _Original(pid, p, js, key.name)
            for p in active
            for pid, (js, key) in record_pairs(sessions_dir(home, p)).items()
            if str(js) not in copy_paths
        ]
        if rows and not originals:
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"session-bridge manifest 에 복사본 {len(rows)} 건이 있는데 인식되는 "
                        "원본 레코드 쌍이 하나도 없음 — 하네스 레코드 형식 변경 의심"
                    ),
                    location=manifest,
                    suggestion=(
                        f"python3 {lib} status --check 로 대조; 형식이 바뀌었으면 ccinspector "
                        "session-bridge 갱신 전까지 프로필 간 메시징 불가"
                    ),
                )
            )

        protocols: Counter[str] = Counter()
        for o in originals:
            if not pid_alive(o.pid):
                continue  # 죽은 원본은 다음 reconcile 몫
            missing = [
                q
                for q in active
                if q != o.profile
                and not (
                    (sessions_dir(home, q) / o.json_path.name).is_file()
                    and (sessions_dir(home, q) / o.key_name).is_file()
                )
            ]
            data = _read_record(o.json_path)
            name = data.get("name") if data else None
            label = f"'{name}'" if isinstance(name, str) and name else "(이름 없음)"
            if missing:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=(
                            f"세션 {label}(pid {o.pid}, {o.profile}) 이 프로필 "
                            f"{', '.join(missing)} 에서 안 보임 — 그 프로필 세션의 ListAgents 에 "
                            "없고 SendMessage 가 닿지 않는다"
                        ),
                        location=o.json_path,
                        suggestion=f"{sync_cmd} (전체 reconcile, 멱등)",
                    )
                )
            if data is not None:
                proto = data.get("peerProtocol")
                if proto != EXPECTED_PEER_PROTOCOL:
                    protocols["없음" if proto is None else str(proto)] += 1
        for value, n in sorted(protocols.items()):
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"peerProtocol≠{EXPECTED_PEER_PROTOCOL} 원본 레코드 {n} 건(값 {value}) — "
                        f"브리지는 protocol {EXPECTED_PEER_PROTOCOL} 로만 검증됨: "
                        "검증되지 않은 하네스 변경"
                    ),
                    suggestion=(
                        "프로필 간 SendMessage 왕복을 수동 확인하고 ccinspector session-bridge "
                        "spec 의 실측 표를 갱신"
                    ),
                )
            )

        n_stale, worst = stale_copies(rows)
        if n_stale:
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"session-bridge 복사본 {n_stale} 건이 원본보다 5분 이상 낡음"
                        f"(최대 {worst / 60:.0f}분) — 다음 SessionStart/SessionEnd 훅까지 다른 "
                        "프로필의 ListAgents 에 이름·상태가 구식으로 보인다"
                    ),
                    suggestion=f"{sync_cmd} (즉시 갱신); 잦으면 복사본 신선도 워처 검토",
                )
            )
        return results

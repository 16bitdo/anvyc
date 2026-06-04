# AWS 계정 인증/연결 상태 점검 — Phase 1 (보고, 읽기 전용) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 프로젝트가 쓰는 AWS profile 의 인증 방식(SSO/static/assume-role/credential_process/web_identity)과 연결 상태를 `anvyc doctor`·`anvyc project doctor`·`anvyc aws profile list/show` 로 보고한다(읽기 전용, doctor 는 offline; 진짜 liveness 는 `--probe` opt-in).

**Architecture:** 순수 오프라인 코어 `core/aws_profile_state.py`(네트워크 0)가 profile→상태를 판정하고, 전역 체크(`aws-account-status`)·project 체크(`aws_account_status`)·CLI(`aws profile`)가 이를 공유한다. SSO 캐시 파싱은 기존 `core/creds.py:detect_aws_sso` 를 재사용한다. 네트워크 probe 는 `core/aws_probe.py` 로 물리적 분리해 doctor 가 구조적으로 offline 임을 보장한다.

**Tech Stack:** Python 3.13, Typer(CLI), `configparser`(INI 파싱), `pytest`+`typer.testing.CliRunner`, `subprocess`(probe).

**Spec:** `docs/superpowers/specs/2026-06-04-aws-profile-and-sso-status-design.md` (§4 아키텍처, §5 상태→결과 매핑, §6.1 조회 명령, §9 Phase 1).

**구현 정밀화 메모(spec 대비)**:
- spec §6 의 `--aws-config` 플래그는 **드롭** — 테스트는 기존 컨벤션(`HOME` monkeypatch + `~/.aws/*` 구성)으로 격리한다(단일파일 override 의 비일관 회피).
- spec §5 의 "static, 키 없음 → WARNING" 은 **`incomplete` 로 흡수** — static 은 키가 실제 존재할 때만 탐지되므로 항상 `present`(INFO); 인증키가 전무한 config 섹션은 `incomplete`(WARNING)가 담당.
- `~/.aws/credentials` 는 **섹션 이름만** 읽는다(값=시크릿 미독). 따라서 credentials 에만 있는 `aws_session_token`(임시 자격)은 `static` 으로 분류(static_temporary 는 config 의 `aws_session_token` 키로만 탐지) — 임시 자격은 신뢰할 만료 필드가 없어 무해한 degradation.

---

## File Structure

**신규 파일**
- `src/anvyc/core/aws_profile_state.py` — `AUTH_*`/`TOKEN_NONE` 상수, `AwsProfileState` dataclass, `detect_auth_method()`, `evaluate_profile_state()`, `state_to_result()`. **네트워크 의존 0.**
- `src/anvyc/core/aws_probe.py` — `ProbeResult` dataclass, `probe_caller_identity()`(subprocess → `aws sts get-caller-identity`). CLI `--probe` 전용.
- `src/anvyc/checks/aws_account_status.py` — `AwsAccountStatusCheck`(전역 doctor 체크).
- 테스트: `tests/unit/test_aws_config_profile.py`, `tests/unit/test_aws_profile_state.py`, `tests/unit/test_aws_account_status_check.py`, `tests/unit/test_project_doctor_aws_account.py`, `tests/unit/test_aws_probe.py`, `tests/unit/test_aws_profile_cli.py`.

**수정 파일**
- `src/anvyc/utils/aws_config.py` — `DEFAULT_AWS_CREDENTIALS` 상수 + `load_profile_config()`·`load_profile_sso_meta()`·`load_credentials_profile_names()`.
- `src/anvyc/core/doctor.py` — `_REGISTRY` 에 `"aws-account-status"` 등록.
- `src/anvyc/core/project_doctor.py` — `_check_aws_account_status()` 추가 + `run_project_doctor()` wire(8→9 체크).
- `src/anvyc/cli.py` — `aws_app`/`aws_profile_app` 등록 + `list`/`show` 명령.
- 문서: `README.md`, `docs/multi-account.md`, `docs/doctor-json-schema.md`, `docs/design-axes/cp-05-creds.md`, `DESIGN.md`, `CONTEXT.md`, `RELEASE_NOTES.md`.

**시그니처 계약(전 태스크 공유)**
```python
# utils/aws_config.py
load_profile_config(profile: str, path: Path | None = None) -> dict[str, str] | None
load_profile_sso_meta(profile: str, path: Path | None = None) -> tuple[str | None, str | None] | None
load_credentials_profile_names(path: Path | None = None) -> set[str]
# core/aws_profile_state.py
detect_auth_method(keys: dict[str, str], *, has_static: bool) -> str
evaluate_profile_state(profile: str, *, home: Path | None = None, now: datetime | None = None) -> AwsProfileState
state_to_result(state: AwsProfileState, *, check_name: str) -> CheckResult | None
# core/aws_probe.py
probe_caller_identity(profile: str, *, timeout: float = 8.0) -> ProbeResult
```
상태 문자열: SSO=`valid|expiring|expired|unknown|none`, assume_role=`source_ok|source_missing|env`, credential_process=`cmd_ok|cmd_missing`, web_identity=`classified`, static/static_temporary=`present`, undefined=`missing`, incomplete=`incomplete`.

---

## Task 1: `load_profile_config` — `~/.aws/config` 섹션 키 조회

**Files:**
- Modify: `src/anvyc/utils/aws_config.py`
- Test: `tests/unit/test_aws_config_profile.py`

- [ ] **Step 1: Write the failing test**

```python
"""utils/aws_config — profile 섹션/credentials/sso meta 조회."""
from pathlib import Path

from anvyc.utils.aws_config import load_profile_config


def test_profile_config_named(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "[profile ws-dev]\nregion = ap-northeast-2\nsso_session = ws\n", encoding="utf-8"
    )
    keys = load_profile_config("ws-dev", cfg)
    assert keys == {"region": "ap-northeast-2", "sso_session": "ws"}


def test_profile_config_default_section(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text("[default]\nregion = us-east-1\n", encoding="utf-8")
    assert load_profile_config("default", cfg) == {"region": "us-east-1"}


def test_profile_config_missing_profile(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text("[profile a]\nregion = x\n", encoding="utf-8")
    assert load_profile_config("nope", cfg) is None


def test_profile_config_missing_file(tmp_path: Path) -> None:
    assert load_profile_config("a", tmp_path / "none") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_config_profile.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_profile_config'`.

- [ ] **Step 3: Add the implementation**

`src/anvyc/utils/aws_config.py` 끝에 추가:
```python
def load_profile_config(profile: str, path: Path | None = None) -> dict[str, str] | None:
    """`[profile X]`(또는 `[default]`) 섹션의 key→value. profile 부재/파싱 실패 → None."""
    target = path or DEFAULT_AWS_CONFIG
    if not target.is_file():
        return None
    cp = configparser.RawConfigParser()
    try:
        cp.read(target, encoding="utf-8")
    except (OSError, configparser.Error):
        return None
    section = "default" if profile == "default" else f"{_PROFILE_PREFIX}{profile}"
    if not cp.has_section(section):
        return None
    return dict(cp.items(section))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_aws_config_profile.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/utils/aws_config.py tests/unit/test_aws_config_profile.py
git commit -m "feat(aws): load_profile_config — ~/.aws/config 섹션 키 조회"
```

---

## Task 2: `load_credentials_profile_names` — `~/.aws/credentials` 섹션 이름(값 미독)

**Files:**
- Modify: `src/anvyc/utils/aws_config.py`
- Test: `tests/unit/test_aws_config_profile.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_config_profile.py` 에 추가 (상단 import 에 `load_credentials_profile_names` 추가):
```python
from anvyc.utils.aws_config import load_credentials_profile_names


def test_credentials_names(tmp_path: Path) -> None:
    creds = tmp_path / "credentials"
    creds.write_text(
        "[default]\naws_access_key_id = AKIA_X\n\n[legacy]\naws_access_key_id = AKIA_Y\n",
        encoding="utf-8",
    )
    assert load_credentials_profile_names(creds) == {"default", "legacy"}


def test_credentials_missing_file(tmp_path: Path) -> None:
    assert load_credentials_profile_names(tmp_path / "none") == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_config_profile.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_credentials_profile_names'`.

- [ ] **Step 3: Add the implementation**

`src/anvyc/utils/aws_config.py` 의 상단 상수 영역(`DEFAULT_AWS_CONFIG` 아래)에 추가:
```python
DEFAULT_AWS_CREDENTIALS = Path("~/.aws/credentials").expanduser()
```
파일 끝에 함수 추가:
```python
def load_credentials_profile_names(path: Path | None = None) -> set[str]:
    """`~/.aws/credentials` 의 `[name]` 섹션 이름 집합. **값(시크릿)은 읽지 않음.**

    config 와 달리 섹션이 `[profilename]` (접두사 'profile ' 없음). 부재/파싱 실패 → 빈 set.
    """
    target = path or DEFAULT_AWS_CREDENTIALS
    if not target.is_file():
        return set()
    cp = configparser.RawConfigParser()
    try:
        cp.read(target, encoding="utf-8")
    except (OSError, configparser.Error):
        return set()
    return set(cp.sections())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_aws_config_profile.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/utils/aws_config.py tests/unit/test_aws_config_profile.py
git commit -m "feat(aws): load_credentials_profile_names — credentials 섹션 이름(값 미독)"
```

---

## Task 3: `load_profile_sso_meta` — profile → (sso_session, sso_start_url) 역추적

**Files:**
- Modify: `src/anvyc/utils/aws_config.py`
- Test: `tests/unit/test_aws_config_profile.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_config_profile.py` 에 추가 (import 에 `load_profile_sso_meta` 추가):
```python
from anvyc.utils.aws_config import load_profile_sso_meta


def test_sso_meta_modern(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "[sso-session ws]\nsso_start_url = https://d-x.awsapps.com/start\n\n"
        "[profile dev]\nsso_session = ws\n",
        encoding="utf-8",
    )
    assert load_profile_sso_meta("dev", cfg) == ("ws", "https://d-x.awsapps.com/start")


def test_sso_meta_legacy_direct(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "[profile old]\nsso_start_url = https://leg.awsapps.com/start\n", encoding="utf-8"
    )
    assert load_profile_sso_meta("old", cfg) == (None, "https://leg.awsapps.com/start")


def test_sso_meta_non_sso(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text("[profile plain]\nregion = ap-northeast-2\n", encoding="utf-8")
    assert load_profile_sso_meta("plain", cfg) is None


def test_sso_meta_missing_profile(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text("[profile a]\nregion = x\n", encoding="utf-8")
    assert load_profile_sso_meta("nope", cfg) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_config_profile.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_profile_sso_meta'`.

- [ ] **Step 3: Add the implementation**

`src/anvyc/utils/aws_config.py` 파일 끝에 추가:
```python
def load_profile_sso_meta(
    profile: str, path: Path | None = None
) -> tuple[str | None, str | None] | None:
    """profile → (sso_session, sso_start_url). 비-SSO → None.

    신형: `sso_session=S` → `[sso-session S]` 의 sso_start_url 해석.
    구형: profile 의 sso_start_url 직접 → (None, url).
    """
    keys = load_profile_config(profile, path)
    if keys is None:
        return None
    session = keys.get("sso_session")
    if session:
        target = path or DEFAULT_AWS_CONFIG
        cp = configparser.RawConfigParser()
        try:
            cp.read(target, encoding="utf-8")
        except (OSError, configparser.Error):
            return (session, None)
        sec = f"{_SSO_SESSION_PREFIX}{session}"
        url = cp.get(sec, "sso_start_url", fallback=None) if cp.has_section(sec) else None
        return (session, url)
    direct = keys.get("sso_start_url")
    if direct:
        return (None, direct)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_aws_config_profile.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/utils/aws_config.py tests/unit/test_aws_config_profile.py
git commit -m "feat(aws): load_profile_sso_meta — profile→(sso_session, start_url) 역추적"
```

---

## Task 4: `AwsProfileState` + `detect_auth_method`

**Files:**
- Create: `src/anvyc/core/aws_profile_state.py`
- Test: `tests/unit/test_aws_profile_state.py`

- [ ] **Step 1: Write the failing test**

```python
"""core/aws_profile_state — 인증 방식 탐지 + profile 상태 판정."""
from anvyc.core.aws_profile_state import (
    AUTH_ASSUME_ROLE,
    AUTH_CREDENTIAL_PROCESS,
    AUTH_INCOMPLETE,
    AUTH_SSO,
    AUTH_STATIC,
    AUTH_STATIC_TEMP,
    AUTH_WEB_IDENTITY,
    detect_auth_method,
)


def test_detect_sso() -> None:
    assert detect_auth_method({"sso_session": "ws"}, has_static=False) == AUTH_SSO
    assert detect_auth_method({"sso_start_url": "u"}, has_static=False) == AUTH_SSO


def test_detect_assume_role() -> None:
    keys = {"role_arn": "arn:...", "source_profile": "base"}
    assert detect_auth_method(keys, has_static=False) == AUTH_ASSUME_ROLE


def test_detect_credential_process() -> None:
    assert detect_auth_method({"credential_process": "aws-vault exec x"}, has_static=False) == AUTH_CREDENTIAL_PROCESS


def test_detect_web_identity() -> None:
    assert detect_auth_method({"web_identity_token_file": "/t"}, has_static=False) == AUTH_WEB_IDENTITY


def test_detect_static_and_temp() -> None:
    assert detect_auth_method({}, has_static=True) == AUTH_STATIC
    assert detect_auth_method({"aws_session_token": "x"}, has_static=True) == AUTH_STATIC_TEMP


def test_detect_incomplete() -> None:
    assert detect_auth_method({"region": "us-east-1"}, has_static=False) == AUTH_INCOMPLETE


def test_detect_precedence_sso_over_static() -> None:
    # sso_session + 정적 키가 공존해도 SSO 우선.
    assert detect_auth_method({"sso_session": "ws"}, has_static=True) == AUTH_SSO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_profile_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.aws_profile_state'`.

- [ ] **Step 3: Create the module**

`src/anvyc/core/aws_profile_state.py`:
```python
"""AWS profile 인증 방식 + 연결 상태 판정 (읽기 전용, **네트워크 의존 0**).

doctor / project doctor / `aws profile` 가 공유하는 순수 코어. SSO 캐시 파싱은
`core/creds.py:detect_aws_sso` 를 재사용한다. 네트워크 liveness probe 는
`core/aws_probe.py` 로 분리(이 모듈은 import 하지 않음) → doctor 가 구조적으로 offline.
"""
from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from anvyc.checks.base import CheckResult, Severity
from anvyc.core.creds import (
    AWS_SSO_WARN_DAYS,
    STATUS_EXPIRED,
    STATUS_EXPIRING,
    STATUS_UNKNOWN,
    STATUS_VALID,
    detect_aws_sso,
)
from anvyc.utils.aws_config import (
    load_aws_profile_names,
    load_credentials_profile_names,
    load_profile_config,
    load_profile_sso_meta,
)

AUTH_UNDEFINED = "undefined"
AUTH_SSO = "sso"
AUTH_STATIC = "static"
AUTH_STATIC_TEMP = "static_temporary"
AUTH_ASSUME_ROLE = "assume_role"
AUTH_CREDENTIAL_PROCESS = "credential_process"
AUTH_WEB_IDENTITY = "web_identity"
AUTH_INCOMPLETE = "incomplete"

TOKEN_NONE = "none"  # SSO profile 인데 캐시 토큰 없음(미로그인)


@dataclass
class AwsProfileState:
    profile: str
    defined: bool
    auth_method: str = AUTH_UNDEFINED
    status: str = ""
    sso_session: str | None = None
    expires_at: str | None = None
    expires_in_seconds: int | None = None
    source_profile: str | None = None
    credential_process_cmd: str | None = None
    token_file_exists: bool | None = None


def detect_auth_method(keys: dict[str, str], *, has_static: bool) -> str:
    """profile 섹션 키 + 정적 자격 존재 여부로 인증 방식 분류 (AWS SDK 해석 우선순위 정합)."""
    if "sso_session" in keys or "sso_start_url" in keys:
        return AUTH_SSO
    if "role_arn" in keys and ("source_profile" in keys or "credential_source" in keys):
        return AUTH_ASSUME_ROLE
    if "credential_process" in keys:
        return AUTH_CREDENTIAL_PROCESS
    if "web_identity_token_file" in keys:
        return AUTH_WEB_IDENTITY
    if has_static or "aws_access_key_id" in keys:
        return AUTH_STATIC_TEMP if "aws_session_token" in keys else AUTH_STATIC
    return AUTH_INCOMPLETE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_aws_profile_state.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/aws_profile_state.py tests/unit/test_aws_profile_state.py
git commit -m "feat(aws): AwsProfileState + detect_auth_method (인증 방식 분류)"
```

---

## Task 5: `evaluate_profile_state` — 방식별 오프라인 상태 판정

**Files:**
- Modify: `src/anvyc/core/aws_profile_state.py`
- Test: `tests/unit/test_aws_profile_state.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_profile_state.py` 에 추가 (import 에 `evaluate_profile_state`, `AUTH_UNDEFINED`, `TOKEN_NONE` 추가, 상단에 `import json`·`from datetime import UTC, datetime`·`from pathlib import Path`):
```python
import json
from datetime import UTC, datetime
from pathlib import Path

from anvyc.core.aws_profile_state import AUTH_UNDEFINED, TOKEN_NONE, evaluate_profile_state

_NOW = datetime(2026, 6, 4, tzinfo=UTC)


def _home(tmp_path: Path, config: str = "", credentials: str = "") -> Path:
    aws = tmp_path / ".aws"
    aws.mkdir(parents=True)
    if config:
        (aws / "config").write_text(config, encoding="utf-8")
    if credentials:
        (aws / "credentials").write_text(credentials, encoding="utf-8")
    return tmp_path


def _write_sso_cache(home: Path, start_url: str, expires_at: str) -> None:
    cache = home / ".aws" / "sso" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "tok.json").write_text(
        json.dumps({"startUrl": start_url, "expiresAt": expires_at}), encoding="utf-8"
    )


def test_eval_undefined(tmp_path: Path) -> None:
    home = _home(tmp_path, "[profile other]\nregion = x\n")
    st = evaluate_profile_state("ghost", home=home, now=_NOW)
    assert st.defined is False
    assert st.auth_method == AUTH_UNDEFINED


def test_eval_sso_valid(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n"
        "[profile dev]\nsso_session = ws\n",
    )
    _write_sso_cache(home, "https://u/start", "2026-06-05T00:00:00Z")  # +1d → valid
    st = evaluate_profile_state("dev", home=home, now=_NOW)
    assert st.auth_method == "sso"
    assert st.status == "valid"
    assert st.sso_session == "ws"


def test_eval_sso_expired(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n[profile dev]\nsso_session = ws\n",
    )
    _write_sso_cache(home, "https://u/start", "2026-06-03T00:00:00Z")  # -1d → expired
    st = evaluate_profile_state("dev", home=home, now=_NOW)
    assert st.status == "expired"


def test_eval_sso_not_logged_in(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n[profile dev]\nsso_session = ws\n",
    )
    # 캐시 디렉터리 없음 → 미로그인
    st = evaluate_profile_state("dev", home=home, now=_NOW)
    assert st.status == TOKEN_NONE


def test_eval_static(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile legacy]\nregion = us-east-1\n",
        credentials="[legacy]\naws_access_key_id = AKIA_X\n",
    )
    st = evaluate_profile_state("legacy", home=home, now=_NOW)
    assert st.auth_method == "static"
    assert st.status == "present"


def test_eval_assume_role_source_ok(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile base]\nregion = x\n\n[profile deploy]\nrole_arn = arn:aws:iam::1:role/r\nsource_profile = base\n",
    )
    st = evaluate_profile_state("deploy", home=home, now=_NOW)
    assert st.auth_method == "assume_role"
    assert st.status == "source_ok"
    assert st.source_profile == "base"


def test_eval_assume_role_source_missing(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile deploy]\nrole_arn = arn:aws:iam::1:role/r\nsource_profile = gone\n",
    )
    st = evaluate_profile_state("deploy", home=home, now=_NOW)
    assert st.status == "source_missing"


def test_eval_credential_process_missing(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile vault]\ncredential_process = /no/such/bin-xyz exec x\n",
    )
    st = evaluate_profile_state("vault", home=home, now=_NOW)
    assert st.auth_method == "credential_process"
    assert st.status == "cmd_missing"


def test_eval_web_identity(tmp_path: Path) -> None:
    home = _home(
        tmp_path,
        "[profile oidc]\nrole_arn = arn:aws:iam::1:role/r\nweb_identity_token_file = /no/token\n",
    )
    st = evaluate_profile_state("oidc", home=home, now=_NOW)
    assert st.auth_method == "web_identity"
    assert st.token_file_exists is False


def test_eval_incomplete(tmp_path: Path) -> None:
    home = _home(tmp_path, "[profile bare]\nregion = us-east-1\n")
    st = evaluate_profile_state("bare", home=home, now=_NOW)
    assert st.auth_method == "incomplete"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_profile_state.py -v`
Expected: FAIL — `ImportError: cannot import name 'evaluate_profile_state'`.

- [ ] **Step 3: Add the implementation**

`src/anvyc/core/aws_profile_state.py` 끝에 추가:
```python
def evaluate_profile_state(
    profile: str, *, home: Path | None = None, now: datetime | None = None
) -> AwsProfileState:
    """profile 의 인증 방식과 오프라인 상태를 판정한다 (네트워크 호출 없음)."""
    home = home or Path.home()
    now = now or datetime.now(UTC)
    config_path = home / ".aws" / "config"
    creds_path = home / ".aws" / "credentials"

    if profile not in load_aws_profile_names(config_path):
        return AwsProfileState(profile=profile, defined=False, auth_method=AUTH_UNDEFINED, status="missing")

    keys = load_profile_config(profile, config_path) or {}
    has_static = (profile in load_credentials_profile_names(creds_path)) or ("aws_access_key_id" in keys)
    method = detect_auth_method(keys, has_static=has_static)
    st = AwsProfileState(profile=profile, defined=True, auth_method=method)

    if method == AUTH_SSO:
        meta = load_profile_sso_meta(profile, config_path) or (None, None)
        st.sso_session, start_url = meta
        if not start_url:
            st.status = STATUS_UNKNOWN
            return st
        by_url = {
            c.identifier: c
            for c in detect_aws_sso(home, warn_threshold_days=AWS_SSO_WARN_DAYS, now=now)
        }
        cred = by_url.get(start_url)
        if cred is None:
            st.status = TOKEN_NONE
        else:
            st.status = cred.status
            st.expires_at = cred.expires_at
            st.expires_in_seconds = cred.expires_in_seconds
        return st

    if method == AUTH_ASSUME_ROLE:
        src = keys.get("source_profile")
        if src:
            st.source_profile = src
            st.status = "source_ok" if src in load_aws_profile_names(config_path) else "source_missing"
        else:
            st.status = "env"
        return st

    if method == AUTH_CREDENTIAL_PROCESS:
        cmd = keys.get("credential_process", "")
        st.credential_process_cmd = cmd
        first = shlex.split(cmd)[0] if cmd.strip() else ""
        st.status = "cmd_ok" if (first and shutil.which(first)) else "cmd_missing"
        return st

    if method == AUTH_WEB_IDENTITY:
        tf = keys.get("web_identity_token_file", "")
        st.token_file_exists = bool(tf) and Path(tf).expanduser().is_file()
        st.status = "classified"
        return st

    if method in (AUTH_STATIC, AUTH_STATIC_TEMP):
        st.status = "present"
        return st

    st.status = "incomplete"
    return st
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_aws_profile_state.py -v`
Expected: PASS (17 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/aws_profile_state.py tests/unit/test_aws_profile_state.py
git commit -m "feat(aws): evaluate_profile_state — 방식별 오프라인 상태 판정 (SSO 캐시 재사용)"
```

---

## Task 6: `state_to_result` — 상태 → CheckResult 매퍼 (≤WARNING)

**Files:**
- Modify: `src/anvyc/core/aws_profile_state.py`
- Test: `tests/unit/test_aws_profile_state.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_profile_state.py` 에 추가 (import 에 `state_to_result`, `AwsProfileState`, `AUTH_*` 보강, `from anvyc.checks.base import Severity`):
```python
from anvyc.checks.base import Severity
from anvyc.core.aws_profile_state import (
    AUTH_ASSUME_ROLE,
    AUTH_CREDENTIAL_PROCESS,
    AUTH_INCOMPLETE,
    AwsProfileState,
    state_to_result,
)

CN = "aws-account-status"


def test_result_undefined_warns() -> None:
    st = AwsProfileState(profile="ghost", defined=False, auth_method=AUTH_UNDEFINED, status="missing")
    r = state_to_result(st, check_name=CN)
    assert r is not None and r.severity is Severity.WARNING
    assert r.check_name == CN and "미정의" in r.message


def test_result_sso_valid_info() -> None:
    st = AwsProfileState(profile="dev", defined=True, auth_method="sso", status="valid", sso_session="ws")
    r = state_to_result(st, check_name=CN)
    assert r is not None and r.severity is Severity.INFO and "연결됨" in r.message


def test_result_sso_none_warns() -> None:
    st = AwsProfileState(profile="dev", defined=True, auth_method="sso", status=TOKEN_NONE, sso_session="ws")
    r = state_to_result(st, check_name=CN)
    assert r is not None and r.severity is Severity.WARNING and "미로그인" in r.message
    assert "aws sso login --profile dev" in (r.suggestion or "")


def test_result_sso_never_critical() -> None:
    # 만료여도 ≤WARNING (CRITICAL 은 creds-expiry 소유).
    st = AwsProfileState(profile="dev", defined=True, auth_method="sso", status="expired", sso_session="ws")
    r = state_to_result(st, check_name=CN)
    assert r is not None and r.severity is Severity.WARNING


def test_result_static_info() -> None:
    st = AwsProfileState(profile="legacy", defined=True, auth_method="static", status="present")
    r = state_to_result(st, check_name=CN)
    assert r is not None and r.severity is Severity.INFO


def test_result_assume_role_missing_warns() -> None:
    st = AwsProfileState(profile="deploy", defined=True, auth_method=AUTH_ASSUME_ROLE, status="source_missing", source_profile="gone")
    r = state_to_result(st, check_name=CN)
    assert r is not None and r.severity is Severity.WARNING and "gone" in r.message


def test_result_credential_process_missing_warns() -> None:
    st = AwsProfileState(profile="v", defined=True, auth_method=AUTH_CREDENTIAL_PROCESS, status="cmd_missing", credential_process_cmd="x exec")
    r = state_to_result(st, check_name=CN)
    assert r is not None and r.severity is Severity.WARNING


def test_result_incomplete_warns() -> None:
    st = AwsProfileState(profile="bare", defined=True, auth_method=AUTH_INCOMPLETE, status="incomplete")
    r = state_to_result(st, check_name=CN)
    assert r is not None and r.severity is Severity.WARNING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_profile_state.py -v`
Expected: FAIL — `ImportError: cannot import name 'state_to_result'`.

- [ ] **Step 3: Add the implementation**

`src/anvyc/core/aws_profile_state.py` 끝에 추가:
```python
def state_to_result(state: AwsProfileState, *, check_name: str) -> CheckResult | None:
    """AwsProfileState → CheckResult. CRITICAL 미발행(만료 escalation 은 creds-expiry)."""
    m, s, p = state.auth_method, state.status, state.profile

    if m == AUTH_UNDEFINED:
        return CheckResult(
            check_name=check_name, severity=Severity.WARNING,
            message=f"AWS profile '{p}' 가 ~/.aws/config 에 미정의",
            suggestion=f"anvyc aws profile create {p} --sso ... (또는 .envrc AWS_PROFILE 수정)",
        )

    if m == AUTH_SSO:
        sess = f", session {state.sso_session}" if state.sso_session else ""
        if s in (STATUS_VALID, STATUS_EXPIRING):
            return CheckResult(check_name=check_name, severity=Severity.INFO, message=f"SSO 연결됨 '{p}'{sess}")
        if s == STATUS_EXPIRED:
            return CheckResult(
                check_name=check_name, severity=Severity.WARNING,
                message=f"SSO 세션 만료 '{p}'{sess} — 재로그인 필요",
                suggestion=f"aws sso login --profile {p}",
            )
        if s == TOKEN_NONE:
            return CheckResult(
                check_name=check_name, severity=Severity.WARNING,
                message=f"미로그인 '{p}'{sess} — SSO 로그인 필요",
                suggestion=f"aws sso login --profile {p}",
            )
        return CheckResult(check_name=check_name, severity=Severity.INFO, message=f"SSO 토큰 상태 불명 '{p}'{sess}")

    if m in (AUTH_STATIC, AUTH_STATIC_TEMP):
        kind = "임시 자격" if m == AUTH_STATIC_TEMP else "정적 키"
        return CheckResult(check_name=check_name, severity=Severity.INFO, message=f"{kind} 구성됨 '{p}'")

    if m == AUTH_ASSUME_ROLE:
        if s == "source_ok":
            return CheckResult(check_name=check_name, severity=Severity.INFO, message=f"역할 위임 '{p}' (source: {state.source_profile})")
        if s == "source_missing":
            return CheckResult(
                check_name=check_name, severity=Severity.WARNING,
                message=f"'{p}' 의 source_profile '{state.source_profile}' 미정의",
                suggestion="source profile 생성/수정 (anvyc aws profile)",
            )
        return CheckResult(check_name=check_name, severity=Severity.INFO, message=f"'{p}' 환경 기반 위임 (credential_source)")

    if m == AUTH_CREDENTIAL_PROCESS:
        if s == "cmd_ok":
            return CheckResult(check_name=check_name, severity=Severity.INFO, message=f"credential_process 구성됨 '{p}'")
        return CheckResult(
            check_name=check_name, severity=Severity.WARNING,
            message=f"'{p}' 의 credential_process 명령 미발견: {state.credential_process_cmd}",
            suggestion="해당 도구 설치 / PATH 확인",
        )

    if m == AUTH_WEB_IDENTITY:
        tf = "존재" if state.token_file_exists else "부재"
        return CheckResult(check_name=check_name, severity=Severity.INFO, message=f"web identity '{p}' (token_file {tf})")

    return CheckResult(
        check_name=check_name, severity=Severity.WARNING,
        message=f"'{p}' 인증 구성 불완전 (사용 가능한 자격 키 없음)",
        suggestion="profile 키 보완 (anvyc aws profile edit)",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_aws_profile_state.py -v`
Expected: PASS (25 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/aws_profile_state.py tests/unit/test_aws_profile_state.py
git commit -m "feat(aws): state_to_result — 상태→CheckResult 매퍼 (≤WARNING)"
```

---

## Task 7: 전역 doctor 체크 `aws-account-status` 등록

**Files:**
- Create: `src/anvyc/checks/aws_account_status.py`
- Modify: `src/anvyc/core/doctor.py`
- Test: `tests/unit/test_aws_account_status_check.py`

- [ ] **Step 1: Write the failing test**

```python
"""aws-account-status 전역 doctor 체크 — cwd 프로젝트 scope."""
from pathlib import Path

import pytest

from anvyc.checks.aws_account_status import AwsAccountStatusCheck
from anvyc.checks.base import CheckContext, Severity


def _home(tmp_path: Path, config: str) -> Path:
    aws = tmp_path / ".aws"
    aws.mkdir(parents=True)
    (aws / "config").write_text(config, encoding="utf-8")
    return tmp_path


def test_silent_when_scope_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path, "[profile dev]\nregion = x\n")))
    # scope=None(기본) / frozenset() 모두 silent.
    assert AwsAccountStatusCheck().run(CheckContext()) == []
    assert AwsAccountStatusCheck().run(CheckContext(current_project_aws_profiles=frozenset())) == []


def test_reports_undefined_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path, "[profile other]\nregion = x\n")))
    ctx = CheckContext(current_project_aws_profiles=frozenset({"ghost"}))
    res = AwsAccountStatusCheck().run(ctx)
    assert len(res) == 1
    assert res[0].severity is Severity.WARNING
    assert res[0].check_name == "aws-account-status"
    assert "미정의" in res[0].message


def test_reports_static_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = _home(tmp_path, "[profile legacy]\nregion = us-east-1\n")
    (home / ".aws" / "credentials").write_text("[legacy]\naws_access_key_id = AKIA_X\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    ctx = CheckContext(current_project_aws_profiles=frozenset({"legacy"}))
    res = AwsAccountStatusCheck().run(ctx)
    assert len(res) == 1 and res[0].severity is Severity.INFO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_account_status_check.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.checks.aws_account_status'`.

- [ ] **Step 3: Create the check + register**

`src/anvyc/checks/aws_account_status.py`:
```python
"""aws-account-status check — 현재 프로젝트(cwd scope)가 쓰는 AWS profile 의 인증/연결 상태.

`ctx.current_project_aws_profiles`(doctor 진입 cwd walk-up 으로 주입)에 한정.
scope=None/빈 frozenset → silent(cwd 가 프로젝트 아님/AWS profile 미사용).
read-only·offline — 네트워크 probe 는 `anvyc aws profile --probe` 에서만.
"""
from __future__ import annotations

from anvyc.checks.base import CheckContext, CheckResult
from anvyc.core.aws_profile_state import evaluate_profile_state, state_to_result


class AwsAccountStatusCheck:
    name = "aws-account-status"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        scope = ctx.current_project_aws_profiles
        if not scope:  # None 또는 빈 frozenset → silent
            return []
        out: list[CheckResult] = []
        for prof in sorted(scope):
            res = state_to_result(evaluate_profile_state(prof), check_name=self.name)
            if res is not None:
                out.append(res)
        return out
```

`src/anvyc/core/doctor.py` 수정:
1. import 블록(다른 `from anvyc.checks...` 사이, 알파벳 순 위치)에 추가:
```python
from anvyc.checks.aws_account_status import AwsAccountStatusCheck
```
2. `_REGISTRY` 의 `"aws-profile-status": AwsProfileStatusCheck(),` 줄 **다음**에 추가:
```python
    "aws-account-status": AwsAccountStatusCheck(),
```

- [ ] **Step 4: Run test + doctor 회귀 확인**

Run: `pytest tests/unit/test_aws_account_status_check.py tests/integration/test_doctor_json.py -v`
Expected: PASS. (test_doctor_json 은 check_name 집합/개수를 고정 단언하지 않으므로 영향 없음 — green 확인.)

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/checks/aws_account_status.py src/anvyc/core/doctor.py tests/unit/test_aws_account_status_check.py
git commit -m "feat(doctor): aws-account-status 체크 — cwd 프로젝트 AWS 인증/연결 상태"
```

---

## Task 8: `project doctor` 에 `aws_account_status` 추가 (8→9 체크)

**Files:**
- Modify: `src/anvyc/core/project_doctor.py`
- Test: `tests/unit/test_project_doctor_aws_account.py`

**참고:** project doctor 는 기존 `aws_profile_defined`(정의 여부)를 유지한다. 신규 체크는 **profile 정의됨일 때만** 인증/연결 상태를 보고하고, **미정의는 `aws_profile_defined` 에 위임**(중복 WARNING 회피)한다.

- [ ] **Step 1: Write the failing test**

```python
"""project doctor 의 aws_account_status 체크."""
from pathlib import Path

import pytest

from anvyc.core.project_doctor import run_project_doctor


def _home_with_profile(tmp_path: Path) -> Path:
    aws = tmp_path / "home" / ".aws"
    aws.mkdir(parents=True)
    (aws / "config").write_text(
        "[profile ws-dev]\nregion = ap-northeast-2\n", encoding="utf-8"
    )
    (aws / "credentials").write_text(
        "[ws-dev]\naws_access_key_id = AKIA_X\n", encoding="utf-8"
    )
    return tmp_path / "home"


def test_project_doctor_reports_aws_account_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(_home_with_profile(tmp_path)))
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".envrc").write_text('export AWS_PROFILE="ws-dev"\n', encoding="utf-8")

    report = run_project_doctor(proj)
    names = {r.check_name for r in report.results}
    assert "aws_account_status" in names
    acc = next(r for r in report.results if r.check_name == "aws_account_status")
    assert "ws-dev" in acc.message


def test_project_doctor_no_aws_profile_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(_home_with_profile(tmp_path)))
    proj = tmp_path / "proj2"
    proj.mkdir()
    (proj / ".envrc").write_text('export FOO="bar"\n', encoding="utf-8")

    report = run_project_doctor(proj)
    assert "aws_account_status" not in {r.check_name for r in report.results}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_project_doctor_aws_account.py -v`
Expected: FAIL — `aws_account_status` not in names (AssertionError).

- [ ] **Step 3: Add the check + wire**

`src/anvyc/core/project_doctor.py` 수정:
1. import 추가(상단 `from anvyc.utils.aws_config import load_aws_profile_names` 아래):
```python
from anvyc.core.aws_profile_state import evaluate_profile_state, state_to_result
```
2. `_check_aws_profile_defined` 함수 **다음**에 신규 함수 추가:
```python
def _check_aws_account_status(info: ProjectInfo) -> list[CheckResult]:
    """profile 정의됨일 때 인증 방식·연결 상태 보고. 미정의는 aws_profile_defined 에 위임."""
    if not info.aws_profile:
        return []
    state = evaluate_profile_state(info.aws_profile)
    if not state.defined:
        return []  # 미정의 → aws_profile_defined 가 보고
    res = state_to_result(state, check_name="aws_account_status")
    return [res] if res is not None else []
```
3. `run_project_doctor` 의 `report.results.extend(_check_aws_profile_defined(info))` 줄 **다음**에 추가:
```python
    report.results.extend(_check_aws_account_status(info))
```
4. 모듈 docstring 의 "Check list (D14):" 를 8→9 로 갱신 — `1. aws_profile_defined` 아래에 한 줄 추가:
```
1b. aws_account_status        인증 방식별 연결 상태 (SSO 토큰/static/assume-role/process)
```

- [ ] **Step 4: Run test + project doctor 회귀 확인**

Run: `pytest tests/unit/test_project_doctor_aws_account.py tests/integration/test_project_doctor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/project_doctor.py tests/unit/test_project_doctor_aws_account.py
git commit -m "feat(project-doctor): aws_account_status — 인증 방식별 연결 상태 (9번째 체크)"
```

---

## Task 9: `core/aws_probe.py` — opt-in 네트워크 liveness

**Files:**
- Create: `src/anvyc/core/aws_probe.py`
- Test: `tests/unit/test_aws_probe.py`

- [ ] **Step 1: Write the failing test**

```python
"""core/aws_probe — aws sts get-caller-identity wrapper (opt-in)."""
import subprocess

import pytest

from anvyc.core import aws_probe
from anvyc.core.aws_probe import ProbeResult, probe_caller_identity


def test_probe_aws_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws_probe.shutil, "which", lambda _: None)
    r = probe_caller_identity("dev")
    assert r.ok is False and "aws CLI" in (r.error or "")


def test_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws_probe.shutil, "which", lambda _: "/usr/bin/aws")

    def fake_run(*_a, **_k):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"Account": "123456789012", "Arn": "arn:aws:iam::1:user/x"}', stderr="",
        )

    monkeypatch.setattr(aws_probe.subprocess, "run", fake_run)
    r = probe_caller_identity("dev")
    assert r.ok is True and r.account == "123456789012"


def test_probe_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws_probe.shutil, "which", lambda _: "/usr/bin/aws")

    def fake_run(*_a, **_k):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=[], returncode=255, stdout="", stderr="Unable to locate credentials\n",
        )

    monkeypatch.setattr(aws_probe.subprocess, "run", fake_run)
    r = probe_caller_identity("dev")
    assert r.ok is False and "credentials" in (r.error or "")


def test_probe_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws_probe.shutil, "which", lambda _: "/usr/bin/aws")

    def fake_run(*_a, **_k):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="aws", timeout=8.0)

    monkeypatch.setattr(aws_probe.subprocess, "run", fake_run)
    assert probe_caller_identity("dev").error == "timeout"


def test_proberesult_dataclass() -> None:
    assert ProbeResult(ok=True, account="1").account == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_probe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.aws_probe'`.

- [ ] **Step 3: Create the module**

`src/anvyc/core/aws_probe.py`:
```python
"""AWS 계정 liveness probe — `aws sts get-caller-identity` (opt-in, 네트워크).

`anvyc aws profile --probe` 전용. doctor 는 이 모듈을 import 하지 않는다(offline 보장).
출력의 Account/Arn 은 식별자(로그에 흔함, 비밀 아님)라 표기 — 자격(키/토큰)은 미출력.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class ProbeResult:
    ok: bool
    account: str | None = None
    arn: str | None = None
    error: str | None = None


def probe_caller_identity(profile: str, *, timeout: float = 8.0) -> ProbeResult:
    """`aws sts get-caller-identity --profile X` 실행 결과. aws 부재/실패 시 graceful."""
    if shutil.which("aws") is None:
        return ProbeResult(ok=False, error="aws CLI 미설치 — probe 불가")
    try:
        proc = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--profile", profile, "--output", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(ok=False, error="timeout")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        return ProbeResult(ok=False, error=(tail[-1][:200] if tail else "exit != 0"))
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ProbeResult(ok=False, error="parse error")
    return ProbeResult(ok=True, account=data.get("Account"), arn=data.get("Arn"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_aws_probe.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/aws_probe.py tests/unit/test_aws_probe.py
git commit -m "feat(aws): aws_probe — opt-in sts get-caller-identity (doctor 와 분리)"
```

---

## Task 10: `anvyc aws profile list`

**Files:**
- Modify: `src/anvyc/cli.py`
- Test: `tests/unit/test_aws_profile_cli.py`

- [ ] **Step 1: Write the failing test**

```python
"""anvyc aws profile list/show CLI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def _home(tmp_path: Path) -> Path:
    aws = tmp_path / ".aws"
    aws.mkdir(parents=True)
    (aws / "config").write_text(
        "[profile ws-dev]\nregion = ap-northeast-2\nsso_session = ws\n\n"
        "[sso-session ws]\nsso_start_url = https://u/start\n\n"
        "[profile legacy]\nregion = us-east-1\n",
        encoding="utf-8",
    )
    (aws / "credentials").write_text("[legacy]\naws_access_key_id = AKIA_X\n", encoding="utf-8")
    return tmp_path


def test_list_human(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "list"])
    assert result.exit_code == 0
    assert "ws-dev" in result.stdout
    assert "legacy" in result.stdout


def test_list_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    names = {p["name"]: p for p in data["profiles"]}
    assert names["ws-dev"]["auth_method"] == "sso"
    assert names["legacy"]["auth_method"] == "static"


def test_list_no_status_skips_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "list", "--no-status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["profiles"][0]["status"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_profile_cli.py -v`
Expected: FAIL — `No such command 'aws'` (exit_code != 0).

- [ ] **Step 3: Register the group + `list`**

`src/anvyc/cli.py` 수정:
1. 그룹 등록 — `project_app` 등록 블록(`app.add_typer(project_app, ...)`, 약 129행) **다음**에 추가:
```python
aws_app = typer.Typer(name="aws", help="AWS profile 조회/관리 (~/.aws/config).")
app.add_typer(aws_app, name="aws", rich_help_panel=PANEL_PROJECT)

aws_profile_app = typer.Typer(name="profile", help="AWS profile 조회/관리 (인증 방식·연결 상태).")
aws_app.add_typer(aws_profile_app, name="profile")
```
2. 파일 끝(다른 `@..._app.command` 들과 같은 영역)에 명령 추가:
```python
@aws_profile_app.command("list")
def aws_profile_list(
    as_json: bool = typer.Option(False, "--json", help="JSON 출력."),
    status: bool = typer.Option(True, "--status/--no-status", help="연결 상태 판정(오프라인)."),
    probe: bool = typer.Option(False, "--probe", help="네트워크 liveness (aws sts get-caller-identity)."),
) -> None:
    """~/.aws/config 의 profile 목록 + 인증 방식 + (기본) 오프라인 연결 상태."""
    import json as _json
    from pathlib import Path

    from rich.markup import escape

    from anvyc.core.aws_profile_state import evaluate_profile_state
    from anvyc.utils.aws_config import load_aws_profile_names

    # HOME-기준 경로로 통일 — DEFAULT_AWS_CONFIG(import 시점 고정)을 우회해
    # 테스트의 HOME monkeypatch 및 실행 시점 HOME 변경을 일관되게 반영.
    home = Path.home()
    names = sorted(load_aws_profile_names(home / ".aws" / "config"))
    rows: list[dict[str, object]] = []
    for name in names:
        row: dict[str, object] = {"name": name, "auth_method": None, "status": None}
        if status:
            st = evaluate_profile_state(name, home=home)
            row["auth_method"] = st.auth_method
            row["status"] = st.status
            row["sso_session"] = st.sso_session
            row["expires_at"] = st.expires_at
        row["probe"] = None
        if probe:
            from anvyc.core.aws_probe import probe_caller_identity

            pr = probe_caller_identity(name)
            row["probe"] = {"ok": pr.ok, "account": pr.account, "arn": pr.arn, "error": pr.error}
        rows.append(row)

    if as_json:
        typer.echo(_json.dumps({"profiles": rows}, ensure_ascii=False))
        return
    if not rows:
        typer.echo("AWS profile 없음 (~/.aws/config).")
        return
    for row in rows:
        line = f"{row['name']}"
        if row.get("auth_method"):
            line += f"  [{row['auth_method']}] {row.get('status')}"
        pr = row.get("probe")
        if isinstance(pr, dict):
            line += f"  probe={'ok ' + str(pr['account']) if pr['ok'] else 'fail: ' + str(pr['error'])}"
        typer.echo(escape(line))
```

- [ ] **Step 4: Run test + help-panel 회귀 확인**

Run: `pytest tests/unit/test_aws_profile_cli.py tests/unit/test_cli_help_panels.py -v`
Expected: PASS (`aws` 그룹은 PANEL_PROJECT 에 추가 — 5 panel 헤더 단언 영향 없음).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_aws_profile_cli.py
git commit -m "feat(cli): anvyc aws profile list — 인증 방식·연결 상태 + opt-in --probe"
```

---

## Task 11: `anvyc aws profile show <name>`

**Files:**
- Modify: `src/anvyc/cli.py`
- Test: `tests/unit/test_aws_profile_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_profile_cli.py` 에 추가:
```python
def test_show_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "show", "ws-dev", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == "ws-dev"
    assert data["auth_method"] == "sso"
    assert data["sso_session"] == "ws"


def test_show_unknown_profile_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    result = runner.invoke(app, ["aws", "profile", "show", "ghost"])
    assert result.exit_code == 1
    assert "ghost" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_aws_profile_cli.py -v`
Expected: FAIL — `No such command 'show'` 또는 exit_code 불일치.

- [ ] **Step 3: Add the `show` command**

`src/anvyc/cli.py` 의 `aws_profile_list` **다음**에 추가:
```python
@aws_profile_app.command("show")
def aws_profile_show(
    name: str = typer.Argument(..., help="profile 이름."),
    as_json: bool = typer.Option(False, "--json", help="JSON 출력."),
    probe: bool = typer.Option(False, "--probe", help="네트워크 liveness (aws sts get-caller-identity)."),
) -> None:
    """단일 profile 의 해석 키 + 인증 방식 + 연결 상태 (+--probe 시 라이브 verdict)."""
    import json as _json
    from pathlib import Path

    from rich.markup import escape

    from anvyc.core.aws_profile_state import evaluate_profile_state
    from anvyc.utils.aws_config import load_profile_config

    home = Path.home()  # HOME-기준 통일 (DEFAULT_AWS_CONFIG import-고정 우회)
    keys = load_profile_config(name, home / ".aws" / "config")
    if keys is None:
        typer.echo(f"profile '{name}' 가 ~/.aws/config 에 없음.")
        raise typer.Exit(1)

    st = evaluate_profile_state(name, home=home)
    out: dict[str, object] = {
        "name": name,
        "auth_method": st.auth_method,
        "status": st.status,
        "sso_session": st.sso_session,
        "expires_at": st.expires_at,
        "source_profile": st.source_profile,
        "keys": keys,
        "probe": None,
    }
    if probe:
        from anvyc.core.aws_probe import probe_caller_identity

        pr = probe_caller_identity(name)
        out["probe"] = {"ok": pr.ok, "account": pr.account, "arn": pr.arn, "error": pr.error}

    if as_json:
        typer.echo(_json.dumps(out, ensure_ascii=False))
        return
    typer.echo(escape(f"{name}  [{st.auth_method}] {st.status}"))
    for k, v in keys.items():
        typer.echo(escape(f"  {k} = {v}"))
    pr_out = out["probe"]
    if isinstance(pr_out, dict):
        typer.echo(escape(f"  probe: {'ok ' + str(pr_out['account']) if pr_out['ok'] else 'fail: ' + str(pr_out['error'])}"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_aws_profile_cli.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_aws_profile_cli.py
git commit -m "feat(cli): anvyc aws profile show — 단일 profile 키·연결 상태"
```

---

## Task 12: 문서 갱신 + 전체 테스트 + lint

**Files:**
- Modify: `README.md`, `docs/multi-account.md`, `docs/doctor-json-schema.md`, `docs/design-axes/cp-05-creds.md`, `DESIGN.md`, `CONTEXT.md`, `RELEASE_NOTES.md`

- [ ] **Step 1: `docs/doctor-json-schema.md` — check_name 추가**

"## 3. Result 객체" 의 check_name 예시 줄에 `aws-account-status` 를 포함하고, 문서 어딘가(예: check 목록/주석)에 한 줄 추가:
```markdown
> v0.x.0+: `aws-account-status` — cwd 프로젝트가 쓰는 AWS profile 의 인증 방식·연결 상태(offline). schema 자체는 불변(새 check_name 값일 뿐).
```

- [ ] **Step 2: `README.md` §11 (다수 계정 관리) — 사용 예 추가**

§11 끝에 추가:
```markdown
### AWS profile 인증/연결 상태 (v0.x.0+)

`anvyc doctor` / `anvyc project doctor` 는 **현재 프로젝트가 쓰는 AWS profile**(`.envrc AWS_PROFILE`)의 인증 방식(SSO/static/assume-role/credential_process/web_identity)과 연결 상태를 보고한다(offline). 진짜 연결 확인은 opt-in:

​```bash
anvyc aws profile list                 # 인증 방식 + 오프라인 상태
anvyc aws profile show ws-dev          # 단일 profile 상세
anvyc aws profile list --probe         # aws sts get-caller-identity (네트워크)
​```
```

- [ ] **Step 3: `docs/multi-account.md` / `docs/design-axes/cp-05-creds.md` / `DESIGN.md` 갱신**

- `docs/multi-account.md`: "AWS profile 인증/연결 상태" 절 추가 — 위 명령 + 인증 방식별 상태 표(spec §5 요약).
- `docs/design-axes/cp-05-creds.md`: "§ creds-expiry 와 aws-account-status 역할 분리" 단락 추가 — "aws-account-status=연결 존재/유효(≤WARNING), creds-expiry=만료 escalation(CRITICAL 포함). 두 체크 공존, 중복 expired 보고는 의도된 분리."
- `DESIGN.md`: `project doctor` 체크 목록 8→9(`aws_account_status` 추가) + 신규 `anvyc aws profile` 명령군 한 줄.

- [ ] **Step 4: `CONTEXT.md` / `RELEASE_NOTES.md`**

- `RELEASE_NOTES.md`: 다음 버전 항목에 "feat: AWS 계정 인증/연결 상태 점검(`aws-account-status`) + `anvyc aws profile list/show` (Phase 1, 읽기). Phase 2(CRUD) 예정." 추가.
- `CONTEXT.md`(심볼릭 링크 — `../anvyc-internal/CONTEXT.md`): 진행 상태에 Phase 1 완료 반영.

- [ ] **Step 5: 전체 테스트 + lint + 커밋**

Run:
```bash
pytest -q && ruff check src tests && mypy src
```
Expected: 모두 통과(green). 실패 시 해당 태스크로 돌아가 수정.

```bash
git add README.md docs/multi-account.md docs/doctor-json-schema.md docs/design-axes/cp-05-creds.md DESIGN.md RELEASE_NOTES.md
git commit -m "docs(aws): AWS 계정 인증/연결 상태 점검 + aws profile 명령 (Phase 1)"
```

---

## Self-Review (작성자 체크 — 완료)

- **Spec 커버리지**: §4 모듈(aws_profile_state/aws_probe/checks) → T4–T7,T9 · §5 매핑 15행 → T6 · §6.1 list/show+probe → T10,T11 · 전역+project 진입점 → T7,T8 · §9 Phase 1 산출물 전부 · §10 테스트(상태 전수·probe mock·CLI·doctor 회귀) · §11 문서 → T12. **갭 없음.**
- **Placeholder 스캔**: 모든 코드 step 에 실제 코드. "TBD/적절히 처리" 없음.
- **타입/시그니처 일관성**: `evaluate_profile_state(profile,*,home,now)`·`state_to_result(state,*,check_name)`·`detect_auth_method(keys,*,has_static)`·`probe_caller_identity(profile,*,timeout)`·`AwsProfileState` 필드·`AUTH_*`/`TOKEN_NONE` 상수·상태 문자열이 T4→T11 전 구간 일치. 체크명 `aws-account-status`(전역)/`aws_account_status`(project) 일관.

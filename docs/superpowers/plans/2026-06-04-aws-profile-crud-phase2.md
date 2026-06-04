# AWS profile CRUD — Phase 2 (쓰기) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `anvyc aws profile create/edit/rm` 로 `~/.aws/config` 의 profile 을 안전하게 생성·수정·삭제한다 — 주석 보존 surgical 텍스트 편집 + diff 미리보기 + `--dry-run` + `.bak` 백업 + 재파싱 검증/롤백, 정적 시크릿 불가침.

**Architecture:** 저수준 INI 도구 `core/ini_io.py`(atomic 텍스트 쓰기 + 섹션 라인 범위 탐지)와 순수 CRUD 로직 `core/aws_config_edit.py`(섹션 단위 텍스트 치환 + 안전가드, Phase 1 `core/project_roots_edit.py` 의 `_write_roots` 패턴 이식)를 만들고, `cli.py` 의 기존 `aws_profile_app` 에 `create/edit/rm` 를 얇게 얹는다. `configparser` 는 파싱·검증 전용; 원문/주석은 텍스트 편집으로 보존한다.

**Tech Stack:** Python 3.11+, `configparser`(검증), `difflib`(diff), `tempfile`+`os.replace`(atomic), Typer(CLI), `pytest`+`typer.testing.CliRunner`.

**Spec:** `docs/superpowers/specs/2026-06-04-aws-profile-and-sso-status-design.md` (§4 Phase 2 모듈, §6.2 명령, §7 의미론, §8 엣지, §10 테스트). **Phase 1 은 main 에 머지됨**(PR #173) — `utils/aws_config.py` 의 `load_aws_profile_names`/`load_profile_config`/`load_profile_sso_meta`/`DEFAULT_AWS_CONFIG`, `cli.py` 의 `aws_profile_app`(list/show) 가 이미 존재한다.

**구현 정밀화 메모(spec 대비):**
- create 는 **플래그 구동만**(대화형 TTY 프롬프트 미도입 — YAGNI·테스트 용이). 새 sso-session 생성에 `--start-url` 누락 시 에러.
- 안전 쓰기는 Phase 1 `_write_roots` 패턴 그대로: **write → 재파싱 검증 → 실패 시 원본 복구**(`.bak` 동반). 우리 구성은 항상 유효 INI 를 생성하므로 롤백 분기는 방어용(monkeypatch 로 테스트).
- `~/.aws/credentials` 는 **건드리지 않으며**, `aws_access_key_id`/`aws_secret_access_key`/`aws_session_token` 키 입력은 거부한다.

---

## File Structure

**신규 파일**
- `src/anvyc/core/ini_io.py` — `atomic_write_text(text, path)`, `locate_section(lines, name) -> (start, end) | None`. (yaml_io 의 INI 형제, 순수.)
- `src/anvyc/core/aws_config_edit.py` — `AwsConfigEditError`, `ProfileEditResult`, `STATIC_CRED_KEYS`, `create_profile`/`edit_profile`/`remove_profile` + 내부 헬퍼(`_profile_header`/`_reject_static_keys`/`_render_diff`/`_validate_ini`/`_commit`).
- 테스트: `tests/unit/test_ini_io.py`, `tests/unit/test_aws_config_edit.py`.

**수정 파일**
- `src/anvyc/cli.py` — 기존 `aws_profile_app` 에 `create`/`edit`/`rm` 명령 + 공용 `_apply_aws_edit` 헬퍼.
- `tests/unit/test_aws_profile_cli.py` — create/edit/rm CLI 테스트 추가(기존 파일).
- 문서: `README.md`, `docs/multi-account.md`, `DESIGN.md`, `RELEASE_NOTES.md`.

**시그니처 계약(전 태스크 공유)**
```python
# core/ini_io.py
atomic_write_text(text: str, path: Path) -> None
locate_section(lines: list[str], name: str) -> tuple[int, int] | None   # name = 대괄호 내부 ("profile X" | "default" | "sso-session S")
# core/aws_config_edit.py
class AwsConfigEditError(ValueError): ...
@dataclass ProfileEditResult: action:str; profile:str; changed:bool; diff:str; written:bool; config_path:Path; backup_path:Path|None=None; warnings:list[str]=...
STATIC_CRED_KEYS = frozenset({"aws_access_key_id","aws_secret_access_key","aws_session_token"})
create_profile(config_path, profile, *, sso_session=None, start_url=None, sso_region=None, account_id=None, role_name=None, region=None, output=None, make_backup=True, write=True) -> ProfileEditResult
edit_profile(config_path, profile, *, sets: dict[str,str], make_backup=True, write=True) -> ProfileEditResult
remove_profile(config_path, profile, *, make_backup=True, write=True) -> ProfileEditResult
# cli.py
_apply_aws_edit(result: ProfileEditResult, *, dry_run: bool, yes: bool, commit_fn) -> None
```
`lines` 는 항상 `text.splitlines(keepends=True)` (개행 보존 → `"".join(lines)` 로 원문 정확 복원).

---

## Task 1: `core/ini_io.py` — atomic 텍스트 쓰기 + 섹션 라인 범위

**Files:**
- Create: `src/anvyc/core/ini_io.py`
- Test: `tests/unit/test_ini_io.py`

- [ ] **Step 1: Write the failing test**

```python
"""core/ini_io — atomic 텍스트 쓰기 + INI 섹션 라인 범위."""
from pathlib import Path

from anvyc.core.ini_io import atomic_write_text, locate_section


def test_atomic_write_creates_and_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "sub" / "config"
    atomic_write_text("hello\n", p)
    assert p.read_text(encoding="utf-8") == "hello\n"
    atomic_write_text("world\n", p)
    assert p.read_text(encoding="utf-8") == "world\n"


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def test_locate_named_profile() -> None:
    text = "[default]\nregion = a\n\n[profile dev]\nregion = b\nsso_session = s\n"
    assert locate_section(_lines(text), "default") == (0, 3)
    assert locate_section(_lines(text), "profile dev") == (3, 6)


def test_locate_last_section_runs_to_eof() -> None:
    text = "[profile a]\nregion = x\n\n[sso-session s]\nsso_start_url = u\n"
    lines = _lines(text)
    start, end = locate_section(lines, "sso-session s")
    assert (start, end) == (3, len(lines))


def test_locate_preserves_comments_in_range() -> None:
    text = "[profile dev]\n# a comment\nregion = b\n[profile other]\nregion = c\n"
    start, end = locate_section(_lines(text), "profile dev")
    assert _lines(text)[start:end] == ["[profile dev]\n", "# a comment\n", "region = b\n"]


def test_locate_missing_returns_none() -> None:
    assert locate_section(_lines("[profile a]\nregion = x\n"), "profile zzz") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ini_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.ini_io'`.

- [ ] **Step 3: Create the module**

`src/anvyc/core/ini_io.py`:
```python
"""INI 텍스트 안전 쓰기 + 섹션 라인 범위 탐지 (yaml_io 의 INI 형제).

`~/.aws/config` 같은 사용자 소유 INI 를 surgical 하게 편집하기 위한 저수준 도구.
configparser 는 파싱/검증에만 쓰고, 실제 쓰기는 원문 텍스트(주석 포함)를 보존하며
섹션 라인 범위만 치환한다.
"""
from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path

_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")


def atomic_write_text(text: str, path: Path) -> None:
    """tempfile.mkstemp + os.replace 로 원자적 텍스트 쓰기 (부분쓰기 방지)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def locate_section(lines: list[str], name: str) -> tuple[int, int] | None:
    """`[name]` 섹션의 라인 범위 (start, end). 없으면 None.

    start = 헤더 라인 인덱스, end = 다음 섹션 헤더 직전(없으면 len(lines)).
    lines[start:end] = 헤더 + 본문(주석 포함). name 은 대괄호 내부 문자열 그대로.
    """
    start: int | None = None
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m is None:
            continue
        if start is None:
            if m.group("name").strip() == name:
                start = i
            continue
        return (start, i)
    if start is None:
        return None
    return (start, len(lines))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ini_io.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/ini_io.py tests/unit/test_ini_io.py
git commit -m "feat(aws): ini_io — atomic 텍스트 쓰기 + 섹션 라인 범위 탐지"
```

---

## Task 2: `core/aws_config_edit.py` — 스캐폴딩 + `create_profile`

**Files:**
- Create: `src/anvyc/core/aws_config_edit.py`
- Test: `tests/unit/test_aws_config_edit.py`

- [ ] **Step 1: Write the failing test**

```python
"""core/aws_config_edit — profile CRUD (surgical 텍스트 편집)."""
from pathlib import Path

import pytest

from anvyc.core.aws_config_edit import (
    AwsConfigEditError,
    create_profile,
)


def _cfg(tmp_path: Path, text: str = "") -> Path:
    p = tmp_path / "config"
    if text:
        p.write_text(text, encoding="utf-8")
    return p


def test_create_into_empty_file(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    res = create_profile(
        cfg, "ws-dev", sso_session="ws", start_url="https://u/start",
        sso_region="ap-northeast-2", account_id="111122223333",
        role_name="Dev", region="ap-northeast-2", output="json",
    )
    assert res.written is True and res.changed is True
    text = cfg.read_text(encoding="utf-8")
    assert "[sso-session ws]" in text
    assert "sso_start_url = https://u/start" in text
    assert "[profile ws-dev]" in text
    assert "sso_session = ws" in text
    assert "sso_account_id = 111122223333" in text
    # 결과가 유효 INI 인지 (round-trip)
    from anvyc.utils.aws_config import load_profile_config
    keys = load_profile_config("ws-dev", cfg)
    assert keys is not None and keys["sso_role_name"] == "Dev"


def test_create_appends_preserving_existing_and_comments(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "# top comment\n[profile keep]\nregion = us-east-1\n")
    res = create_profile(cfg, "new", region="us-west-2")
    text = cfg.read_text(encoding="utf-8")
    assert "# top comment" in text  # 주석 보존
    assert "[profile keep]" in text  # 기존 보존
    assert "[profile new]" in text
    assert res.backup_path is not None and res.backup_path.is_file()  # .bak


def test_create_existing_sso_session_is_referenced_not_duplicated(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\nsso_region = ap-northeast-2\n",
    )
    create_profile(cfg, "second", sso_session="ws", account_id="9", role_name="R")
    text = cfg.read_text(encoding="utf-8")
    assert text.count("[sso-session ws]") == 1  # 중복 생성 안 함
    assert "[profile second]" in text
    assert "sso_session = ws" in text


def test_create_existing_profile_errors(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile dup]\nregion = x\n")
    with pytest.raises(AwsConfigEditError, match="이미 존재"):
        create_profile(cfg, "dup", region="y")


def test_create_new_sso_session_requires_start_url(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    with pytest.raises(AwsConfigEditError, match="start-url"):
        create_profile(cfg, "p", sso_session="brand-new", account_id="9")


def test_create_dry_run_writes_nothing(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile a]\nregion = x\n")
    before = cfg.read_text(encoding="utf-8")
    res = create_profile(cfg, "b", region="y", write=False)
    assert res.written is False
    assert res.changed is True and res.diff  # diff 는 계산됨
    assert cfg.read_text(encoding="utf-8") == before  # 파일 불변


def test_create_rollback_on_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # _validate_ini 가 실패하면 원본 복구 + 에러 (방어 분기).
    import anvyc.core.aws_config_edit as ace

    cfg = _cfg(tmp_path, "[profile a]\nregion = x\n")
    before = cfg.read_text(encoding="utf-8")

    def boom(_text: str) -> None:
        raise AwsConfigEditError("forced invalid")

    monkeypatch.setattr(ace, "_validate_ini", boom)
    with pytest.raises(AwsConfigEditError):
        create_profile(cfg, "b", region="y")
    assert cfg.read_text(encoding="utf-8") == before  # 롤백됨
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_aws_config_edit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'anvyc.core.aws_config_edit'`.

- [ ] **Step 3: Create the module (scaffolding + create_profile)**

`src/anvyc/core/aws_config_edit.py`:
```python
"""`~/.aws/config` profile CRUD — surgical 텍스트 편집 (Phase 2).

project_roots_edit 의 안전 패턴(.bak + atomic + 재파싱 검증 + 롤백)을 INI 에 이식.
configparser 는 검증 전용; 원문/주석 보존을 위해 섹션 라인 범위만 치환한다.
`~/.aws/credentials`(정적 시크릿)는 절대 건드리지 않으며, 정적 자격 키 입력은 거부한다.
"""
from __future__ import annotations

import configparser
import contextlib
import difflib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from anvyc.core.ini_io import atomic_write_text, locate_section
from anvyc.utils.aws_config import load_profile_sso_meta

STATIC_CRED_KEYS = frozenset(
    {"aws_access_key_id", "aws_secret_access_key", "aws_session_token"}
)


class AwsConfigEditError(ValueError):
    """profile CRUD 입력/검증 오류 (이미 존재 / 부재 / 정적 시크릿 키 / 무효 INI)."""


@dataclass
class ProfileEditResult:
    action: str                       # "create" | "edit" | "remove"
    profile: str
    changed: bool
    diff: str                         # ~/.aws/config 의 unified diff (사람용 미리보기)
    written: bool
    config_path: Path
    backup_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def _profile_header(profile: str) -> str:
    return "default" if profile == "default" else f"profile {profile}"


def _reject_static_keys(keys: Iterable[str]) -> None:
    bad = sorted(STATIC_CRED_KEYS.intersection(k.lower() for k in keys))
    if bad:
        raise AwsConfigEditError(
            f"정적 자격 키는 anvyc 가 쓰지 않습니다: {', '.join(bad)}. "
            "`~/.aws/credentials` 는 `aws configure` 로 직접 관리하세요."
        )


def _render_diff(before: str, after: str, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
    )


def _validate_ini(text: str) -> None:
    cp = configparser.RawConfigParser()
    try:
        cp.read_string(text)
    except configparser.Error as e:
        raise AwsConfigEditError(f"결과가 유효한 INI 가 아님: {e}") from e


def _commit(config_path: Path, new_text: str, *, make_backup: bool) -> Path | None:
    """백업 → atomic write → 재파싱 검증 → 실패 시 원본 복구 (`_write_roots` 패턴)."""
    original = config_path.read_bytes() if config_path.is_file() else None
    backup: Path | None = None
    if make_backup and original is not None:
        backup = config_path.with_name(config_path.name + ".bak")
        backup.write_bytes(original)
    atomic_write_text(new_text, config_path)
    try:
        _validate_ini(config_path.read_text(encoding="utf-8"))
    except AwsConfigEditError:
        if original is not None:
            config_path.write_bytes(original)
        else:
            with contextlib.suppress(OSError):
                config_path.unlink()
        raise
    return backup


def _append_block(before: str, block_text: str) -> str:
    """기존 내용과 빈 줄 1개로 구분해 block 을 EOF 에 덧붙인다(끝 개행 보장)."""
    head = before.rstrip("\n")
    out = (head + "\n\n" if head else "") + block_text
    if not out.endswith("\n"):
        out += "\n"
    return out


def create_profile(
    config_path: Path,
    profile: str,
    *,
    sso_session: str | None = None,
    start_url: str | None = None,
    sso_region: str | None = None,
    account_id: str | None = None,
    role_name: str | None = None,
    region: str | None = None,
    output: str | None = None,
    make_backup: bool = True,
    write: bool = True,
) -> ProfileEditResult:
    """SSO 우선 profile 생성 — EOF append. 기존 profile 이면 에러."""
    before = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    lines = before.splitlines(keepends=True)
    header = _profile_header(profile)
    warnings: list[str] = []

    if locate_section(lines, header) is not None:
        raise AwsConfigEditError(f"profile '{profile}' 가 이미 존재합니다 — edit 를 사용하세요.")
    if profile == "default":
        warnings.append("default profile 생성은 비권장입니다(명시 이름 권장).")

    blocks: list[str] = []
    if sso_session:
        sess_header = f"sso-session {sso_session}"
        if locate_section(lines, sess_header) is None:
            if not start_url:
                raise AwsConfigEditError(
                    f"새 sso-session '{sso_session}' 생성에는 --start-url 이 필요합니다."
                )
            sess: list[str] = [f"[{sess_header}]\n", f"sso_start_url = {start_url}\n"]
            if sso_region:
                sess.append(f"sso_region = {sso_region}\n")
            blocks.append("".join(sess))
        elif start_url:
            existing = load_profile_sso_meta_for_session(before, sso_session)
            if existing and existing != start_url:
                warnings.append(
                    f"기존 sso-session '{sso_session}' 의 start_url 이 다릅니다 "
                    f"(기존 {existing} ≠ 입력 {start_url}) — 기존 블록 유지."
                )

    prof: list[str] = [f"[{header}]\n"]
    if sso_session:
        prof.append(f"sso_session = {sso_session}\n")
    if account_id:
        prof.append(f"sso_account_id = {account_id}\n")
    if role_name:
        prof.append(f"sso_role_name = {role_name}\n")
    if region:
        prof.append(f"region = {region}\n")
    if output:
        prof.append(f"output = {output}\n")
    blocks.append("".join(prof))

    after = _append_block(before, "\n".join(blocks))
    diff = _render_diff(before, after, config_path)
    changed = after != before
    backup: Path | None = None
    written = False
    if write and changed:
        backup = _commit(config_path, after, make_backup=make_backup)
        written = True
    return ProfileEditResult(
        action="create", profile=profile, changed=changed, diff=diff,
        written=written, config_path=config_path, backup_path=backup, warnings=warnings,
    )


def load_profile_sso_meta_for_session(text: str, session: str) -> str | None:
    """text 안 `[sso-session session]` 의 sso_start_url (없으면 None) — 경고 비교용."""
    cp = configparser.RawConfigParser()
    with contextlib.suppress(configparser.Error):
        cp.read_string(text)
        return cp.get(f"sso-session {session}", "sso_start_url", fallback=None)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_aws_config_edit.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/aws_config_edit.py tests/unit/test_aws_config_edit.py
git commit -m "feat(aws): aws_config_edit create_profile + 안전 쓰기 스캐폴딩(.bak/검증/롤백)"
```

---

## Task 3: `edit_profile` — 섹션 내 키 in-place 치환(주석 보존) + 정적키 거부

**Files:**
- Modify: `src/anvyc/core/aws_config_edit.py`
- Test: `tests/unit/test_aws_config_edit.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_config_edit.py` 에 추가 (import 에 `edit_profile` 추가):
```python
from anvyc.core.aws_config_edit import edit_profile


def test_edit_replaces_key_in_place_preserving_comments(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "[profile dev]\n# keep me\nregion = us-east-1\noutput = json\n\n[profile other]\nregion = z\n",
    )
    res = edit_profile(cfg, "dev", sets={"region": "ap-northeast-2"})
    text = cfg.read_text(encoding="utf-8")
    assert "region = ap-northeast-2" in text
    assert "region = us-east-1" not in text
    assert "# keep me" in text                 # 섹션 내 주석 보존
    assert "[profile other]\nregion = z" in text  # 다른 섹션 불변
    assert res.changed is True


def test_edit_inserts_new_key(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile dev]\nregion = us-east-1\n")
    edit_profile(cfg, "dev", sets={"output": "yaml"})
    from anvyc.utils.aws_config import load_profile_config
    keys = load_profile_config("dev", cfg)
    assert keys is not None and keys["output"] == "yaml" and keys["region"] == "us-east-1"


def test_edit_rejects_static_cred_keys(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile dev]\nregion = us-east-1\n")
    with pytest.raises(AwsConfigEditError, match="정적 자격 키"):
        edit_profile(cfg, "dev", sets={"aws_access_key_id": "AKIA_X"})


def test_edit_missing_profile_errors(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile dev]\nregion = x\n")
    with pytest.raises(AwsConfigEditError, match="없습니다"):
        edit_profile(cfg, "ghost", sets={"region": "y"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_aws_config_edit.py -v`
Expected: FAIL — `ImportError: cannot import name 'edit_profile'`.

- [ ] **Step 3: Add the implementation**

`src/anvyc/core/aws_config_edit.py` 에 추가 (상단 import 에 `import re` 추가):
```python
def edit_profile(
    config_path: Path,
    profile: str,
    *,
    sets: dict[str, str],
    make_backup: bool = True,
    write: bool = True,
) -> ProfileEditResult:
    """profile 섹션의 키를 in-place 치환(없으면 섹션 끝에 삽입). 주석/타 섹션 보존."""
    _reject_static_keys(sets.keys())
    if not config_path.is_file():
        raise AwsConfigEditError(f"~/.aws/config 가 없습니다: {config_path}")
    before = config_path.read_text(encoding="utf-8")
    lines = before.splitlines(keepends=True)
    header = _profile_header(profile)
    span = locate_section(lines, header)
    if span is None:
        raise AwsConfigEditError(f"profile '{profile}' 가 없습니다 — create 를 사용하세요.")
    start, end = span
    section = lines[start:end]

    remaining = dict(sets)
    patterns = {k: re.compile(rf"^(\s*){re.escape(k)}\s*=") for k in sets}
    new_section: list[str] = []
    for ln in section:
        replaced = False
        for k, rx in patterns.items():
            if k not in remaining:
                continue
            m = rx.match(ln)
            if m:
                new_section.append(f"{m.group(1)}{k} = {remaining.pop(k)}\n")
                replaced = True
                break
        if not replaced:
            new_section.append(ln)
    if remaining:
        insert_at = len(new_section)
        while insert_at > 1 and new_section[insert_at - 1].strip() == "":
            insert_at -= 1
        new_section[insert_at:insert_at] = [f"{k} = {v}\n" for k, v in remaining.items()]

    after = "".join(lines[:start] + new_section + lines[end:])
    diff = _render_diff(before, after, config_path)
    changed = after != before
    backup: Path | None = None
    written = False
    if write and changed:
        backup = _commit(config_path, after, make_backup=make_backup)
        written = True
    return ProfileEditResult(
        action="edit", profile=profile, changed=changed, diff=diff,
        written=written, config_path=config_path, backup_path=backup,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_aws_config_edit.py -v`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/aws_config_edit.py tests/unit/test_aws_config_edit.py
git commit -m "feat(aws): edit_profile — 섹션 키 in-place 치환(주석 보존) + 정적키 거부"
```

---

## Task 4: `remove_profile` — 섹션 삭제(주석 보존) + orphan sso-session 경고

**Files:**
- Modify: `src/anvyc/core/aws_config_edit.py`
- Test: `tests/unit/test_aws_config_edit.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_config_edit.py` 에 추가 (import 에 `remove_profile` 추가):
```python
from anvyc.core.aws_config_edit import remove_profile


def test_remove_deletes_section_preserving_rest(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "# header\n[profile keep]\nregion = a\n\n[profile gone]\nregion = b\n\n[profile keep2]\nregion = c\n",
    )
    res = remove_profile(cfg, "gone")
    text = cfg.read_text(encoding="utf-8")
    assert "[profile gone]" not in text
    assert "# header" in text
    assert "[profile keep]" in text and "[profile keep2]" in text
    assert res.changed is True and res.backup_path is not None


def test_remove_warns_orphan_sso_session(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n[profile only]\nsso_session = ws\n",
    )
    res = remove_profile(cfg, "only")
    assert any("orphan" in w for w in res.warnings)
    # 자동 삭제 안 함
    assert "[sso-session ws]" in cfg.read_text(encoding="utf-8")


def test_remove_no_orphan_warning_when_session_still_used(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        "[sso-session ws]\nsso_start_url = https://u/start\n\n"
        "[profile a]\nsso_session = ws\n\n[profile b]\nsso_session = ws\n",
    )
    res = remove_profile(cfg, "a")
    assert not any("orphan" in w for w in res.warnings)


def test_remove_missing_profile_errors(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "[profile a]\nregion = x\n")
    with pytest.raises(AwsConfigEditError, match="없습니다"):
        remove_profile(cfg, "ghost")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_aws_config_edit.py -v`
Expected: FAIL — `ImportError: cannot import name 'remove_profile'`.

- [ ] **Step 3: Add the implementation**

`src/anvyc/core/aws_config_edit.py` 에 추가:
```python
def remove_profile(
    config_path: Path,
    profile: str,
    *,
    make_backup: bool = True,
    write: bool = True,
) -> ProfileEditResult:
    """profile 섹션 삭제(주석/타 섹션 보존). 고아 sso-session 은 경고만(자동 삭제 안 함)."""
    if not config_path.is_file():
        raise AwsConfigEditError(f"~/.aws/config 가 없습니다: {config_path}")
    before = config_path.read_text(encoding="utf-8")
    lines = before.splitlines(keepends=True)
    header = _profile_header(profile)
    span = locate_section(lines, header)
    if span is None:
        raise AwsConfigEditError(f"profile '{profile}' 가 없습니다.")
    start, end = span
    warnings: list[str] = []

    meta = load_profile_sso_meta(profile, config_path)
    removed_session = meta[0] if meta else None  # (sso_session, start_url)

    end_trim = end
    if end_trim < len(lines) and lines[end_trim].strip() == "":
        end_trim += 1  # 섹션 직후 빈 줄 1개 정리
    after = "".join(lines[:start] + lines[end_trim:])

    if removed_session:
        cp = configparser.RawConfigParser()
        still_used = False
        with contextlib.suppress(configparser.Error):
            cp.read_string(after)
            for s in cp.sections():
                if (s == "default" or s.startswith("profile ")) and (
                    cp.get(s, "sso_session", fallback=None) == removed_session
                ):
                    still_used = True
                    break
        if not still_used and locate_section(
            after.splitlines(keepends=True), f"sso-session {removed_session}"
        ) is not None:
            warnings.append(
                f"sso-session '{removed_session}' 가 더 이상 참조되지 않습니다(orphan) — "
                "필요 시 수동 삭제하세요(자동 삭제 안 함)."
            )

    diff = _render_diff(before, after, config_path)
    changed = after != before
    backup: Path | None = None
    written = False
    if write and changed:
        backup = _commit(config_path, after, make_backup=make_backup)
        written = True
    return ProfileEditResult(
        action="remove", profile=profile, changed=changed, diff=diff,
        written=written, config_path=config_path, backup_path=backup, warnings=warnings,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_aws_config_edit.py -v`
Expected: PASS (15 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/core/aws_config_edit.py tests/unit/test_aws_config_edit.py
git commit -m "feat(aws): remove_profile — 섹션 삭제(주석 보존) + orphan sso-session 경고"
```

---

## Task 5: CLI `aws profile create` + `_apply_aws_edit` 헬퍼

**Files:**
- Modify: `src/anvyc/cli.py`
- Test: `tests/unit/test_aws_profile_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_profile_cli.py` 에 추가 (파일 상단에 이미 `runner`/`app`/`json`/`_home` 존재):
```python
def test_create_writes_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    result = runner.invoke(
        app,
        ["aws", "profile", "create", "newp", "--region", "ap-northeast-2", "--yes"],
    )
    assert result.exit_code == 0
    text = (tmp_path / ".aws" / "config").read_text(encoding="utf-8")
    assert "[profile newp]" in text and "region = ap-northeast-2" in text


def test_create_dry_run_no_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile a]\nregion = x\n", encoding="utf-8")
    result = runner.invoke(
        app, ["aws", "profile", "create", "b", "--region", "y", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "[profile b]" not in (tmp_path / ".aws" / "config").read_text(encoding="utf-8")


def test_create_existing_errors_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile dup]\nregion = x\n", encoding="utf-8")
    result = runner.invoke(
        app, ["aws", "profile", "create", "dup", "--region", "y", "--yes"]
    )
    assert result.exit_code == 1
    assert "이미 존재" in result.stdout


def test_create_confirm_abort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    result = runner.invoke(
        app, ["aws", "profile", "create", "p", "--region", "y"], input="n\n"
    )
    assert result.exit_code == 0
    assert not (tmp_path / ".aws" / "config").exists() or "[profile p]" not in (
        tmp_path / ".aws" / "config"
    ).read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_aws_profile_cli.py -k create -v`
Expected: FAIL — `No such command 'create'` (exit_code != 0).

- [ ] **Step 3: Add the helper + `create` command**

**먼저** `src/anvyc/cli.py` 의 기존 `if TYPE_CHECKING:` 블록(약 92행)에 다음 import 를 추가한다 — `from __future__ import annotations` 가 있어 주석은 lazy 문자열이므로 런타임 import 가 아니다(mypy 만 해석):
```python
    from collections.abc import Callable

    from anvyc.core.aws_config_edit import ProfileEditResult
```
그 다음, `aws_profile_show` 함수 **다음**에 헬퍼와 명령을 추가한다 (module 상단의 `console`(L197), `escape`(L18), `typer` 사용):
```python
def _apply_aws_edit(
    result: ProfileEditResult,
    *,
    dry_run: bool,
    yes: bool,
    commit_fn: Callable[[], ProfileEditResult],
) -> None:
    """ProfileEditResult 미리보기(write=False) → diff/경고 출력 → dry-run/확인 → commit."""
    if not result.changed:
        console.print("변경 없음.", soft_wrap=True)
        return
    console.print(escape(result.diff), soft_wrap=True)
    for w in result.warnings:
        console.print(escape(f"경고: {w}"), soft_wrap=True)
    if dry_run:
        console.print("(dry-run — 쓰기 안 함)", soft_wrap=True)
        return
    if not yes and not typer.confirm("위 변경을 적용할까요?"):
        console.print("취소됨.", soft_wrap=True)
        return
    final = commit_fn()
    console.print(escape(f"적용됨: {final.action} '{final.profile}'"), soft_wrap=True)
    if final.backup_path:
        console.print(escape(f"백업: {final.backup_path}"), soft_wrap=True)


@aws_profile_app.command("create")
def aws_profile_create(
    name: str = typer.Argument(..., help="profile 이름."),
    sso_session: str | None = typer.Option(None, "--sso-session", help="SSO 세션 이름."),
    start_url: str | None = typer.Option(None, "--start-url", help="신규 sso-session 의 start URL."),
    sso_region: str | None = typer.Option(None, "--sso-region", help="신규 sso-session 의 region."),
    account_id: str | None = typer.Option(None, "--account-id", help="sso_account_id."),
    role_name: str | None = typer.Option(None, "--role-name", help="sso_role_name."),
    region: str | None = typer.Option(None, "--region", help="region."),
    output: str | None = typer.Option(None, "--output", help="output 형식."),
    dry_run: bool = typer.Option(False, "--dry-run", help="변경 미리보기만(쓰기 안 함)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="확인 프롬프트 생략."),
) -> None:
    """SSO 우선 profile 생성 (~/.aws/config 에 append). diff 미리보기 + .bak."""
    from pathlib import Path

    from anvyc.core.aws_config_edit import AwsConfigEditError, create_profile

    config_path = Path.home() / ".aws" / "config"
    kwargs = dict(
        sso_session=sso_session, start_url=start_url, sso_region=sso_region,
        account_id=account_id, role_name=role_name, region=region, output=output,
    )
    try:
        preview = create_profile(config_path, name, write=False, **kwargs)
    except AwsConfigEditError as e:
        console.print(escape(f"오류: {e}"), soft_wrap=True)
        raise typer.Exit(code=1) from None
    _apply_aws_edit(
        preview, dry_run=dry_run, yes=yes,
        commit_fn=lambda: create_profile(config_path, name, write=True, **kwargs),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_aws_profile_cli.py -k create -v`
Expected: PASS (4 passed). Also run `.venv/bin/pytest tests/unit/test_cli_help_panels.py -q` (still green).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_aws_profile_cli.py
git commit -m "feat(cli): anvyc aws profile create — SSO 우선 생성(diff/dry-run/.bak/확인)"
```

---

## Task 6: CLI `aws profile edit`

**Files:**
- Modify: `src/anvyc/cli.py`
- Test: `tests/unit/test_aws_profile_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_profile_cli.py` 에 추가:
```python
def test_edit_sets_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text(
        "[profile dev]\nregion = us-east-1\n", encoding="utf-8"
    )
    result = runner.invoke(
        app, ["aws", "profile", "edit", "dev", "--set", "region=ap-northeast-2", "--yes"]
    )
    assert result.exit_code == 0
    assert "region = ap-northeast-2" in (tmp_path / ".aws" / "config").read_text(encoding="utf-8")


def test_edit_rejects_static_key_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile dev]\nregion = x\n", encoding="utf-8")
    result = runner.invoke(
        app, ["aws", "profile", "edit", "dev", "--set", "aws_access_key_id=AKIA_X", "--yes"]
    )
    assert result.exit_code == 1
    assert "정적 자격 키" in result.stdout


def test_edit_missing_profile_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile dev]\nregion = x\n", encoding="utf-8")
    result = runner.invoke(
        app, ["aws", "profile", "edit", "ghost", "--set", "region=y", "--yes"]
    )
    assert result.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_aws_profile_cli.py -k edit -v`
Expected: FAIL — `No such command 'edit'`.

- [ ] **Step 3: Add the `edit` command**

`src/anvyc/cli.py` 의 `aws_profile_create` **다음**에 추가:
```python
@aws_profile_app.command("edit")
def aws_profile_edit(
    name: str = typer.Argument(..., help="profile 이름."),
    set_: list[str] | None = typer.Option(
        None, "--set", help="key=value (반복 가능). 정적 자격 키는 거부.", metavar="KEY=VALUE"
    ),
    region: str | None = typer.Option(None, "--region", help="region 단축."),
    output: str | None = typer.Option(None, "--output", help="output 단축."),
    sso_session: str | None = typer.Option(None, "--sso-session", help="sso_session 단축."),
    dry_run: bool = typer.Option(False, "--dry-run", help="변경 미리보기만."),
    yes: bool = typer.Option(False, "--yes", "-y", help="확인 프롬프트 생략."),
) -> None:
    """profile 키 수정 (in-place, 주석 보존). ~/.aws/credentials 정적 키는 거부."""
    from pathlib import Path

    from anvyc.core.aws_config_edit import AwsConfigEditError, edit_profile

    sets: dict[str, str] = {}
    for item in set_:
        if "=" not in item:
            console.print(escape(f"오류: --set 는 key=value 형식이어야 합니다: {item}"), soft_wrap=True)
            raise typer.Exit(code=1) from None
        k, v = item.split("=", 1)
        sets[k.strip()] = v.strip()
    if region is not None:
        sets["region"] = region
    if output is not None:
        sets["output"] = output
    if sso_session is not None:
        sets["sso_session"] = sso_session
    if not sets:
        console.print("수정할 키가 없습니다 (--set / --region / --output / --sso-session).", soft_wrap=True)
        raise typer.Exit(code=1) from None

    config_path = Path.home() / ".aws" / "config"
    try:
        preview = edit_profile(config_path, name, sets=sets, write=False)
    except AwsConfigEditError as e:
        console.print(escape(f"오류: {e}"), soft_wrap=True)
        raise typer.Exit(code=1) from None
    _apply_aws_edit(
        preview, dry_run=dry_run, yes=yes,
        commit_fn=lambda: edit_profile(config_path, name, sets=sets, write=True),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_aws_profile_cli.py -k edit -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_aws_profile_cli.py
git commit -m "feat(cli): anvyc aws profile edit — 키 수정(정적키 거부/주석 보존)"
```

---

## Task 7: CLI `aws profile rm`

**Files:**
- Modify: `src/anvyc/cli.py`
- Test: `tests/unit/test_aws_profile_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_aws_profile_cli.py` 에 추가:
```python
def test_rm_deletes_with_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text(
        "[profile keep]\nregion = a\n\n[profile gone]\nregion = b\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["aws", "profile", "rm", "gone", "--yes"])
    assert result.exit_code == 0
    text = (tmp_path / ".aws" / "config").read_text(encoding="utf-8")
    assert "[profile gone]" not in text and "[profile keep]" in text


def test_rm_dry_run_no_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile gone]\nregion = b\n", encoding="utf-8")
    result = runner.invoke(app, ["aws", "profile", "rm", "gone", "--dry-run"])
    assert result.exit_code == 0
    assert "[profile gone]" in (tmp_path / ".aws" / "config").read_text(encoding="utf-8")


def test_rm_confirm_abort_keeps_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile gone]\nregion = b\n", encoding="utf-8")
    result = runner.invoke(app, ["aws", "profile", "rm", "gone"], input="n\n")
    assert result.exit_code == 0
    assert "[profile gone]" in (tmp_path / ".aws" / "config").read_text(encoding="utf-8")


def test_rm_missing_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "config").write_text("[profile a]\nregion = x\n", encoding="utf-8")
    result = runner.invoke(app, ["aws", "profile", "rm", "ghost", "--yes"])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_aws_profile_cli.py -k rm -v`
Expected: FAIL — `No such command 'rm'`.

- [ ] **Step 3: Add the `rm` command**

`src/anvyc/cli.py` 의 `aws_profile_edit` **다음**에 추가:
```python
@aws_profile_app.command("rm")
def aws_profile_rm(
    name: str = typer.Argument(..., help="삭제할 profile 이름."),
    dry_run: bool = typer.Option(False, "--dry-run", help="변경 미리보기만."),
    yes: bool = typer.Option(False, "--yes", "-y", help="확인 프롬프트 생략."),
) -> None:
    """profile 삭제 (~/.aws/config). 고아 sso-session 은 경고만(자동 삭제 안 함)."""
    from pathlib import Path

    from anvyc.core.aws_config_edit import AwsConfigEditError, remove_profile

    config_path = Path.home() / ".aws" / "config"
    try:
        preview = remove_profile(config_path, name, write=False)
    except AwsConfigEditError as e:
        console.print(escape(f"오류: {e}"), soft_wrap=True)
        raise typer.Exit(code=1) from None
    _apply_aws_edit(
        preview, dry_run=dry_run, yes=yes,
        commit_fn=lambda: remove_profile(config_path, name, write=True),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_aws_profile_cli.py -k rm -v`
Expected: PASS (4 passed). Then full CLI file: `.venv/bin/pytest tests/unit/test_aws_profile_cli.py -v` (all pass).

- [ ] **Step 5: Commit**

```bash
git add src/anvyc/cli.py tests/unit/test_aws_profile_cli.py
git commit -m "feat(cli): anvyc aws profile rm — 삭제(확인/dry-run/.bak/orphan 경고)"
```

---

## Task 8: 문서 갱신 + 전체 테스트/lint

**Files:**
- Modify: `README.md`, `docs/multi-account.md`, `DESIGN.md`, `RELEASE_NOTES.md`

- [ ] **Step 1: `README.md` §11 — CRUD 사용 예 추가**

§11 의 "AWS profile 인증/연결 상태" 절 아래에 추가 (Phase 2):
```markdown
#### profile 생성/수정/삭제 (Phase 2)

​```bash
anvyc aws profile create ws-dev --sso-session ws --start-url https://d-x.awsapps.com/start \
  --account-id 111122223333 --role-name Dev --region ap-northeast-2 --dry-run   # 미리보기
anvyc aws profile create ws-dev --sso-session ws --region ap-northeast-2 -y      # 적용(.bak 백업)
anvyc aws profile edit ws-dev --set region=us-east-1 -y
anvyc aws profile rm ws-dev                                                      # 확인 후 삭제
​```

`~/.aws/config` 만 수정하며(주석 보존), `~/.aws/credentials`(정적 키)는 건드리지 않는다.
변경 전 unified diff 미리보기 + `--dry-run` + `.bak` 백업 + 재파싱 검증을 거친다.
```

- [ ] **Step 2: `docs/multi-account.md` — CRUD 절 추가**

"AWS profile 인증/연결 상태" 섹션 뒤에 "profile CRUD (Phase 2)" 절: `create/edit/rm` 명령 + 안전 절차(diff/dry-run/.bak/재파싱 검증/롤백), 정적 시크릿 불가침, 고아 sso-session 경고 정책을 2~4줄로 기술.

- [ ] **Step 3: `DESIGN.md` + `RELEASE_NOTES.md`**

- `DESIGN.md`: 신규 `anvyc aws profile create/edit/rm` 명령 + `core/ini_io.py`/`core/aws_config_edit.py` 모듈을 기존 aws 명령군 설명에 한 줄씩 추가.
- `RELEASE_NOTES.md`: `v0.21.0 (unreleased)` 항목(또는 다음 미출시 항목)에 "feat: `anvyc aws profile create/edit/rm` — `~/.aws/config` profile CRUD (surgical 텍스트 편집 + diff/dry-run/.bak/재파싱 검증, 정적 시크릿 불가침). AWS account-status Phase 2." 추가.

- [ ] **Step 4: 전체 검증 + 커밋**

Run:
```bash
.venv/bin/pytest -q && .venv/bin/ruff check src tests && .venv/bin/mypy src/anvyc/ tests/
```
Expected: 모두 green. 실패 시 해당 태스크로 돌아가 수정.

```bash
git add README.md docs/multi-account.md DESIGN.md RELEASE_NOTES.md
git commit -m "docs(aws): aws profile CRUD (Phase 2) 사용 예 + 설계/릴리스 노트"
```

---

## Self-Review (작성자 체크 — 완료)

- **Spec 커버리지**: §4 Phase 2 모듈(ini_io, aws_config_edit) → T1·T2 · §6.2 create/edit/rm(+dry-run/--yes/diff) → T5·T6·T7 · §7 의미론(locate_section·EOF append·in-place 치환·섹션 삭제+trailing trim·orphan 경고·default 특례·기존 sso-session 참조·정적키 거부·재파싱 검증) → T1~T4 · §8 엣지(config 부재 create 생성·이미존재/부재 에러) → T2~T4 · §10 테스트(create append·기존 sso-session 참조·edit 주석보존·rm 주석보존·orphan·정적키 거부·.bak·롤백·locate_section) → T1~T4 · 문서 → T8. **갭 없음.**
- **Placeholder 스캔**: 모든 코드 step 에 실제 코드. "TBD/적절히 처리" 없음.
- **타입/시그니처 일관성**: `create_profile`/`edit_profile`/`remove_profile`(`config_path, profile, *, …, make_backup, write`)·`ProfileEditResult` 필드·`AwsConfigEditError`·`_apply_aws_edit(result,*,dry_run,yes,commit_fn)`·`atomic_write_text`/`locate_section` 시그니처가 T1→T7 일치. CLI 는 `Path.home()/".aws"/"config"` 로 경로 도출(HOME monkeypatch 테스트 격리). 정적키 거부 키셋 = `STATIC_CRED_KEYS`.

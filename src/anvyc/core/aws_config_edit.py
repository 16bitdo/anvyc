"""`~/.aws/config` profile CRUD — surgical 텍스트 편집 (Phase 2).

project_roots_edit 의 안전 패턴(.bak + atomic + 재파싱 검증 + 롤백)을 INI 에 이식.
configparser 는 검증 전용; 원문/주석 보존을 위해 섹션 라인 범위만 치환한다.
`~/.aws/credentials`(정적 시크릿)는 절대 건드리지 않으며, 정적 자격 키 입력은 거부한다.
"""
from __future__ import annotations

import configparser
import contextlib
import difflib
import re
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


def _is_comment(line: str) -> bool:
    s = line.strip()
    return s.startswith("#") or s.startswith(";")


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

    # 삭제 범위: (1) 헤더 바로 위 연속 주석(이 섹션의 leading comment)까지 뒤로 확장,
    # (2) 본문 끝(첫 빈 줄)에서 종료 — 그 뒤 빈 줄/주석은 다음 섹션 소유이므로 보존.
    lead = start
    while lead > 0 and _is_comment(lines[lead - 1]):
        lead -= 1
    # 본문 끝 = next 섹션 헤더에서 역방향으로 그 섹션의 leading 주석 + separator 빈 줄을 제외한 위치.
    # (본문 내부 빈 줄이 있어도 본문 전체를 올바르게 포함 — 첫 빈 줄에서 끊지 않음.)
    body_end = end
    while body_end > start + 1 and _is_comment(lines[body_end - 1]):
        body_end -= 1
    while body_end > start + 1 and lines[body_end - 1].strip() == "":
        body_end -= 1
    head = lines[:lead]
    tail = lines[body_end:]
    while tail and tail[0].strip() == "":  # seam 빈 줄 제거(아래서 필요 시 1개만 재삽입)
        tail.pop(0)
    if head and tail and head[-1].strip() != "":
        head = [*head, "\n"]
    after = "".join(head + tail)
    after = after.rstrip("\n")
    if after:
        after += "\n"

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

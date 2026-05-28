"""anvyc CLI entrypoint (Typer).

MVP 단계에서는 명령어 시그니처와 흐름만 정의하고, 실제 동작은 core/adapters 구현 후 연결한다.
"""

from __future__ import annotations

import contextlib
import json as jsonlib
import os
import subprocess
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from anvyc import __version__
from anvyc.checks.base import Severity
from anvyc.core.activity import collect_sessions
from anvyc.core.apply import ApplyBlockedError, ApplyReport, run_apply
from anvyc.core.backup import BackupBlockedError, run_backup
from anvyc.core.creds import (
    DEFAULT_WARN_THRESHOLD_DAYS,
    ROTATE_KINDS,
    STATUS_EXPIRED,
    STATUS_EXPIRING,
    STATUS_UNKNOWN,
    STATUS_VALID,
    RotateError,
    collect_credentials,
    plan_rotate,
    rotate_credential,
)
from anvyc.core.diff import compute_diff
from anvyc.core.doctor import DoctorReport, run_doctor
from anvyc.core.list import list_backups
from anvyc.core.restore import run_restore
from anvyc.core.snapshot import (
    SnapshotDiffError,
    SnapshotNotFoundError,
    SnapshotRestoreError,
    create_snapshot,
    diff_snapshot,
    list_snapshots,
    plan_restore,
    restore_snapshot,
)
from anvyc.core.status import compute_status
from anvyc.core.sync import (
    ALL_KEEP_CHOICES,
    STATUS_DIFF,
    STATUS_LOCAL_ONLY,
    STATUS_REMOTE_ONLY,
    STATUS_SAME,
    SyncConflictError,
    SyncError,
    compute_sync_status,
    list_conflicts,
    load_remote_manifest,
    pull_to_local,
    push_to_remote,
    resolve_conflict,
    scan_local_manifest,
)
from anvyc.core.workctx import (
    DEFAULT_TTL_SEC as WORKCTX_DEFAULT_TTL_SEC,
)
from anvyc.core.workctx import (
    EXPLICIT_KIND as WORKCTX_EXPLICIT_KIND,
)
from anvyc.core.workctx import (
    clear as workctx_clear,
)
from anvyc.core.workctx import (
    resolve_cache_path as workctx_resolve_cache_path,
)
from anvyc.core.workctx import (
    status as workctx_status,
)
from anvyc.core.workctx import (
    switch as workctx_switch,
)
from anvyc.templates import DEFAULT_ANVYC_YAML
from anvyc.utils.errors import print_error, safe_msg

app = typer.Typer(
    name="anvyc",
    help="여러 장치에서 개발 도구 설정을 안전하게 백업/비교/복원/동기화한다.",
    no_args_is_help=True,
)

# --- panel 그룹 상수 (v0.16.0+) ---
PANEL_CORE = "Core (backup/apply/restore)"
PANEL_PROJECT = "Project view"
PANEL_CONTROL = "Control plane (audit / snapshot / creds / sync / workctx / cost)"
PANEL_MCP = "MCP / serve"
PANEL_EXTERNAL = "External tools"

git_app = typer.Typer(name="git", help=".anvyc 영역에 대한 Git 작업 wrapper.")
app.add_typer(git_app, name="git", rich_help_panel=PANEL_EXTERNAL)

sops_app = typer.Typer(name="sops", help="SOPS 단독 명령 (encrypt/decrypt/rotate-keys).")
app.add_typer(sops_app, name="sops", rich_help_panel=PANEL_EXTERNAL)

config_app = typer.Typer(name="config", help="anvyc.yaml 편집/조회.")
app.add_typer(config_app, name="config", rich_help_panel=PANEL_PROJECT)

tools_app = typer.Typer(name="tools", help="anvyc 가 관리하는 도구 조회/관리.")
app.add_typer(tools_app, name="tools", rich_help_panel=PANEL_PROJECT)

project_app = typer.Typer(name="project", help="cwd 의 connection 정보 조회 (v0.8.0+).")
app.add_typer(project_app, name="project", rich_help_panel=PANEL_PROJECT)

snapshot_app = typer.Typer(
    name="snapshot",
    help="작업 회복 — git stash + meta 묶음 snapshot (v0.14.0+).",
)
app.add_typer(snapshot_app, name="snapshot", rich_help_panel=PANEL_CONTROL)

creds_app = typer.Typer(
    name="creds",
    help="자격 lifecycle — AWS SSO / GitHub / Claude OAuth 만료 상태 (v0.14.0+).",
)
app.add_typer(creds_app, name="creds", rich_help_panel=PANEL_CONTROL)

sync_app = typer.Typer(
    name="sync",
    help="cross-machine state sync — control plane 자산 (health / snapshot meta) 머신 간 동기화 (v0.14.x+).",
)
app.add_typer(sync_app, name="sync", rich_help_panel=PANEL_CONTROL)

sync_conflict_app = typer.Typer(
    name="conflict",
    help="conflict resolution — sha256 불일치 entry 의 수동 해결.",
)
sync_app.add_typer(sync_conflict_app, name="conflict")

workctx_app = typer.Typer(
    name="workctx",
    help="work-cwd context — explicit override (Bash cd 불가 시) + statusline / cache 컨텍스트 전환 (v0.15.0+).",
)
app.add_typer(workctx_app, name="workctx", rich_help_panel=PANEL_CONTROL)

cost_app = typer.Typer(
    name="cost",
    help="cost observability — Anthropic / AWS Cost Explorer / GitHub Billing 통합 합산 (v0.16.0+).",
)
app.add_typer(cost_app, name="cost", rich_help_panel=PANEL_CONTROL)

mcp_app = typer.Typer(
    name="mcp",
    help="MCP server 설정 자동 등록 — Claude Code / Cursor 의 mcp.json 편집을 대신 (v0.16.0+).",
)
app.add_typer(mcp_app, name="mcp", rich_help_panel=PANEL_MCP)

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"anvyc v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="버전 출력 후 종료.",
    ),
) -> None:
    """anvyc 전역 옵션."""


@app.command(rich_help_panel=PANEL_CORE)
def init(
    root: Path = typer.Option(Path.cwd(), "--root", help="anvyc 프로젝트 루트."),
    force: bool = typer.Option(False, "--force", help="기존 anvyc.yaml 이 있어도 덮어쓴다."),
    from_git: str | None = typer.Option(
        None,
        "--from-git",
        help="git URL 에서 .anvyc/ 를 clone (apply 는 수동 실행 권장).",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="대화형 wizard 로 anvyc.yaml 생성 (도구별 enable/path 입력).",
    ),
) -> None:
    """`.anvyc/` 와 `anvyc.yaml` 초기화.

    `--from-git <url>` 사용 시 기존 `.anvyc/` 에 clone 하지 않고 fail-fast.
    clone 후 `.anvyc/anvyc.yaml` 검증, next-step (doctor + apply --dry-run) 안내.

    `--interactive` 사용 시 10개 도구에 대해 enable 여부와 path 를 prompt.
    `--from-git` 과 함께 사용 불가 (의미 충돌).
    """
    if interactive and from_git:
        console.print(
            "[red]error[/] --interactive 와 --from-git 은 동시 사용 불가 "
            "(의미 충돌 — wizard 로 생성 또는 git 에서 clone 중 하나만)"
        )
        raise typer.Exit(code=1)

    anvyc_dir = root / ".anvyc"

    if interactive:
        _run_init_wizard(anvyc_dir, force=force)
        return

    if from_git:
        if anvyc_dir.exists():
            console.print(f"[red]error[/] {anvyc_dir} 이미 존재 — 다른 --root 사용 또는 수동 제거")
            raise typer.Exit(code=1)
        try:
            proc = subprocess.run(
                ["git", "clone", from_git, str(anvyc_dir)],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            console.print("[red]error[/] git binary 미설치")
            raise typer.Exit(code=1) from None
        if proc.returncode != 0:
            print_error(f"git clone 실패\n{proc.stderr.strip()}")
            raise typer.Exit(code=1)
        config_path = anvyc_dir / "anvyc.yaml"
        if not config_path.is_file():
            console.print(
                f"[red]error[/] clone 된 repo 에 anvyc.yaml 부재: {config_path}\n"
                f"  ({anvyc_dir} 는 그대로 두니 직접 검증 후 제거하세요)"
            )
            raise typer.Exit(code=1)
        console.print(f"[green]cloned[/] {from_git} → {anvyc_dir}")
        _print_init_next_steps()
        return

    config_path = anvyc_dir / "anvyc.yaml"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True, exist_ok=True)
    if config_path.exists() and not force:
        console.print(f"[yellow]exists[/] {config_path} (use --force to overwrite)")
    else:
        config_path.write_text(DEFAULT_ANVYC_YAML)
        console.print(f"[green]wrote[/] {config_path}")
    console.print(f"[green]ready[/] {anvyc_dir}")
    _print_init_next_steps()


def _print_init_next_steps() -> None:
    """init 끝에서 통일된 next-step 안내 (v0.16.0+)."""
    console.print("\n[bold]next[/]")
    console.print("  1. [cyan]anvyc doctor[/]          # 환경 정합성 점검 (20 check)")
    console.print("  2. [cyan]anvyc backup[/]          # 첫 백업 생성")
    console.print(
        "  3. [cyan]anvyc apply[/]           "
        "# 다른 머신에서 — default dry-run plan, --apply 시 실 적용"
    )
    console.print(
        "[dim]  AI agent 통합: [cyan]anvyc mcp install[/]   "
        "(Claude Code / Cursor 의 mcp.json 자동 등록)[/]"
    )
    console.print(
        "[dim]  shell completion: [cyan]anvyc --install-completion[/]   "
        "(zsh/bash/fish 자동 완성)[/]"
    )


# wizard 의 도구별 default 값 (file-based adapter 만 file path 입력 필요)
_WIZARD_FILE_DEFAULTS: dict[str, list[str]] = {
    "shell": ["~/.zshrc", "~/.zprofile"],
    "shell_prompt": ["~/.config/starship.toml", "~/.p10k.zsh"],
    "git": ["~/.gitconfig", "~/.gitignore_global"],
    "aws": ["~/.aws/config"],
    "gh": ["~/.config/gh/config.yml"],
    "pulumi": ["~/.pulumi/config.json"],
}
_WIZARD_DEV_ENV_DEFAULTS = {
    "project_roots": ["~/dev"],
    "patterns": [".envrc", ".tool-versions", ".python-version", ".nvmrc"],
}
_WIZARD_TOOLS_ORDER = (
    "shell",
    "shell_prompt",
    "git",
    "aws",
    "gh",
    "pulumi",
    "cursor",
    "claude",
    "iterm2",
    "dev_env",
)


def _parse_csv(answer: str, default: list[str]) -> list[str]:
    """comma-separated 입력을 list 로. 빈 입력 → default."""
    a = answer.strip()
    if not a:
        return default
    return [p.strip() for p in a.split(",") if p.strip()]


def _run_init_wizard(anvyc_dir: Path, *, force: bool) -> None:
    """대화형 wizard — 10 도구의 enable/path 를 prompt 한 후 yaml 작성."""
    import yaml as _yaml
    from rich.syntax import Syntax

    config_path = anvyc_dir / "anvyc.yaml"
    if config_path.exists() and not force:
        console.print(f"[red]error[/] {config_path} 이미 존재 — 다른 --root 사용 또는 --force")
        raise typer.Exit(code=1)

    console.print("[bold]anvyc init wizard[/] — 10개 도구 설정\n")

    tools_cfg: dict[str, dict[str, Any]] = {}
    for tool in _WIZARD_TOOLS_ORDER:
        default_enabled = tool != "dev_env"  # dev_env 은 default disabled (안전)
        enabled = typer.confirm(f"Enable {tool}?", default=default_enabled)
        entry: dict[str, Any] = {"enabled": enabled}
        if not enabled:
            tools_cfg[tool] = entry
            continue
        if tool in _WIZARD_FILE_DEFAULTS:
            default_files = _WIZARD_FILE_DEFAULTS[tool]
            answer = typer.prompt(
                f"  files for {tool}",
                default=", ".join(default_files),
            )
            entry["files"] = _parse_csv(answer, default_files)
        elif tool == "cursor":
            # Cursor 3-layer (DESIGN §15.1) 의 핵심 토글만 노출 — 나머지는 adapter defaults.
            mask = typer.confirm(
                "  Layer A: mask MCP tokens (mcp.json 의 token 자동 마스킹, v0.2+)?",
                default=False,
            )
            gsa_ans = typer.prompt(
                "  Layer B: globalStorage allowlist csv (빈 입력 = 없음)",
                default="",
            )
            gsa = _parse_csv(gsa_ans, [])
            proj_enabled = typer.confirm(
                "  Layer C: enable project-local cursor configs (~/<root>/.cursor)?",
                default=False,
            )
            proj_cfg: dict[str, Any] = {"enabled": proj_enabled, "roots": []}
            if proj_enabled:
                proj_roots_ans = typer.prompt(
                    "    project_roots",
                    default="~/dev",
                )
                proj_cfg["roots"] = _parse_csv(proj_roots_ans, ["~/dev"])
            entry["global"] = {"mask_mcp_tokens": mask}
            entry["ide"] = {"global_storage_allowlist": gsa}
            entry["projects"] = proj_cfg
        elif tool == "claude":
            console.print(
                "  [dim]advanced (include/exclude) 는 yaml 직접 편집 권장 — adapter defaults 사용[/]"
            )
        elif tool == "iterm2":
            # mode 는 'safe' 단일 (DESIGN §14.2). 추가 prompt 불요 — adapter default 가 채움.
            pass
        elif tool == "dev_env":
            roots_ans = typer.prompt(
                "  project_roots",
                default=", ".join(_WIZARD_DEV_ENV_DEFAULTS["project_roots"]),
            )
            entry["project_roots"] = _parse_csv(
                roots_ans, _WIZARD_DEV_ENV_DEFAULTS["project_roots"]
            )
            patterns_ans = typer.prompt(
                "  patterns",
                default=", ".join(_WIZARD_DEV_ENV_DEFAULTS["patterns"]),
            )
            entry["patterns"] = _parse_csv(patterns_ans, _WIZARD_DEV_ENV_DEFAULTS["patterns"])
        tools_cfg[tool] = entry

    yaml_dict = {
        "version": 1,
        "storage": {"root": ".anvyc", "keep_backups": 5, "keep_local_backups": 5},
        "security": {
            "secret_scan": True,
            "block_on_secret": True,
            "allow_encrypted_secrets": True,
        },
        "tools": tools_cfg,
    }
    yaml_text = _yaml.safe_dump(yaml_dict, sort_keys=False, allow_unicode=True)

    console.print("\n[bold]preview:[/]")
    console.print(Syntax(yaml_text, "yaml", line_numbers=False))

    confirm_write = typer.confirm(f"\nWrite to {config_path}?", default=True)
    if not confirm_write:
        console.print("[yellow]aborted — nothing written[/]")
        raise typer.Exit(code=0)

    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml_text)
    console.print(f"[green]wrote[/] {config_path}")
    console.print(f"[green]ready[/] {anvyc_dir}")
    _print_init_next_steps()


@app.command(rich_help_panel=PANEL_CORE)
def doctor(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="모든 finding 나열."),
    strict: bool = typer.Option(False, "--strict", help="warning 이상 발견 시 exit 1."),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
    only: list[str] | None = typer.Option(None, "--only", help="실행할 check 이름 (반복 가능)."),
    skip: list[str] | None = typer.Option(None, "--skip", help="건너뛸 check 이름 (반복 가능)."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
) -> None:
    """환경을 read-only 로 진단한다. DESIGN.md §27 참고."""
    report = run_doctor(config_path=config, only=only or None, skip=skip or None)

    if json_out:
        payload = {
            "results": [r.to_dict() for r in report.results],
            "summary": _summary_counts(report),
        }
        typer.echo(jsonlib.dumps(payload, ensure_ascii=False, indent=2))
    elif verbose:
        _print_verbose(report)
    else:
        _print_summary(report)

    if strict and report.has_blocking():
        raise typer.Exit(code=1)


def _summary_counts(report: DoctorReport) -> dict[str, int]:
    buckets = report.by_severity()
    return {s.value: len(buckets[s]) for s in Severity}


def _print_summary(report: DoctorReport) -> None:
    buckets = report.by_severity()
    total = sum(len(v) for v in buckets.values())
    if total == 0:
        console.print("[green]doctor: clean — no cross-user findings[/]")
        return

    table = Table(title="[cross-user audit] 요약", show_header=True, header_style="bold")
    table.add_column("severity", style="bold")
    table.add_column("count", justify="right")
    for s in Severity:
        cnt = len(buckets[s])
        if cnt == 0:
            continue
        style = _severity_style(s)
        table.add_row(f"[{style}]{s.value}[/]", str(cnt))
    console.print(table)

    # 상위 5건 location 노출
    head = report.results[:5]
    if head:
        console.print("\n[bold]Top findings:[/]")
        for r in head:
            loc = _short_path(r.location)
            line = f":{r.line}" if r.line else ""
            console.print(
                f"  [{_severity_style(r.severity)}]{r.severity.value}[/] {loc}{line} — {r.message}"
            )
        if len(report.results) > 5:
            console.print(f"  ... and {len(report.results) - 5} more (use --verbose)")


def _print_verbose(report: DoctorReport) -> None:
    if not report.results:
        console.print("[green]doctor: clean — no cross-user findings[/]")
        return
    table = Table(title="[cross-user audit] findings", show_header=True, header_style="bold")
    table.add_column("severity", style="bold")
    table.add_column("location")
    table.add_column("line", justify="right")
    table.add_column("message")
    table.add_column("suggestion", overflow="fold")
    for r in report.results:
        loc = _short_path(r.location)
        table.add_row(
            f"[{_severity_style(r.severity)}]{r.severity.value}[/]",
            loc,
            str(r.line) if r.line else "",
            r.message,
            r.suggestion or "",
        )
    console.print(table)


def _severity_style(s: Severity) -> str:
    return {
        Severity.INFO: "dim",
        Severity.INFO_ALIASED: "cyan",
        Severity.WARNING: "yellow",
        Severity.WARNING_FOREIGN: "yellow",
        Severity.WARNING_DANGLING: "yellow",
        Severity.CRITICAL: "red bold",
    }[s]


def _short_path(p: Path | None) -> str:
    if p is None:
        return ""
    home = str(Path.home())
    s = str(p)
    return s.replace(home, "~", 1) if s.startswith(home) else s


@app.command(rich_help_panel=PANEL_CORE)
def backup(
    root: Path | None = typer.Option(None, "--root", help=".anvyc 디렉터리 경로."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    only: list[str] | None = typer.Option(None, "--only", help="특정 도구만 백업 (반복 가능)."),
    force: bool = typer.Option(False, "--force", help="medium 위험까지 허용하고 진행."),
) -> None:
    """enabled adapter 들의 설정 파일을 `.anvyc/backups/<ts>/`에 백업한다."""
    try:
        result = run_backup(root=root, config_path=config, only=only or None, force=force)
    except BackupBlockedError as e:
        from anvyc.utils.errors import print_blocked_error

        print_blocked_error(
            "backup",
            e.reasons,
            next_steps=e.next_steps,
            allow_force=e.allow_force,
            console=console,
        )
        raise typer.Exit(code=2) from e

    console.print(f"[green]backup[/] {_short_path(result.backup_dir)}")
    table = Table(show_header=True, header_style="bold")
    table.add_column("tool")
    table.add_column("file")
    table.add_column("sha256")
    for mf in result.inventory.files:
        table.add_row(
            mf.tool,
            _short_path(mf.target_path),
            (mf.sha256 or "")[:12],
        )
    console.print(table)
    # SOPS 로 암호화된 secret_files 도 metadata 에서 표시
    import json as _jl

    meta_path = result.backup_dir / "metadata.json"
    if meta_path.is_file():
        try:
            meta = _jl.loads(meta_path.read_text())
            encrypted = [f for f in meta.get("files", []) if f.get("encryption")]
            if encrypted:
                console.print(f"\n[cyan]🔒 SOPS-encrypted ({len(encrypted)}):[/]")
                for f in encrypted:
                    marker = "[red]FAILED[/]" if "FAILED" in f["encryption"] else "[cyan]ok[/]"
                    console.print(f"  {marker}  {f['targetPath']}  ({f['encryption']})")
        except (OSError, ValueError):
            pass
    if result.secret_findings:
        console.print(
            f"[yellow]경고[/]: secret scan 에서 {len(result.secret_findings)}건 발견 "
            "(force 옵션으로 진행됨 또는 medium 이하)"
        )


@app.command(rich_help_panel=PANEL_CORE)
def status(
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
    backup_id: str | None = typer.Option(
        None, "--backup-id", help="비교 대상 backup. 미지정 시 current 또는 최신."
    ),
) -> None:
    """current(target) vs backup 의 drift 를 요약한다."""
    try:
        report = compute_status(root, backup_id=backup_id)
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1) from e

    counts = report.counts()
    console.print(f"[bold]backup[/] {_short_path(report.backup_dir)}")
    console.print(
        f"  unchanged={counts.get('unchanged', 0)}  "
        f"[yellow]modified={counts.get('modified', 0)}[/]  "
        f"[red]missing={counts.get('missing', 0)}[/]"
    )
    if not report.entries:
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("state")
    table.add_column("tool")
    table.add_column("target")
    table.add_column("sha256 (target)")
    for entry in report.entries:
        style = {"unchanged": "dim", "modified": "yellow", "missing": "red"}[entry.state]
        table.add_row(
            f"[{style}]{entry.state}[/]",
            entry.tool,
            _short_path(entry.target_path),
            (entry.actual_sha256 or "—")[:12],
        )
    console.print(table)


@app.command(rich_help_panel=PANEL_CORE)
def diff(
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
    backup_id: str | None = typer.Option(
        None, "--backup-id", help="비교 대상 backup. 미지정 시 current/최신."
    ),
    only_changed: bool = typer.Option(True, "--only-changed/--all", help="변경된 파일만 출력."),
) -> None:
    """backup → 현재 target unified diff 를 출력한다."""
    try:
        report = compute_status(root, backup_id=backup_id)
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1) from e

    printed = 0
    for entry in report.entries:
        if only_changed and entry.state == "unchanged":
            continue
        target = entry.target_resolved
        d = compute_diff(
            entry.source_path,
            target,
            label_source=f"backup:{entry.source_path.name}",
            label_target=f"target:{_short_path(entry.target_path)}",
        )
        console.print(f"\n[bold]── {_short_path(entry.target_path)} ({entry.state})[/]")
        if not d.unified:
            console.print("  (no diff)")
            continue
        for line in d.unified.splitlines():
            # diff line 본문은 Rich markup 으로 오해될 수 있는 `[xxx]` 를 포함할
            # 수 있어 escape — 색상 태그만 Rich 가 해석.
            if line.startswith("+") and not line.startswith("+++"):
                console.print(f"[green]{safe_msg(line)}[/]")
            elif line.startswith("-") and not line.startswith("---"):
                console.print(f"[red]{safe_msg(line)}[/]")
            elif line.startswith("@@"):
                console.print(f"[cyan]{safe_msg(line)}[/]")
            else:
                console.print(line)
        printed += 1
    if printed == 0:
        console.print("[green]no differences[/]")


@app.command(rich_help_panel=PANEL_CORE)
def apply(
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    backup_id: str | None = typer.Option(
        None, "--backup-id", help="적용할 backup id. 미지정 시 current/최신."
    ),
    only: list[str] | None = typer.Option(None, "--only", help="특정 도구만 (반복 가능)."),
    apply_changes: bool = typer.Option(
        False, "--apply", help="실제 적용 (기본 dry-run — 계획만 출력)."
    ),
    force: bool = typer.Option(False, "--force", help="medium 위험까지 허용하고 진행."),
) -> None:
    """backup 의 설정을 현재 target 에 적용 (default dry-run, v0.16.0+).

    안전 표준 — `snapshot restore` / `creds rotate` / `cost gc` / `sync push/pull`
    과 동일:
    - 기본: 계획만 출력 (target 무변경)
    - `--apply` 명시 시 실 적용 (적용 전 local-backup 자동 생성)

    예) anvyc apply                # 계획 출력 (dry-run)
        anvyc apply --apply        # 실제 적용
        anvyc apply --only shell   # 특정 도구의 계획만
    """
    dry_run = not apply_changes
    try:
        report = run_apply(
            root=root,
            config_path=config,
            backup_id=backup_id,
            only=only or None,
            dry_run=dry_run,
            force=force,
        )
    except ApplyBlockedError as e:
        from anvyc.utils.errors import print_blocked_error

        print_blocked_error(
            "apply",
            e.reasons,
            next_steps=e.next_steps,
            allow_force=e.allow_force,
            console=console,
        )
        raise typer.Exit(code=2) from e
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1) from e

    _print_apply_report(report)
    if dry_run:
        console.print(
            "\n[yellow]note[/yellow] v0.15.x 와 동작이 다릅니다 — "
            "`anvyc apply` 는 이제 dry-run 입니다."
        )
        console.print("  실제 적용: [bold]anvyc apply --apply[/bold]")
    if not dry_run and report.has_error():
        raise typer.Exit(code=3)


def _print_apply_report(report: ApplyReport, label: str = "apply") -> None:
    color = "yellow" if report.dry_run else "green"
    mode = f"{label} dry-run" if report.dry_run else label
    console.print(f"[{color}]{mode}[/] backup={_short_path(report.backup_dir)}")
    if report.local_backup_dir is not None:
        console.print(f"  local-backup → {_short_path(report.local_backup_dir)}")

    counts = report.counts()
    parts = []
    for state in ("applied", "skipped", "would_apply", "would_skip", "error"):
        if counts.get(state, 0):
            color = {"applied": "green", "error": "red bold"}.get(state, "dim")
            parts.append(f"[{color}]{state}={counts[state]}[/]")
    if parts:
        console.print("  " + "  ".join(parts))

    table = Table(show_header=True, header_style="bold")
    table.add_column("state")
    table.add_column("tool")
    table.add_column("target")
    table.add_column("before → after")
    for e in report.entries:
        style = {
            "applied": "green",
            "skipped": "dim",
            "would_apply": "yellow",
            "would_skip": "dim",
            "error": "red bold",
        }.get(e.state_after, "white")
        msg = e.error or f"{e.state_before} → {e.state_after}"
        table.add_row(
            f"[{style}]{e.state_after}[/]",
            e.tool,
            _short_path(e.target_path),
            msg,
        )
    console.print(table)


@app.command(rich_help_panel=PANEL_CORE)
def restore(
    backup_id: str = typer.Argument(..., help="복원할 backup id (예: 20260518-130000)."),
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    only: list[str] | None = typer.Option(None, "--only", help="특정 도구만 (반복 가능)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="실제 변경 없이 시나리오만 출력."),
    force: bool = typer.Option(False, "--force", help="medium 위험까지 허용."),
) -> None:
    """특정 backup 으로 target 을 복원한다. apply 와 동일하나 backup_id 가 필수.

    backup_id 는 `anvyc list` 에서 확인 가능. 예시:
        anvyc restore 20260518-130000
        anvyc restore 20260518-130000 --dry-run
    """
    try:
        report = run_restore(
            root=root,
            backup_id=backup_id,
            config_path=config,
            only=only or None,
            dry_run=dry_run,
            force=force,
        )
    except ApplyBlockedError as e:
        from anvyc.utils.errors import print_blocked_error

        print_blocked_error(
            "restore",
            e.reasons,
            next_steps=e.next_steps,
            allow_force=e.allow_force,
            console=console,
        )
        raise typer.Exit(code=2) from e
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1) from e

    _print_apply_report(report, label="restore")
    if not dry_run and report.has_error():
        raise typer.Exit(code=3)


@app.command(name="list", rich_help_panel=PANEL_CORE)
def list_(
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
) -> None:
    """보관 중인 backup 목록을 출력한다."""
    backups = list_backups(root)
    if not backups:
        console.print(f"[yellow]no backups under {_short_path(root)}/backups[/]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("current")
    table.add_column("backup_id")
    table.add_column("generated_utc")
    table.add_column("host")
    table.add_column("os/arch")
    table.add_column("tools")
    table.add_column("files", justify="right")
    for b in backups:
        table.add_row(
            "[green]●[/]" if b.is_current else "",
            b.backup_id,
            b.generated_at_utc,
            b.hostname,
            f"{b.os}/{b.arch}" if b.os else "",
            ",".join(b.included_tools),
            str(b.file_count),
        )
    console.print(table)


@app.command(name="scan-secrets", rich_help_panel=PANEL_CORE)
def scan_secrets(
    paths: list[Path] | None = typer.Argument(
        None, help="스캔할 파일/디렉터리. 지정 안 하면 --staged 필요."
    ),
    staged: bool = typer.Option(
        False, "--staged", help="현재 cwd 의 git 저장소에서 staged 파일만 스캔."
    ),
    root: Path | None = typer.Option(None, "--root", help="--staged 의 git repo 경로 override."),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
    quiet: bool = typer.Option(
        False, "--quiet", help="발견 시에도 메시지 최소화 (pre-commit hook 용)."
    ),
    force: bool = typer.Option(False, "--force", help="medium 까지 허용 (비-block)."),
) -> None:
    """secret 패턴을 스캔한다.

    exit code:
      0 — clean / 또는 force 로 medium 허용
      1 — block (critical/high/medium 발견)
    """
    import subprocess as _sp

    from anvyc.security.policy import evaluate
    from anvyc.security.scanner import scan_paths

    targets: list[Path] = []
    if staged:
        repo_root = (root or Path.cwd()).resolve()
        try:
            out = _sp.run(
                ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except _sp.CalledProcessError as e:
            print_error(f"git diff --cached 실패: {e.stderr}")
            raise typer.Exit(code=2) from e
        for rel in out.splitlines():
            rel = rel.strip()
            if not rel:
                continue
            targets.append(repo_root / rel)
    elif paths:
        targets = list(paths)
    else:
        console.print("[red]paths 또는 --staged 중 하나를 지정해야 합니다[/]")
        raise typer.Exit(code=2)

    findings = scan_paths([t for t in targets if t.exists()])
    decision = evaluate(findings, force=force)

    if json_out:
        payload = {
            "findings": [
                {
                    "path": str(f.path),
                    "line": f.line_number,
                    "pattern": f.pattern,
                    "severity": f.severity,
                    "excerpt": f.excerpt,
                }
                for f in findings
            ],
            "block": decision.block,
            "reasons": decision.reasons,
        }
        typer.echo(jsonlib.dumps(payload, ensure_ascii=False, indent=2))
    elif not quiet:
        if not findings:
            console.print("[green]scan-secrets: clean[/]")
        else:
            table = Table(show_header=True, header_style="bold")
            table.add_column("severity")
            table.add_column("pattern")
            table.add_column("location")
            table.add_column("line", justify="right")
            for f in findings:
                style = {
                    "critical": "red bold",
                    "high": "red",
                    "medium": "yellow",
                    "low": "dim",
                }.get(f.severity, "white")
                table.add_row(
                    f"[{style}]{f.severity}[/]",
                    f.pattern,
                    _short_path(f.path),
                    str(f.line_number),
                )
            console.print(table)
            if decision.block:
                console.print("\n[red bold]차단됨 — reasons:[/]")
                for r in decision.reasons[:5]:
                    console.print(f"  • {r}")

    raise typer.Exit(code=1 if decision.block else 0)


@git_app.command("init")
def git_init(
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
) -> None:
    """.anvyc 영역을 Git 저장소로 초기화. .gitignore + pre-commit hook 자동 설치."""
    from anvyc.storage.git import GitError, init_repo

    try:
        init_repo(root.resolve())
    except GitError as e:
        print_error(e)
        raise typer.Exit(code=1) from e
    console.print(f"[green]git init OK[/] {_short_path(root.resolve())}")
    console.print("  [dim]pre-commit hook 설치됨 — push 전 secret scan 자동 실행[/]")


@git_app.command("status")
def git_status(
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
) -> None:
    """.anvyc 영역의 git status (--short)."""
    from anvyc.storage.git import GitError, status

    try:
        out = status(root.resolve())
    except GitError as e:
        print_error(e)
        raise typer.Exit(code=1) from e
    if out.strip():
        typer.echo(out, nl=False)
    else:
        console.print("[green]clean[/]")


@git_app.command("commit")
def git_commit(
    message: str = typer.Option(..., "-m", "--message", help="커밋 메시지."),
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
) -> None:
    """.anvyc 영역의 git commit. pre-commit hook 이 secret scan 강제."""
    from anvyc.storage.git import GitError, commit

    try:
        out = commit(root.resolve(), message)
    except GitError as e:
        print_error(f"commit failed: {e}")
        raise typer.Exit(code=1) from e
    if out:
        typer.echo(out, nl=False)


@git_app.command("push")
def git_push(
    remote: str = typer.Option("origin", "--remote"),
    branch: str | None = typer.Option(None, "--branch"),
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
) -> None:
    """.anvyc 영역의 git push."""
    from anvyc.storage.git import GitError, push

    try:
        out = push(root.resolve(), remote=remote, branch=branch)
    except GitError as e:
        print_error(f"push failed: {e}")
        raise typer.Exit(code=1) from e
    if out:
        typer.echo(out, nl=False)


@sops_app.command("encrypt")
def sops_encrypt(
    src: Path = typer.Argument(..., help="암호화할 파일 (평문)."),
    output: Path | None = typer.Option(None, "-o", "--output", help="출력 경로. 미지정 시 자동."),
    mode: str | None = typer.Option(
        None, "--mode", help="binary | inplace. 미지정 시 yaml 의 format."
    ),
    config: Path | None = typer.Option(None, "--config", help="anvyc.yaml 위치."),
) -> None:
    """파일을 SOPS 로 암호화. anvyc.yaml security.sops 의 recipients 사용."""
    from anvyc.core.config import load_anvyc_config
    from anvyc.core.sops import SopsError
    from anvyc.core.sops import encrypt as sops_encrypt_fn

    cfg = load_anvyc_config(config)
    recipients = cfg.security.sops.age_recipients
    if not recipients:
        console.print("[red]anvyc.yaml security.sops.age_recipients 가 비어 있습니다.[/]")
        raise typer.Exit(code=2)
    used_mode = mode or cfg.security.sops.format or "binary"
    if output is None:
        if used_mode == "inplace":
            output = src.with_suffix(src.suffix + ".sops")
        else:
            output = src.with_suffix(src.suffix + ".sops.json")
    try:
        sops_encrypt_fn(src, output, recipients, mode=used_mode)
    except SopsError as e:
        print_error(f"encrypt 실패: {e}")
        raise typer.Exit(code=1) from e
    console.print(f"[green]encrypted[/] {_short_path(src)} → {_short_path(output)}  ({used_mode})")


@sops_app.command("decrypt")
def sops_decrypt(
    src: Path = typer.Argument(..., help="SOPS 암호화 파일."),
    output: Path | None = typer.Option(
        None, "-o", "--output", help="평문 출력 경로. 미지정 시 stdout."
    ),
    config: Path | None = typer.Option(None, "--config", help="anvyc.yaml 위치."),
) -> None:
    """SOPS 파일을 복호화. anvyc.yaml security.sops.age_identity_file 사용.

    src 의 파일명에 .sops.json 이 있으면 binary 모드, 아니면 inplace 모드로 자동 판정.
    """
    import tempfile

    from anvyc.core.config import load_anvyc_config
    from anvyc.core.sops import SopsError
    from anvyc.core.sops import decrypt as sops_decrypt_fn

    cfg = load_anvyc_config(config)
    identity = Path(cfg.security.sops.age_identity_file).expanduser()
    identity_arg: Path | None = identity if identity.is_file() else None

    name = src.name.lower()
    mode = "binary" if ".sops.json" in name else "inplace"

    # output 미지정 시 stdout — temp 로 일단 받아서 출력
    if output is None or str(output) == "-":
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tmp = Path(tf.name)
        try:
            sops_decrypt_fn(src, tmp, identity_file=identity_arg, mode=mode)
            typer.echo(tmp.read_text(), nl=False)
        except SopsError as e:
            print_error(f"decrypt 실패: {e}")
            raise typer.Exit(code=1) from e
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        return

    try:
        sops_decrypt_fn(src, output, identity_file=identity_arg, mode=mode)
    except SopsError as e:
        print_error(f"decrypt 실패: {e}")
        raise typer.Exit(code=1) from e
    console.print(f"[green]decrypted[/] {_short_path(src)} → {_short_path(output)}  ({mode})")


@sops_app.command("rotate-keys")
def sops_rotate_keys(
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
    backup_id: str | None = typer.Option(
        None, "--backup-id", help="특정 backup 만. 미지정 시 모든 backup."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="변경 없이 처리 대상만 출력."),
    strict: bool = typer.Option(
        False, "--strict", help="1건 실패 시 즉시 exit 1 (default: continue)."
    ),
    config: Path | None = typer.Option(None, "--config", help="anvyc.yaml 위치."),
) -> None:
    """모든 backup 의 SOPS 파일을 anvyc.yaml 의 현재 age_recipients 로 재암호화."""
    import json as _jl

    from anvyc.core.config import load_anvyc_config
    from anvyc.core.sops import SopsError, rotate_recipients

    cfg = load_anvyc_config(config)
    recipients = cfg.security.sops.age_recipients
    if not recipients:
        console.print("[red]anvyc.yaml security.sops.age_recipients 가 비어 있습니다.[/]")
        raise typer.Exit(code=2)
    identity = Path(cfg.security.sops.age_identity_file).expanduser()
    identity_arg: Path | None = identity if identity.is_file() else None

    backups_root = root / "backups"
    if not backups_root.is_dir():
        console.print(f"[yellow]no backups under {_short_path(root)}/backups[/]")
        raise typer.Exit(code=0)

    if backup_id:
        target_backups = [backups_root / backup_id]
        if not target_backups[0].is_dir():
            console.print(f"[red]backup not found: {backup_id}[/]")
            raise typer.Exit(code=1)
    else:
        target_backups = sorted([d for d in backups_root.iterdir() if d.is_dir()])

    rotated: list[Path] = []
    skipped: list[Path] = []
    failed: list[tuple[Path, str]] = []

    for backup_dir in target_backups:
        meta_path = backup_dir / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            meta = _jl.loads(meta_path.read_text())
        except (OSError, ValueError):
            continue
        for entry in meta.get("files") or []:
            enc = entry.get("encryption", "")
            if not enc.startswith("sops/"):
                continue
            mode = "inplace" if enc.endswith("/inplace") else "binary"
            sops_file = backup_dir / str(entry.get("sourcePath", ""))
            if not sops_file.is_file():
                skipped.append(sops_file)
                continue
            if dry_run:
                rotated.append(sops_file)
                continue
            try:
                rotate_recipients(sops_file, recipients, identity_file=identity_arg, mode=mode)
                rotated.append(sops_file)
            except SopsError as e:
                failed.append((sops_file, str(e)))
                if strict:
                    console.print(f"[red bold]strict mode — abort: {sops_file} ({e})[/]")
                    raise typer.Exit(code=1) from e

    # 보고
    label = "would-rotate" if dry_run else "rotated"
    console.print(f"[green]{label}[/] {len(rotated)} files")
    if skipped:
        console.print(f"[dim]skipped (missing): {len(skipped)}[/]")
    if failed:
        console.print(f"[red]failed: {len(failed)}[/]")
        for f, err in failed[:5]:
            console.print(f"  • {_short_path(f)}: {err}")
        if len(failed) > 5:
            console.print(f"  ... and {len(failed) - 5} more")
        if not strict:
            raise typer.Exit(code=3)


# ============================================================================
# config / tools subcommands (v0.6.3 — W3)
# ============================================================================


def _resolve_anvyc_yaml(explicit: Path | None) -> Path:
    """anvyc.yaml 경로 결정. config.py 와 동일한 후보 순서."""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    candidates.extend(
        [
            Path.cwd() / "anvyc.yaml",
            Path.cwd() / ".anvyc" / "anvyc.yaml",
            Path("~/.anvyc/anvyc.yaml").expanduser(),
        ]
    )
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


@config_app.command("edit")
def config_edit(
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
) -> None:
    """`$EDITOR` 로 `anvyc.yaml` 을 편집 후 schema 검증.

    편집 전 자동으로 `.bak.<ts>` 백업 생성. invalid yaml 또는 schema 위반 시
    원본 복구 + exit 1.
    """
    import os
    import shlex
    import shutil
    import time

    yaml_path = _resolve_anvyc_yaml(config)
    if not yaml_path.is_file():
        console.print(
            f"[red]error[/] anvyc.yaml 부재: {yaml_path}\n"
            f"  → anvyc init 으로 생성 후 다시 시도하세요."
        )
        raise typer.Exit(code=1)

    ts = time.strftime("%Y%m%d-%H%M%S")
    bak_path = yaml_path.with_suffix(yaml_path.suffix + f".bak.{ts}")
    shutil.copy2(yaml_path, bak_path)

    editor = os.environ.get("EDITOR") or "vi"
    try:
        editor_argv = shlex.split(editor)
    except ValueError as e:
        print_error(f"EDITOR 파싱 실패: {e}")
        bak_path.unlink(missing_ok=True)
        raise typer.Exit(code=1) from e
    try:
        proc = subprocess.run([*editor_argv, str(yaml_path)])
    except FileNotFoundError:
        console.print(f"[red]error[/] EDITOR 실행 실패: {editor}")
        bak_path.unlink(missing_ok=True)
        raise typer.Exit(code=1) from None
    if proc.returncode != 0:
        console.print(f"[yellow]editor exit {proc.returncode} — 변경 폐기[/]")
        shutil.copy2(bak_path, yaml_path)
        bak_path.unlink(missing_ok=True)
        raise typer.Exit(code=proc.returncode)

    # schema 검증
    try:
        import yaml as _yaml

        with yaml_path.open("r", encoding="utf-8") as f:
            _yaml.safe_load(f)
        from anvyc.core.config import load_anvyc_config

        load_anvyc_config(yaml_path)
    except Exception as e:
        print_error(f"schema 검증 실패: {e}")
        console.print(f"[dim]원본 복구: {bak_path} → {yaml_path}[/]")
        shutil.copy2(bak_path, yaml_path)
        raise typer.Exit(code=1) from e

    console.print(f"[green]ok[/] schema 검증 통과 ({yaml_path})")
    console.print(f"[dim]backup: {bak_path}[/]")


@config_app.command("show")
def config_show(
    effective: bool = typer.Option(
        False,
        "--effective",
        help="default 값까지 채워진 effective view (default: raw).",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="기계 가독 JSON 출력 (--effective 와 함께 권장)."
    ),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """`anvyc.yaml` 을 raw 또는 effective view 로 출력 (yaml / json).

    조합:
      (no flag)               → raw yaml
      --effective             → effective yaml (default 채워짐)
      --json                  → raw → 무의미, --effective 와 함께 사용
      --effective --json      → effective dict JSON
    """
    yaml_path = _resolve_anvyc_yaml(config)
    if not yaml_path.is_file():
        console.print(f"[red]error[/] anvyc.yaml 부재: {yaml_path}")
        raise typer.Exit(code=1)

    if not effective:
        if json_out:
            console.print(
                "[yellow]warning[/] --json 은 --effective 와 함께 사용 권장 (raw yaml 그대로 출력)"
            )
        typer.echo(yaml_path.read_text(encoding="utf-8"))
        return

    import dataclasses

    import yaml as _yaml

    from anvyc.core.config import load_anvyc_config

    cfg = load_anvyc_config(yaml_path)
    payload = dataclasses.asdict(cfg)
    payload.pop("source", None)
    payload.pop("overlay_source", None)

    if json_out:
        typer.echo(jsonlib.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        typer.echo(_yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


def _collect_tools_rows(config: Path | None) -> list[dict[str, Any]]:
    """tools list 의 row 데이터 수집 (renderer 와 분리)."""
    from anvyc.core.backup import ADAPTERS
    from anvyc.core.config import load_anvyc_config

    cfg = load_anvyc_config(config) if config else load_anvyc_config()
    rows: list[dict[str, Any]] = []
    for name, cls in ADAPTERS.items():
        tool_cfg = cfg.tools.get(name)
        enabled = tool_cfg.enabled if tool_cfg else True
        files_count = 0
        secrets_count = 0
        if tool_cfg is not None:
            files_count = len(tool_cfg.files) + len(tool_cfg.include)
            secrets_count = len(tool_cfg.secret_files)
        try:
            if name in {"shell", "git", "aws", "gh", "pulumi"}:
                files_arg = tuple(tool_cfg.files) if tool_cfg and tool_cfg.files else ()
                adapter = cls(files=files_arg)  # type: ignore[call-arg]
            else:
                adapter = cls()
            detected = adapter.detect()
        except Exception:
            detected = False
        rows.append(
            {
                "tool": name,
                "enabled": enabled,
                "detected": detected,
                "files": files_count,
                "secrets": secrets_count,
            }
        )
    return rows


@tools_app.command("list")
def tools_list(
    config: Path | None = typer.Option(None, "--config"),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """anvyc 가 관리하는 도구들의 enabled / detect / file-count 표시."""
    rows = _collect_tools_rows(config)

    if json_out:
        typer.echo(jsonlib.dumps(rows, ensure_ascii=False, indent=2))
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("tool")
    table.add_column("enabled")
    table.add_column("detected")
    table.add_column("files", justify="right")
    table.add_column("secrets", justify="right")
    table.add_column("notes", style="dim")

    for r in rows:
        table.add_row(
            r["tool"],
            "[green]✓[/]" if r["enabled"] else "[dim]✗[/]",
            "[green]✓[/]" if r["detected"] else "[yellow]✗[/]",
            str(r["files"]),
            str(r["secrets"]),
            "",
        )

    console.print(table)
    console.print(
        "[dim]미지원 (v0.7+ 계획): vscode, helix, neovim — "
        "docs/archive/improvement-plan-ux-review.md 참조[/]"
    )


# ============================================================================
# project subcommand (v0.8.0 — W7.3)
# ============================================================================


@project_app.command("show")
def project_show(
    path: Path = typer.Option(Path.cwd(), "--path", help="대상 project root (default: cwd)."),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
    reveal_secrets: bool = typer.Option(
        False,
        "--reveal-secrets",
        help="dev_env 의 secret 패턴 매칭 값을 raw 로 노출 (default: ***REDACTED***).",
    ),
) -> None:
    """cwd (또는 --path) 의 AWS / GitHub / Pulumi / dev_env 통합 view.

    D11c: dev_env 의 값에 anvyc secret PATTERNS 매칭 시 자동 ***REDACTED***.
    op:// 1Password reference 는 placeholder 이므로 redaction 면제.
    `--reveal-secrets` 지정 시 raw 값 출력 (위험 — agent/log 에 노출 주의).
    """
    if not path.exists():
        console.print(f"[red]error[/] path not found: {path}")
        raise typer.Exit(code=1)
    from anvyc.core.project_info import collect_project_info, to_dict

    info = collect_project_info(path, redact_secrets=not reveal_secrets)
    payload = to_dict(info)

    if json_out:
        typer.echo(jsonlib.dumps(payload, ensure_ascii=False, indent=2))
        return

    # human rendering
    console.print(f"[bold]path[/] {payload['path']}")
    console.print(f"[bold]aws_profile[/] {payload['aws_profile'] or '[dim](unset)[/]'}")
    console.print(f"[bold]gh_account[/] {payload['gh_account'] or '[dim](unset)[/]'}")
    console.print(f"[bold]claude_account[/] {payload['claude_account'] or '[dim](unset)[/]'}")
    gh = payload.get("github") or []
    if gh:
        console.print("[bold]github[/]")
        for r in gh:
            console.print(
                f"  • {r['name']}: {r['owner']}/{r['repo']}"
                + (f"  (ssh alias: {r['ssh_alias']})" if r["ssh_alias"] else "")
                + f"  [{r['protocol']}]"
            )
    else:
        console.print("[bold]github[/] [dim](no remote)[/]")
    pul = payload.get("pulumi")
    if pul:
        stacks = ", ".join(pul["stacks"]) or "[dim](no stack)[/]"
        console.print(
            f"[bold]pulumi[/] {pul['project_name']} "
            f"(runtime={pul['runtime'] or '-'}, "
            f"backend={pul.get('backend') or '-'}, stacks={stacks})"
        )
    else:
        console.print("[bold]pulumi[/] [dim](no Pulumi.yaml)[/]")
    de = payload.get("dev_env") or {}
    if de:
        console.print(f"[bold]dev_env[/] ({len(de)} export(s))")
        for k, v in de.items():
            console.print(f"  {k}={v}")
    else:
        console.print("[bold]dev_env[/] [dim](no .envrc)[/]")
    tv = payload.get("tool_versions") or {}
    if tv:
        console.print(f"[bold]tool_versions[/] {tv}")


@app.command(rich_help_panel=PANEL_MCP)
def serve(
    mcp: bool = typer.Option(
        False, "--mcp", help="MCP server (stdio) 실행 — Claude Code/Cursor 호출 가능 (v0.9.0+)."
    ),
) -> None:
    """외부 도구를 위한 server mode (v0.9.0+).

    현재 지원: `--mcp` (stdio Model Context Protocol).
    Claude Code / Cursor 등이 mcp.json 으로 anvyc 의 5 read-only tool 호출.

    requires: `pip install 'anvyc[mcp]'` 또는 `uv tool install 'anvyc[mcp]'`.
    상세: docs/mcp-integration.md
    """
    if not mcp:
        console.print("[red]error[/] --mcp 옵션 필요 (현재 지원 transport).")
        raise typer.Exit(code=1)
    try:
        from anvyc.mcp.server import run as mcp_run
    except SystemExit as e:
        # mcp 미설치 시 mcp/server.py 가 SystemExit 던짐 — print_error 가
        # message 본문을 Rich escape 해 "[mcp]" 같은 pip extra 표기를 그대로
        # 노출 (PR #71 회귀 방지).
        print_error(e)
        raise typer.Exit(code=1) from e
    mcp_run()


@app.command(rich_help_panel=PANEL_PROJECT)
def prompt(
    path: Path = typer.Option(Path.cwd(), "--path", help="대상 디렉터리 (default: cwd)."),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력 (key→value 매핑)."),
) -> None:
    """현재 디렉터리의 계정 라우팅을 shell prompt 용 한 줄로 출력 (v0.13.0+).

    설정된 필드만 공백 구분 `key:value` 로 출력하고, 없으면 빈 출력.
    starship custom command / powerlevel10k 세그먼트 연동 — docs/shell-prompt.md.
    prompt 컨텍스트라 어떤 오류도 셸을 깨지 않도록 조용히 빈 출력 + exit 0 한다.
    """
    segments: list[tuple[str, str]] = []
    try:
        if path.is_dir():
            from anvyc.core.project_info import collect_project_info

            # prompt 출력은 파생 계정 필드만 쓰므로 dev_env redaction 불필요.
            info = collect_project_info(path, redact_secrets=False)
            for label, value in (
                ("aws", info.aws_profile),
                ("gh", info.gh_account),
                ("claude", info.claude_account),
                ("pulumi", info.pulumi.get("backend") if info.pulumi else None),
            ):
                if value:
                    segments.append((label, str(value)))
    except Exception:
        # prompt 컨텍스트 — 어떤 실패도 셸 prompt 를 깨지 않도록 빈 출력으로 흡수.
        segments = []

    if json_out:
        typer.echo(jsonlib.dumps(dict(segments), ensure_ascii=False))
    elif segments:
        typer.echo(" ".join(f"{key}:{value}" for key, value in segments))


@project_app.command("doctor")
def project_doctor(
    path: Path = typer.Option(Path.cwd(), "--path", help="대상 project root (default: cwd)."),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
    strict: bool = typer.Option(False, "--strict", help="warning 이상 발견 시 exit 1."),
) -> None:
    """cwd (또는 --path) 의 connection 정합성 8 check.

    1. aws_profile_defined        .envrc AWS_PROFILE ↔ ~/.aws/config
    2. github_remote_parseable    origin URL parse
    3. gh_account_routing         origin ssh alias ↔ .envrc GH_CONFIG_DIR
    4. claude_account_dir_exists  .envrc CLAUDE_CONFIG_DIR → config 디렉터리 존재
    5. pulumi_stacks_valid        stack 이름 형식
    6. pulumi_backend_routing     Pulumi.yaml backend ↔ .envrc PULUMI_BACKEND_URL
    7. dev_env_secret_safety      raw secret 없이 op:// 사용 여부 (CRITICAL)
    8. tool_versions_installed    python/node binary PATH 존재
    """
    if not path.exists():
        console.print(f"[red]error[/] path not found: {path}")
        raise typer.Exit(code=1)
    from anvyc.core.project_doctor import run_project_doctor

    report = run_project_doctor(path)

    if json_out:
        payload = {
            "path": str(report.path),
            "results": [r.to_dict() for r in report.results],
        }
        typer.echo(jsonlib.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print(f"[bold]project doctor[/] {report.path}")
        if not report.results:
            console.print(
                "[dim]no checks applicable (no .envrc / .git / Pulumi.yaml / tool_versions)[/]"
            )
        else:
            table = Table(show_header=True, header_style="bold")
            table.add_column("severity")
            table.add_column("check")
            table.add_column("message")
            for r in report.results:
                style = _severity_style(r.severity)
                table.add_row(
                    f"[{style}]{r.severity.value}[/]",
                    r.check_name,
                    r.message,
                )
            console.print(table)
            # suggestion 출력 (blocking 만)
            for r in report.results:
                if r.severity.is_blocking and r.suggestion:
                    console.print(f"  [dim]→ {r.suggestion}[/]")

    if strict and report.has_blocking():
        raise typer.Exit(code=1)


@project_app.command("list")
def project_list(
    roots: list[str] | None = typer.Option(
        None,
        "--root",
        help="scan root (반복 가능, 미지정 시 anvyc.yaml project_roots 또는 표준 루트).",
    ),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
    reveal_secrets: bool = typer.Option(
        False,
        "--reveal-secrets",
        help="dev_env secret 패턴 매칭 값을 raw 노출 (default: ***REDACTED***).",
    ),
) -> None:
    """입력 root(들) 의 모든 project 의 connection matrix.

    각 entry 는 `anvyc project show` 와 동일 schema (DESIGN §32).
    D11c redaction 동일 적용 — `--reveal-secrets` 명시 시 raw 값.
    """
    from anvyc.core.project_discovery import discover_projects
    from anvyc.core.project_info import collect_project_info, to_dict
    from anvyc.core.project_roots import resolve_project_roots

    roots_arg = roots if roots else list(resolve_project_roots())
    projects = discover_projects(roots_arg)
    infos = [collect_project_info(p, redact_secrets=not reveal_secrets) for p in projects]
    payload = [to_dict(i) for i in infos]

    if json_out:
        typer.echo(jsonlib.dumps(payload, ensure_ascii=False, indent=2))
        return

    if not payload:
        console.print(f"[dim]no projects found under: {', '.join(roots_arg)}[/]")
        return

    console.print(f"[bold]{len(payload)} project(s) found[/]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("path", style="cyan")
    table.add_column("aws_profile")
    table.add_column("gh_account")
    table.add_column("claude_account")
    table.add_column("github")
    table.add_column("pulumi")
    table.add_column("dev_env", justify="right")
    for entry in payload:
        gh_summary = "—"
        if entry["github"]:
            owners = sorted({r["owner"] for r in entry["github"]})
            gh_summary = ", ".join(owners)
        pul_summary = "—"
        if entry["pulumi"]:
            stacks = ",".join(entry["pulumi"]["stacks"]) or "(no stack)"
            pul_summary = f"{entry['pulumi']['project_name']} [{stacks}]"
        table.add_row(
            _short_path(Path(entry["path"])),
            entry["aws_profile"] or "—",
            entry["gh_account"] or "—",
            entry["claude_account"] or "—",
            gh_summary,
            pul_summary,
            str(len(entry["dev_env"])),
        )
    console.print(table)


@app.command(rich_help_panel=PANEL_CONTROL)
def activity(
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
    limit: int | None = typer.Option(None, "--limit", help="최대 표시 session 수"),
    agent: str | None = typer.Option(
        None,
        "--agent",
        help=(
            "단일 agent 만 조회 (claude_code / cursor / codex). 미지정 시 모든 "
            "등록 agent 통합 (CP-7). Cursor/Codex 는 현재 stub — 명시 시 "
            "NotImplementedError 메시지 표시."
        ),
    ),
) -> None:
    """AI agent session 활동 요약 (CP-7 멀티 에이전트 지원).

    기본 (--agent 미지정) 은 모든 등록 agent 의 union — 현재는 Claude Code
    transcript (`~/.claude*/projects/*/*.jsonl`) 만 impl 이라 byte-equal.
    Cursor / Codex 는 stub 으로 silent skip 된다 (단일 --agent 명시 시
    명시적 NotImplementedError 메시지).
    """
    try:
        sessions = collect_sessions(agent=agent)
    except KeyError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e
    except NotImplementedError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e
    if limit is not None:
        sessions = sessions[:limit]

    if json_out:
        payload = [s.to_dict() for s in sessions]
        typer.echo(jsonlib.dumps(payload, ensure_ascii=False, indent=2))
        return

    if not sessions:
        console.print("[dim]no Claude Code session found under ~/.claude*/projects/[/]")
        return

    console.print(f"[bold]{len(sessions)} session(s) found[/]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("session", style="cyan")
    table.add_column("cwd")
    table.add_column("git", style="dim")
    table.add_column("events", justify="right")
    table.add_column("tool calls", justify="right")
    table.add_column("duration (s)", justify="right")
    table.add_column("top tools")
    for s in sessions:
        top_tools = ", ".join(f"{name}={cnt}" for name, cnt in s.tools_used.most_common(3))
        dur = f"{s.duration_seconds:.0f}" if s.duration_seconds is not None else "—"
        cwd_display = _short_path(Path(s.cwd)) if s.cwd else "—"
        table.add_row(
            s.session_id[:8],
            cwd_display,
            s.git_branch or "—",
            str(s.event_count),
            str(s.tool_call_count),
            dur,
            top_tools or "—",
        )
    console.print(table)


@snapshot_app.command("create")
def snapshot_create(
    label: str | None = typer.Option(
        None,
        "--label",
        "-l",
        help="사람 가독 label (선택). 의미 있는 마커 권장 (예: 'before-refactor').",
    ),
    session_id: str | None = typer.Option(
        None,
        "--session-id",
        help="Claude session id 명시 override. 미지정 시 CLAUDE*_SESSION_ID env 추출.",
    ),
    repo: Path = typer.Option(
        Path.cwd(),
        "--repo",
        help="git working tree 루트 (기본 cwd).",
    ),
    anvyc_root: Path | None = typer.Option(
        None,
        "--anvyc-root",
        help="`.anvyc/` 디렉터리 경로 override (기본 <repo>/.anvyc).",
    ),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """현재 workspace snapshot 1건 생성 (`git stash create` + meta).

    autopilot 의 reckless 변경 직전 명시적 marker 로 사용. working tree 가
    clean 이어도 시점 anchor 로 생성됨 (`working_clean=true`).

    저장 위치: `<anvyc_root>/snapshots/<id>/meta.json`
    git stash anchor: `refs/anvyc-snapshots/<id>` (GC 방지)

    CP-4 1/3 — list/diff (2/3), restore (3/3) 는 후속 PR.
    """
    anvyc_dir = anvyc_root or (repo / ".anvyc")
    try:
        meta = create_snapshot(
            repo, anvyc_dir, label=label, session_id=session_id
        )
    except ValueError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if json_out:
        typer.echo(jsonlib.dumps(meta.to_dict(), ensure_ascii=False, indent=2))
        return

    console.print(f"[bold green]snapshot created[/]  id={meta.id}")
    if meta.label:
        console.print(f"  label:             {meta.label}")
    console.print(f"  branch:            {meta.git_branch or '—'}")
    console.print(f"  claude session:    {meta.claude_session_id or '—'}")
    console.print(f"  uncommitted files: {meta.uncommitted_count}")
    if meta.working_clean:
        console.print("  [dim]working tree clean — anchor marker only[/]")
    else:
        console.print(f"  git stash ref:     {meta.git_stash_ref or '—'}")
        console.print(f"  git stash sha:     {meta.git_stash_sha or '—'}")
    console.print(f"  meta:              {anvyc_dir / 'snapshots' / meta.id / 'meta.json'}")


@snapshot_app.command("list")
def snapshot_list(
    anvyc_root: Path | None = typer.Option(
        None,
        "--anvyc-root",
        help="`.anvyc/` 디렉터리 경로 override (기본 <cwd>/.anvyc).",
    ),
    limit: int | None = typer.Option(None, "--limit", help="최대 표시 snapshot 수."),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """`.anvyc/snapshots/` 인덱스를 created_at 내림차순으로 출력.

    CP-4 2/3 — 1/3 의 schema v1 위에 read-only query.
    """
    anvyc_dir = anvyc_root or (Path.cwd() / ".anvyc")
    snapshots = list_snapshots(anvyc_dir)
    if limit is not None:
        snapshots = snapshots[:limit]

    if json_out:
        typer.echo(jsonlib.dumps([m.to_dict() for m in snapshots], ensure_ascii=False, indent=2))
        return

    if not snapshots:
        console.print(f"[dim]no snapshots under {anvyc_dir / 'snapshots'}[/]")
        return

    console.print(f"[bold]{len(snapshots)} snapshot(s)[/]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", style="cyan")
    table.add_column("created_at")
    table.add_column("branch", style="dim")
    table.add_column("label")
    table.add_column("files", justify="right")
    table.add_column("state")
    for m in snapshots:
        state = "[dim]clean[/]" if m.working_clean else "[yellow]has-stash[/]"
        table.add_row(
            m.id,
            m.created_at,
            m.git_branch or "—",
            m.label or "—",
            str(m.uncommitted_count),
            state,
        )
    console.print(table)


@snapshot_app.command("diff")
def snapshot_diff(
    snapshot_id: str = typer.Argument(..., help="비교 기준 snapshot id."),
    against: str | None = typer.Option(
        None,
        "--against",
        help="다른 snapshot id (지정 시 두 snapshot 의 stash 간 비교; 미지정 시 현재 working tree 와 비교).",
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="git working tree 루트."),
    anvyc_root: Path | None = typer.Option(
        None,
        "--anvyc-root",
        help="`.anvyc/` 디렉터리 경로 override (기본 <repo>/.anvyc).",
    ),
) -> None:
    """snapshot 의 stash sha 와 비교 대상 (현재 또는 다른 snapshot) 간 unified diff.

    CP-4 2/3 — read-only. working_clean=true 인 snapshot 은 비교 대상 없음
    안내 메시지만 반환.
    """
    anvyc_dir = anvyc_root or (repo / ".anvyc")
    try:
        diff_text = diff_snapshot(repo, anvyc_dir, snapshot_id, against=against)
    except SnapshotNotFoundError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except SnapshotDiffError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    if diff_text:
        typer.echo(diff_text)
    # 빈 diff 는 silent — git diff 표준 동작과 일치.


@snapshot_app.command("restore")
def snapshot_restore(
    snapshot_id: str = typer.Argument(..., help="복원할 snapshot id."),
    force: bool = typer.Option(
        False,
        "--force",
        help="실제 복원 수행. 미지정 시 dry-run (계획만 출력, working tree 무변경).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="--force 시의 confirm prompt 자동 수락 (CI / 자동화용).",
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="git working tree 루트."),
    anvyc_root: Path | None = typer.Option(
        None,
        "--anvyc-root",
        help="`.anvyc/` 디렉터리 경로 override (기본 <repo>/.anvyc).",
    ),
) -> None:
    """snapshot 시점의 working tree 변경분을 현재 위에 apply (**destructive**).

    안전 절차:
    - 기본 dry-run — 변경 계획 + 경고만 출력 (working tree 무변경).
    - `--force` 시 실 실행. confirm prompt 가 한 번 더 요구 (`--yes` 로 자동 수락).
    - 실 실행 직전 **auto pre-restore snapshot** 자동 생성 (label=
      `pre-restore-<target-id>`) — restore 가 실패하거나 사용자가 되돌리고
      싶을 때 회복 채널.
    - `git stash apply` 가 conflict 면 raise — pre-restore snapshot id 안내.

    CP-4 3/3 — axis 완결. paired: rbr rule `18-git-codebase-sync` 갱신.
    """
    anvyc_dir = anvyc_root or (repo / ".anvyc")

    try:
        plan = plan_restore(repo, anvyc_dir, snapshot_id)
    except SnapshotNotFoundError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    console.print(f"[bold]restore plan[/]  target={plan.target_id}")
    if plan.target_label:
        console.print(f"  label:                {plan.target_label}")
    console.print(f"  target branch:        {plan.target_branch or '—'}")
    console.print(f"  target stash sha:     {plan.target_stash_sha or '—'}")
    console.print(f"  target working clean: {plan.target_working_clean}")
    console.print(f"  current branch:       {plan.current_branch or '—'}")
    console.print(f"  current uncommitted:  {plan.current_uncommitted_count}")
    pre_msg = (
        f"yes (label=pre-restore-{plan.target_id})"
        if plan.will_create_pre_restore_snapshot
        else "no (target is clean marker)"
    )
    console.print(f"  auto pre-restore:     {pre_msg}")
    if plan.git_apply_command:
        console.print(f"  git apply command:    {' '.join(plan.git_apply_command)}")

    for w in plan.warnings:
        console.print(f"  [yellow]warning:[/] {w}")

    if not force:
        console.print("[dim]\n(dry-run — no changes. add --force to actually restore.)[/]")
        return

    if not yes and not typer.confirm("\n실제로 restore 를 수행할까요?"):
        console.print("[dim]aborted.[/]")
        raise typer.Exit(code=0)

    try:
        result = restore_snapshot(repo, anvyc_dir, snapshot_id)
    except SnapshotRestoreError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    if not result.applied:
        console.print(
            f"[dim]no-op — target snapshot {result.target_id} 은 clean marker.[/]"
        )
        return

    console.print(f"\n[bold green]restored[/]  target={result.target_id}")
    console.print(f"  pre-restore snapshot: {result.pre_restore_snapshot_id}")
    if result.git_apply_stdout:
        console.print(f"  [dim]git stdout:[/]\n{result.git_apply_stdout}")
    if result.git_apply_stderr:
        console.print(f"  [dim]git stderr:[/]\n{result.git_apply_stderr}")


@creds_app.command("status")
def creds_status(
    warn_days: int = typer.Option(
        DEFAULT_WARN_THRESHOLD_DAYS,
        "--warn-days",
        help="expiring 분류 threshold (일 단위, 기본 7).",
    ),
    home: Path | None = typer.Option(
        None,
        "--home",
        help="검사 root 디렉터리 override (기본 $HOME). 테스트 / 다른 머신 mount 시.",
    ),
    no_probe: bool = typer.Option(
        False,
        "--no-probe",
        help="GitHub gh CLI probe (만료 헤더 추출) 비활성화 — offline / CI 모드.",
    ),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """AWS SSO / GitHub / Claude OAuth credential 발견 + 만료 상태 (read-only).

    CP-5 1/3 — token detection + 만료 계산 + status 분류. 2/3 (doctor check
    통합), 3/3 (rotate) 는 후속 PR.
    """
    report = collect_credentials(
        home=home,
        warn_threshold_days=warn_days,
        probe_github_expiry=not no_probe,
    )

    if json_out:
        typer.echo(jsonlib.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return

    creds = report.credentials
    if not creds:
        console.print(f"[dim]no credentials found under {home or Path.home()}[/]")
        return

    expired = sum(1 for c in creds if c.status == STATUS_EXPIRED)
    expiring = sum(1 for c in creds if c.status == STATUS_EXPIRING)
    console.print(
        f"[bold]{len(creds)} credential(s)[/] — "
        f"expired={expired} expiring={expiring} (threshold={warn_days}d)"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("kind", style="cyan")
    table.add_column("identifier")
    table.add_column("expires_at", style="dim")
    table.add_column("expires_in", justify="right")
    table.add_column("status")
    status_color = {
        STATUS_VALID: "[green]valid[/]",
        STATUS_EXPIRING: "[yellow]expiring[/]",
        STATUS_EXPIRED: "[bold red]expired[/]",
        STATUS_UNKNOWN: "[dim]unknown[/]",
    }
    for c in creds:
        sec = c.expires_in_seconds
        if sec is None:
            in_disp = "—"
        elif sec < 0:
            in_disp = f"{sec // 86400}d (past)"
        else:
            days = sec // 86400
            in_disp = f"{days}d" if days else f"{sec // 3600}h"
        table.add_row(
            c.kind,
            c.identifier,
            c.expires_at or "—",
            in_disp,
            status_color.get(c.status, c.status),
        )
    console.print(table)


@creds_app.command("rotate")
def creds_rotate(
    kind: str = typer.Argument(..., help=f"회전 대상 — {' / '.join(ROTATE_KINDS)}."),
    force: bool = typer.Option(
        False,
        "--force",
        help="실제 회전 수행. 미지정 시 dry-run (계획만 출력).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="--force 시의 confirm prompt 자동 수락.",
    ),
    timeout: int = typer.Option(
        300,
        "--timeout",
        help="subprocess timeout (초). browser 인증 사용자 응답 고려 기본 5분.",
    ),
) -> None:
    """자격 회전 — native re-auth 명령 위임 (**destructive**).

    안전 절차 (snapshot restore §35.7 패턴 미러):
    - 기본 dry-run — plan + warnings 만 출력.
    - `--force` 시 confirm prompt (`--yes` 자동 수락).
    - 외부 명령 (`aws sso login` / `gh auth refresh` 등) subprocess 호출.
    - claude_oauth 는 직접 회전 불가 — 사용자 수동 조치 안내만.

    1Password 통합 (`--from-op REF`) 은 후속 polish (browser-based OAuth 가
    PAT 보다 안전한 다수 케이스를 우선).

    CP-5 3/3 — axis 완결. paired: rbr rule `26-secrets-1password` 갱신.
    """
    try:
        plan = plan_rotate(kind)
    except RotateError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    console.print(f"[bold]rotate plan[/]  kind={plan.kind}")
    console.print(f"  description:    {plan.description}")
    if plan.command:
        console.print(f"  command:        {' '.join(plan.command)}")
    else:
        console.print("  command:        [dim](사용자 수동 조치 필요)[/]")
    for w in plan.warnings:
        console.print(f"  [yellow]warning:[/] {w}")

    if not force:
        console.print("[dim]\n(dry-run — no changes. add --force to actually rotate.)[/]")
        return

    if not plan.command:
        console.print("\n[dim]claude_oauth — anvyc CLI 가 직접 실행할 수 없음. 위 안내 참조.[/]")
        return

    if not yes and not typer.confirm("\n실제로 rotation 을 수행할까요?"):
        console.print("[dim]aborted.[/]")
        raise typer.Exit(code=0)

    try:
        result = rotate_credential(kind, timeout_seconds=timeout)
    except RotateError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    if not result.executed:
        console.print(f"\n[dim]no-op — {result.note}[/]")
        return

    color = typer.colors.GREEN if result.return_code == 0 else typer.colors.RED
    typer.secho(
        f"\nrotation completed  kind={result.kind}  rc={result.return_code}",
        fg=color,
        bold=True,
    )
    if result.stdout_tail:
        console.print(f"  [dim]stdout (tail):[/]\n{result.stdout_tail}")
    if result.stderr_tail:
        console.print(f"  [dim]stderr (tail):[/]\n{result.stderr_tail}")
    if result.return_code != 0:
        raise typer.Exit(code=result.return_code or 1)


@sync_app.command("status")
def sync_status(
    target: Path = typer.Option(
        ...,
        "--target",
        help="remote target filesystem path (mount / git clone / sync 폴더 — manifest 와 payload 가 위치).",
    ),
    machine_id: str | None = typer.Option(
        None,
        "--machine-id",
        help="local machine id override (기본: env ANVYC_MACHINE_ID > <user>@<hostname>).",
    ),
    home: Path | None = typer.Option(
        None,
        "--home",
        help="검사 root 디렉터리 override (기본 $HOME). 테스트 / 다른 머신 mount 시.",
    ),
    dev_root: Path | None = typer.Option(
        None,
        "--dev-root",
        help="workspace 루트 override (기본 <home>/dev). CP-4 snapshot meta scan 대상.",
    ),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """local control plane state vs remote sync target diff (read-only).

    CP-6 1/3 — schema v1 + drift detection. push/pull (2/3) 는 후속 PR.

    Remote layout: \\<target\\>/anvyc-sync-manifest.json (단일 machine 기준
    1/3 MVP). 부재 시 모든 local item 이 `local_only` 로 표시 — push 후보.
    """
    h = home or Path.home()
    local = scan_local_manifest(home=h, dev_root=dev_root, machine_id=machine_id)
    remote = load_remote_manifest(target) if target.is_dir() else None
    report = compute_sync_status(local, remote, remote_target=target)

    if json_out:
        typer.echo(jsonlib.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return

    console.print(f"[bold]sync status[/]  machine_id={report.machine_id}")
    console.print(f"  remote target:   {report.remote_target}")
    console.print(f"  checked_at:      {report.checked_at}")

    s = report.summary
    total = sum(s.values())
    if total == 0:
        console.print("  [dim]no items local or remote — nothing to sync.[/]")
        return

    if remote is None:
        console.print(f"  [yellow]remote manifest 부재[/] — 모든 {s[STATUS_LOCAL_ONLY]} local item 이 push 후보 (CP-6 2/3).")

    console.print(
        f"  summary:         same={s[STATUS_SAME]}  local_only={s[STATUS_LOCAL_ONLY]}  "
        f"remote_only={s[STATUS_REMOTE_ONLY]}  diff={s[STATUS_DIFF]}"
    )

    actionable = [e for e in report.diff_entries if e.status != STATUS_SAME]
    if not actionable:
        console.print("  [green]✓ in sync[/]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("status", style="cyan")
    table.add_column("relative_path")
    table.add_column("local size", justify="right")
    table.add_column("remote size", justify="right")
    status_color = {
        STATUS_LOCAL_ONLY: "[yellow]local_only[/]",
        STATUS_REMOTE_ONLY: "[magenta]remote_only[/]",
        STATUS_DIFF: "[bold red]diff[/]",
    }
    for e in actionable:
        table.add_row(
            status_color.get(e.status, e.status),
            e.relative_path,
            str(e.local.size) if e.local else "—",
            str(e.remote.size) if e.remote else "—",
        )
    console.print(table)


@sync_app.command("push")
def sync_push(
    target: Path = typer.Option(..., "--target", help="remote target filesystem path."),
    force: bool = typer.Option(
        False,
        "--force",
        help="conflict (sha256 불일치) 발생 시 local 본문으로 overwrite. 미지정 시 skip.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="dry-run 출력 후 자동 진행 (confirm prompt skip).",
    ),
    machine_id: str | None = typer.Option(None, "--machine-id"),
    home: Path | None = typer.Option(None, "--home"),
    dev_root: Path | None = typer.Option(None, "--dev-root"),
) -> None:
    """local control plane state 를 remote target 에 mirror (**write**).

    안전 절차 (CP-4 restore §35.7 패턴 미러):
    - dry-run plan 출력 (status entries)
    - confirm prompt (--yes 자동 수락)
    - per-file atomic copy (tempfile + os.replace)
    - manifest atomic write
    - conflict (sha256 불일치) 기본 skip — --force 명시 시 overwrite
    - remote-only items 는 보존 (push 가 삭제 안 함 — destructive 회피)

    CP-6 2/3 — schema v1 위에 write 단. conflict resolution (3/3) 후속.
    """
    h = home or Path.home()
    local = scan_local_manifest(home=h, dev_root=dev_root, machine_id=machine_id)
    remote = load_remote_manifest(target) if target.is_dir() else None
    report = compute_sync_status(local, remote, remote_target=target)

    s = report.summary
    console.print(f"[bold]push plan[/]  target={target}")
    console.print(
        f"  summary: same={s[STATUS_SAME]}  local_only={s[STATUS_LOCAL_ONLY]}  "
        f"remote_only={s[STATUS_REMOTE_ONLY]}  diff={s[STATUS_DIFF]}"
    )
    will_copy = s[STATUS_LOCAL_ONLY] + (s[STATUS_DIFF] if force else 0)
    will_skip_conflict = 0 if force else s[STATUS_DIFF]
    console.print(
        f"  will copy: {will_copy} (local_only + diff*force) | "
        f"skip-conflict: {will_skip_conflict} | preserved remote-only: {s[STATUS_REMOTE_ONLY]}"
    )
    if s[STATUS_DIFF] > 0 and not force:
        console.print("  [yellow]warning:[/] diff entries 가 있음 — --force 없이 skip 됨")

    if will_copy == 0 and s[STATUS_REMOTE_ONLY] == 0:
        console.print("[dim](nothing to do — already in sync)[/]")
        return

    if not yes and not typer.confirm("\nproceed?"):
        console.print("[dim]aborted.[/]")
        raise typer.Exit(code=0)

    try:
        result = push_to_remote(local, target, home=h, dev_root=dev_root, force=force)
    except SyncError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    color = typer.colors.GREEN if result.items_failed == 0 else typer.colors.YELLOW
    typer.secho(
        f"\npush done — copied={result.items_copied} "
        f"skipped_same={result.items_skipped_same} "
        f"skipped_conflict={result.items_skipped_conflict} "
        f"failed={result.items_failed} "
        f"manifest_written={result.manifest_written}",
        fg=color,
        bold=True,
    )
    if result.failed_paths:
        console.print("  failed paths:")
        for p in result.failed_paths[:10]:
            console.print(f"    - {p}")


@sync_app.command("pull")
def sync_pull(
    target: Path = typer.Option(..., "--target", help="remote target filesystem path."),
    force: bool = typer.Option(
        False,
        "--force",
        help="conflict (sha256 불일치) 발생 시 remote 본문으로 local overwrite. 미지정 시 skip.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="dry-run 출력 후 자동 진행.",
    ),
    machine_id: str | None = typer.Option(None, "--machine-id"),
    home: Path | None = typer.Option(None, "--home"),
    dev_root: Path | None = typer.Option(None, "--dev-root"),
) -> None:
    """remote target 의 state 를 local 에 mirror (**write**).

    안전 절차 (push 와 대칭):
    - dry-run plan 출력
    - confirm prompt (--yes 자동 수락)
    - per-file atomic copy
    - conflict (sha256 불일치) 기본 skip — --force 명시 시 local overwrite
    - local-only items 는 보존 (pull 이 삭제 안 함)

    CP-6 2/3.
    """
    h = home or Path.home()
    local = scan_local_manifest(home=h, dev_root=dev_root, machine_id=machine_id)
    remote = load_remote_manifest(target) if target.is_dir() else None
    if remote is None:
        typer.secho(
            f"error: remote manifest 부재 또는 손상: {target}/anvyc-sync-manifest.json",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    report = compute_sync_status(local, remote, remote_target=target)

    s = report.summary
    console.print(f"[bold]pull plan[/]  target={target}")
    console.print(
        f"  summary: same={s[STATUS_SAME]}  local_only={s[STATUS_LOCAL_ONLY]}  "
        f"remote_only={s[STATUS_REMOTE_ONLY]}  diff={s[STATUS_DIFF]}"
    )
    will_copy = s[STATUS_REMOTE_ONLY] + (s[STATUS_DIFF] if force else 0)
    will_skip_conflict = 0 if force else s[STATUS_DIFF]
    console.print(
        f"  will copy: {will_copy} (remote_only + diff*force) | "
        f"skip-conflict: {will_skip_conflict} | preserved local-only: {s[STATUS_LOCAL_ONLY]}"
    )
    if s[STATUS_DIFF] > 0 and not force:
        console.print("  [yellow]warning:[/] diff entries 가 있음 — --force 없이 skip 됨")

    if will_copy == 0:
        console.print("[dim](nothing to pull)[/]")
        return

    if not yes and not typer.confirm("\nproceed?"):
        console.print("[dim]aborted.[/]")
        raise typer.Exit(code=0)

    try:
        result = pull_to_local(target, home=h, dev_root=dev_root, machine_id=machine_id, force=force)
    except SyncError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    color = typer.colors.GREEN if result.items_failed == 0 else typer.colors.YELLOW
    typer.secho(
        f"\npull done — copied={result.items_copied} "
        f"skipped_same={result.items_skipped_same} "
        f"skipped_conflict={result.items_skipped_conflict} "
        f"failed={result.items_failed}",
        fg=color,
        bold=True,
    )
    if result.failed_paths:
        console.print("  failed paths:")
        for p in result.failed_paths[:10]:
            console.print(f"    - {p}")


@sync_conflict_app.command("list")
def sync_conflict_list(
    target: Path = typer.Option(..., "--target", help="remote target filesystem path."),
    machine_id: str | None = typer.Option(None, "--machine-id"),
    home: Path | None = typer.Option(None, "--home"),
    dev_root: Path | None = typer.Option(None, "--dev-root"),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """현재 conflict (sha256 불일치) entries 만 표시 — resolve 후보 인덱스.

    CP-6 3/3 — read-only. auto-resolve 없음; `resolve <path> --keep ...` 로
    entry 별 수동 해결 (rule 27-cross-machine-sync-policy 준수).
    """
    h = home or Path.home()
    try:
        conflicts = list_conflicts(target, home=h, dev_root=dev_root, machine_id=machine_id)
    except SyncError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if json_out:
        typer.echo(jsonlib.dumps([e.to_dict() for e in conflicts], ensure_ascii=False, indent=2))
        return

    if not conflicts:
        console.print("[green]✓ no conflicts[/]")
        return

    console.print(f"[bold]{len(conflicts)} conflict(s)[/]  target={target}")
    table = Table(show_header=True, header_style="bold")
    table.add_column("relative_path")
    table.add_column("local sha", style="cyan")
    table.add_column("remote sha", style="magenta")
    table.add_column("local mtime", style="dim")
    table.add_column("remote mtime", style="dim")
    for e in conflicts:
        loc_sha = e.local.sha256[:12] if e.local else "—"
        rem_sha = e.remote.sha256[:12] if e.remote else "—"
        loc_mt = e.local.mtime if e.local else "—"
        rem_mt = e.remote.mtime if e.remote else "—"
        table.add_row(e.relative_path, loc_sha, rem_sha, loc_mt, rem_mt)
    console.print(table)
    console.print(
        "\n[dim]해결: anvyc sync conflict resolve <relative_path> --target <…> --keep local|remote[/]"
    )


@sync_conflict_app.command("resolve")
def sync_conflict_resolve(
    relative_path: str = typer.Argument(..., help="conflict 의 relative_path."),
    target: Path = typer.Option(..., "--target", help="remote target filesystem path."),
    keep: str = typer.Option(
        ...,
        "--keep",
        help=f"보존 측 — {' / '.join(ALL_KEEP_CHOICES)}. local 이면 remote 가 overwrite; remote 이면 local 이 overwrite.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="confirm prompt 자동 수락."),
    machine_id: str | None = typer.Option(None, "--machine-id"),
    home: Path | None = typer.Option(None, "--home"),
    dev_root: Path | None = typer.Option(None, "--dev-root"),
) -> None:
    """단일 conflict 를 명시 해결 (destructive — 반대편 본문 overwrite).

    안전 절차:
    - keep 값 검증 (local|remote 만 허용)
    - relative_path 의 현 conflict 여부 확인 (안 그러면 error)
    - confirm prompt (--yes 자동)
    - atomic copy (push-one 또는 pull-one 분기)

    CP-6 3/3 — axis 완결. paired: rbr rule `27-cross-machine-sync-policy`.
    """
    if keep not in ALL_KEEP_CHOICES:
        typer.secho(
            f"error: --keep must be one of {ALL_KEEP_CHOICES}, got {keep!r}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    h = home or Path.home()
    console.print(f"[bold]conflict resolve plan[/]  path={relative_path}  keep={keep}")
    if keep == "local":
        console.print("  → local 본문이 remote 를 overwrite (push-one) + remote manifest 갱신")
    else:
        console.print("  → remote 본문이 local 을 overwrite (pull-one); local 측 manifest 없음")

    if not yes and not typer.confirm("\nproceed?"):
        console.print("[dim]aborted.[/]")
        raise typer.Exit(code=0)

    try:
        result = resolve_conflict(
            target,
            relative_path,
            keep=keep,
            home=h,
            dev_root=dev_root,
            machine_id=machine_id,
        )
    except SyncConflictError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except SyncError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.secho(
        f"\nresolved — operation={result.operation} "
        f"manifest_written={result.manifest_written}",
        fg=typer.colors.GREEN,
        bold=True,
    )


# ── workctx (CP-12 PR-12E) ────────────────────────────────────────────────


@workctx_app.command("switch")
def workctx_switch_cmd(
    path: Path = typer.Argument(..., help="Override 할 디렉터리 (절대 또는 상대 경로)."),
    ttl: int = typer.Option(
        WORKCTX_DEFAULT_TTL_SEC,
        "--ttl",
        help=f"TTL (초). 기본 {WORKCTX_DEFAULT_TTL_SEC}s.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="cache profile (예: claude / claude-edward). $WORK_CWD_CACHE env 우선.",
    ),
) -> None:
    """Explicit override 활성화 — statusline / cache 가 즉시 이 경로를 work-cwd 로 인식.

    Bash `cd` 가 불가능한 시나리오 (sandbox, sub-shell 격리, 명시 의도 표현)
    에서 사용. TTL 내 자동 만료 — `workctx clear` 로 즉시 해제 가능.

    캐시 위치 우선순위:
      1. $WORK_CWD_CACHE env (cci `wire-hooks-cwd-changed.py` 가 settings.json 에 주입)
      2. --profile <name> → ~/.<profile>/.work-cwd-cache
      3. ~/.claude/.work-cwd-cache (최종 fallback)
    """
    abs_path = path.expanduser().resolve()
    if not abs_path.exists():
        typer.secho(
            f"warn: {abs_path} 미존재 — 그대로 진행 (statusline 표시는 raw 경로).",
            fg=typer.colors.YELLOW,
            err=True,
        )
    cache = workctx_resolve_cache_path(profile)
    row = workctx_switch(cache, str(abs_path), ttl_sec=ttl)
    typer.secho(
        f"workctx switch → {abs_path} (ttl={ttl}s, expires_at={row.explicit_expires_at})",
        fg=typer.colors.GREEN,
        bold=True,
    )
    typer.echo(f"  cache: {cache}")


@workctx_app.command("clear")
def workctx_clear_cmd(
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="cache profile. $WORK_CWD_CACHE env 우선.",
    ),
) -> None:
    """Explicit override 해제. activity (cwd_changed / file_op) row 는 보존."""
    cache = workctx_resolve_cache_path(profile)
    removed = workctx_clear(cache)
    if removed > 0:
        typer.secho(
            f"workctx clear — {removed} explicit row(s) removed",
            fg=typer.colors.GREEN,
        )
    else:
        typer.echo("workctx clear — (no explicit row to remove)")
    typer.echo(f"  cache: {cache}")


@workctx_app.command("show")
def workctx_show_cmd(
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="cache profile. $WORK_CWD_CACHE env 우선.",
    ),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """Current effective work-cwd + cache state.

    Priority (statusline resolver 와 동일):
      1. Latest non-expired explicit row.
      2. Latest activity (cwd_changed | file_op), stale flag if age > 60s.
      3. None.
    """
    cache = workctx_resolve_cache_path(profile)
    state = workctx_status(cache)

    if json_out:
        eff = None
        if state.effective is not None:
            eff = {
                "kind": state.effective_kind,
                "path": state.effective.path,
                "ts": state.effective.ts,
            }
            if state.effective_kind == WORKCTX_EXPLICIT_KIND:
                eff["expires_at"] = state.effective.explicit_expires_at
                eff["remaining_sec"] = state.effective_remaining_sec
            else:
                eff["age_sec"] = state.effective_age_sec
                eff["stale"] = state.effective_stale
        out = {
            "cache": str(state.cache_path),
            "rows": len(state.rows),
            "effective": eff,
        }
        typer.echo(jsonlib.dumps(out, indent=2))
        return

    typer.echo(f"cache : {state.cache_path}")
    typer.echo(f"rows  : {len(state.rows)}")
    if state.effective is None:
        typer.echo("effective: (none — fall back to launch cwd)")
        return

    table = Table(show_header=False, box=None)
    table.add_row("kind", state.effective_kind)
    table.add_row("path", state.effective.path)
    if state.effective_kind == WORKCTX_EXPLICIT_KIND:
        table.add_row("expires_at", str(state.effective.explicit_expires_at))
        table.add_row("remaining_sec", f"{state.effective_remaining_sec}s")
    else:
        table.add_row("age_sec", f"{state.effective_age_sec}s")
        table.add_row("stale", "yes" if state.effective_stale else "no")
    console.print(table)


# ---------- cost (CP-13 PR-13B1) -----------------------------------------


@cost_app.command("collect")
def cost_collect(
    source: str | None = typer.Option(
        None,
        "--source",
        "-s",
        help="source 필터 (현재 'anthropic' 만, AWS/GitHub 는 PR-13C/D).",
    ),
    period: str = typer.Option(
        "mtd",
        "--period",
        "-p",
        help="mtd | YYYY-MM (default: mtd, UTC store).",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="기계 가독 JSON 출력."
    ),
) -> None:
    """어댑터 직접 호출 + 캐시 저장 + 합산 출력 (refresh)."""
    from anvyc.core.cost.api import summary_json, summary_text

    if json_out:
        console.print(
            summary_json(source=source, period_spec=period, refresh=True)
        )
    else:
        console.print(
            summary_text(source=source, period_spec=period, refresh=True)
        )


@cost_app.command("summary")
def cost_summary(
    source: str | None = typer.Option(
        None, "--source", "-s", help="source 필터."
    ),
    period: str = typer.Option(
        "mtd", "--period", "-p", help="mtd | YYYY-MM."
    ),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """캐시 read + 합산 (캐시 비어있으면 즉시 collect)."""
    from anvyc.core.cost.api import summary_json, summary_text

    if json_out:
        console.print(summary_json(source=source, period_spec=period))
    else:
        console.print(summary_text(source=source, period_spec=period))


@cost_app.command("ledger")
def cost_ledger(
    source: str | None = typer.Option(
        None, "--source", "-s", help="source 필터."
    ),
    account: str | None = typer.Option(
        None, "--account", "-a", help="account 필터."
    ),
    period: str | None = typer.Option(
        None,
        "--period",
        "-p",
        help="mtd | YYYY-MM (미지정 시 모든 cache row).",
    ),
    include_meta: bool = typer.Option(
        False, "--meta", help="measurement_cost / org_id / collected_at 추가."
    ),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """period 의 cache rows 표 출력 (CP-13 PR-13B2)."""
    import json as _json

    from rich.table import Table

    from anvyc.core.cost.api import ledger_rows, resolve_period

    period_obj = resolve_period(period) if period else None
    rows = ledger_rows(
        period=period_obj,
        source=source,
        account=account,
        include_meta=include_meta,
    )

    if json_out:
        console.print(_json.dumps(rows, ensure_ascii=False, indent=2))
        return

    table = Table(title=f"cost ledger ({len(rows)} rows)")
    cols = [
        "cache_date",
        "source",
        "account",
        "amount_usd",
        "models",
        "pricing_v",
    ]
    if include_meta:
        cols += ["measurement_cost", "org_id", "collected_at"]
    for c in cols:
        table.add_column(c)
    for r in rows:
        row_vals = [
            str(r["cache_date"]),
            str(r["source"]),
            str(r["account"]),
            f"${r['amount_usd']:.4f}",
            str(r["model_breakdown_count"]),
            str(r["pricing_version"])
            if r["pricing_version"] is not None
            else "-",
        ]
        if include_meta:
            row_vals += [
                f"${r.get('measurement_cost_usd', 0):.4f}",
                str(r.get("org_id") or "-"),
                str(r.get("collected_at") or "-"),
            ]
        table.add_row(*row_vals)
    console.print(table)


@cost_app.command("cleanup")
def cost_cleanup(
    keep_days: int = typer.Option(
        90,
        "--keep-days",
        help="raw daily cache retention (default 90d, DESIGN §38.5).",
    ),
    apply_changes: bool = typer.Option(
        False,
        "--apply",
        help="기본 dry-run. --apply 시 실 삭제 (확인 prompt 없이).",
    ),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """raw daily cache retention 정리 — cache GC (alias: `gc`, PR-13B2)."""
    import json as _json

    from anvyc.core.cost.api import gc_raw_daily

    result = gc_raw_daily(keep_days=keep_days, dry_run=not apply_changes)

    if json_out:
        console.print(_json.dumps(result, ensure_ascii=False, indent=2))
        return

    if result["dry_run"]:
        console.print(
            "[yellow]dry-run[/yellow] — --apply 로 실 삭제. 아래는 예정 동작."
        )
    console.print(
        f"today: {result['today']}, cutoff: {result['cutoff']} "
        f"(keep {result['keep_days']}d)"
    )
    action = "would remove" if result["dry_run"] else "removed"
    console.print(
        f"{action}: [red]{result['removed_count']}[/red] files, "
        f"kept: [green]{result['kept_count']}[/green] files"
    )


@cost_app.command("gc")
def cost_gc(
    keep_days: int = typer.Option(
        90,
        "--keep-days",
        help="raw daily cache retention (default 90d, DESIGN §38.5).",
    ),
    apply_changes: bool = typer.Option(
        False,
        "--apply",
        help="기본 dry-run. --apply 시 실 삭제 (확인 prompt 없이).",
    ),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """Alias of `anvyc cost cleanup` — cache GC (raw daily cache retention)."""
    cost_cleanup(keep_days=keep_days, apply_changes=apply_changes, json_out=json_out)


# ---------- mcp (PR A — anvyc mcp install/uninstall/status) ----------------


def _short_home(path: Path) -> str:
    """`~/...` 단축 표기 — 출력 가독성 (--json 출력 영향 없음)."""
    try:
        home = Path.home()
        return f"~/{path.relative_to(home)}"
    except ValueError:
        return str(path)


def _print_install_plans(plans: list[Any], *, action: str) -> None:
    """action = 'install' 또는 'uninstall' — plan 표 출력."""
    from rich.table import Table

    table = Table(title=f"mcp {action} plan")
    table.add_column("ide")
    table.add_column("scope")
    table.add_column("path")
    table.add_column("current")
    if action == "install":
        table.add_column("new file?")
        table.add_column("backup")
    else:
        table.add_column("remaining")
    table.add_column("other servers")

    for plan in plans:
        row = [
            plan.ide,
            plan.scope,
            _short_home(plan.target_path),
            plan.current_state,
        ]
        if action == "install":
            row.append("yes" if plan.will_write_new_file else "no")
            row.append(_short_home(plan.backup_path) if plan.backup_path else "—")
        else:
            row.append(", ".join(plan.remaining_servers) or "—")
        row.append(", ".join(plan.existing_servers) if action == "install"
                   else ", ".join(plan.remaining_servers))
        # `other servers` 컬럼이 install 의 existing_servers / uninstall 의 remaining_servers
        # 와 의미 중복이지만 표 친화 위해 동일 처리.
        table.add_row(*row[: len(table.columns)])

    console.print(table)


@mcp_app.command("install")
def mcp_install(
    ide: str = typer.Option(
        "auto",
        "--ide",
        help="claude | cursor | both | auto. auto = 감지된 IDE 모두.",
    ),
    scope: str = typer.Option(
        "user",
        "--scope",
        help="user (~/.claude/mcp.json 또는 ~/.cursor/mcp.json) | project (<cwd>/.mcp.json or <cwd>/.cursor/mcp.json).",
    ),
    apply_changes: bool = typer.Option(
        False,
        "--apply",
        help="기본 dry-run. --apply 시 atomic write 로 실제 mcp.json 작성.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="--apply 시의 confirm prompt 자동 수락."
    ),
    absolute_path: bool = typer.Option(
        False,
        "--absolute-path",
        help="entry 의 command 를 `shutil.which('anvyc')` 절대 경로로 박음 (PATH 의존 회피, dev-install / multi-account 환경에서 robust).",
    ),
    claude_config_dirs: str = typer.Option(
        "",
        "--claude-config-dirs",
        help="multi-account 일괄 등록 — csv 로 여러 CLAUDE_CONFIG_DIR 지정 (예: `~/.claude,~/.claude-edward`). 단일 `CLAUDE_CONFIG_DIR` env 와 `--ide claude` 의 claude 항목을 override.",
    ),
) -> None:
    """anvyc 를 Claude Code / Cursor 의 mcp.json 에 자동 등록.

    안전 절차 (CP-4/CP-5/cost cleanup 의 destructive 패턴 미러):
    - 기본 dry-run — plan 표 출력만 (파일 무변경).
    - --apply 시 atomic write (tempfile + os.replace).
    - 기존 mcpServers 의 다른 entry 는 항상 보존.
    - 기존 anvyc entry 가 다른 command 면 .bak 자동 생성 후 표준값으로 overwrite.

    --absolute-path: dev wrapper (`~/.local/bin/anvyc`) 또는 IDE 가 다른 PATH 에서
    spawn 하는 환경에서 `anvyc` not-found 회피.

    --claude-config-dirs: multi-account 일괄 등록. 각 dir 마다 `<dir>/mcp.json` 에
    entry 작성. 예: `--claude-config-dirs ~/.claude,~/.claude-edward`.
    """
    import shutil

    from anvyc.core.mcp_setup import apply_install, plan_install, resolve_ides

    command_path: str | None = None
    if absolute_path:
        resolved = shutil.which("anvyc")
        if resolved is None:
            print_error(
                "anvyc binary 가 PATH 에 없습니다 — --absolute-path 사용 불가. "
                "anvyc 를 먼저 설치하거나 PATH 를 확인하세요."
            )
            raise typer.Exit(code=2)
        command_path = resolved
        console.print(f"[dim]absolute-path: {_short_home(Path(command_path))}[/dim]")

    claude_dirs_list = _parse_csv(claude_config_dirs, [])

    try:
        ides = resolve_ides(
            ide,
            home=None,
            claude_config_dir=os.environ.get("CLAUDE_CONFIG_DIR"),
        )
    except ValueError as e:
        print_error(e)
        raise typer.Exit(code=2) from e

    if not ides:
        console.print(
            "[yellow]no IDE detected[/yellow] — `~/.claude` / `~/.cursor` 둘 다 부재. "
            "`--ide claude` 또는 `--ide cursor` 로 명시하면 신규 작성됩니다."
        )
        raise typer.Exit(code=0)

    plans = plan_install(
        ides,
        scope=scope,
        claude_config_dir=os.environ.get("CLAUDE_CONFIG_DIR"),
        claude_config_dirs=claude_dirs_list or None,
        command_path=command_path,
    )
    _print_install_plans(plans, action="install")

    if not apply_changes:
        console.print(
            "\n[yellow]dry-run[/yellow] — 변경 없음. 실제 적용: "
            "[bold]anvyc mcp install --apply[/bold]"
        )
        return

    if not yes and not typer.confirm("\n적용하시겠습니까?", default=False):
        console.print("취소.")
        raise typer.Exit(code=1)

    results = apply_install(plans)
    for r in results:
        if not r.written:
            console.print(
                f"[dim]skip[/dim] {r.plan.ide}: 이미 동일 등록 ({_short_home(r.plan.target_path)})"
            )
            continue
        backup_msg = (
            f" (.bak={_short_home(r.plan.backup_path)})"
            if r.backup_written and r.plan.backup_path
            else ""
        )
        console.print(
            f"[green]wrote[/green] {r.plan.ide}: "
            f"{_short_home(r.plan.target_path)}{backup_msg}"
        )

    console.print(
        "\n[bold]next[/bold] IDE 재시작 필요 — Cmd+Q 후 재실행 "
        '(또는 Claude Code: "Developer: Reload Window").'
    )


@mcp_app.command("uninstall")
def mcp_uninstall(
    ide: str = typer.Option(
        "auto",
        "--ide",
        help="claude | cursor | both | auto.",
    ),
    scope: str = typer.Option("user", "--scope"),
    apply_changes: bool = typer.Option(False, "--apply"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """mcp.json 에서 anvyc entry 만 제거 — 다른 server 는 보존."""
    from anvyc.core.mcp_setup import apply_uninstall, plan_uninstall, resolve_ides

    try:
        ides = resolve_ides(
            ide,
            home=None,
            claude_config_dir=os.environ.get("CLAUDE_CONFIG_DIR"),
        )
    except ValueError as e:
        print_error(e)
        raise typer.Exit(code=2) from e

    if not ides:
        console.print("[yellow]no IDE detected[/yellow].")
        raise typer.Exit(code=0)

    plans = plan_uninstall(
        ides,
        scope=scope,
        claude_config_dir=os.environ.get("CLAUDE_CONFIG_DIR"),
    )
    _print_install_plans(plans, action="uninstall")

    if not apply_changes:
        console.print(
            "\n[yellow]dry-run[/yellow] — 변경 없음. 실제 적용: "
            "[bold]anvyc mcp uninstall --apply[/bold]"
        )
        return

    if not yes and not typer.confirm("\n적용하시겠습니까?", default=False):
        console.print("취소.")
        raise typer.Exit(code=1)

    results = apply_uninstall(plans)
    for r in results:
        if not r.removed:
            console.print(
                f"[dim]skip[/dim] {r.plan.ide}: anvyc 등록 없음 "
                f"({_short_home(r.plan.target_path)})"
            )
            continue
        console.print(
            f"[green]removed[/green] {r.plan.ide}: "
            f"{_short_home(r.plan.target_path)}"
        )

    console.print(
        "\n[bold]next[/bold] IDE 재시작 시점에 anvyc tool 이 사라집니다."
    )


@mcp_app.command("status")
def mcp_status(
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
) -> None:
    """양쪽 IDE 의 mcp.json 에 anvyc 등록 상태 표 출력 (read-only)."""
    from rich.table import Table

    from anvyc.core.mcp_setup import collect_status

    rows = collect_status(
        claude_config_dir=os.environ.get("CLAUDE_CONFIG_DIR"),
    )

    if json_out:
        payload = [
            {
                "ide": r.ide,
                "scope": r.scope,
                "path": str(r.path),
                "exists": r.exists,
                "has_anvyc": r.has_anvyc,
                "anvyc_command": r.anvyc_command,
                "anvyc_args": r.anvyc_args,
                "other_servers": r.other_servers,
            }
            for r in rows
        ]
        typer.echo(jsonlib.dumps(payload, ensure_ascii=False, indent=2))
        return

    table = Table(title="mcp.json 등록 상태")
    table.add_column("ide")
    table.add_column("scope")
    table.add_column("path")
    table.add_column("anvyc")
    table.add_column("command")
    table.add_column("다른 server")

    for r in rows:
        anvyc_cell = (
            "[green]✓ yes[/green]" if r.has_anvyc
            else ("[dim]— no[/dim]" if r.exists else "[dim]missing[/dim]")
        )
        command_cell = r.anvyc_command or "—"
        others = ", ".join(r.other_servers) or "—"
        table.add_row(r.ide, r.scope, _short_home(r.path), anvyc_cell, command_cell, others)

    console.print(table)


if __name__ == "__main__":
    app()

"""anvyc CLI entrypoint (Typer).

MVP 단계에서는 명령어 시그니처와 흐름만 정의하고, 실제 동작은 core/adapters 구현 후 연결한다.
"""

from __future__ import annotations

import contextlib
import json as jsonlib
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
from anvyc.core.diff import compute_diff
from anvyc.core.doctor import DoctorReport, run_doctor
from anvyc.core.list import list_backups
from anvyc.core.restore import run_restore
from anvyc.core.status import compute_status
from anvyc.templates import DEFAULT_ANVYC_YAML

app = typer.Typer(
    name="anvyc",
    help="여러 장치에서 개발 도구 설정을 안전하게 백업/비교/복원/동기화한다.",
    no_args_is_help=True,
    add_completion=False,
)

git_app = typer.Typer(name="git", help=".anvyc 영역에 대한 Git 작업 wrapper.")
app.add_typer(git_app, name="git")

sops_app = typer.Typer(name="sops", help="SOPS 단독 명령 (encrypt/decrypt/rotate-keys).")
app.add_typer(sops_app, name="sops")

config_app = typer.Typer(name="config", help="anvyc.yaml 편집/조회.")
app.add_typer(config_app, name="config")

tools_app = typer.Typer(name="tools", help="anvyc 가 관리하는 도구 조회/관리.")
app.add_typer(tools_app, name="tools")

project_app = typer.Typer(name="project", help="cwd 의 connection 정보 조회 (v0.8.0+).")
app.add_typer(project_app, name="project")

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


@app.command()
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

    `--interactive` 사용 시 9개 도구에 대해 enable 여부와 path 를 prompt.
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
            console.print(f"[red]error[/] git clone 실패\n{proc.stderr.strip()}")
            raise typer.Exit(code=1)
        config_path = anvyc_dir / "anvyc.yaml"
        if not config_path.is_file():
            console.print(
                f"[red]error[/] clone 된 repo 에 anvyc.yaml 부재: {config_path}\n"
                f"  ({anvyc_dir} 는 그대로 두니 직접 검증 후 제거하세요)"
            )
            raise typer.Exit(code=1)
        console.print(f"[green]cloned[/] {from_git} → {anvyc_dir}")
        console.print("[bold]next[/] anvyc doctor  &&  anvyc apply --dry-run  &&  anvyc apply")
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


# wizard 의 도구별 default 값 (file-based adapter 만 file path 입력 필요)
_WIZARD_FILE_DEFAULTS: dict[str, list[str]] = {
    "shell": ["~/.zshrc", "~/.zprofile"],
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
    """대화형 wizard — 9 도구의 enable/path 를 prompt 한 후 yaml 작성."""
    import yaml as _yaml
    from rich.syntax import Syntax

    config_path = anvyc_dir / "anvyc.yaml"
    if config_path.exists() and not force:
        console.print(f"[red]error[/] {config_path} 이미 존재 — 다른 --root 사용 또는 --force")
        raise typer.Exit(code=1)

    console.print("[bold]anvyc init wizard[/] — 9개 도구 설정\n")

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


@app.command()
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


@app.command()
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


@app.command()
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
        console.print(f"[red]{e}[/]")
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


@app.command()
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
        console.print(f"[red]{e}[/]")
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
            if line.startswith("+") and not line.startswith("+++"):
                console.print(f"[green]{line}[/]")
            elif line.startswith("-") and not line.startswith("---"):
                console.print(f"[red]{line}[/]")
            elif line.startswith("@@"):
                console.print(f"[cyan]{line}[/]")
            else:
                console.print(line)
        printed += 1
    if printed == 0:
        console.print("[green]no differences[/]")


@app.command()
def apply(
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
    config: Path | None = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    backup_id: str | None = typer.Option(
        None, "--backup-id", help="적용할 backup id. 미지정 시 current/최신."
    ),
    only: list[str] | None = typer.Option(None, "--only", help="특정 도구만 (반복 가능)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="실제 변경 없이 적용 시나리오만 출력."),
    force: bool = typer.Option(False, "--force", help="medium 위험까지 허용하고 진행."),
) -> None:
    """backup 의 설정을 현재 target 에 적용한다. 적용 전 local-backup 자동 생성.

    처음 사용 시 --dry-run 으로 변경 예정 사항을 먼저 확인 권장.
    예) anvyc apply --dry-run
        anvyc apply --only shell --dry-run
    """
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
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1) from e

    _print_apply_report(report)
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


@app.command()
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
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1) from e

    _print_apply_report(report, label="restore")
    if not dry_run and report.has_error():
        raise typer.Exit(code=3)


@app.command(name="list")
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


@app.command(name="scan-secrets")
def scan_secrets(
    paths: list[Path] | None = typer.Argument(
        None, help="스캔할 파일/디렉터리. 지정 안 하면 --staged 필요."
    ),
    staged: bool = typer.Option(
        False, "--staged", help="현재 cwd 의 git 저장소에서 staged 파일만 스캔."
    ),
    root: Path | None = typer.Option(None, "--root", help="--staged 의 git repo 경로 override."),
    json_out: bool = typer.Option(False, "--json", help="JSON 출력."),
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
            console.print(f"[red]git diff --cached 실패: {e.stderr}[/]")
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
        console.print(f"[red]{e}[/]")
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
        console.print(f"[red]{e}[/]")
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
        console.print(f"[red]commit failed: {e}[/]")
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
        console.print(f"[red]push failed: {e}[/]")
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
        console.print(f"[red]encrypt 실패: {e}[/]")
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
            console.print(f"[red]decrypt 실패: {e}[/]")
            raise typer.Exit(code=1) from e
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        return

    try:
        sops_decrypt_fn(src, output, identity_file=identity_arg, mode=mode)
    except SopsError as e:
        console.print(f"[red]decrypt 실패: {e}[/]")
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
        console.print(f"[red]error[/] EDITOR 파싱 실패: {e}")
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
        console.print(f"[red]error[/] schema 검증 실패: {e}")
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
        False, "--json", help="machine-readable JSON (--effective 와 함께 권장)."
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
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON 출력."),
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
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON 출력."),
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


@app.command()
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
        # mcp 미설치 시 mcp/server.py 가 SystemExit 던짐 — 그대로 표시
        console.print(f"[red]error[/] {e}")
        raise typer.Exit(code=1) from e
    mcp_run()


@app.command()
def prompt(
    path: Path = typer.Option(Path.cwd(), "--path", help="대상 디렉터리 (default: cwd)."),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON 출력 (key→value)."),
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
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON."),
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
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON 출력."),
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


@app.command()
def activity(
    json_out: bool = typer.Option(False, "--json", help="JSON 출력"),
    limit: int | None = typer.Option(None, "--limit", help="최대 표시 session 수"),
) -> None:
    """Claude Code session 활동 요약 (`~/.claude*/projects/*/*.jsonl`).

    멀티계정 환경의 모든 session transcript 를 수집해 session 별 메타데이터와
    tool 호출 카운트를 출력한다. 데이터 수집은 read-only — write 작업 없음.
    CP-1 (audit / observability) 의 2/3 — collector 는 core/activity.py, MCP tool
    노출은 후속 PR.
    """
    sessions = collect_sessions()
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


if __name__ == "__main__":
    app()

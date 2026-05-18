"""anvyc CLI entrypoint (Typer).

MVP 단계에서는 명령어 시그니처와 흐름만 정의하고, 실제 동작은 core/adapters 구현 후 연결한다.
"""
from __future__ import annotations

import json as jsonlib
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from anvyc import __version__
from anvyc.checks.base import Severity
from anvyc.core.apply import ApplyBlocked, ApplyReport, run_apply
from anvyc.core.restore import run_restore
from anvyc.core.backup import BackupBlocked, run_backup
from anvyc.core.diff import compute_diff
from anvyc.core.doctor import DoctorReport, run_doctor
from anvyc.core.list import list_backups
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
) -> None:
    """`.anvyc/` 와 `anvyc.yaml` 초기화."""
    anvyc_dir = root / ".anvyc"
    config_path = anvyc_dir / "anvyc.yaml"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True, exist_ok=True)
    if config_path.exists() and not force:
        console.print(f"[yellow]exists[/] {config_path} (use --force to overwrite)")
    else:
        config_path.write_text(DEFAULT_ANVYC_YAML)
        console.print(f"[green]wrote[/] {config_path}")
    console.print(f"[green]ready[/] {anvyc_dir}")


@app.command()
def doctor(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="모든 finding 나열."),
    strict: bool = typer.Option(False, "--strict", help="warning 이상 발견 시 exit 1."),
    json_out: bool = typer.Option(False, "--json", help="기계 가독 JSON 출력."),
    only: Optional[list[str]] = typer.Option(None, "--only", help="실행할 check 이름 (반복 가능)."),
    skip: Optional[list[str]] = typer.Option(None, "--skip", help="건너뛸 check 이름 (반복 가능)."),
    config: Optional[Path] = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
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
                f"  [{_severity_style(r.severity)}]{r.severity.value}[/] "
                f"{loc}{line} — {r.message}"
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
    root: Optional[Path] = typer.Option(None, "--root", help=".anvyc 디렉터리 경로."),
    config: Optional[Path] = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    only: Optional[list[str]] = typer.Option(None, "--only", help="특정 도구만 백업 (반복 가능)."),
    force: bool = typer.Option(False, "--force", help="medium 위험까지 허용하고 진행."),
) -> None:
    """enabled adapter 들의 설정 파일을 `.anvyc/backups/<ts>/`에 백업한다."""
    try:
        result = run_backup(root=root, config_path=config, only=only or None, force=force)
    except BackupBlocked as e:
        console.print("[red bold]backup 중단: secret scan 차단[/]")
        for r in e.reasons:
            console.print(f"  • {r}")
        console.print("\n[dim]--force 로 medium 위험을 허용할 수 있습니다 (critical/high 는 강제 불가).[/]")
        raise typer.Exit(code=2)

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
    backup_id: Optional[str] = typer.Option(None, "--backup-id", help="비교 대상 backup. 미지정 시 current 또는 최신."),
) -> None:
    """current(target) vs backup 의 drift 를 요약한다."""
    try:
        report = compute_status(root, backup_id=backup_id)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1)

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
    for e in report.entries:
        style = {"unchanged": "dim", "modified": "yellow", "missing": "red"}[e.state]
        table.add_row(
            f"[{style}]{e.state}[/]",
            e.tool,
            _short_path(e.target_path),
            (e.actual_sha256 or "—")[:12],
        )
    console.print(table)


@app.command()
def diff(
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
    backup_id: Optional[str] = typer.Option(None, "--backup-id", help="비교 대상 backup. 미지정 시 current/최신."),
    only_changed: bool = typer.Option(True, "--only-changed/--all", help="변경된 파일만 출력."),
) -> None:
    """backup → 현재 target unified diff 를 출력한다."""
    try:
        report = compute_status(root, backup_id=backup_id)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1)

    printed = 0
    for e in report.entries:
        if only_changed and e.state == "unchanged":
            continue
        target = e.target_resolved
        d = compute_diff(
            e.source_path,
            target,
            label_source=f"backup:{e.source_path.name}",
            label_target=f"target:{_short_path(e.target_path)}",
        )
        console.print(f"\n[bold]── {_short_path(e.target_path)} ({e.state})[/]")
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
    config: Optional[Path] = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    backup_id: Optional[str] = typer.Option(None, "--backup-id", help="적용할 backup id. 미지정 시 current/최신."),
    only: Optional[list[str]] = typer.Option(None, "--only", help="특정 도구만 (반복 가능)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="실제 변경 없이 적용 시나리오만 출력."),
    force: bool = typer.Option(False, "--force", help="medium 위험까지 허용하고 진행."),
) -> None:
    """backup 의 설정을 현재 target 에 적용한다. 적용 전 local-backup 자동 생성."""
    try:
        report = run_apply(
            root=root,
            config_path=config,
            backup_id=backup_id,
            only=only or None,
            dry_run=dry_run,
            force=force,
        )
    except ApplyBlocked as e:
        console.print("[red bold]apply 중단: secret scan 차단[/]")
        for r in e.reasons:
            console.print(f"  • {r}")
        console.print("\n[dim]--force 로 medium 위험을 허용할 수 있습니다.[/]")
        raise typer.Exit(code=2)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1)

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
    config: Optional[Path] = typer.Option(None, "--config", help="명시 anvyc.yaml 경로."),
    only: Optional[list[str]] = typer.Option(None, "--only", help="특정 도구만 (반복 가능)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="실제 변경 없이 시나리오만 출력."),
    force: bool = typer.Option(False, "--force", help="medium 위험까지 허용."),
) -> None:
    """특정 backup 으로 target 을 복원한다. apply 와 동일하나 backup_id 가 필수."""
    try:
        report = run_restore(
            root=root,
            backup_id=backup_id,
            config_path=config,
            only=only or None,
            dry_run=dry_run,
            force=force,
        )
    except ApplyBlocked as e:
        console.print("[red bold]restore 중단: secret scan 차단[/]")
        for r in e.reasons:
            console.print(f"  • {r}")
        console.print("\n[dim]--force 로 medium 위험을 허용할 수 있습니다.[/]")
        raise typer.Exit(code=2)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1)

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
    paths: Optional[list[Path]] = typer.Argument(None, help="스캔할 파일/디렉터리. 지정 안 하면 --staged 필요."),
    staged: bool = typer.Option(False, "--staged", help="현재 cwd 의 git 저장소에서 staged 파일만 스캔."),
    root: Optional[Path] = typer.Option(None, "--root", help="--staged 의 git repo 경로 override."),
    json_out: bool = typer.Option(False, "--json", help="JSON 출력."),
    quiet: bool = typer.Option(False, "--quiet", help="발견 시에도 메시지 최소화 (pre-commit hook 용)."),
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
            raise typer.Exit(code=2)
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
                style = {"critical": "red bold", "high": "red", "medium": "yellow", "low": "dim"}.get(
                    f.severity, "white"
                )
                table.add_row(
                    f"[{style}]{f.severity}[/]",
                    f.pattern,
                    _short_path(f.path),
                    str(f.line_number),
                )
            console.print(table)
            if decision.block:
                console.print(f"\n[red bold]차단됨 — reasons:[/]")
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
        raise typer.Exit(code=1)
    console.print(f"[green]git init OK[/] {_short_path(root.resolve())}")
    console.print(f"  [dim]pre-commit hook 설치됨 — push 전 secret scan 자동 실행[/]")


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
        raise typer.Exit(code=1)
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
        raise typer.Exit(code=1)
    if out:
        typer.echo(out, nl=False)


@git_app.command("push")
def git_push(
    remote: str = typer.Option("origin", "--remote"),
    branch: Optional[str] = typer.Option(None, "--branch"),
    root: Path = typer.Option(Path(".anvyc"), "--root", help=".anvyc 디렉터리."),
) -> None:
    """.anvyc 영역의 git push."""
    from anvyc.storage.git import GitError, push
    try:
        out = push(root.resolve(), remote=remote, branch=branch)
    except GitError as e:
        console.print(f"[red]push failed: {e}[/]")
        raise typer.Exit(code=1)
    if out:
        typer.echo(out, nl=False)


if __name__ == "__main__":
    app()

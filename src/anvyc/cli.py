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
from anvyc.core.doctor import DoctorReport, run_doctor

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
) -> None:
    """`.anvyc/` 와 `anvyc.yaml` 초기화 (MVP TODO)."""
    console.print(f"[yellow]TODO[/]: init at {root}")


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
def backup() -> None:
    """현재 환경 설정을 `.anvyc/backups/<timestamp>/`에 저장한다 (MVP TODO)."""
    console.print("[yellow]TODO[/]: backup")


@app.command()
def status() -> None:
    """현재 target 상태와 마지막 backup의 차이를 요약한다 (MVP TODO)."""
    console.print("[yellow]TODO[/]: status")


@app.command()
def diff() -> None:
    """target과 source(backup) 간 unified diff 출력 (MVP TODO)."""
    console.print("[yellow]TODO[/]: diff")


@app.command()
def apply(
    dry_run: bool = typer.Option(False, "--dry-run", help="실제 변경 없이 적용 시나리오만 출력."),
) -> None:
    """source 설정을 target에 적용한다. 적용 전 local backup 자동 생성 (MVP TODO)."""
    console.print(f"[yellow]TODO[/]: apply (dry_run={dry_run})")


@app.command()
def restore(backup_id: str = typer.Argument(..., help="복원할 backup id (timestamp).")) -> None:
    """특정 backup으로 target을 복원한다 (MVP TODO)."""
    console.print(f"[yellow]TODO[/]: restore {backup_id}")


@app.command(name="list")
def list_backups() -> None:
    """보관 중인 backup 목록을 출력한다 (MVP TODO)."""
    console.print("[yellow]TODO[/]: list")


@app.command(name="scan-secrets")
def scan_secrets(
    target: Optional[Path] = typer.Argument(None, help="스캔 대상 경로. 미지정 시 현재 target."),
) -> None:
    """secret 패턴을 스캔한다 (MVP TODO)."""
    console.print(f"[yellow]TODO[/]: scan-secrets target={target}")


@git_app.command("init")
def git_init() -> None:
    """.anvyc 영역을 Git 저장소로 초기화 (MVP TODO)."""
    console.print("[yellow]TODO[/]: git init")


@git_app.command("status")
def git_status() -> None:
    """.anvyc 영역의 git status (MVP TODO)."""
    console.print("[yellow]TODO[/]: git status")


@git_app.command("commit")
def git_commit(
    message: str = typer.Option(..., "-m", "--message", help="커밋 메시지."),
) -> None:
    """.anvyc 영역의 git commit (MVP TODO)."""
    console.print(f"[yellow]TODO[/]: git commit -m {message!r}")


@git_app.command("push")
def git_push() -> None:
    """.anvyc 영역의 git push. pre-commit secret scan 통과 시에만 허용 (MVP TODO)."""
    console.print("[yellow]TODO[/]: git push")


if __name__ == "__main__":
    app()

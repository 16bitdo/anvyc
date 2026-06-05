"""core/gh_account_view — 오프라인 계정 뷰 조립(네트워크 0)."""

from pathlib import Path
from types import SimpleNamespace

from anvyc.core.gh_account_view import collect_accounts


def _mk_gh(config_home: Path, dirname: str, host: str, user: str) -> None:
    d = config_home / dirname
    d.mkdir(parents=True, exist_ok=True)
    # oauth_token 라인 포함 — 토큰 불가침 회귀 가드
    (d / "hosts.yml").write_text(
        f"{host}:\n    users:\n        {user}:\n            oauth_token: ghp_SECRET_DO_NOT_READ\n",
        encoding="utf-8",
    )


def test_discovered_account_logged_in(tmp_path: Path) -> None:
    ch = tmp_path / ".config"
    _mk_gh(ch, "gh-16bitdo", "github.com", "16bitdo")
    views = collect_accounts(config_home=ch, owner_accounts={}, cwd=tmp_path)
    assert len(views) == 1
    v = views[0]
    assert v.account == "16bitdo" and v.logged_in is True
    assert v.config_dir is not None and v.expiry_status == "unknown"


def test_routed_owners_reverse_index(tmp_path: Path) -> None:
    ch = tmp_path / ".config"
    _mk_gh(ch, "gh-heisgone", "github.com", "heisgone")
    views = collect_accounts(config_home=ch, owner_accounts={"whatap": "heisgone"}, cwd=tmp_path)
    assert views[0].routed_owners == ["whatap"]


def test_mapped_but_not_logged_in(tmp_path: Path) -> None:
    ch = tmp_path / ".config"
    ch.mkdir(parents=True)
    views = collect_accounts(config_home=ch, owner_accounts={"acme": "ghost"}, cwd=tmp_path)
    ghost = next(v for v in views if v.account == "ghost")
    assert ghost.logged_in is False and ghost.config_dir is None


def test_no_token_value_leaks(tmp_path: Path) -> None:
    ch = tmp_path / ".config"
    _mk_gh(ch, "gh-16bitdo", "github.com", "16bitdo")
    views = collect_accounts(config_home=ch, owner_accounts={}, cwd=tmp_path)
    assert "ghp_SECRET_DO_NOT_READ" not in repr(views)


def test_probe_results_merged(tmp_path: Path) -> None:
    """probe_results 제공 시 (host, account) 키로 status/expires_at 병합."""
    ch = tmp_path / ".config"
    _mk_gh(ch, "gh-16bitdo", "github.com", "16bitdo")
    probe = {
        ("github.com", "16bitdo"): SimpleNamespace(
            status="valid", expires_at="2026-12-31T00:00:00Z"
        )
    }
    views = collect_accounts(config_home=ch, owner_accounts={}, cwd=tmp_path, probe_results=probe)
    assert views[0].expiry_status == "valid"
    assert views[0].expires_at == "2026-12-31T00:00:00Z"


def test_cwd_routed_via_origin_alias(tmp_path: Path) -> None:
    """cwd 가 origin SSH alias(github.com-<account>) repo 면 cwd_routed=True."""
    ch = tmp_path / ".config"
    _mk_gh(ch, "gh-16bitdo", "github.com", "16bitdo")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com-16bitdo:16bitdo/anvyc.git\n',
        encoding="utf-8",
    )
    views = collect_accounts(config_home=ch, owner_accounts={}, cwd=tmp_path)
    assert views[0].cwd_routed is True

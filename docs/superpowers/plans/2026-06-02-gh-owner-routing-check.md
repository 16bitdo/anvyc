# gh owner↔alias 라우팅 검증 강화 — 구현 플랜

> **For agentic workers:** TDD. Steps use `- [ ]` checkboxes.

**Goal:** `project-gh-account-mapping` check 가 현재 `ssh alias ↔ .envrc` 일치만 보는 사각지대를 메운다 — repo **owner ↔ alias** 정합(rule 25)을 **static(config 매핑) 우선 + dynamic(gh write 권한) 보강**으로 검증해 argus-slack-bot 류(self-consistent 하나 owner 와 안 맞는 라우팅)를 포착.

**Architecture:** owner→기대 account 매핑은 `anvyc.yaml` `doctor.gh_owner_accounts`(config SoT, rule 25 미러). 미설정 시 owner-검증 완전 skip(무오탐, 기존 동작 불변). static 불일치 repo 에만 dynamic `gh api .../permissions`(routed 계정 write 여부) 호출 → 확정 WARN vs 이탈 INFO.

**결정(승인됨):** 검증=static+dynamic, 매핑 SoT=anvyc.yaml config, 구조=기존 check 확장.

## 판정 로직
| owner∈매핑? | alias==기대? | dynamic write? | 결과 |
|---|---|---|---|
| 미설정/owner없음 | — | — | skip (무오탐) |
| O | 일치 | (미호출) | OK |
| O | 불일치 | False | **WARNING** (확정 misroute) |
| O | 불일치 | True/불확정 | **INFO** (규약 이탈하나 동작/확인불가 — collaborator?) |
dynamic 은 static 불일치 시에만 → 정상 repo network 0.

---

## Task 1: config 주입 (owner 매핑 → CheckContext)

**Files:** `src/anvyc/core/config.py`, `src/anvyc/checks/base.py`

- [ ] **base.py — CheckContext 필드 추가** (`creds_warn_thresholds` 옆):
```python
    # owner→gh account(=ssh alias suffix) 매핑. 빈 dict = owner-routing 검증 skip(무오탐).
    # anvyc.yaml `doctor.gh_owner_accounts` 에서 주입(rule 25 미러).
    gh_owner_accounts: dict[str, str] = field(default_factory=dict)
```

- [ ] **config.py — `DoctorConfig`(L109) 와 `DoctorOnlyConfig`(L379) 양쪽에 필드 추가**:
```python
    gh_owner_accounts: dict[str, str] = field(default_factory=dict)
```

- [ ] **config.py — load_anvyc_config(L328~) 파싱** (creds 옆):
```python
    gh_owner_accounts = dict(doctor_raw.get("gh_owner_accounts") or {})
```
그리고 `DoctorConfig(...)` 생성(L336)에 `gh_owner_accounts=gh_owner_accounts,` 추가.

- [ ] **config.py — DoctorOnlyConfig 빌더(L388~)** 에 `gh_owner_accounts=cfg.doctor.gh_owner_accounts,` 추가.

- [ ] **config.py — build_check_context(L399)** CheckContext(...) 호출에 `gh_owner_accounts=dict(cfg.gh_owner_accounts),` 추가.

- [ ] **Step: 회귀** `.venv/bin/python -m pytest tests/unit/test_config*.py -q` — 기존 config 테스트 green(필드 추가가 기존 파싱 안 깸).

## Task 2: check owner-routing 패스 + dynamic 보강

**Files:** `src/anvyc/checks/project_gh_account.py`

- [ ] **Step 1: 실패 테스트 먼저** (Task 3 에서 작성 → 여기 구현으로 통과).

- [ ] **Step 2: origin 파싱에 owner/repo 포함.** 기존 `_origin_ssh_alias` 는 alias 만 반환 → owner/repo 도 함께 쓰도록 target 수집부에서 `parse_git_config` 의 `remote.owner`/`remote.repo` 를 capture. (target tuple 을 `(project_dir, alias, owner, repo)` 로 확장하거나, owner-routing 전용 수집 루프 추가.)

- [ ] **Step 3: dynamic 헬퍼 추가** (모듈 레벨, patch 가능):
```python
def _repo_write_access(owner: str, repo: str, account: str) -> bool | None:
    """routed account(gh-<account>) 로 owner/repo write(push|admin) 권한 보유 여부.
    조회 실패/권한키 부재 → None(불확정). doctor 내 network — static 불일치 시에만 호출."""
    import json
    import os
    import subprocess
    env = {**os.environ, "GH_CONFIG_DIR": os.path.expanduser(f"~/.config/gh-{account}")}
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}", "--jq", ".permissions"],
            capture_output=True, text=True, check=False, timeout=15, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        perm = json.loads(proc.stdout) or {}
    except (ValueError, AttributeError):
        return None
    if not isinstance(perm, dict):
        return None
    return bool(perm.get("push") or perm.get("admin"))
```

- [ ] **Step 4: run() 에 owner-routing 패스 추가** (기존 alias↔envrc 패스 *뒤*, 독립 findings):
```python
        # owner↔alias 라우팅 검증 (rule 25; ctx.gh_owner_accounts 설정 시에만).
        for project_dir, alias, owner, repo in routing_targets:
            expected = ctx.gh_owner_accounts.get(owner)
            if not expected or alias == expected:
                continue
            write = _repo_write_access(owner, repo, alias)
            if write is False:
                results.append(CheckResult(
                    check_name=self.name, severity=Severity.WARNING,
                    message=(f"{owner}/{repo}: owner '{owner}' 는 alias '{expected}' 라우팅이어야 "
                             f"하나 '{alias}' 사용 — 그 계정은 write 권한 없음(misroute)"),
                    location=project_dir,
                    suggestion=(f"remote 를 github.com-{expected} 로, .envrc GH_CONFIG_DIR 를 "
                                f"gh-{expected} 로 (rule 25)"),
                ))
            else:
                results.append(CheckResult(
                    check_name=self.name, severity=Severity.INFO,
                    message=(f"{owner}/{repo}: alias '{alias}'(기대 '{expected}') 불일치 — "
                             f"write 가능(collaborator?) 또는 권한 확인 불가; 의도 확인 권고"),
                    location=project_dir,
                ))
```
(기존 alias↔envrc summary INFO/warning 로직은 그대로 유지 — owner-routing 은 별도 finding set.)

## Task 3: 테스트

**Files:** `tests/unit/test_project_gh_account.py`

- [ ] 기존 테스트는 `CheckContext()` (gh_owner_accounts 빈) → owner-검증 skip → 그대로 green(회귀 가드).
- [ ] 신규 케이스 (monkeypatch `_repo_write_access`):
```python
def test_owner_alias_match_no_owner_warn(docs):
    proj = docs / "p"; _write_origin(proj, "git@github.com-16bitdo:16bitdo/p.git"); _write_envrc_gh(proj, "16bitdo")
    res = ProjectGhAccountMappingCheck().run(CheckContext(gh_owner_accounts={"16bitdo": "16bitdo"}))
    assert not any("misroute" in r.message or "불일치" in r.message for r in res)

def test_owner_alias_mismatch_no_write_warns(docs, monkeypatch):
    proj = docs / "p"; _write_origin(proj, "git@github.com-16bitdo:whatap/p.git"); _write_envrc_gh(proj, "16bitdo")
    monkeypatch.setattr("anvyc.checks.project_gh_account._repo_write_access", lambda o,r,a: False)
    res = ProjectGhAccountMappingCheck().run(CheckContext(gh_owner_accounts={"whatap": "heisgone"}))
    assert any(r.severity is Severity.WARNING and "misroute" in r.message for r in res)

def test_owner_alias_mismatch_with_write_info(docs, monkeypatch):
    proj = docs / "p"; _write_origin(proj, "git@github.com-16bitdo:whatap/p.git"); _write_envrc_gh(proj, "16bitdo")
    monkeypatch.setattr("anvyc.checks.project_gh_account._repo_write_access", lambda o,r,a: True)
    res = ProjectGhAccountMappingCheck().run(CheckContext(gh_owner_accounts={"whatap": "heisgone"}))
    assert any(r.severity is Severity.INFO and "불일치" in r.message for r in res)

def test_owner_not_in_mapping_skips(docs, monkeypatch):
    proj = docs / "p"; _write_origin(proj, "git@github.com-16bitdo:pyroscopy/p.git"); _write_envrc_gh(proj, "16bitdo")
    called = {"n": 0}
    monkeypatch.setattr("anvyc.checks.project_gh_account._repo_write_access", lambda o,r,a: called.__setitem__("n", called["n"]+1) or False)
    res = ProjectGhAccountMappingCheck().run(CheckContext(gh_owner_accounts={"whatap": "heisgone"}))
    assert called["n"] == 0  # pyroscopy 미매핑 → dynamic 미호출
```
- [ ] `.venv/bin/python -m pytest tests/unit/test_project_gh_account.py -v` → 전부 green.

## Task 4: config 적용 + 문서 + 검증

- [ ] `~/.anvyc/anvyc.yaml` 에 `doctor.gh_owner_accounts: {16bitdo: 16bitdo, whatap: heisgone}` 추가(라이브 활성화).
- [ ] 라이브: `anvyc doctor --only project-gh-account-mapping` → 현 ~/dev(전부 정합)에서 owner-warn 0 확인.
- [ ] DESIGN.md 1줄(owner↔alias 검증 추가) + rule 25 에 "anvyc doctor 가 gh_owner_accounts 로 owner↔alias 정합 검증(config 는 rule 25 표 미러)" 주석.

## 검증 / PR / 주의
- 전체 unit + ruff + mypy + doctor 통합(test_doctor_json) green.
- PR + self-merge — ⚠️ anvyc PR-강제 + **gh active 가 heisgone 으로 드리프트 중** → PR 전 `GH_CONFIG_DIR=~/.config/gh-16bitdo gh auth switch -u 16bitdo` 선행 필수.
- SoT 중복: config 는 rule 25 미러 — 불일치 방지 위해 향후 rule 25 머신가독화 통합 검토(follow-up).
- opt-in 무오탐: gh_owner_accounts 미설정 머신은 owner-검증 완전 skip(기존 동작 불변).

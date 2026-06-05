# `anvyc github` — GitHub 계정 통합 뷰 + 라우팅 관리 설계

- **날짜**: 2026-06-05
- **상태**: 초안 — 검토 대기
- **프로젝트**: anvyc (L2-environment)
- **관련**: `utils/gh_hosts.py`(`GhAccount`·`parse_hosts_yml`·`discover_gh_accounts`·`select_config_dir_for_user`), `core/creds.py:375`(`detect_github` — GitHub PAT/OAuth 만료), `core/gh_route.py`(`resolve_account`/`run_gh` — `anvyc gh` passthrough), `core/project_init.py`(`write_envrc_gh_routing`·`resolve_routing_account`·`gh_account_logged_in`), `core/project_doctor.py:106`(`_check_gh_account_routing`), `core/config.py:117`(`DoctorConfig.gh_owner_accounts`), `core/cost/adapters/github.py`(`discover_gh_accounts` 소비처), `docs/superpowers/specs/2026-06-02-anvyc-gh-routing-design.md`(`anvyc gh` 선행), `docs/superpowers/specs/2026-06-04-aws-profile-and-sso-status-design.md`(대칭 선례)

## 1. 배경 / 문제

`anvyc aws profile`(2026-06-04, v0.21.0)은 AWS 계정을 *한 명령군에서* 조회·상태점검·CRUD 한다. GitHub `gh` 계정에는 **동등한 통합 표면이 없다.** 현재 gh 관련 정보·조작은 다섯 군데로 흩어져 있다.

| 위치 | 하는 일 | 스코프 | 한계 |
|------|---------|--------|------|
| `anvyc gh <args>` (`cli.py:726`, `core/gh_route.py`) | cwd origin account 로 `gh` 실행 (토큰 주입) | 실행(exec) | 계정 **조회/관리 아님** — passthrough |
| `anvyc creds status` (`core/creds.py:375` `detect_github`) | `~/.config/gh*` 계정 + PAT/OAuth 만료 | 전역 lifecycle | AWS/Claude 와 섞인 만료 축만, 라우팅 무관 |
| `anvyc project show` / `project doctor` (`project_doctor.py:106`) | cwd `.envrc GH_CONFIG_DIR` ↔ origin alias 정합 | 단일 프로젝트 | 계정 인벤토리·만료 없음 |
| `anvyc project init` (`project_init.py:18`) | cwd `.envrc` 에 `GH_CONFIG_DIR` 라우팅 작성 | 단일 프로젝트(쓰기) | owner→account 매핑 자체는 못 고침 |
| `anvyc.yaml doctor.gh_owner_accounts` (`config.py:117`) | owner→account 라우팅 매핑(SoT) | 전역 설정 | **수기 편집뿐** — CRUD 명령 부재 |

**문제 1 — GitHub 계정 통합 뷰 부재.** "내 머신에 어떤 gh 계정이 있고(account/host), 로그인돼 있나, 토큰 만료는, 그리고 *지금 이 프로젝트는 어느 계정으로 라우팅*되나?" 를 한 명령으로 못 본다. `aws profile list/show` 의 GitHub 대응물이 없다.

**문제 2 — 라우팅 매핑 CRUD 부재.** owner→account 매핑(`doctor.gh_owner_accounts`)은 `anvyc project init`(#176)·`gh_account_routing` 체크가 **소비**하지만, 추가/수정/삭제는 `anvyc.yaml` 손편집뿐이다. `config roots`/`config projects`(#167·#169)가 컨테이너 root·프로젝트 목록에 준 CRUD 를 라우팅 매핑에는 안 줬다.

**핵심 비대칭 — 그리고 그 이유.** AWS 는 *비밀 아님*(`~/.aws/config`: profile/region/role)과 *비밀*(`~/.aws/credentials`: 정적 키)이 **파일 단위로 분리**돼, anvyc 가 config 만 안전하게 CRUD 한다(정적 키 입력 거부 — `aws_config_edit._reject_static_keys`). **gh 의 "계정"은 토큰 그 자체(`~/.config/gh*/hosts.yml`)** 라, 같은 의미의 "계정 CRUD"는 곧 비밀 쓰기가 된다. → 본 설계는 **비밀을 건드리지 않는 두 축(통합 뷰 = 읽기, 라우팅 = 비밀-아닌 설정)만** 다루고, 인증(login/refresh/token 기록)은 `gh auth`·1Password 에 위임한다.

## 2. 목표 / Non-goals

**목표**:
- GitHub 계정 **통합 읽기 뷰** — `anvyc github account <list|show>`. 발견된 계정(account/host/config_dir) + 로그인 여부 + (opt-in) 토큰 만료 + **현재 프로젝트 라우팅 해석**을 `aws profile list/show` 와 동형 UX 로. **보고 전용.**
- 진짜 토큰 유효성/만료는 **opt-in 네트워크 `--probe`** (`detect_github(probe_expiry=True)` → `gh api` 만료 헤더). 기본은 오프라인(dir/hosts.yml stat + 매핑 해석)만 — doctor 와 동일 원칙.
- **라우팅 매핑 CRUD** — owner→account 매핑(`anvyc.yaml doctor.gh_owner_accounts`)을 `<list|set|rm>` 로 관리. `config roots`/`config projects` 의 안전쓰기(dry-run·`.bak`·재검증) 패턴 이식.
- (선택) **프로젝트 라우팅 적용** — `anvyc github use [<account>]` 가 cwd `.envrc` 의 `GH_CONFIG_DIR` 를 작성(`write_envrc_gh_routing` 재사용). `aws profile use`(미구현 후보)의 GitHub 선행.
- 명령 표면은 `anvyc gh`(passthrough)와 **충돌하지 않는 신규 그룹**.

**Non-goals**:
- `~/.config/gh*/hosts.yml`(토큰) **쓰기 불가침** — 계정 생성/로그인/로그아웃/토큰 기록을 anvyc 가 대행하지 않는다. `gh auth login|switch|logout` 위임.
- 토큰 값을 **입력받지도, 저장하지도, 출력하지도 않는다** (rule 26 / CP-15 "값 미보유"; Phase 3 자체 getpass 방안은 2026-05-29 폐기됨).
- **전역 active account 자동 전환 안 함** — `anvyc gh` 설계(2026-06-02)의 non-goal 승계. 라우팅은 `GH_CONFIG_DIR`(프로젝트별 격리)로, race 의 근원인 전역 switch 를 우회한다.
- 토큰 **회전(rotate) 안 함** — 만료 escalation·회전은 `anvyc creds`(CP-5)가 `gh auth refresh` 위임으로 소유. 본 그룹은 만료를 *표시*만(역할 분리, `aws-account-status`↔`creds-expiry` 선례와 동일).
- 프로젝트당 **다중 gh account 안 함** — 현 모델(`.envrc` 단일 `GH_CONFIG_DIR`) 유지.
- `gh` adapter(`adapters/gh.py`)의 백업 범위(`config.yml` 포함 / `hosts.yml` 제외) **변경 안 함**.

## 3. 결정 (제안)

| 결정 | 선택 | 근거 |
|------|------|------|
| 명령 표면 | **신규 top-level 그룹 `anvyc github`** (관리·조회) — `anvyc gh`(exec passthrough)와 분리 | `anvyc gh` 는 `allow_extra_args`+`ignore_unknown_options` passthrough(`cli.py:726`)라 하위명령 불가 — `anvyc gh account` 는 `gh account` 로 해석됨. `gh`=실행, `github`=anvyc-native 관리로 역할 이원화 |
| 명사 | gh 도메인 용어 **`account`** (AWS 의 `profile` 차용 회피) | gh 자체가 "account/user"(`gh auth switch --user`). 사용자도 "gh 계정"으로 표현 |
| 인증 경계 | **읽기 + 라우팅(비밀 아님)만**. login/refresh/token 기록은 `gh auth`·1Password 위임 | `hosts.yml`=토큰. anvyc 시크릿 비저장 원칙(원칙 1·rule 26·CP-15) |
| 토큰 불가침 | 뷰는 `hosts.yml` 의 **host/user 만** 파싱(`parse_hosts_yml` — `oauth_token` 라인 미접근), 로그인 여부는 **stat**(`gh_account_logged_in`) | aws `~/.aws/credentials` "존재만 확인, 값 미독" 선례와 동형 |
| liveness | **오프라인 기본 + opt-in `--probe`**(`detect_github(probe_expiry=True)`) | doctor offline 원칙. 만료 헤더(`X-GitHub-Token-Expiration`)는 식별자급, 토큰 아님 |
| 라우팅 매핑 쓰기 | `anvyc.yaml doctor.gh_owner_accounts` **surgical 안전쓰기**(dry-run·`.bak`·재검증·롤백) | `core/project_roots_edit.py`+`core/yaml_io.py` 이식. 비밀 아님 |
| 라우팅 매핑 위치 | `anvyc github route <list|set|rm>` (그룹 응집) — **대안**: `anvyc config gh-routes`(config 도메인) | §12 미해결. 기본은 `github` 응집(발견성). config 측 대칭도 일리 |
| 만료/회전 관계 | **역할 분리** — `github account` 는 인벤토리+로그인+만료 *표시*. escalation/회전은 `creds` 유지 | blast radius 최소화(gate/scheduler 의존), 메시지 축 상이 |
| 단계 | **Phase 1 통합 뷰(읽기, `--probe`) → Phase 2 라우팅 CRUD(+`use`)** 별도 PR | Phase 1 이 사용자 핵심(통합 뷰)을 저 blast radius 로 충족, Phase 2 가 위에 구축 — aws profile Phase 분리 답습 |

## 4. 아키텍처

```
─────────────────────────── Phase 1 (읽기 — 통합 뷰) ───────────────────────────
utils/gh_hosts.py          # (기존, 재사용) discover_gh_accounts() -> [GhAccount(config_dir,host,user)]
                           #   parse_hosts_yml: host/user 만 (token 미접근)  ·  select_config_dir_for_user(user)
core/creds.py:375          # (기존, 재사용) detect_github(home,*,warn_threshold_days,now,probe_expiry) -> [CredentialStatus]
                           #   probe_expiry=False → 오프라인(만료 unknown), True → gh api 만료 헤더 (--probe)
core/gh_route.py:21        # (기존, 재사용) resolve_account(cwd) -> account|None   (origin ssh alias)
core/project_init.py       # (기존, 재사용) resolve_routing_account(path, owner_accounts), gh_account_logged_in(account)
core/config.py:117         # (기존, 재사용) DoctorConfig.gh_owner_accounts: dict[owner,account]
core/gh_account_view.py    # (신규) 순수 조립 — 네트워크 의존 0(기본)
                           #   @dataclass GhAccountView(account, host, config_dir, logged_in, expiry_status, expires_at,
                           #                             routed_owners: list[str], cwd_routed: bool)
                           #   collect_accounts(*, home, owner_accounts, cwd, now, probe) -> list[GhAccountView]
                           #     discover_gh_accounts ⨝ detect_github(만료) ⨝ owner_accounts(역인덱스) ⨝ resolve_account(cwd)
cli.py                     # github_app = _typer(name="github"); app.add_typer(.., PANEL_PROJECT)
                           #   github_account_app = _typer(name="account"); github_app.add_typer(.., "account")
                           #   account: list / show <account> (--probe, --json)
─────────────────────────── Phase 2 (쓰기 — 라우팅) ───────────────────────────
core/gh_routes_edit.py     # (신규) owner→account 매핑 CRUD — project_roots_edit 패턴 이식
                           #   set_route(owner, account) / remove_route(owner) -> RoutesEditResult(diff, backup_path, …)
                           #   yaml_io 안전쓰기(.bak + atomic + 재파싱 검증/롤백). doctor.gh_owner_accounts 키만 surgical 갱신
cli.py                     # github route: list / set <owner> <account> / rm <owner>   (--dry-run, --yes)
                           #   github use [<account>]  → write_envrc_gh_routing(cwd/.envrc, account)  (project_init 재사용)
```

**토큰-free 보장**: `core/gh_account_view.py`(뷰 조립)는 `hosts.yml` 의 host/user(`parse_hosts_yml`)·dir stat·매핑·`.envrc` 만 읽는다. 토큰 값은 어떤 경로로도 읽지/보유하지 않는다. 만료는 `detect_github(probe_expiry=True)` 가 `gh api`(gh 가 토큰 사용, anvyc 는 미수신)로 헤더만 취득 — `--probe` 한정.

**라우팅 해석 흐름**(`collect_accounts`, 읽기 전용):
```
discover_gh_accounts(home)                      → 머신의 (config_dir, host, user) 인벤토리
  각 account →
    logged_in   = gh_account_logged_in(user)    (hosts.yml 존재 stat)
    expiry      = detect_github(probe_expiry) 의 동 user 항목 (없으면 unknown)
    routed_owners = {owner | owner_accounts[owner] == user}   (gh_owner_accounts 역인덱스)
    cwd_routed  = (resolve_account(cwd) == user)              (현재 프로젝트가 이 계정으로?)
```

## 5. 뷰 모델 → 표시 매핑 (오프라인, 보고 전용)

`github account list` 기본 컬럼: `account · host · logged_in · expiry(--probe 시) · routed(owners/✓cwd)`.

| 신호 | 오프라인 판정 | 표시(요지) |
|---|---|---|
| 로그인 | `~/.config/gh-<user>/hosts.yml` 존재 | `✓ logged in` / `✗ 미로그인 — gh auth login` |
| 만료(`--probe`) | `detect_github` status(valid/expiring/expired/unknown) | `valid (~Nd)` / `expiring` / `expired — gh auth refresh` / `unknown(no TTL)` |
| 만료(기본) | 미조회 | `— (--probe 로 확인)` |
| 라우팅(owner) | `gh_owner_accounts` 역인덱스 | `owners: 16bitdo` / `(매핑 없음)` |
| 라우팅(cwd) | `resolve_account(cwd)==user` | `✓ 현재 프로젝트` |
| 매핑만 있고 계정 부재 | owner→account 가 인벤토리에 없음 | `⚠ 매핑된 account 'X' 미로그인` |

- 만료 escalation(WARNING/CRITICAL)·회전 제안은 `creds`(CP-5) 소유 — 여기선 INFO 급 표시만.
- `--probe` 미지정 시 `expiry_status="unknown"`, 네트워크 0.

## 6. 명령 스펙 — `anvyc github`

출력 규약은 doctor·`aws profile` 과 동일(Panel 미사용, Rich `escape()`+`soft_wrap`). 토큰은 어떤 명령도 출력하지 않는다.

### 6.1 조회 (Phase 1, 읽기)

| 명령 | 인자/플래그 | 동작 |
|------|-------------|------|
| `github account list` | `[--json] [--probe]` | 계정 인벤토리 + 로그인 + (—/`--probe` 만료) + 라우팅(owners/✓cwd) |
| `github account show <account>` | `[--json] [--probe]` | 단일 계정 상세 — host·config_dir·로그인·만료·이 계정으로 라우팅되는 owners·cwd 여부 |

`list --json` 예:
```json
{"accounts": [
  {"account": "16bitdo", "host": "github.com", "config_dir": "~/.config/gh-16bitdo",
   "logged_in": true, "expiry_status": "valid", "expires_at": "2026-09-01T00:00:00Z",
   "routed_owners": ["16bitdo"], "cwd_routed": true},
  {"account": "heisgone", "host": "github.com", "config_dir": "~/.config/gh-heisgone",
   "logged_in": true, "expiry_status": "unknown", "expires_at": null,
   "routed_owners": ["whatap"], "cwd_routed": false}
]}
```
`--probe` 미지정 시 `expiry_status="unknown"`, `expires_at=null`(네트워크 미수행).

### 6.2 라우팅 (Phase 2, 쓰기)

| 명령 | 인자/플래그 | 동작 |
|------|-------------|------|
| `github route list` | `[--json]` | `doctor.gh_owner_accounts` 매핑 + 각 account 로그인/존재 여부 |
| `github route set <owner> <account>` | `[--dry-run] [--yes]` | `anvyc.yaml doctor.gh_owner_accounts[owner]=account` 추가/치환 |
| `github route rm <owner>` | `[--dry-run] [--yes]` | 매핑에서 owner 제거 |
| `github use [<account>]` | `[--no-allow] [--dry-run]` | cwd `.envrc` 의 `GH_CONFIG_DIR`→`gh-<account>` 작성. account 생략 시 `resolve_routing_account(cwd, 매핑)` 도출 |

**공통 안전 절차**(route set/rm): 변경 전/후 `anvyc.yaml` unified diff 미리보기 → `--dry-run` 이면 출력 후 exit 0 → 확인 프롬프트(`--yes` 생략) → `.bak` → atomic 쓰기 → YAML 재파싱+스키마 검증 → 실패 시 `.bak` 복구. (`core/project_roots_edit.py`/`yaml_io.py` 동형.)

**시크릿 가드**: 어떤 인자도 토큰/비밀을 받지 않는다(owner·account 식별자만). `use` 는 `.envrc` 에 `GH_CONFIG_DIR`(경로)만 쓴다 — 토큰 미관여.

## 7. 핵심 의미론

- **계정 발견**: `discover_gh_accounts(home)` = `~/.config/gh*` 디렉터리들의 `hosts.yml` walk(`utils/gh_hosts.py:111`). 한 user 가 복수 dir 에 있으면 `select_config_dir_for_user` 의 선호(`~/.config/gh-<user>` 우선) 적용.
- **토큰 미독**: `parse_hosts_yml`(`gh_hosts.py:38`)은 `host:`/`users:`/`<user>:` 라인만 정규식 추출 — `oauth_token` 라인은 건드리지 않는다. 로그인 판정은 `gh_account_logged_in`(`project_init.py:83`) = `hosts.yml` **존재 stat**(내용 미독).
- **만료**: `detect_github(home, probe_expiry=…)`(`creds.py:375`) 재사용. 기본 `probe_expiry=False`(오프라인 unknown), `--probe` 시 True → `gh api` 만료 헤더. gh 가 토큰을 사용하고 anvyc 는 헤더만 수신.
- **owner→account 역인덱스**: `gh_owner_accounts`(`config.py:117`, anvyc.yaml `doctor.gh_owner_accounts`)를 `{account: [owners]}` 로 뒤집어 각 계정의 `routed_owners` 산출.
- **cwd 라우팅**: `resolve_account(cwd)`(`gh_route.py:21`, origin ssh alias) == account 인지로 `cwd_routed` 판정. `aws profile` 의 `current_project_aws_profiles` 와 대칭.
- **매핑 surgical 쓰기**(Phase 2): `anvyc.yaml` 의 `doctor.gh_owner_accounts` 키만 갱신, 나머지 키·주석·서식 보존(전체 재직렬화 회피 — `project_roots_edit` 와 동일 원칙).
- **`use` 의 `.envrc` 쓰기**: `write_envrc_gh_routing(envrc, account)`(`project_init.py:18`) 재사용 — idempotent(created/added/replaced/unchanged), `.gitignore` `.envrc` 보장은 `project init` 에 위임(중복 회피).

## 8. 엣지 / 에러 처리

- `~/.config/gh*` 부재: `account list` → 빈 인벤토리 안내("`gh auth login` 으로 계정 추가").
- 매핑(`gh_owner_accounts`)은 있으나 해당 account 미로그인: `⚠ 매핑된 account 'X' 미로그인` (WARNING 급 표시, 차단 안 함).
- `--probe` 인데 `gh` 미설치/네트워크 불가: 만료 `unknown` 로 graceful, "probe 불가 — gh CLI 필요" 안내(오프라인 정보는 그대로).
- `github use` 인데 account 도출 불가(매핑 없음 + origin alias 없음): 명확 에러 + 비0 exit, **silent fallback 금지**(`anvyc gh` 원칙 승계).
- `route set` 의 account 가 미로그인: 경고하되 매핑은 작성(미래 로그인 대비) — 단 1줄 안내.
- `anvyc.yaml` 부재(Phase 2): `route set` → 최소 스캐폴딩 생성(`config roots add` 첫 추가 패턴과 동일).
- cwd 가 프로젝트 밖(home 등): `cwd_routed=false` 일관, 에러 아님.

## 9. 단계 계획

**Phase 1 — 통합 뷰(읽기, `--probe` 포함)**
- 산출물: `core/gh_account_view.py`(`GhAccountView`·`collect_accounts`), `cli.py` `github_app`/`github_account_app` + `account list`/`show`(`--probe`·`--json`), 문서.
- 신규 코어는 기존 secret-safe 프리미티브(`discover_gh_accounts`·`detect_github`·`resolve_account`·`gh_owner_accounts`)의 **조립**뿐 — blast radius 작음. 사용자 핵심(통합 뷰) 즉시 충족.

**Phase 2 — 라우팅 CRUD(쓰기) + `use`**
- 산출물: `core/gh_routes_edit.py`(`set_route`/`remove_route` + 안전가드), `cli.py` `github route list/set/rm` + `github use`, 문서.
- `anvyc.yaml` 안전쓰기(diff·`.bak`·재검증) + `.envrc` 작성(`write_envrc_gh_routing` 재사용).

스펙은 하나(통합), 구현 계획에서 두 Phase 로 시퀀싱(각 별도 PR). 향후(별도) 후보: `github account`↔`creds` 의 GitHub 만료 dedupe, `aws profile use` 대칭화, org-level billing 계정(`cost.github.accounts`)과의 뷰 통합.

## 10. 테스트 전략 (TDD)

- **단위 `core/gh_account_view`**: tmp `~/.config/gh*/hosts.yml`(단일/다중 dir·다중 user) + 주입 `owner_accounts`·`now` → `collect_accounts` 의 logged_in/routed_owners/cwd_routed 정확성, `--probe` off 시 `expiry_status=unknown` 및 **네트워크 호출 0**, 토큰 라인 미독 단언.
- **단위 `utils/gh_hosts`**(기존 보강): `discover_gh_accounts`·`select_config_dir_for_user` 회귀(이미 일부 존재 시 확장).
- **단위 `core/gh_routes_edit`**(Phase 2): `set_route` 추가/치환, `remove_route`, 주석/타 키 보존, `.bak` 생성, 재파싱 실패→롤백, owner/account 식별자 외 입력 없음 단언.
- **CLI(`CliRunner`)**: `account list`/`show`(`--json`·`--probe` mock), `route set`/`rm`(`--dry-run` 무변경·`--yes`·확인 중단), `use`(`.envrc` 작성·account 도출 실패 시 비0 exit). tmp HOME monkeypatch, **토큰 미출력** 단언.
- **회귀**: `anvyc gh <args>` passthrough 불변(신규 `github` 그룹과 무충돌), `creds status` GitHub 만료 불변, `project doctor` `gh_account_routing` 불변.

## 11. 문서 갱신

- `README.md` §11(다수 계정 관리): GitHub 행을 "라우팅+관측 only" → `anvyc github account/route/use` 로 확장. AWS profile 과의 대칭/차이(인증 위임) 명기.
- `docs/multi-account.md`: GitHub 계정 통합 뷰 + 라우팅 CRUD + 인증 위임 경계.
- `docs/design-axes/cp-05-creds.md`: `creds` 의 GitHub 만료 ↔ `github account` 표시의 역할 분리 1줄.
- `DESIGN.md`: 신규 `github` 명령군, secret 경계(토큰 불가침) 명문화.
- `CONTEXT.md` / `RELEASE_NOTES.md`: 진행/릴리스 반영.

## 12. 미해결 질문

1. **명령 그룹 네이밍** — `anvyc github`(관리) vs `anvyc gh`(exec) 이원화가 충분히 명확한가, 아니면 `anvyc ghacct`/`gh-account` 등 더 분명한 이름이 나은가? (`gh` passthrough 와의 시각적 인접성 우려.)
2. **라우팅 매핑 위치** — `github route`(그룹 응집) vs `config gh-routes`(`config roots`/`config projects` 와 도메인 대칭). 둘 다 정당 — 발견성 vs 설정-CRUD 일관성 trade-off.
3. **`github use` 포함 여부** — Phase 2 에 넣을지, `aws profile use` 와 함께 별건으로 뺄지(대칭 유지 차원).

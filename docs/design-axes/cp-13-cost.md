# CP-13 — Cost observability 설계

> CP-13 (Cost observability / costwatch) 의 구조 SoT. 결정 SoT 는
> [`role-based-ruleset/docs/adr/v6-cp13-cost-observability.md`](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/adr/v6-cp13-cost-observability.md)
> (Accepted v1.1, 2026-05-27 rbr#90 cut-over). 본 문서는 DESIGN §38 의
> 본문 분리본.
>
> audit ([CP-1](https://github.com/16bitdo/role-based-ruleset/blob/main/ROADMAP.md)) /
> scheduler (CP-3) / creds ([CP-5](./cp-05-creds.md)) / sync ([CP-6](./cp-06-sync.md))
> 위에서 AI agent 의 실행 비용 (Anthropic + AWS + GitHub) 을 동일
> `schema_version: 1` 로 통합.

## 1. 설계 원칙

1. **결정 SoT vs 구조 SoT 분리** — 8축 결정 (배치 / 소스 / 구현 순서 / 알림 /
   통화 / dep / account / PR 분리) 은 ADR §2 가 본문, schema · adapter
   contract · cache 정책은 본 문서가 본문. ADR 변경 시 본 문서의 schema 본문
   동기 갱신.
2. **schema_version 합의** — `CostReport` 는 CP-3 health / CP-4 snapshot /
   CP-5 creds / CP-6 sync 와 동일 `schema_version: 1` 단일 키. 추가 차원은
   확장-호환 만 (기존 키 변경 금지, 필드 추가만 허용).
3. **measurement-cost 자기 관찰 (ADR R1)** — Cost Explorer 호출 자체 비용
   등 측정 비용을 `meta.measurement_cost_usd` 에 동봉. 자기 잠식 방지.
4. **원통화 USD 저장 / 표시 시 KRW 변환** — store 는 항상 USD, display 는
   `fx_rate_basis` (출처 + 날짜) 캡처 후 KRW 변환. 회계 재현성.
5. **profile 명 = account 1차 키 (ADR R13)** — Claude 3 프로필 (`.claude` /
   `.claude-edward` / `.claude-jklee`) 의 분리 합산. organization_id 는
   `meta.org_id` 부속.
6. **optional dep 격리 (ADR R11)** — `cost-aws` / `cost-anthropic` /
   `cost-github` 그룹. anvyc core dep (`typer / rich / pathspec / pyyaml`)
   보존.
7. **observability only** — cost 는 PostToolUse hook 으로 차단 부적합. CP-2
   risk-gate 와 채널 분리. 알림은 statusline + CP-3 macOS notification 만.

## 2. CostReport schema v1

```yaml
schema_version: 1
source: anthropic | aws | github
account: <profile_name>             # Anthropic: profile 명 (edward / jklee / default)
                                    # AWS:      aws_profile 명
                                    # GitHub:   gh login 명 (16bitdo / heisgone)
period:
  start: 2026-05-01T00:00:00Z       # 항상 UTC store
  end:   2026-06-01T00:00:00Z       # exclusive
currency: USD                       # 항상 USD store
amount: 123.45                      # period 총합
breakdown:                          # 차원별 분해 (optional)
  - dim: model                      # open string. 권장 enum:
                                    #   model / service / repo / workflow / tag / sku / cache_tier
    key: claude-sonnet-4-6
    amount: 67.89
collected_at: 2026-05-27T..Z
fx_rate_basis: ecb:2026-05-27       # display 시 사용, TTL=1d / stale 7d WARNING
meta:
  measurement_cost_usd: 0.01        # R1 자기 관찰
  pricing_version: 1                # R9 mitigation (가격표 SoT 버전)
  org_id: <opt>                     # R13 부속 (Anthropic organization_id 등)
```

### 2.1 확장 호환 규칙

- 기존 키 의미 변경 금지. 새 차원은 `breakdown[].dim` 의 open string 으로 추가.
- `meta` 는 source 별 자유. 단 `measurement_cost_usd` / `pricing_version` /
  `org_id` 3 키는 공통 reserved.

## 3. Adapter Protocol + 어댑터 lifecycle

### 3.1 CostAdapter Protocol

```python
class CostAdapter(Protocol):
    name: str                                       # "anthropic" / "aws" / "github"
    optional_dep_group: str | None                  # e.g. "cost-aws"

    def discover_accounts(self) -> Iterator[Account]: ...
    def fetch_period(
        self, account: Account, period: Period
    ) -> CostReport: ...
    def supports_realtime(self) -> bool: ...        # invoice 채널이 (i) 실시간인지
```

`Account` = `(source, key)` 튜플. 어댑터별 의미:

| source | key | discover 채널 |
|---|---|---|
| anthropic | profile 명 | `~/.claude*/projects/` glob |
| aws | aws_profile 명 | `~/.aws/config` + `project_list` 의 `aws_profile` 보강 |
| github | gh login 명 | `gh auth status --hostname github.com-<alias>` |

### 3.2 어댑터 채널

| source | (i) 실시간 | (ii) 청구 진실 |
|---|---|---|
| anthropic | session jsonl 의 token 합산 × `pricing/anthropic.yaml` (PR-13A0/A) | **v0.2 deferred** — Anthropic 측 admin API 공식 endpoint 미공개 (rbr ADR v1.2 §2.3 / §4.2.3 / §5, 2026-05-27 WebFetch 실측) |
| aws | `ce:GetCostAndUsage` (PR-13C) | 동일 API + 월말 잠금 |
| github | `/orgs/{org}/settings/billing/*` (PR-13D) | 동일 API |

(i) 가 MTD 실시간, (ii) 가 월말 진실 — diff > 5% 시 doctor WARNING (§6).

### 3.3 어댑터 graceful skip

optional dep 부재 시 `CostAdapterDepMissing(source=...)` raise → 상위 호출자가
catch + doctor `cost-<src>-dep-missing` WARNING + 설치 안내 (`pip install
'anvyc[cost-aws]'`).

## 4. 명령 contract (CP-13 시리즈)

| 명령 | 시점 | 동작 |
|---|---|---|
| `anvyc cost collect [--source <s>] [--period <p>]` | scheduler 일1회 + 수동 | 어댑터 호출 → 캐시 저장 → CostReport JSON stdout |
| `anvyc cost summary [--group-by <dim>] [--period mtd\|eom\|<period>]` | 사용자 ad-hoc / MCP | 캐시 집계 + KRW 표시 + EOM forecast |
| `anvyc cost ledger [--source <s>] [--meta]` | 회계 검증 | period 별 row table, `--meta` 시 measurement_cost / pricing_version 노출 |
| `anvyc cost reconcile [--source anthropic]` | 월말 + scheduler | **v0.2 deferred** — (ii) admin API channel 정착 후 (rbr ADR v1.2 §2.3 / §4.2.3 / §5) |
| `anvyc cost gc [--keep-days N] [--apply]` | retention 정리 | raw 90d 외 cache 파일 삭제. **기본 dry-run** + `--apply` 로 실 삭제 (PR-13B2). aggregate 24m 은 PR-13C/D 의 aggregate 도입 후. |

MCP tool (`anvyc/mcp/server.py`):

| MCP tool | 응답 |
|---|---|
| `cost_summary` | `{ source, account, period, total_usd, total_krw, breakdown[], forecast_eom_usd, fx_rate_basis }` |
| `cost_reconciliation` | `{ source, account, period, (i)_usd, (ii)_usd, gap_pct, status }` |

`activity_summary` (기존, PR-13A 확장): `total_cost_usd` / `cost_by_model` /
`pricing_version` 키 추가 (확장 호환).

## 5. 캐시 / Retention 정책

### 5.1 캐시 layout

```
~/.config/anvyc/cost/
├── cache/
│   ├── anthropic/<profile_name>/<YYYY-MM-DD>.json     # raw daily
│   ├── aws/<aws_profile>/<YYYY-MM-DD>.json
│   ├── github/<gh_login>/<YYYY-MM-DD>.json
│   └── fx/<YYYY-MM-DD>.json                            # FX rate (TTL=1d)
├── aggregate/
│   └── <source>/<account>/<YYYY-MM>.json               # monthly aggregate
├── budgets.yml                                         # 사용자 예산 정책
└── pricing/                                            # PR-13A0 가격표 SoT 사본
    └── anthropic.yaml
```

> **v7 정정 (PR-13F)**: 6h rolling window state 의 권위 위치는
> `~/.config/cc-inspect/cost-window.json` 입니다 (ADR §4.5 정합). ccinspector
> 의 `modules/scheduler/cost-window.py` 가 owner 이며, `cost.sh` task 가 매
> tick update, `health-status.py` 의 `cost_severity` 가 read. anvyc namespace
> 의 `cost/state/` 디렉터리는 v0.2 별도 ADR 까지 사용 안 함 (cross-machine
> sync ([CP-6](./cp-06-sync.md)) 통합 후 anvyc 측 mirror 검토).

### 5.2 Retention

| 영역 | 기본 | 만료 / 알림 |
|---|---|---|
| `cache/<src>/<acct>/*.json` (raw daily) | 90d | 자동 삭제 (`anvyc cost gc`) |
| `aggregate/<src>/<acct>/*.json` (monthly) | 24m | 자동 삭제 |
| `~/.config/cc-inspect/cost-window.json` (ccinspector owner, PR-13F) | rolling 6 tick | overwrite (cost.sh task 가 매 tick update) |
| `cache/fx/*.json` | TTL=1d | stale 7d 시 WARNING, 14d 시 statusline `~` prefix |
| `pricing/anthropic.yaml` | 90d 갱신 | `effective_date` 90d 초과 시 WARNING (R9) |

### 5.3 Atomic write

`tempfile.mkstemp(dir=parent)` + chunked write + `os.replace`. CP-4 snapshot ·
CP-6 sync 의 atomic write 패턴 미러.

## 6. doctor check 등록

`anvyc/checks/_REGISTRY` 에 5종 추가 (CP-3 scheduler 가 자동 호출):

| check id | 동작 | severity |
|---|---|---|
| `cost-anthropic-reconciliation` | (i) session sum vs (ii) invoice gap > 5% | WARNING |
| `cost-<src>-dep-missing` | optional dep import fail | WARNING (graceful skip) |
| `cost-aws-explorer-iam` | `ce:GetCostAndUsage` 권한 부재 | WARNING + 정책 JSON 출력 |
| `cost-fx-stale` | FX cache 7d 초과 stale | WARNING |
| `cost-pricing-stale` | `pricing/anthropic.yaml` 의 `effective_date` 90d 초과 | WARNING |

CP-5 의 `creds-expiry` 패턴 미러 — CP-3 scheduler 의 `doctor --strict
--json` 호출 시 health JSON payload 에 자동 합류 (별도 wire 불요).

## 7. Cross-axis 시너지

| Axis | 통합 채널 |
|---|---|
| **CP-1** audit | session jsonl 이 Anthropic source 채널 (i). `activity_summary` 응답이 PR-13A 로 `total_cost_usd` 차원 확장 |
| **CP-3** scheduler | `cost` task (interval=86400s) + `cost-budget-exceeded` predicate (health-status.py) + 6h rolling window state |
| **CP-4** snapshot | snapshot meta 에 `cost_summary` 포함 검토 (v0.2) |
| **CP-5** creds | Anthropic admin API key / AWS Cost Explorer 권한 / GitHub PAT 의 1Password ref 등록 채널 재사용 |
| **CP-6** sync | `cache/aggregate/<src>/<acct>/*.json` 가 cross-machine sync 대상. 단 source 별 dedup 필요 (account 단위 합산이 자연) |
| **CP-12** work-cwd | repo breakdown (`dim: repo`) 의 cwd 매핑에 활용 |

## 8. 보안 경계

- **token / API key 본문 sync 영구 금지** — CP-6 의 정책 (rule 26·27) 동일 적용.
  costwatch 는 *결과 caching* 만, secret 본문은 1Password ref 만.
- **breakdown 의 PII redact** — `dim: repo` 의 key 가 repo 절대 경로 / branch
  명 / commit msg 일 가능성 → anvyc redact 함수 재사용. 출구별 정책:

  | 출구 | redact 강도 |
  |---|---|
  | stdout (`anvyc cost summary`) | full (user 본인) |
  | cache jsonl | redacted (commit msg / branch 명 마스킹) |
  | macOS notification | aggregate only (no breakdown) |
  | statusline 세그먼트 | total + forecast 만 |

- **org_id 의 명시적 opt-in** — `meta.org_id` 노출은 `anvyc cost summary
  --include-org-id` 명시 시에만. 기본 미노출.

## 9. Out of scope (CP-13 axis 완결 기준)

본 axis 의 v6 범위 외:

- **Pulumi preview cost diff** — AWS Pricing API 매핑 어댑터. CP-14 후보.
- **Cloudflare / Vercel / Notion 등 추가 SaaS adapter** — `CostAdapter`
  Protocol 만 v6 에서 동결, 어댑터는 v7 별도 ADR.
- **Cursor billing 차원** — Cursor 가 official billing API 미공개. v7+.
- **`finops-engineer` role 신설** — v6 는 devops-engineer 흡수. ADR §5 의
  분리 trigger 충족 시 v0.2 별도.
- **Slack 출구** — redaction policy 분리 필요. v0.2 ADR 별도.
- **다머신 합산 dedup rule** — CP-6 sync 위에서 account 단위 dedup. v0.2.
- **GitHub Copilot billing** — admin 권한 요구. v7 별도.
- **Anthropic batch tier 할인 처리** — invoice (ii) 채널 정착 후 검토.

## 10. 변경 이력

| 일자 | version | 변경 |
|---|---|---|
| 2026-05-27 | 1 | 초안 — ADR v1.1 (Accepted 2026-05-27 rbr#90) 의 구조 SoT 본문 1차 작성. PR-13Z-anvyc 로 합류. schema v1 동결 + adapter Protocol + cache layout + doctor 5종 + cross-axis 매핑 + 보안 경계. |
| 2026-05-27 | 2 | PR-13B1 진입 시 (ii) channel defer 반영 (ADR v1.2 / rbr#91). §3.2 의 어댑터 채널 표에서 anthropic (ii) admin API monthly invoice → **v0.2 deferred** 로 정정. 본문 구조 / schema / doctor / cross-axis / 보안 경계 부분은 동결 (확장-호환). |
| 2026-05-27 | 3 | PR-13B2 진입. §4 의 `anvyc cost reconcile` 행을 **v0.2 deferred** 로 정정 ((ii) channel 의존). `anvyc cost gc` 행을 **기본 dry-run / `--apply` 시 실 삭제** 로 정정 (CP-4 snapshot 패턴 미러 — destructive 작업 안전 기본값). retention 의 aggregate 24m 부분은 aggregate cache 도입 (PR-13C/D 이후) 후 활성. KRW display 의 fx 출처 = `open.er-api.com` (ADR v1.2 §2.1 / §7 확정, stdlib urllib 만 사용). |
| 2026-05-27 | 4 | PR-13C 진입. AWS Cost Explorer adapter 도입 (`core/cost/adapters/aws.py`, optional dep `cost-aws = ["boto3>=1.34"]`). discover_accounts 정책 = **auto-ALL** (`~/.aws/config` 의 모든 profile, sts 호출 없는 정적 read — 비용 0). fetch_period 의 graceful skip 4 분류: `sso_expired` / `access_denied` / `api_error` / dep missing (`meta.extra.error`). doctor `cost-aws-explorer-iam` check 도입 (`SimulatePrincipalPolicy` — 호출 비용 0). IAM policy 템플릿 `templates/aws-cost-readonly.json` (`ce:GetCostAndUsage` + `ce:GetDimensionValues` + `ce:GetTags`). `ADAPTER_REGISTRY` 가 `importlib.util.find_spec("boto3")` 로 lazy 등록 — startup 비용 0, boto3 부재 시 'aws' 키 미등록 (graceful skip). |
| 2026-05-27 | 5 | PR-13D 진입. GitHub Billing adapter 도입 (`core/cost/adapters/github.py`, optional dep `cost-github = ["httpx>=0.27"]`). endpoint = **Enhanced Billing Platform** (`GET /organizations/{org}/settings/billing/usage` 와 `/users/{user}/settings/billing/usage`) — ADR §1.3/§4.4 의 legacy `/orgs/{org}/settings/billing/{actions,packages,shared-storage}` 는 docs index 비노출 (WebFetch 실측 2026-05-27). discover_accounts = **auto-ALL** (`~/.config/gh*` glob walk + hosts.yml 의 user, indent-flexible parser). account.key 인코딩 = `"<user>"` (user-level) 또는 `"<user>@<org>"` (org-level). graceful skip 4 분류: `unauthorized` / `forbidden` / `enhanced_billing_disabled` / `api_error` (+ `no_token`/`no_config_dir`). 인증 = **fine-grained PAT** — user-level 은 Account `Plan: Read`, org-level 은 Organization `Administration: Read`. 측정 차원 = breakdown dim=`product` (Enhanced billing 의 `usageItems[].product` 자연 매핑, Actions/Packages/Storage/Copilot 통합). doctor `cost-github-pat-scope` check 도입 — user-level billing endpoint smoke 호출로 PAT 권한 검증. `utils/gh_hosts.py` 신규 — `~/.config/gh*` walk + minimal YAML parser (PyYAML 미의존, gh 1.x 2-space 와 신버전 4-space indent 모두 인식). |
| 2026-05-27 | 6 | polish-anvyc (CP-13 polish 묶음 #3). `summarize_reports` 반환 dict 에 `collected_at_latest` (ISO 8601) 추가 — reports 중 가장 최근 `CostReport.collected_at` 노출. `summary_payload` 가 본 키를 자동 전파 (MCP `cost_summary` / CLI `cost summary` 응답에 노출). 호출자 (ccinspector statusline cost reader, 향후 6h rolling window state, staleness 표시) 가 단일 진입점으로 활용. 확장-호환 (기존 키 변경 0, 추가만). cache.py / ledger.py 의 collected_at 직렬화/역변환은 정상 — 본 polish 는 합산-레벨 노출만 추가. |
| 2026-05-27 | 7 | PR-13F chore (§5.1 정정). 6h rolling window state 의 권위 위치를 `~/.config/cc-inspect/cost-window.json` (ccinspector namespace, ADR §4.5 정합) 으로 정정. 기존 cache layout 의 `state/cost-window.json` (anvyc namespace) 라인 제거. ccinspector 의 `modules/scheduler/cost-window.py` 가 owner — `cost.sh` task 가 매 tick update (per-source totals dict), `health-status.py` 의 `cost_severity` 가 read (어느 source 라도 6h 증가율 ≥ 20% 시 severity 한 단계 상향, cap FAIL). anvyc 측 코드 변경 0 — polish #3 의 `summarize_reports.collected_at_latest` + 기존 `by_source` 가 단일 입력 제공. v0.2 별도 ADR 에서 cross-machine sync (CP-6) 통합 시 anvyc namespace mirror 검토. |
| 2026-05-27 | 8 | polish-anvyc CP-13H (whatap org-level fix). `anvyc.yaml` 의 top-level `cost.github.accounts` config 옵션 도입 — list of `"<user>"` (user-level) 또는 `"<user>@<org>"` (org-level). `core/config.py` 에 `CostConfig` + `CostGithubConfig` dataclass 추가. `ADAPTER_REGISTRY._build_registry()` 가 `load_anvyc_config()` 호출 → `GitHubBillingAdapter(accounts_override=cfg.cost.github.accounts)` 전달 (빈 list → adapter 자동 discover 유지). 동기 = PR-13D 의 fine-grained PAT (Resource owner=whatap, Org `Administration: Read`) token 은 org-level endpoint 만 호출 가능, adapter 가 default 로 user-level (`/users/heisgone/...`) 호출 → 403 forbidden. 본 config 옵션으로 `heisgone@whatap` 명시 시 org-level (`/organizations/whatap/...`) 호출 → 정상. ADR §4.4 의 account.key 인코딩 자연 확장 (변경 0). config 부재 / 빈 cost section → 기존 동작 보존. |

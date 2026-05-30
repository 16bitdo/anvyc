# AI agent control-plane axes

> anvyc 는 `role-based-ruleset` × `ccinspector` 와 함께 **AI agent autopilot 의
> L2 Environment layer** 책임을 맡는다. 각 axis 는 `schema_version: 1` 단일
> 키로 통합되며 CP-3 scheduler 의 `anvyc doctor --strict --json` 호출에
> 자동 합류한다.

## 1. axis 요약 (v0.14.0+)

| Axis | 명령 | 의도 | 본문 |
|---|---|---|---|
| **CP-1** audit | `anvyc activity` + MCP `activity_summary` / `tool_call_stats` | session jsonl 의 read-only 집계 — autopilot 사후 추적 | DESIGN §34 |
| **CP-4** snapshot | `anvyc snapshot {create\|list\|diff\|restore}` | autopilot 실수 회복. git stash + meta schema v1. 4-layer safety | [design-axes/cp-04-snapshot.md](./design-axes/cp-04-snapshot.md) |
| **CP-5** creds | `anvyc creds {status\|rotate}` + `creds-expiry` check | AWS SSO / GitHub PAT / Claude OAuth 만료 사전 감지 (per-kind 임계: aws_sso 1h / 그 외 7d) + native re-auth 위임 | [design-axes/cp-05-creds.md](./design-axes/cp-05-creds.md) |
| **CP-6** sync | `anvyc sync {status\|push\|pull}` + `conflict {list\|resolve}` | control-plane 자산 (snapshot meta / activity / creds) 머신 간 동기화 | [design-axes/cp-06-sync.md](./design-axes/cp-06-sync.md) |
| **CP-12** work-cwd | `anvyc workctx {switch\|clear\|show}` + `work-cwd-track-wired` check | launch dir 에 고정된 statusline 의 한계 해소 — agent 의 실 작업 cwd 를 cache schema v1 로 누적 | DESIGN §27 |
| **CP-13** cost | `anvyc cost {collect\|summary\|ledger\|gc}` + MCP `cost_summary` + 2 doctor check | Anthropic (i) / AWS Cost Explorer / GitHub Billing 통합 | [design-axes/cp-13-cost.md](./design-axes/cp-13-cost.md) |

### Control plane SoT 위치 (외부)

- [role-based-ruleset/ROADMAP.md §4](https://github.com/16bitdo/role-based-ruleset/blob/main/ROADMAP.md) (사람 가독)
- [metadata/control-plane-roadmap.yaml](https://github.com/16bitdo/role-based-ruleset/blob/main/metadata/control-plane-roadmap.yaml) (기계 가독)
- [docs/control-plane-v1-recap.md](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/control-plane-v1-recap.md) (회고)

---

## 2. Cost observability (CP-13, in-flight)

AI agent 의 실행 비용 — Anthropic (Claude session token) / AWS (Cost Explorer)
/ GitHub (Enhanced Billing Platform) — 을 동일 `CostReport schema v1` 로 통합.
저장은 항상 USD, 표시 시 `fx_rate_basis` (출처+날짜) 캡처 후 KRW 변환 — 회계
재현성 보장.

### 2.1 빠른 사용

```bash
# 1) 어댑터 직접 호출 + 캐시 저장 (refresh)
anvyc cost collect --source anthropic --period mtd

# 2) 캐시 read + 합산 (캐시 비어있으면 즉시 collect)
anvyc cost summary --period mtd
anvyc cost summary --period 2026-05 --json

# 3) period 의 cache rows 표
anvyc cost ledger --source anthropic --meta

# 4) raw daily cache retention 정리 (기본 dry-run, --apply 시 실 삭제)
anvyc cost gc --keep-days 90
anvyc cost gc --apply
```

### 2.2 어댑터 채널

| source | (i) 실시간 | (ii) 청구 진실 |
|---|---|---|
| anthropic | session jsonl 의 token 합산 × `pricing/anthropic.yaml` | **v0.2 deferred** — admin API 공식 endpoint 미공개 |
| aws | `ce:GetCostAndUsage` (`[cost-aws]` extra) | 동일 API + 월말 잠금 |
| github | `/organizations/{org}/settings/billing/usage` 또는 `/users/{user}/settings/billing/usage` (`[cost-github]` extra) | 동일 API |

(i) 가 MTD 실시간, (ii) 가 월말 진실 — diff > 5% 시 doctor WARNING.

### 2.3 doctor check (CP-13)

| check id | 동작 | severity |
|---|---|---|
| `cost-anthropic-reconciliation` | (i) session sum vs (ii) invoice gap > 5% | WARNING |
| `cost-<src>-dep-missing` | optional dep import fail | WARNING (graceful skip) |
| `cost-aws-explorer-iam` | `SimulatePrincipalPolicy` 로 `ce:GetCostAndUsage` 권한 부재 감지 | WARNING + 정책 JSON 안내 |
| `cost-fx-stale` | FX cache 7d 초과 stale | WARNING |
| `cost-pricing-stale` | `pricing/anthropic.yaml` 의 `effective_date` 90d 초과 | WARNING |
| `cost-github-pat-scope` | user-level billing endpoint smoke 호출로 fine-grained PAT 권한 검증 | WARNING |

### 2.4 설치 (optional dep)

```bash
# AWS Cost Explorer
uv tool install --upgrade 'anvyc[cost-aws]'    # boto3 자동 포함

# GitHub Enhanced Billing
uv tool install --upgrade 'anvyc[cost-github]' # httpx 자동 포함

# 둘 다 + MCP
uv tool install --upgrade 'anvyc[cost-aws,cost-github,mcp]'
```

extra 미설치 시 어댑터는 silent skip — anvyc core 동작에는 영향 없음
(graceful degradation).

### 2.5 anvyc.yaml `cost.github.accounts` override (PR-13H)

fine-grained PAT 의 Resource owner 가 org 인 경우, user-level endpoint 가
403 forbidden 으로 떨어지므로 명시 routing 이 필요하다.

```yaml
# anvyc.yaml
cost:
  github:
    accounts:
      - "16bitdo"          # user-level   → /users/16bitdo/.../billing/usage
      - "heisgone@whatap"  # org-level    → /organizations/whatap/.../billing/usage
```

빈 list / 미선언 시 GitHub adapter 가 `~/.config/gh*` glob walk 으로 자동
discover (user-level only). `examples/anvyc.yaml` 의 `cost.github.accounts`
예시 참고.

### 2.6 캐시 / Retention

```
~/.config/anvyc/cost/
├── cache/
│   ├── anthropic/<profile>/<YYYY-MM-DD>.json   # raw daily (90d retention)
│   ├── aws/<aws_profile>/<YYYY-MM-DD>.json
│   ├── github/<gh_login>/<YYYY-MM-DD>.json
│   └── fx/<YYYY-MM-DD>.json                     # FX rate (TTL=1d, stale 7d WARNING)
├── aggregate/<source>/<account>/<YYYY-MM>.json # monthly aggregate (24m)
├── budgets.yml
└── pricing/anthropic.yaml                       # PR-13A0 가격표 SoT 사본
```

6h rolling window state 의 권위 위치는
`~/.config/cc-inspect/cost-window.json` (ccinspector owner).

상세 schema / adapter Protocol / 보안 경계 / 변경 이력은
[design-axes/cp-13-cost.md](./design-axes/cp-13-cost.md) 참조.

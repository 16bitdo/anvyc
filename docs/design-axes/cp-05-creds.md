# CP-5 — Credentials Lifecycle 설계

> Control Plane v2 의 마지막 axis. GitHub PAT / AWS session / Claude OAuth
> 토큰 만료를 사전 감지 + 회전 절차를 native re-auth + 1Password CLI 로 연결.
> 본 문서는 DESIGN §36 의 본문 분리본.

## 1. 설계 원칙

- **Read-only first**: 1/3·2/3 는 모두 read-only (detection / status / doctor
  check). 3/3 의 rotate 만 write — destructive 절차는 snapshot/restore
  ([CP-4 §7](./cp-04-snapshot.md)) 같은 confirm + dry-run + auto pre-rotate
  backup 패턴 적용.
- **Source 다양성 수용**: 각 credential kind 의 만료 source 가 다름 — SSO
  는 파일, GitHub 은 HTTP header, Claude 는 keychain. detection 은 source
  별 helper 로 분리, 공통 `CredentialStatus` 로 합성.
- **Schema 우선 안정화** (v1 cut-over 학습 L7 적용): 1/3 머지 시점에
  `schema_version: 1` 확정 → 2/3 doctor check + 3/3 rotate 가 동일 schema
  를 입력 contract 로 가정. CP-3 health / CP-4 snapshot 과 같은 패턴.

## 2. CredentialStatus / CredentialsReport schema v1

```json
{
  "schema_version": 1,
  "generated_at": "2026-05-25T00:00:00Z",
  "warn_threshold_days": 7,
  "credentials": [
    {
      "kind": "aws_sso" | "github" | "claude_oauth",
      "identifier": "<profile/start_url/email>",
      "source": "<file path 또는 'gh CLI'>",
      "expires_at": "ISO8601 UTC | null",
      "expires_in_seconds": int | null,
      "status": "valid" | "expiring" | "expired" | "unknown"
    },
    ...
  ]
}
```

| key | 의미 |
|---|---|
| `kind` | credential 종류 (3 kind, 후속 확장 가능) |
| `identifier` | 사람 식별용 — SSO start_url / GitHub host/user / Claude email |
| `source` | 발견 위치 — `.aws/sso/cache/*.json` / `.config/gh/hosts.yml` / `.claude*.json` |
| `expires_at` | ISO8601 UTC. null = 만료 정보 없음 / 미지원 source. |
| `expires_in_seconds` | now 기준 잔여 초 (음수 = 만료 후 경과 초) |
| `status` | `valid` (잔여 ≥ threshold) / `expiring` (0 < 잔여 < threshold) / `expired` (잔여 ≤ 0) / `unknown` (`expires_at=null`, 단 detected 면 valid 로 재분류) |

## 3. 명령 contract (CP-5 시리즈)

| 명령 | PR | 안전 등급 | 책임 |
|---|---|---|---|
| `anvyc creds status [--warn-days N] [--no-probe] [--json] [--home <path>]` | 1/3 (#37, merged) | read-only | 3 kind detection + classification. `--no-probe` 로 gh CLI 호출 비활성 (CI / offline). `--home` 으로 검사 root override. |
| doctor `creds-expiry-within-7d` check | 2/3 (#38, merged) | read-only | `core/doctor.py` 의 `_REGISTRY` 에 등록 — `collect_credentials(probe_github_expiry=False)` 호출. expired→CRITICAL / expiring→WARNING / valid·unknown silent. CP-3 scheduler 가 doctor 호출 시 자동 포함. |
| `anvyc creds rotate <kind> [--force] [--yes] [--timeout N]` | 3/3 (#39, merged) | **destructive** | native re-auth 위임 (`aws sso login` / `gh auth refresh` / claude_oauth = 사용자 수동 안내). dry-run 기본 + `--force` + confirm prompt. token 본문 노출 회피 (stdout/stderr tail 2 KiB 만). `--from-op REF` (1Password 통합) 은 후속 polish. §8 참조. |

## 4. Source 별 detection 전략

| Kind | Source | Expiry 추출 | Status |
|---|---|---|---|
| `aws_sso` | `~/.aws/sso/cache/*.json` | `expiresAt` 필드 직접 read | full classification |
| `github` | `~/.config/gh/hosts.yml` (간이 YAML parser — PyYAML 미의존) | `gh api -i user --hostname <host>` 의 `X-GitHub-Token-Expiration` 헤더 (없으면 `valid` 로 처리 — classic OAuth 는 만료 없음) | detected → `valid` (probe 실패 시), header 있으면 full |
| `claude_oauth` | `~/.claude*.json` 의 `oauthAccount` 필드 | 직접 노출 안 됨 (실 token 은 keychain 등 별 location) | `valid` (detected) + `expires_at=null`. keychain 접근 보강은 후속 polish. |

## 5. CP-3 scheduler 자연 시너지

CP-3 scheduler 의 `run-scheduler.sh` 가 이미 `anvyc doctor --strict --json`
일1회 호출 중. **CP-5 2/3 머지 시점**에 `creds_expiry_within_7d` check 가
doctor 에 자동 합류 → scheduler 가 자동 호출 → CP-3 health JSON 의 doctor
payload 에 만료 정보 포함 → CP-3 statusline 인디케이터에 자동 노출
(severity 계산 규칙에 따라 expired→FAIL / expiring→WARN).

**별도 wire 작업 불요** — CP-3 axis 가 만든 일반화된 doctor JSON contract
의 cross-axis 재사용 가치 입증 (v1 cut-over 학습 L7 의 확장 효과).

## 6. Out of scope (CP-5 axis 완결 기준)

- Claude OAuth 의 실 expiry 추출 (keychain 접근) — polish
- GitHub PAT 의 fine-grained scope 검사 (현재는 만료만)
- credential 자동 회전 자동화 (CP-3 scheduler 가 자동 호출하는 형태) — polish
- `--from-op REF` (1Password 통합) — browser-based OAuth 가 다수 케이스에서
  더 안전. PAT-only 워크플로 사용자만 의미 — polish.
- `creds rotate` 의 auto pre-rotate backup — credential 자체 backup 은 보안
  위험이라 의도적 제외 (사용자가 `anvyc creds status` 로 이전 expires_at 만
  기록 보존하는 정도).

## 7. 보안 경계

- `creds status` 출력에 **token 본문 노출 금지** — identifier (email/profile
  이름) 만. expires_at 은 timestamp.
- `--json` 출력도 동일 — secret 본문 미포함.
- `rotate` 의 stdout/stderr 는 **tail 2 KiB 만 capture** — 외부 명령이
  실수로 token 본문을 print 해도 trail 만 보존. anvyc 자체는 token 을
  직접 핸들 안 함 — 외부 명령 (aws/gh) 에 위임 (rule 26-secrets-1password
  준수).

## 8. Rotate 안전 절차 ([CP-4 §7](./cp-04-snapshot.md) 패턴 미러)

rotate 는 destructive — snapshot/restore 의 4-layer 안전 패턴 미러.

1. **`plan_rotate(kind)`** — kind 검증 + 실행될 command + warnings 산출.
   CLI 가 `--force` 없으면 plan + warnings 만 출력 후 종료 (no-op = dry-run).
2. **`--force` 시** confirm prompt 1회 (`--yes` / `-y` 자동 수락).
3. **External command 위임** — 각 kind 별 native re-auth:

   | kind | command | 부수효과 |
   |---|---|---|
   | `aws_sso` | `aws sso login` | 브라우저 OAuth 흐름 → `~/.aws/sso/cache/*.json` 갱신 |
   | `github` | `gh auth refresh` | OAuth refresh → `~/.config/gh/hosts.yml` token 갱신 |
   | `claude_oauth` | (없음) | 사용자 수동 안내만 — Claude Code UI 에서 re-login |

4. **결과 capture**: `RotateResult` 에 `return_code` + `stdout_tail` /
   `stderr_tail` (각 2 KiB). 외부 명령 부재 → `RotateError("외부 명령 부재")`.
   timeout (기본 300s — browser 인증 사용자 대기 고려) 초과 →
   `RotateError("rotation timeout")`.

회복 채널:
- rotation 후 `anvyc creds status` 로 새 expires_at 확인.
- rotation 실패 (rc != 0) → CLI 가 exit code 그대로 전파; 사용자가 원인
  진단 (예: SSO 인증 cancel, gh login 만료된 base credential 등).

**1Password 통합 (`--from-op REF`)** 은 후속 polish — 사용자가 PAT 를
`op://...` 에 보관한 경우만 의미. AWS SSO + gh OAuth 같은 다수 케이스는
browser refresh 가 더 안전 (token 자체가 OS keychain / 표준 cache 에 저장).

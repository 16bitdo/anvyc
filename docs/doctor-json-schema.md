# `anvyc doctor --json` schema

> v0.5.3+ 안정 schema. CI / 다른 도구 통합용. 출력은 valid JSON 으로
> 안정적이며 회귀 테스트로 보장된다. 필드는 **추가만** 한다 — 기존 필드의 이름·타입은
> 바뀌지 않는다(v0.25.0 `extras_install` 추가, §5.2).

## 1. 호출 예시

```bash
anvyc doctor --json                          # 전체
anvyc doctor --only cross-user --json        # 특정 check 만
anvyc doctor --skip cursor-projects-suggest --json
```

## 2. Top-level

| 필드 | 타입 | 설명 |
|---|---|---|
| `results` | `list[Result]` | 발견된 모든 finding |
| `summary` | `dict[severity, int]` | 6 severity 각각의 카운트 (0 카운트도 포함) |
| `extras_install` | `{extras: list[str], command: str} \| null` | extras 설치 안내를 합친 명령 — §5.2 (v0.25.0+) |

## 3. Result 객체

| 필드 | 타입 | 비고 |
|---|---|---|
| `check_name` | `str` | 발행한 check (예: `cross-user`, `cursor-symlink-integrity`, `aws-account-status`) |
| `severity` | `str` | `info` / `info-aliased` / `warning` / `warning-foreign` / `warning-dangling` / `critical` |
| `message` | `str` | 사람-가독 요약 |
| `location` | `str \| null` | 절대 경로 또는 null |
| `line` | `int \| null` | 텍스트 매칭의 라인 번호 (해당 시) |
| `suggestion` | `str \| null` | 조치 권유 (해당 시) |

## 4. Summary 객체

```json
{
  "info": 11,
  "info-aliased": 0,
  "warning": 1,
  "warning-foreign": 21,
  "warning-dangling": 0,
  "critical": 0
}
```

## 5. Exit code

| 코드 | 의미 |
|---|---|
| `0` | clean 또는 blocking 없는 결과 (--strict 없을 때) |
| `1` | --strict 일 때 blocking severity (warning*/critical) 발견 |
| `2` | argparse 등 사용 오류 |

## 5.1 신규 check_name (v0.21.0+)

`aws-account-status` (전역 doctor) 및 `aws_account_status` (project doctor) 가 추가됐다.
JSON schema 자체는 변경 없음 — `check_name` 필드의 값이 늘어났을 뿐이며, 기존 CI 파이프라인은 수정 없이 그대로 동작한다.

## 5.2 `extras_install` (v0.25.0+)

blocking 결과 가운데 suggestion 이 **pip extras 설치 안내**인 것들을 명령 하나로 합친 것. 그런 결과가
없으면 `null`.

```json
"extras_install": {
  "extras": ["mcp", "cost-github"],
  "command": "ANVYC_VERSION=v0.25.0 ANVYC_EXTRAS=mcp,cost-github bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)"
}
```

- **check 별 extras suggestion 을 차례로 실행하지 말고 `command` 하나를 실행한다.** 각 suggestion 은
  표시 시점 상태로 따로 계산돼 서로를 모른다 — uv tool · pipx · install.sh 설치본은 재설치가 명령에
  없는 extras 를 지우므로, 차례로 실행하면 뒤의 것이 앞의 것을 지운다.
- `extras` 는 합친 suggestion 의 pip extra 키(레지스트리 순서). `command` 는 실행 중인 anvyc 의 설치
  방식에 맞춘 명령이고, 이미 설치된 extras 를 함께 적는다 — 개발 설치에서는 기본 extras(`dev,mcp,tui`)
  도 들어가므로 `extras` 와 명령의 목록이 다를 수 있다.
- extras 안내가 **1건이어도** 채운다(그때 `command` 는 그 suggestion 의 명령과 같다). 사람용 출력의
  합산 줄은 2건부터지만, 기계 소비자에게는 "`null` 이 아니면 `command` 를 실행" 한 규칙을 준다.
- blocking(warning* · critical)만 합친다. 선택 항목(info — 예: `tui-extra-importable`)은 `results` 에만 있다.
- MCP `doctor` tool 도 같은 필드를 돌려준다.

**호환** — 필드 추가다. 기존 필드는 그대로라 jq · 일반 파서는 수정이 필요 없다. 최상위 키 집합을
정확히 고정한 검증기만 `extras_install` 을 더해야 한다.

## 6. 활용 예 (jq)

```bash
# critical 만 추출
anvyc doctor --json | jq '.results[] | select(.severity == "critical")'

# 특정 location 의 finding 수
anvyc doctor --json | jq '[.results[] | select(.location | contains(".cursor"))] | length'

# CI 게이트: blocking 발견 시 exit 1
anvyc doctor --strict --json > /dev/null

# extras 설치 안내를 합친 명령 (없으면 빈 출력, v0.25.0+)
anvyc doctor --json | jq -r '.extras_install.command // empty'
```

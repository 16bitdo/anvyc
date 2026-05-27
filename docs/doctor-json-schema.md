# `anvyc doctor --json` schema

> v0.5.3+ 안정 schema. CI / 다른 도구 통합용. 출력은 valid JSON 으로
> 안정적이며 회귀 테스트로 보장된다.

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

## 3. Result 객체

| 필드 | 타입 | 비고 |
|---|---|---|
| `check_name` | `str` | 발행한 check (예: `cross-user`, `cursor-symlink-integrity`) |
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

## 6. 활용 예 (jq)

```bash
# critical 만 추출
anvyc doctor --json | jq '.results[] | select(.severity == "critical")'

# 특정 location 의 finding 수
anvyc doctor --json | jq '[.results[] | select(.location | contains(".cursor"))] | length'

# CI 게이트: blocking 발견 시 exit 1
anvyc doctor --strict --json > /dev/null
```

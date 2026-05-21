# anvyc 개선 계획 — 기본 스캔 루트 `~/Documents` → `~/dev` 이전

> 작성일: 2026-05-21
> 대상 버전: v0.11.0 기준
> 검토 범위: 사용자 프로젝트 루트(`~/Documents`)를 가정한 코드·테스트·문서 전반
> 배경: 사용자가 25개 프로젝트를 `~/Documents` → `~/dev` 로 이전. `dotfiles-claude` 는 이전 완료(2026-05-21, PR #10). anvyc 는 별도 PR 로 분리(`dotfiles-claude/docs/path-migration-report.md` P2-4 권고).
> 상태: **리뷰 완료 / 수정 미착수** — 본 문서를 인계 기준으로 후속 PR 진행.

---

## 0. TL;DR

anvyc 는 "사용자 프로젝트 루트"의 기본값으로 `~/Documents` 를 **6개 모듈에 하드코딩**하고 있다. 프로젝트가 `~/dev` 로 이전된 현재, anvyc 기본 실행은 **빈 결과 또는 stale 오탐**을 낸다.

- **근본 문제 2가지**: (1) `project-aws-profile-mapping`·`project-gh-account-mapping` 두 체크는 config override 경로가 아예 없음(하드코딩 상수 직접 사용). (2) 동일 개념("프로젝트 루트")이 4곳에 제각각 상수로 중복 — SoT 부재.
- **모범 선례**: `cursor_projects_suggest.py` 의 `DEFAULT_CANDIDATE_ROOTS` 는 이미 `~/dev` 포함 7-루트 리스트를 스캔 → 나머지 코드가 따라야 할 패턴.
- **권장**: 단순 `~/Documents`→`~/dev` 치환이 아니라 **루트 상수 SoT 단일화 + 체크 config-aware 전환**. 그래야 다음 이전 때 재발하지 않음.

---

## 1. 심각도별 인벤토리

조사 기준: `git grep -nI Documents` (v0.11.0, 2026-05-21).

### 🔴 Tier 1 — config override 불가 (실질 버그)

| 위치 | 내용 |
|---|---|
| `src/anvyc/checks/project_aws_profile.py:18` | `DEFAULT_PROJECT_ROOT = Path("~/Documents").expanduser()` |
| `src/anvyc/checks/project_gh_account.py:26` | `DEFAULT_PROJECT_ROOT = Path("~/Documents").expanduser()` |

- 두 체크의 `run(ctx)` 가 **`ctx` 를 무시**(`# noqa: ARG002`)하고 모듈 상수를 직접 사용 — `_iter_envrcs(DEFAULT_PROJECT_ROOT)` / `_iter_git_dirs(DEFAULT_PROJECT_ROOT)`. anvyc.yaml 이나 CLI 옵션으로 루트를 바꿀 경로가 **없다**.
- **영향**: `anvyc doctor` 실행 시 두 체크가 `~/Documents` 를 스캔. `~/Documents` 잔존 중이면 **구 `.envrc` 를 검사**(stale WARNING/INFO), 정리 후엔 silent 0건. `~/dev` 의 실제 프로젝트는 영영 검사되지 않음.
- `project-gh-account-mapping` 은 v0.11.0 신규 체크(커밋 `2a2a8e7`) — 도입 시점부터 경로가 어긋남.
- **부수 확인 필요**: `src/anvyc/checks/unused_aws_profiles.py` — docstring(L3)이 `~/Documents/**/.envrc` 를 언급. `project_aws_profile` 의 `_iter_envrcs` 를 재사용하는지, 자체 스캔하는지 확인 후 동일 조치.

부수 위치(같은 파일 docstring/주석): `project_aws_profile.py:3,19`, `project_gh_account.py:3,27`.

### 🟠 Tier 2 — override 가능하나 default 가 틀림

| 위치 | 내용 | 비고 |
|---|---|---|
| `src/anvyc/core/project_discovery.py:15` | `DEFAULT_ROOTS = ("~/Documents",)` | `cli.py:1351` `roots_arg = roots if roots else list(DEFAULT_ROOTS)` → `anvyc project list` 무인자 실행 시 빈 결과 |
| `src/anvyc/cli.py:1335` | `--root` help `"... default: ~/Documents"` | 위 옵션의 help 텍스트 |
| `src/anvyc/adapters/dev_env.py:26` | `DEFAULT_PROJECT_ROOTS = ("~/Documents",)` | `core/backup.py:110` 이 anvyc.yaml `dev_env.project_roots` 로 주입 → config 있으면 정상. dev_env 는 `enabled:false` 기본이라 영향 작음 |
| `src/anvyc/adapters/dev_env.py:9` | docstring `default ~/Documents` | |
| `src/anvyc/mcp/server.py:79` | MCP `project_list` 인자 description `"... default: ~/Documents"` | |
| `src/anvyc/mcp/server.py:162` | `discover_projects(roots)` — `roots` 미지정 시 `DEFAULT_ROOTS` fallback | Claude 가 명시 roots 안 주면 빈 결과 |

### 🟡 Tier 3 — 코드 외 / 경미

| 위치 | 내용 |
|---|---|
| `src/anvyc/checks/multi_account_detected.py:21` | `_USERS_DIR_RE = re.compile(r"^Users-([^-]+)-Documents$")` — Cursor user-alias symlink(`~/.cursor/projects/Users-<user>-Documents`) 감지 정규식이 `-Documents$` 에 고정. `~/dev` 기반 키(`Users-edward-dev`)는 미매칭. **INFO 안내 체크라 영향 경미** |
| `src/anvyc/cli.py:161` | `_WIZARD_DEV_ENV_DEFAULTS = {"project_roots": ["~/Documents"], ...}` — `anvyc init` wizard default |
| `src/anvyc/templates.py:89` | `DEFAULT_ANVYC_YAML` 템플릿의 `dev_env.project_roots: - "~/Documents"` → 신규 `anvyc init` 사용자가 구 경로 상속 |
| `tests/unit/test_project_discovery.py:26` | `assert "~/Documents" in DEFAULT_ROOTS` — 상수 변경 시 이 단언이 깨짐(동기 수정 필수) |
| `examples/anvyc.yaml:86` | 주석 예시 `roots: []  # 예: ["~/Documents/anvyc"]` |
| 문서 | `README.md`(419·424·428·465·485·513·518·522·531), `DESIGN.md`(661·662·1274·1521·1540·1567), `CONTEXT.md`(51·60), `RELEASE_NOTES.md`(다수), `docs/improvement-plan-ai-agent.md`(32·221), `docs/improvement-plan-ux-review.md`(21·23·120·121·155·293·303), `docs/mcp-integration.md`(67·68·158·167), ~~`docs/troubleshooting-macos.md`(96·157·159)~~ — dev-wrapper PR(2026-05-21)에서 처리 완료, 본 계획 범위 제외 |

**테스트 fixture 중 무해 항목**(temp dir 이름일 뿐 — 변경 불요): `test_project_aws_profile.py:39`, `test_project_gh_account.py:38`, `test_unused_aws_profiles.py:31` 의 `tmp_path / "Documents"`.

**테스트 fixture 중 동기 수정 필요**(정규식·분류 로직과 결합): `test_multi_account_detected.py:96·98·105` (`Users-edward-Documents` symlink fixture), `test_cross_user_classify.py:32·53`.

### ✅ 모범 선례 — 변경 불요

`src/anvyc/checks/cursor_projects_suggest.py:16-24` 의 `DEFAULT_CANDIDATE_ROOTS` 는 **이미 `~/dev` 포함** 7개 루트(`~/Documents`, `~/Projects`, `~/code`, `~/Code`, `~/dev`, `~/workspace`, `~/src`)를 스캔. 이 체크는 이전 후에도 정상 동작 — 나머지 코드가 수렴해야 할 기준 패턴.

---

## 2. 설계 지적

1. **SoT 부재**: 동일 개념("사용자 프로젝트 루트")이 4곳에 제각각 상수로 중복 — `project_discovery.DEFAULT_ROOTS`, `dev_env.DEFAULT_PROJECT_ROOTS`, `cursor_projects_suggest.DEFAULT_CANDIDATE_ROOTS`, 두 체크의 `DEFAULT_PROJECT_ROOT`. 치환만 하면 다음 이전 때 또 6곳을 찾아야 함.
2. **체크가 config 를 안 받음**: `project_aws_profile`·`project_gh_account` 의 `run(ctx)` 가 `ctx` 를 버림. 반면 `cursor_projects_suggest` 는 `load_anvyc_config()` 를 직접 호출 → 체크에서 config 접근은 이미 가능. 두 체크도 같은 패턴 적용 가능.
3. **단일 루트 vs 멀티 루트**: `cursor_projects_suggest` 만 멀티 candidate 스캔. 나머지는 단일 루트 가정. 이전기처럼 `~/Documents`·`~/dev` 가 공존하는 상황을 고려하면 멀티 루트가 견고함.

---

## 3. 권장 수정 계획

### 3.1 핵심 — 루트 상수 SoT 단일화 (High)

- 신규 `src/anvyc/core/project_roots.py` (또는 기존 `core/config.py` 에 추가):
  - `DEFAULT_PROJECT_ROOTS` — `cursor_projects_suggest` 의 7-루트 리스트를 승격, **`~/dev` 를 선두**로 재배치.
  - `resolve_project_roots(config) -> tuple[str, ...]` — anvyc.yaml 에서 루트를 읽고 없으면 `DEFAULT_PROJECT_ROOTS` fallback 하는 헬퍼.
- 소비처 6곳이 모두 이 SoT 를 참조하도록 수정:
  - `project_discovery.DEFAULT_ROOTS` → 공용 상수 재노출 또는 직접 참조
  - `dev_env.DEFAULT_PROJECT_ROOTS` → 동일
  - `cursor_projects_suggest.DEFAULT_CANDIDATE_ROOTS` → 공용 상수로 대체(동작 동일)
  - `project_aws_profile`·`project_gh_account` → 아래 3.2

### 3.2 핵심 — Tier 1 체크 config-aware 전환 (High)

- `project_aws_profile.py` / `project_gh_account.py` 의 `run(ctx)` 가 `DEFAULT_PROJECT_ROOT` 단일 상수 대신 **멀티 루트** 를 순회하도록 변경.
- 루트 출처: `cursor_projects_suggest` 처럼 `load_anvyc_config()` 사용 또는 `CheckContext` 에 루트를 싣는 방안 검토(`CheckContext` 스키마 확인 필요).
- `_iter_envrcs` / `_iter_git_dirs` 를 루트 리스트 순회로 래핑. `# noqa: ARG002` 제거(ctx 실제 사용 시).

### 3.3 Tier 2/3 (Medium/Low)

- `cli.py:1335`·`mcp/server.py:79` help/description 텍스트 갱신.
- `cli.py:161` `_WIZARD_DEV_ENV_DEFAULTS` → `~/dev`.
- `templates.py:89` `DEFAULT_ANVYC_YAML` → `~/dev` (신규 사용자 영향).
- `multi_account_detected.py:21` 정규식 일반화 — `r"^Users-([^-]+)-(Documents|dev)$"` 또는 마지막 세그먼트 무관 패턴. `test_multi_account_detected.py` fixture 동기.
- `test_project_discovery.py:26` 단언 갱신.
- 문서 일괄 치환 — 단 `RELEASE_NOTES.md` 의 과거 버전 기록은 **시점 기록이므로 보존**. `README.md`·`DESIGN.md`·`CONTEXT.md`·`docs/*.md`·`examples/anvyc.yaml` 의 현재상태 서술만 갱신.

### 3.4 작업 분리 권장

- 1 PR: 3.1 + 3.2 (코드 핵심 + 해당 테스트) — 리뷰 집중도 위해.
- 2 PR(또는 동일 PR 후속 커밋): 3.3 문서·템플릿·wizard.
- anvyc 룰: 코드 구조 변경 시 `README.md`·`CONTEXT.md`·`DESIGN.md` 동기 갱신 필수.

---

## 4. 검증 방법

```bash
cd ~/dev/anvyc

# 1) 잔여 ~/Documents 참조 재확인 (RELEASE_NOTES 이력은 제외 판단)
git grep -nI 'Documents'

# 2) 체크 동작 — ~/dev 의 .envrc / .git 을 실제로 스캔하는지
anvyc doctor --only project-aws-profile-mapping --verbose
anvyc doctor --only project-gh-account-mapping --verbose

# 3) project list 무인자 실행이 ~/dev 프로젝트를 반환하는지
anvyc project list --json | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))'

# 4) 테스트
pytest tests/unit/test_project_discovery.py tests/unit/test_multi_account_detected.py -q
pytest -q   # 전체

# 5) MCP 경로 — Claude 에서 project_list 무인자 호출 결과 확인
```

기대: 두 체크가 `~/dev` 의 프로젝트를 검사, `project list` 무인자가 `~/dev` 프로젝트를 반환, 전체 테스트 green.

---

## 5. 리스크 / 주의

| 리스크 | 완화 |
|---|---|
| 멀티 루트 스캔으로 `~/Documents`·`~/dev` 양쪽이 잡혀 중복/오탐 | `~/Documents` 정리 완료 후엔 자연 해소. 전환기엔 `Path.resolve()` 기준 dedup 확인 |
| `test_project_discovery.py:26` 등 단언 미수정 시 CI red | 코드·테스트 동일 PR 에 포함 |
| `CheckContext` 가 config 를 안 실어줌 | 스키마 확인 — 안 실리면 `load_anvyc_config()` 직접 호출(`cursor_projects_suggest` 선례) |
| 문서 일괄 치환이 `RELEASE_NOTES.md` 이력까지 변경 | 이력 문서는 grep 결과에서 제외, 수동 검토 |

---

## 6. 부록 — 출처

- 상위 분석: `~/dev/dotfiles-claude/docs/path-migration-report.md` §3 P2-4.
- 본 리뷰는 `dotfiles-claude` 경로 이전(2026-05-21, PR #10) 완료 후 후속 작업으로 분리됨.
- 조사 시점 anvyc: v0.11.0, branch `main`, HEAD `2a2a8e7`.

# `anvyc config roots` / `config projects` — 프로젝트 root·개별 프로젝트 관리 설계

- **날짜**: 2026-06-04
- **상태**: 승인됨 (구현 대기)
- **프로젝트**: anvyc (L2-environment)
- **관련**: `core/project_roots.py`(읽기 SoT), `core/project_discovery.py`, `core/guard_targets.py`, `checks/project_*`·`cursor_projects_suggest`(소비처), `core/tools_select.py`(변경 선례), `cli.py` `config edit`/`show`(선례)

## 1. 배경 / 문제

anvyc 가 "사용자 프로젝트 root" 아래를 스캔하는 모든 경로(doctor 의 5개 project-* check, `project list`/MCP `project_list`, `dev_env` 어댑터, `cursor-projects-suggest`, `guard`)는 `core/project_roots.py` 의 `project_roots`(anvyc.yaml top-level)를 SoT 로 참조한다.

**문제 1 — 관리 수단 부재.** 사용자가 root 를 입력/수정/제거하는 유일한 방법은 `anvyc config edit`(수동 `$EDITOR`) 또는 손편집뿐이다. 구조화된 CRUD 명령이 없다.

**문제 2 — 두 개념 혼재.** "프로젝트 root" 는 두 가지를 의미할 수 있다:
- **컨테이너**(`~/dev`): 여러 프로젝트를 *담는* 디렉터리. anvyc 가 자식을 순회(depth ≤ 2)해 `.git`/`Pulumi.yaml` 마커 보유 디렉터리를 프로젝트로 discovery.
- **개별 프로젝트**(`~/dev/anvyc`): 단일 프로젝트의 root 디렉터리(자신이 `.git` 보유).

현재 `project_roots` 항목은 **전적으로 컨테이너로만** 취급된다(`project_discovery._walk` 는 root 의 *자식*만 검사, root 자신은 마커 검사 안 함). 따라서 `project_roots: [~/dev/anvyc]` 를 넣으면 anvyc 의 *자식들*에서 프로젝트를 찾으려 해 **개별 프로젝트가 인식되지 않는다**. 개별 프로젝트는 오직 일회성 CLI 플래그(`guard --project ~/dev/anvyc`)로만 지정 가능하고 **config 영속화 수단이 없다**.

## 2. 목표 / Non-goals

**목표**:
- 컨테이너 root 의 구조화된 CRUD — `anvyc config roots <list|add|rm|clear>`.
- 개별 프로젝트의 포함/제외 CRUD — `anvyc config projects <list|add|rm|exclude|unexclude>`.
- 다수 root·project 동시 지원(varargs).
- 전역 config(`~/.anvyc/anvyc.yaml`) 대상, 안전한 변경(백업 + atomic + schema 재검증).
- 컨테이너와 개별 프로젝트를 **출력·동작에서 구분**.

**Non-goals**:
- `resolve_project_roots` 의미론(명시 리스트 = defaults 완전 대체) **변경 안 함**.
- hostname overlay(`anvyc.<hostname>.yaml`) 편집 안 함 — base 파일만.
- YAML **주석 보존**(ruamel.yaml) v1 미도입 — `yaml.safe_dump` 수용.
- 신규 doctor check 추가 안 함.
- `role-based-ruleset/metadata/branch-strategies.yaml`(별개 manifest)과 통합 안 함.

## 3. 결정 (승인됨)

| 결정 | 선택 | 근거 |
|------|------|------|
| defaults 관계 | **materialize 후 명시 관리** — 첫 add/rm 시 현 defaults(6개)를 명시 리스트로 구체화 후 변경 | default silent 소실 없음, resolve 의미론 불변 |
| 대상 파일 | **전역 `~/.anvyc/anvyc.yaml` 고정** (`--config`/`--local` 오버라이드) | project root 는 사용자-전역 개념 — cwd 무관 일관 |
| 명령 표면 | **전용 서브그룹** `config roots` / `config projects` | 명시 CRUD verb 가 입력/수정/제거와 직결, `git remote add/rm` 관용 |
| 개념 모델 | **두 키 분리** `project_roots`(컨테이너) + `projects`(개별 포함) + `exclude_projects`(개별 제외) | "구분" 명확, exclude 자연, `guard --project` 와 일관 |
| 검증 | **미존재 dir / 마커 없는 projects 항목 → 경고 후 허용** | `anvyc sync` 머신 간 config 공유 — 타 머신에만 있는 경로 차단 금지 |
| 쓰기 | **`.bak` + atomic(tempfile.mkstemp + os.replace) + 쓰기 후 schema 재검증** | `tools_select`·`config edit` 선례, 실패 시 원본 복구 |
| 주석 | **`yaml.safe_dump` 수용**(주석 소실) | `tools_select`·`mcp_setup` 선례 일관, ruamel 신규 의존성 회피 |
| 저장 형식 | **`~` 미확장 + `$HOME` 접두 재축약 + 공백/후행슬래시 정규화** | `DEFAULT_PROJECT_ROOTS` 컨벤션, 머신 간 휴대성 |
| `clear` | **확인 프롬프트 생략 + before→after 출력** | defaults 복귀는 가역적(재-add 가능) |
| 단계 | **Phase 1 `config roots` → Phase 2 `config projects` 별도 PR** | Phase 1 격리(소비처 무변경), Phase 2 가 그 위에 구축 |

## 4. 아키텍처

```
core/project_roots.py        # 읽기 SoT
                             #   resolve_project_roots(cfg)            (기존) — 컨테이너
                             #   resolve_projects(cfg) -> tuple[str]   (신규) — 개별 포함 (raw)
                             #   resolve_excludes(cfg) -> tuple[str]   (신규) — 개별 제외 (raw)
core/project_scope.py        # (신규, Phase 2) 통합 후보 iterator
                             #   iter_project_dirs(cfg, *, markers, max_depth=2) -> list[Path]
                             #     = walk(project_roots, markers) ∪ expand(projects[matching markers])
                             #       − resolve(exclude_projects)
core/project_roots_edit.py   # (신규) 변경 로직 — 순수 함수, config dict 입력
                             #   materialize/add/remove/clear (roots) + add/remove/exclude/unexclude (projects)
                             #   _atomic_write_yaml + .bak + revalidate (tools_select 헬퍼 공유로 추출)
cli.py                       # config_app 하위:
                             #   roots_app    : list/add/rm/clear
                             #   projects_app : list/add/rm/exclude/unexclude
```

**Effective project set** (임의 소비처 기준):

```
effective = ( discover(project_roots, markers) ∪ projects[has markers] ) − exclude_projects
            → 각 소비처가 자기 relevance 필터(.git origin / .cursor / .envrc) 추가 적용
```

- `exclude_projects` 는 **전역 필터**(모든 소비처 적용).
- `projects` 는 **가산 후보**(각 소비처가 요청 마커로 취사).
- 충돌(같은 경로가 `projects` ∩ `exclude_projects`) → **exclude 우선** + 편집 시점 경고.
- dedupe 는 `Path.resolve()` 기준(개별 프로젝트가 컨테이너 자식과 겹쳐도 1회).

읽기 SoT(`project_roots.py`)와 변경 로직(`project_roots_edit.py`)을 분리해 책임을 격리한다. 현재 9개 소비처는 제각각 스캔(`discover_projects` depth 2 / `guard_targets._git_repos_under` depth 1 / 각 check 자체 `_iter_git_dirs`)하므로, Phase 2 에서 `iter_project_dirs` 로 **통일하며 개별/제외를 반영**한다(타깃 개선 — depth 불일치도 해소).

## 5. 개념 모델 / 데이터

`anvyc.yaml` top-level 스키마(예시):

```yaml
project_roots:        # 컨테이너 — 자식을 순회해 프로젝트 discovery
  - ~/dev
  - ~/Projects
projects:             # 개별 프로젝트 — 컨테이너 밖이라도 직접 포함
  - ~/work/client-x
exclude_projects:     # 개별 제외 — 모든 discovery/체크에서 스킵
  - ~/dev/archived
```

`AnvycConfig`(`core/config.py`) 신규 필드:

```python
project_roots: list[str] = field(default_factory=list)      # (기존) 빈 리스트면 SoT DEFAULT
projects: list[str] = field(default_factory=list)           # (신규)
exclude_projects: list[str] = field(default_factory=list)   # (신규)
```

세 키 모두 미설정/빈 리스트 허용. `project_roots` 만 "빈 리스트 → DEFAULT 6개 fallback" 규칙 유지(기존). `projects`/`exclude_projects` 는 빈 = 영향 없음.

## 6. 명령 스펙

공통 플래그(모든 하위 명령): `--config PATH`(명시 파일) · `--local`(cwd-우선 `_resolve_anvyc_yaml` 해석). 둘 다 없으면 **전역 `~/.anvyc/anvyc.yaml`**.

### 6.1 `config roots` (Phase 1)

| 명령 | 인자 | 동작 |
|------|------|------|
| `roots list` | `[--json]` | effective 컨테이너 표시 — 출처(explicit/default) + 존재(✓/✗) + 각 컨테이너의 discovered 프로젝트 수 |
| `roots add` | `<path>...` | materialize(필요 시) → normalize → dedupe → append. 미존재 dir 경고 후 추가. 중복 no-op |
| `roots rm` | `<path>...` | materialize(필요 시) → 일치 항목 제거. 비목록 경로 경고. 결과 빈 리스트 → 키 삭제(=defaults 복귀) |
| `roots clear` | — | `project_roots` 키 삭제 → defaults 복귀. before→after 출력 |

### 6.2 `config projects` (Phase 2)

| 명령 | 인자 | 동작 |
|------|------|------|
| `projects list` | `[--json]` | `projects`(개별 포함) + `exclude_projects`(제외) 표시 — 출처 + 존재(✓/✗) + 마커 유무. 컨테이너 discovered 항목 dim 동시 표시는 선택(optional) |
| `projects add` | `<path>...` | normalize → dedupe → `projects` append. 미존재/마커없음 경고 후 추가. exclude 와 충돌 시 경고 |
| `projects rm` | `<path>...` | `projects` 에서 제거. 비목록 경고 |
| `projects exclude` | `<path>...` | `exclude_projects` append. (`projects` 에도 있으면 exclude 우선 — 경고) |
| `projects unexclude` | `<path>...` | `exclude_projects` 에서 제거 |

**출력 규약**(DESIGN §doctor 출력 가이드 준수): Panel/테두리 미사용, Rich `escape()` + `soft_wrap=True`. 성공 exit 0. 하드 에러(쓰기 실패·재검증 실패→복구) exit 1. 경고(미존재 dir 등)는 비차단.

`--json` 출력 예(`roots list`):

```json
{"roots": [
  {"path": "~/dev", "source": "explicit", "exists": true, "projects": 24},
  {"path": "~/Code", "source": "default", "exists": false, "projects": 0}
]}
```

## 7. 핵심 의미론

- **Materialize**: 대상 파일에 `project_roots` 가 없거나 비면, 첫 `roots add`/`rm` 시 현재 effective(=`DEFAULT_PROJECT_ROOTS` 6개)를 명시 리스트로 구체화한 뒤 변경 적용. → 첫 add = defaults + 신규, 첫 rm = defaults − 대상. default silent 소실 없음. (`projects`/`exclude_projects` 는 defaults 개념이 없어 materialize 불필요 — 빈 리스트에서 시작.)
- **정규화**(`_normalize`): `str.strip()` → 후행 슬래시 제거 → 절대경로가 `$HOME` 하위면 `~/...` 로 재축약 → 그 외 절대경로/상대경로는 그대로(상대경로는 경고). 빈 문자열 제거.
- **dedupe**: 정규화 후 문자열 동등 비교(리스트 내) + 소비처 단계의 `Path.resolve()` 동등(컨테이너↔개별 겹침).
- **검증**: `add`/`exclude` 시 `Path(p).expanduser()` 가 (a) 미존재 → 경고, (b) `projects` 인데 마커(`.git`/`Pulumi.yaml`) 없음 → 경고. 둘 다 **추가는 진행**.
- **materialize 고정 효과**: 구체화 후엔 향후 `DEFAULT_PROJECT_ROOTS` 변경이 자동 반영 안 됨(explicit = pinned) — 의도된 트레이드오프.

## 8. 소비처 통합 (Phase 2)

`iter_project_dirs(cfg, *, markers, max_depth)` 를 신설하고 아래 소비처를 이 함수 기반으로 리팩터한다. 각 소비처는 자기 마커/필터만 전달:

| 소비처 | 현재 스캔 | markers | 추가 필터 |
|--------|-----------|---------|-----------|
| `project_discovery.discover_projects` | depth 2, `.git`+`Pulumi.yaml` | `(".git", "Pulumi.yaml")` | — |
| `guard_targets.resolve_guard_targets` | depth 1, `.git` | `(".git",)` | — (`--project` 경로는 우회 유지) |
| `checks/project_aws_profile` | `.envrc` 보유 | `(".envrc",)` | AWS_PROFILE 정합 |
| `checks/project_gh_account` | `.git` + ssh-alias origin | `(".git",)` | origin ssh alias |
| `checks/project_claude_account` | `.envrc` CLAUDE_CONFIG_DIR | `(".envrc",)` | 라우팅 정합 |
| `checks/project_pulumi_backend` | `Pulumi.yaml` | `("Pulumi.yaml",)` | backend 정합 |
| `checks/unused_aws_profiles` | `.envrc` 집계 | `(".envrc",)` | 미사용 profile |
| `checks/cursor_projects_suggest` | depth 1, `.cursor` | `(".cursor",)` | 미등록 |

- 각 소비처: `iter_project_dirs(cfg, markers=…)` → `projects` 가산 + `exclude_projects` 제거가 일괄 반영.
- `dev_env` 어댑터는 자체 `project_roots`(config 주입) 경로라 별도 검토(영향 작음 — 기본 `enabled:false`).
- **리스크 완화**: 통일 리팩터는 소비처별 회귀 테스트로 가드. 기존 동작(컨테이너 스캔) 보존을 우선 검증한 뒤 개별/제외를 추가.

## 9. 엣지 / 에러 처리

- **대상 config 부재**: `add`/`exclude` → 최소 파일 생성(해당 키만). `list` → defaults/빈 표시. `rm`/`clear`/`unexclude` → "명시 항목 없음" 안내(no-op).
- **overlay**: roots/projects 명령은 base 파일만 편집. `anvyc.<hostname>.yaml` 가 roots 를 override 중이면 `list` 에 안내(편집 대상은 base 임을 명시).
- **충돌**: `projects` ∩ `exclude_projects` → exclude 우선 + 편집 시 경고. 같은 경로 중복 add → no-op.
- **재검증 실패**: 쓰기 후 `load_anvyc_config(target)` 가 throw → `.bak` 복구 + exit 1.
- **`rm` 으로 빈 리스트**: `project_roots` 키 자체 삭제(= `clear` 와 동일 효과, defaults 복귀). `projects`/`exclude_projects` 는 빈 리스트면 키 삭제.

## 10. 단계 계획

**Phase 1 — `config roots` (컨테이너)**
- 산출물: `core/project_roots_edit.py`(roots 부분), `cli.py` `roots_app` 4개 명령, `examples/anvyc.yaml`·README·DESIGN 갱신.
- 소비처 **무변경**(`resolve_project_roots` 이미 사용). 격리·저 blast radius.
- 충족: "여러 프로젝트 root(컨테이너) 입력/수정/제거 + 다수 지원".

**Phase 2 — `config projects` (개별 + 제외)**
- 산출물: `AnvycConfig.projects`/`exclude_projects` 스키마, `core/project_roots.py` `resolve_projects`/`resolve_excludes`, `core/project_scope.py` `iter_project_dirs`, 8개 소비처 리팩터, `cli.py` `projects_app`, 문서 갱신.
- blast radius↑ — 소비처 회귀 테스트 우선.
- 충족: "개별 프로젝트(`~/dev/anvyc`) 포함/제외 관리".

스펙은 하나(통합 모델), 구현 계획에서 두 Phase 로 시퀀싱(각 별도 PR).

## 11. 테스트 전략

- **단위(`project_roots_edit`)**: 첫-add materialize, dedupe idempotent, rm 정규화 매칭, rm→빈 리스트 키삭제, clear 키삭제, 정규화(~축약/후행슬래시/공백/상대경로 경고), 미존재·마커없음 경고-허용, exclude 우선·충돌 경고, atomic+`.bak`, 재검증 실패→복구.
- **단위(`project_scope.iter_project_dirs`)**: 컨테이너∪개별−제외, 마커별 필터, resolve dedupe, max_depth.
- **CLI 동작(`test_tools_select` 스타일)**: roots·projects 각 verb, 전역/`--local`/`--config` 해석, `--json`. tmp config + HOME monkeypatch.
- **소비처 회귀(Phase 2)**: 각 check/discovery 가 리팩터 후에도 기존 컨테이너 스캔 동작 보존 + 개별/제외 신규 반영.

## 12. 문서 갱신

- `examples/anvyc.yaml`: top-level `project_roots`/`projects`/`exclude_projects` 예시 보강(현재 top-level `project_roots` 예시 누락).
- `README.md`: `config roots`/`config projects` 사용 예.
- `DESIGN.md`: §project_roots SoT 설명에 두 개념·`iter_project_dirs` 통합 반영.
- `CONTEXT.md`: 진행 상태 갱신.

# anvyc 지원 도구 목록 → 선택 → 구성 UX 개선 계획

> 상태: **활성 (작업 중)** — 소진 시 `docs/archive/` 로 이동
> 작성일: 2026-05-29
> 대상 버전: v0.16.x → **v0.17.0 후보** (control-plane axis 아님 — UX 기능)
> 검토 범위: 지원 도구 목록의 정보성, 선택 기반 구성/설정 편의성, 메타데이터 SoT 단일화
> 참고: 기존 `anvyc tools list` / `anvyc init --interactive` / `anvyc mcp install` (안전 write 패턴)

---

## 1. 검토 동기

사용자가 anvyc 를 처음 쓰거나 새 머신에서 설정할 때 **"무슨 도구를 관리할 수 있고, 각각 무엇을 포함/제외하는지"** 를 한눈에 보고 **선택만으로 구성**할 수 있어야 한다. 현재는 (a) 목록이 빈약하고, (b) 선택→구성 흐름이 `init` 1회용이며 재실행이 안 되고, (c) 도구 메타데이터가 SoT 없이 5곳에 분산돼 drift 위험이 있다.

## 2. 현황과 갭

지원 도구 = **10개 adapter** (`src/anvyc/core/backup.py` `ADAPTERS`):
`shell · git · aws · gh · cursor · claude · iterm2 · pulumi · dev_env · shell_prompt`.

도구 정보가 **5곳에 중복** — 단일 SoT 부재:

| # | 위치 | 보유 정보 | 문제 |
|---|------|-----------|------|
| 1 | `tools list` (`cli.py`) | enabled/detected/files/secrets 표 | 설명·기본 포함/제외 **없음**, "미지원" 푸터 하드코딩 |
| 2 | `init --interactive` (`cli.py` `_run_init_wizard`) | enable/path 프롬프트 | **init 1회용**, 재실행 불가, `_WIZARD_*` 에 메타 별도 하드코딩, 설명 미표시 |
| 3 | 각 adapter `DEFAULT_FILES` + `exclude()` | 실제 기본 포함/제외 | `label`·`summary`·`category` 미노출, `Adapter` Protocol 에 메타 필드 없음 |
| 4 | README §4 "지원 도구" 표 | 기본 포함/제외 | **수작업** 유지 |
| 5 | MCP `tools_list` (`mcp/server.py`) | rows | `tools list` 와 또 중복 |

**핵심 갭**: 골격(목록→선택→구성)은 wizard 에 있으나 위 (a)(b)(c) 3가지가 막고 있다.

## 3. 목표 상태

```bash
anvyc tools list                 # 설명·기본 포함/제외·감지·활성 컬럼 (읽기 전용, 풍부)
anvyc tools configure            # 체크박스 TUI → space 토글 → enter → diff 미리보기 → 안전 저장 (재실행 가능)
anvyc tools configure --no-tui   # TTY 아님 / [tui] extra 미설치 시 자동 폴백 (번호 토글)
anvyc init --interactive         # 동일 SoT·동일 선택엔진 재사용 (중복 제거)
```

모든 표면(list / configure / wizard / MCP / README)이 **단일 `AdapterMeta` SoT** 를 소비.

## 4. 아키텍처 — `AdapterMeta` SoT

`src/anvyc/adapters/base.py` 에 정적 메타 dataclass 신설, `Adapter` Protocol 확장, 10개 adapter 가 `meta` 클래스 속성으로 노출:

```python
@dataclass(frozen=True)
class AdapterMeta:
    name: str                  # 'aws' (registry key·class.name 과 일치)
    label: str                 # 'AWS CLI'
    summary: str               # '~/.aws/config 백업 (credentials·SSO cache 제외)'
    category: str              # shell|vcs|cloud|iac|ide|ai-agent|terminal|dev-env
    includes: tuple[str, ...]  # 기본 포함 — file-based 는 DEFAULT_FILES 동일 객체 참조
    excludes: tuple[str, ...]  # 기본 제외 (표시용; file-based 는 exclude() 의 부분집합)
    default_enabled: bool = True   # dev_env=False, 그 외 True
    config_kind: str = "files"     # 'files' | 'structured'(cursor/claude/iterm2/dev_env)
    since: str = ""                # 'v0.1.0' — README 버전 표 생성용
```

- **정적**(meta): label/summary/category/includes/excludes/default_enabled/config_kind/since.
- **런타임 파생**(meta 아님): `enabled`(config), `detected`(`adapter.detect()`), file/secret count.
- file-based adapter 는 `includes=DEFAULT_FILES` 로 **동일 객체 참조** → drift 불가. 일관성은 단위 테스트로 강제(§7).
- Protocol 은 `@runtime_checkable` 이나 `isinstance(_, Adapter)` 호출처가 없어 `meta` 추가는 런타임 무영향.

## 5. 표면별 변경

**(A) `tools list` 강화** — `_collect_tools_rows` 가 meta 합류. 컬럼: `label · enabled · detected · 포함 · 제외 · files · secrets`. `--json` 은 meta 키 **추가**(기존 키 유지 → 하위호환). 하드코딩 "미지원" 푸터는 SoT 의 planned/unsupported 목록으로 대체.

**(B) `anvyc tools configure` 신규** (`tools_app`):
- 기본: Textual 체크박스 TUI (행 = 체크박스 + label + 감지표시 + summary, space 토글, enter 저장).
- 저장 시: 현재 `anvyc.yaml` 과 **diff 미리보기 → 확인 → atomic write + `.bak`** (`core/mcp_setup.py` 안전 write 패턴 재사용). 무관 섹션(storage/security/secrets/cost/overlay) 보존.
- 재실행성: 기존 config 의 enabled 상태를 초기 체크 상태로 로드.
- Phase 1 범위: enable/disable + 기본 포함값 적용. 세부 path 편집은 `config edit`/yaml 유지(추후 확장).

**(C) wizard 리팩터** — `init --interactive` 가 SoT + 동일 선택모델 + 동일 writer 재사용. `_WIZARD_FILE_DEFAULTS / _WIZARD_DEV_ENV_DEFAULTS / _WIZARD_TOOLS_ORDER` 제거. 차이는 "신규 전체 yaml 생성(init) vs 기존 갱신(configure)" 뿐.

**(D) MCP / README** — `mcp/server.py` `tools_list` payload 에 meta 합류. README §4 는 `scripts/gen_supported_tools.py` 로 SoT 에서 생성(또는 최소 동기화).

## 6. 의존성·안전·폴백 (안전 기본값)

- **Textual 은 선택 extra `anvyc[tui]`** 로 추가(필수 의존성 아님). 근거: Homebrew 호환 위해 pydantic 을 제거한 전례 — TUI 를 필수로 넣으면 일관성 위배. `[mcp]`/`[cost-aws]` extra 패턴과 동일.
- **폴백 필수**: TTY 아님 / `--no-tui` / textual 미설치 → 번호 토글 메뉴 자동 강등. 헤드리스/CI 완전 동작(test HOME isolation·CI 규율과 정합).
- **model/view 분리**: 순수 "선택 모델 + yaml 머지 writer"(`core/tools_select.py`) 단위 테스트, Textual view(`ui/tui.py`) 얇게. `tui-extra-importable` doctor check 추가(v0.15.2 silent-failure 교훈).
- safe-by-default: 저장 전 항상 diff 미리보기, `.bak` 자동, secret 영역 미접촉.

## 7. 단계별 PR 분해

| PR | 내용 | 주요 파일 | 사용자 영향 | 상태 |
|----|------|-----------|------------|------|
| **PR1** | `AdapterMeta` SoT — dataclass + Protocol 확장 + 10 adapter 채움 + drift 가드 테스트 | `adapters/base.py`, `adapters/*.py`(10), `tests/unit/test_adapter_meta.py` | 없음(기반) | ✅ merged (#120) |
| **PR2** | `tools list` 강화(human+`--json` 추가키) + MCP `tools_list` payload + 푸터 SoT화 | `cli.py`, `mcp/server.py` | 즉시 가치(풍부한 목록) | ✅ 구현 · PR open |
| **PR3** | 순수 선택모델 + 안전 yaml writer/merge + `tools configure`(폴백 경로, textual 無로 완전 동작) | `core/tools_select.py`(신규), `cli.py` | configure 사용 가능(번호 토글) | ✅ 구현 · PR open |
| **PR4** | Textual TUI view + `[tui]` extra + `tui-extra-importable` check + 미설치 폴백 | `ui/tui.py`(신규), `pyproject.toml`, `checks/tui_extra.py`(신규) | TUI 경험 | 예정 |
| **PR5** | `init --interactive` 리팩터 → SoT+선택모델+writer 재사용, `_WIZARD_*` 제거 | `cli.py` | 동작 동일, 중복 제거 | 예정 |
| **PR6** | 문서 — README §4 생성/§8 갱신 + DESIGN/RELEASE_NOTES/CONTEXT + 본 계획 archive | `scripts/gen_supported_tools.py`(신규), `README.md`, `DESIGN.md` 외 | 문서 정합 | 예정 |

PR1–2 만으로도 "풍부한 목록" 선배포 가능. 각 PR 독립 머지·테스트 백업.

## 8. 테스트 전략

- **drift 가드(핵심)**: 10 adapter 전부 `meta` 보유 / `meta.name == registry key == class.name` / `category` 허용값 / file-based `meta.includes == DEFAULT_FILES` / `meta.excludes ⊆ exclude()` (경로형 adapter) / `default_enabled` 정책(dev_env 만 False).
- yaml 머지: configure 저장이 무관 섹션 보존(PR3).
- 폴백: textual 미설치/`--no-tui` 헤드리스 동작(PR3/4).
- TUI: 로직은 순수 모델로 단위 테스트, view 는 Textual Pilot 최소 스모크(선택, PR4).

## 9. 리스크 & 결정 포인트

- **Textual 의존**: 선택 extra + 폴백으로 해소(기본값). "필수 의존 OK" 라면 PR4 단순화되나 Homebrew 영향 검토 필요 → 기본은 optional extra.
- **`tools list --json` 스키마**: 키 **추가만**(제거/변경 없음) → 하위호환.
- **버전/axis**: control-plane axis 아님 → 신규 CP-N 불요. CP 번호는 rbr manifest/ROADMAP 권한이므로 임의 부여 안 함. 버전 태그(v0.17.0 등)는 메인테이너 판단.

## 10. 진행 상태

- [x] 계획 수립 + 본 문서 작성
- [x] PR1 — AdapterMeta SoT (#120 merged)
- [x] PR2 — tools list 강화 + MCP payload (PR open)
- [x] PR3 — 선택모델 + 안전 writer + configure 폴백 (PR open)
- [ ] PR4 — Textual TUI + [tui] extra + doctor check
- [ ] PR5 — wizard 리팩터 (중복 제거)
- [ ] PR6 — 문서 생성/정합 + 본 문서 archive

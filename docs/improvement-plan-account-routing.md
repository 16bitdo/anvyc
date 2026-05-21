# anvyc 개선 계획 — Claude / Cursor / Pulumi 계정 라우팅 추가

> 작성일: 2026-05-21
> 대상 버전: v0.11.0 기준 → v0.12+ 후보
> 검토 범위: anvyc 의 per-project 계정 라우팅을 Claude Code / Cursor / Pulumi 로 확장
> 배경: anvyc 은 AWS(`AWS_PROFILE`)·GitHub(`GH_CONFIG_DIR`) 의 per-project 계정 라우팅을 인식·검증한다 (`project show` / `project doctor` / global doctor check). 같은 모델을 Claude·Cursor·Pulumi 로 확장 요청.
> 상태: **리뷰 완료 / 수정 미착수** — 본 문서를 인계 기준으로 후속 PR 진행. §3.3(Cursor)은 2026-05-21 옵션 A(제외) 확정.

---

## 0. TL;DR

- **Claude Code** — ✅ 깨끗한 확장. `CLAUDE_CONFIG_DIR` 은 `GH_CONFIG_DIR` 의 직접 analog (Claude Code 가 네이티브로 읽는 env var). `.envrc` 라우팅 + `claude_account` 필드 + doctor check 모두 적용 가능.
- **Pulumi** — ✅ 확장 가능, 단 신호원이 다름. per-project 신호가 `.envrc` 가 아니라 **`Pulumi.yaml` 의 `backend` 필드** (+ 선택적 `.envrc` `PULUMI_BACKEND_URL`). "계정" = backend/org.
- **Cursor** — ⚠️ **네이티브 per-project 라우팅 메커니즘이 없음**. Cursor 멀티 계정은 `cursor --user-data-dir=...` *실행 플래그* — env var 도, 프로젝트별도 아님. AWS/gh/Claude 패턴이 성립하지 않음 → §3.3 에서 옵션 A(제외) 확정 (2026-05-21).

**권장 진행 순서**: Phase 1 Claude → Phase 2 Pulumi. Phase 3 Cursor 는 옵션 A(제외) 확정으로 제외 — PR 불요.

---

## 1. 기존 패턴 — AWS / GitHub 라우팅 (확장 템플릿)

| 구성요소 | AWS | GitHub |
|---|---|---|
| per-project 신호 | `.envrc` `export AWS_PROFILE=...` | `.envrc` `export GH_CONFIG_DIR=".../gh-<account>"` |
| 도구 네이티브 인식 | aws CLI 가 `AWS_PROFILE` 읽음 | gh CLI 가 `GH_CONFIG_DIR` 읽음 |
| derive 함수 | (raw 값 그대로) | `_derive_gh_account()` — basename 의 `gh-` prefix strip |
| `ProjectInfo` 필드 | `aws_profile` | `gh_account` |
| global doctor check | `project-aws-profile-mapping` | `project-gh-account-mapping` |
| per-cwd check (`project doctor`) | `aws_profile_defined` | `gh_account_routing` |
| 검증 내용 | `~/.aws/config` 에 profile 정의됨? (1-way) | GH_CONFIG_DIR 계정 == origin ssh alias? (2-way 정합성) |

핵심 코드: `core/project_info.py` (`collect_project_info`·`_derive_gh_account`·`ProjectInfo`), `checks/project_aws_profile.py`·`project_gh_account.py` (global), `core/project_doctor.py` (per-cwd), `core/doctor.py` (check registry), `mcp/server.py` (JSON 노출).

**핵심 통찰**: AWS·gh·Claude 의 신호는 모두 *도구가 네이티브로 읽는 env var* 다. anvyc 은 그 값을 *읽기만* 하고 검증한다. 도구가 안 읽는 var 는 라우팅이 성립하지 않는다 — Cursor 문제의 근원.

참고: `core/project_info.py` 의 `_parse_envrc` 정규식(`_EXPORT_RE`)은 임의의 `export KEY=VALUE` 를 캡처하므로 `CLAUDE_CONFIG_DIR`·`PULUMI_BACKEND_URL` 추가에 정규식 변경은 불필요하다.

---

## 2. 도구별 메커니즘 조사 결과

| 도구 | per-project 신호 | 도구 네이티브? | 라우팅 | 비고 |
|---|---|---|---|---|
| Claude Code | `.envrc` `CLAUDE_CONFIG_DIR` | ✅ Claude Code 가 읽음 (config + auth 토큰 전체) | ✅ 가능 | 멀티 계정 = 계정별 config dir. macOS 는 경로 SHA-256 → Keychain 격리 |
| Pulumi | `Pulumi.yaml` `backend.url` / `.envrc` `PULUMI_BACKEND_URL`·`PULUMI_ACCESS_TOKEN` | ✅ pulumi CLI 가 읽음 | ✅ 가능 (backend 단위) | "계정" = backend/org. Pulumi Cloud org 은 stack 이름 `<org>/<project>/<stack>` 에 |
| Cursor | (없음) — 멀티 계정은 `cursor --user-data-dir=...` 실행 플래그 | ✗ env var 아님, 프로젝트별 아님 | ⚠️ 네이티브 불가 | §3.3 |

(출처: §6)

---

## 3. 권장 수정 계획

### 3.1 Phase 1 — Claude Code 계정 라우팅 (High — 깨끗한 확장)

신호: `.envrc` 의 `export CLAUDE_CONFIG_DIR="$HOME/.claude-<account>"` (anvyc 권장 convention: `~/.claude-<account>`).

- `core/project_info.py`
  - `_derive_claude_account(claude_config_dir)` 신규 — basename 에서 `.claude-` / `claude-` prefix strip → account. 기본 `~/.claude` → `None`. `_derive_gh_account` 패턴 복제.
  - `ProjectInfo` 에 `claude_account: str | None` 추가. `collect_project_info` 에서 `raw_dev_env.get("CLAUDE_CONFIG_DIR")` → derive.
- `checks/project_claude_account.py` 신규 — global check `project-claude-account-mapping`
  - `resolve_project_roots()` 순회 → `.envrc` 의 `CLAUDE_CONFIG_DIR` 수집 → 가리키는 디렉터리 존재 검증.
  - 검증은 **1-way (디렉터리 존재 확인)** — gh 처럼 cross-check 할 "remote" 가 없음. 부재 → WARNING, 존재 → INFO.
- `core/project_doctor.py` — per-cwd check `claude_account_dir_exists` 추가 (`run_project_doctor` check 목록).
- `core/doctor.py` — check registry 에 `project-claude-account-mapping` 등록.
- (선택) `checks/multi_account_detected.py` — `~/.claude-*` 다중 디렉터리 감지 INFO 추가 (AWS/gh/cursor-alias 와 동일 결).

검증 강도: gh 보다 약함 (존재 확인만 — cross-check 대상 부재). 핵심 가치는 `project show`/MCP 에 `claude_account` 를 노출해, agent/사용자가 "이 프로젝트가 어느 Claude 계정으로 라우팅되는지" 를 알 수 있는 것.

### 3.2 Phase 2 — Pulumi backend 라우팅 (Medium)

신호: `Pulumi.yaml` 의 `backend.url` (프로젝트 파일 — 1순위) + 선택적 `.envrc` `PULUMI_BACKEND_URL` / `PULUMI_ACCESS_TOKEN`.

- `utils/pulumi_project.py`
  - `detect_pulumi_project` 가 `Pulumi.yaml` 의 `backend` 키도 파싱 → `PulumiProjectInfo.backend_url`.
  - `to_dict` 의 dict 에 `backend` 추가 → `ProjectInfo.pulumi["backend"]` 로 노출 (pulumi-scoped, top-level 필드 신설 불요).
- `core/project_info.py`
  - `.envrc` 의 `PULUMI_BACKEND_URL` 수집 (raw — 비-secret). `PULUMI_ACCESS_TOKEN` 은 secret → 기존 D11c redaction 으로 자동 마스킹, 값은 추적 안 하고 *존재 여부*만.
- `core/project_doctor.py` — per-cwd check `pulumi_backend_routing`
  - `Pulumi.yaml backend.url` 과 `.envrc PULUMI_BACKEND_URL` 이 둘 다 있으면 일치 검증 (**2-way 정합성** — gh 수준).
  - (강화 옵션) `~/.pulumi/credentials.json` (backup 제외 영역이나 read-only 검증엔 사용 가능) 에 해당 backend 토큰이 있는지 확인 → "backend 선언됐는데 미로그인" WARNING.
- global check `project-pulumi-backend-mapping` 은 선택 — `.envrc PULUMI_BACKEND_URL` 사용 프로젝트가 적으면 per-cwd 만으로 충분.

비고: Pulumi "계정"은 AWS profile / gh account 같은 단일 username 이 아니라 **backend(+org)** 개념. 필드명을 `pulumi.backend` 로 두어 혼동을 피한다.

### 3.3 Phase 3 — Cursor (결정 확정: 옵션 A 제외 — 네이티브 메커니즘 부재)

Cursor 는 `.envrc` 로 라우팅할 env var 가 **없다**. 멀티 계정은 `cursor --user-data-dir=<dir>` 실행 플래그 (per-instance, 사용자가 alias/런처로 관리). anvyc 의 `.envrc` 기반 라우팅 패턴이 성립하지 않는다.

| 옵션 | 내용 | 평가 |
|---|---|---|
| **A. 제외** | Cursor 는 본 계획에서 제외 | 가장 정직 — 네이티브 메커니즘이 없으면 검증할 SoT 도 없음 |
| **B. convention-only** | anvyc 이 `.envrc` 의 `CURSOR_USER_DATA_DIR` (anvyc 정의 convention) 를 인식. 단 Cursor 가 안 읽으므로, 사용자가 wrapper alias 로 `cursor --user-data-dir="$CURSOR_USER_DATA_DIR"` 를 직접 연결해야 의미 있음 | 동작은 가능하나 "anvyc 규약"일 뿐 — gh/Claude 처럼 도구 네이티브가 아니라 오해 소지 |
| **C. detect-only** | 라우팅은 안 하고 `multi_account_detected` 에 "Cursor user-data-dir 후보 다수 감지" INFO 만 추가 | 안전하나 라우팅 가치는 낮음 |

**결정: A (제외)** — 2026-05-21 확정. 네이티브 per-project 라우팅 메커니즘 부재로 검증할 SoT 가 없음. Cursor 는 본 계획에서 제외하며 Phase 3 PR 은 진행하지 않는다.

재검토 조건: ① Cursor 가 `CURSOR_CONFIG_DIR` 류 env var 를 지원, 또는 ② 사용자가 `--user-data-dir` wrapper alias 패턴을 표준 운용으로 채택 → 이 경우 옵션 B 재검토.

### 3.4 공통 변경

- `ProjectInfo` 신규 필드(`claude_account`)·`pulumi["backend"]` → `project show` / `project list` JSON 자동 포함 (`asdict`).
- `mcp/server.py` — `project_show` / `project_list` 출력에 신규 필드 자동 반영 (`to_dict` 경유, schema 변경 backward-compatible).
- 문서 — DESIGN §32(ProjectInfo schema)·§33, README §11(다수 계정 관리), CONTEXT §2 결정 기록, `docs/account-check-flow.mmd` 다이어그램에 Claude/Pulumi 분기 추가.
- 테스트 — `test_project_info.py`(신규 필드), `test_project_claude_account.py`, `project doctor` 통합 테스트.

### 3.5 작업 분리 권장

- PR 1 — Phase 1 (Claude). 깨끗하고 독립적.
- PR 2 — Phase 2 (Pulumi). `pulumi_project.py` 변경 포함.
- ~~PR 3 — Phase 3 (Cursor)~~ — §3.3 에서 옵션 A(제외) 확정. PR 진행 안 함.

---

## 4. 검증 방법

```bash
# Claude
echo 'export CLAUDE_CONFIG_DIR="$HOME/.claude-edward"' >> <project>/.envrc
anvyc project show --json | jq .claude_account        # → "edward"
anvyc project doctor                                  # claude_account_dir_exists check
anvyc doctor --only project-claude-account-mapping

# Pulumi
anvyc project show --json | jq '.pulumi.backend'
anvyc project doctor                                  # pulumi_backend_routing check

pytest -q   # 신규 테스트 포함 전체 green
```

---

## 5. 리스크 / 열린 결정

| 항목 | 메모 |
|---|---|
| Cursor 메커니즘 부재 | §3.3 — 옵션 A(제외) 확정 (2026-05-21). 재검토 조건은 §3.3 참조 |
| Claude check 강도 | cross-check 대상 없음 → 디렉터리 존재 확인만. "mapping" 보다 "surface + 존재" 성격 |
| `_derive_claude_account` convention | `~/.claude-<account>` 가정. `~/.config/claude/...` 등 다른 레이아웃은 basename best-effort |
| Pulumi "계정" 모호성 | backend ≠ username. 필드명 `pulumi.backend` 권장. org 단위 추적은 후속 검토 |
| `PULUMI_ACCESS_TOKEN` 은 secret | 값 추적 금지 — 존재 여부만. 기존 redaction 으로 자동 보호 |
| MCP schema 변경 | 신규 필드 추가는 backward-compatible (consumer 가 모르면 무시) |

---

## 6. 부록 — 출처

- Claude Code 환경변수 / `CLAUDE_CONFIG_DIR`: `https://code.claude.com/docs/en/env-vars`, `anthropics/claude-code#33430` ([DOCS] CLAUDE_CONFIG_DIR for multi-account)
- Cursor 멀티 계정 (`--user-data-dir`): `https://cursor.com/docs/cli/reference/configuration`
- Pulumi state/backend·환경변수: `https://www.pulumi.com/docs/iac/concepts/state-and-backends/`, `https://www.pulumi.com/docs/iac/cli/environment-variables/`
- 조사 시점: 2026-05-21, anvyc v0.11.0, branch main

# anvyc 개선 계획 — AI agent 의 multi-project connection 활용

> 작성일: 2026-05-19
> 대상 버전: v0.7.2 (현재 release) 기준 → v0.7.x / v0.8.x / v0.9.x 로드맵
> 검토 범위: AI agent (Claude / Cursor / ChatGPT) 가 anvyc 를 통해 multi-project
> 환경의 AWS / GitHub / Pulumi 연결 정보를 사용하는 시나리오
> 자매 문서: [improvement-plan-ux-review.md](./improvement-plan-ux-review.md) (설치/다중계정/설정)

---

## 1. 검토 동기

anvyc v0.7.2 까지 머신 간 정적 sync + audit 영역은 충분히 성숙. 다음 자연스러운
확장은 **AI agent 가 anvyc 를 통해 multi-project 환경의 연결 정보에 접근하는
시나리오**. 사용자가 `cd <project>` 한 뒤 AI agent 가:

- "이 프로젝트의 AWS profile 알려줘"
- "이 프로젝트의 GitHub repo 와 사용 account 는?"
- "이 프로젝트의 Pulumi stack 이 뭐야?"
- "여러 프로젝트의 (project × aws × github × pulumi) 매핑 보여줘"

같은 질문에 자율적으로 답하려면, anvyc 가 어떤 통합 view 와 호출 인터페이스를
제공해야 하는지 검토한다.

### 1.1 사용자 환경 grounded 데이터 (2026-05-19 실측)

[improvement-plan-ux-review.md §1.1](./improvement-plan-ux-review.md) 와 동일
환경에 추가:

| 항목 | 값 |
|---|---|
| `~/Documents/` project 수 (`.cursor/` 보유) | 46개 |
| Pulumi project (`Pulumi.yaml` 보유) | 미측정 — 별도 audit 필요 |
| GitHub remote 다양성 | `16bitdo` + `secondary` 2 owner |
| Claude Code 사용 | anvyc 자체 개발에 사용 중 (`.claude/`, `CLAUDE.md`) |
| Cursor IDE 사용 | active, 46 project 의 rules/skills/mcp.json 보유 |
| 1Password CLI (op://) | 단일 계정 |

→ AI agent (Claude Code / Cursor IDE) 가 이미 사용자의 일상 도구. anvyc 가
agent-friendly 인터페이스를 제공하면 직접 호출 가능.

---

## 2. 비교 대상 / scope 경계

### 2.1 anvyc 가 해야 할 영역

| 영역 | 이유 |
|---|---|
| **정적 connection 정보 노출** (cwd → AWS profile / GitHub repo / Pulumi stack) | 각 도구의 config 파일 location 을 anvyc 가 이미 안다 (adapter) |
| **integration view** (project × tools join) | anvyc 의 doctor check 들이 이미 단편적으로 cover, 통합만 부재 |
| **machine-readable output** | 외부 도구/agent 가 stdout parse 안 하고 JSON 직접 활용 |
| **MCP server / tool definition** | AI agent (Claude Code MCP, Cursor) 표준 인터페이스 |

### 2.2 anvyc 가 안 해야 할 영역 (다른 도구의 영역)

| 영역 | 표준 답 |
|---|---|
| runtime credential 발급 | aws-vault, op (1Password) |
| live PR / issue 상태 조회 | gh CLI |
| Pulumi stack live state 조회 | pulumi CLI |
| Git operations | git CLI |
| Cloud resource live state | aws/pulumi CLI |

→ anvyc 는 **정적 매핑 + 검증 + machine-readable view** 에 집중.

---

## 3. 기능 gap 매트릭스

| 영역 | 현재 anvyc (v0.7.2) | AI agent 가 필요한 것 |
|---|---|---|
| cwd → AWS profile | ✓ (project-aws-profile-mapping check, 전체 dump) | ⚠ 단일 cwd 단축 명령 부재 |
| cwd → GitHub remote | ✗ | ✗ `.git/config remote.origin.url` 분석 필요 |
| cwd → Pulumi stack | ✗ | ✗ `Pulumi.yaml` + `Pulumi.<stack>.yaml` 추적 필요 |
| cwd → dev_env 변수 (NODE_ENV/DATABASE_URL) | ⚠ (AWS_PROFILE 만) | ✗ 전 export 추적 필요 |
| cwd → 통합 JSON | ✗ | ✗ `anvyc project show --json` 같은 명령 |
| cross-project matrix | ✗ | ✗ `anvyc project list --json` |
| project connection 정합성 검증 | ⚠ (AWS 영역만, doctor 분산) | ✗ `anvyc project doctor` 통합 |
| machine-readable (다른 명령) | doctor + scan-secrets 만 | ⚠ tools list / config show / project show 도 |
| MCP server / tool def | ✗ | ✗ Claude Code MCP, Cursor 표준 호출 |
| shell prompt 통합 | ✗ | LOW (UX, AI agent 와 무관) |

---

## 4. 시나리오별 평가

### 4.1 시나리오 1 — "이 프로젝트의 AWS profile?"

**현 anvyc**: ⚠ (간접)
```bash
anvyc doctor --only project-aws-profile-mapping --json | jq '.results[] | select(.location | startswith("'$(pwd)'"))'
```

**개선 후 (P1)**: 
```bash
anvyc project show --json | jq .aws_profile
```

### 4.2 시나리오 2 — "이 프로젝트의 GitHub repo + account?"

**현 anvyc**: ✗ (직접 `git remote get-url` 필요)

**개선 후 (P4)**: P1 의 JSON 에 `github: {remote, owner, repo, ssh_alias}` 포함

### 4.3 시나리오 3 — "이 프로젝트의 Pulumi stack?"

**현 anvyc**: ✗ (pulumi adapter 는 global `~/.pulumi/config.json` 만 추적)

**개선 후 (P3)**: project-level `Pulumi.yaml` + `Pulumi.<stack>.yaml` 추적,
P1 의 JSON 에 `pulumi: {project_name, stacks}` 포함

### 4.4 시나리오 4 — "여러 project 의 connection 매트릭스"

**현 anvyc**: ✗

**개선 후 (P2)**:
```bash
anvyc project list --json
# → [{path, aws_profile, github: {...}, pulumi: {...}, dev_env: {...}}, ...]
```

### 4.5 시나리오 5 — "AI agent 가 anvyc 직접 호출"

**현 anvyc**: ⚠ (CLI 만, subprocess + stdout parse 필요)

**개선 후 (P6 MCP server)**: Claude Code 의 MCP tool 또는 Cursor 의 tool
definition 으로 직접 호출 가능. 예시:
```yaml
# Claude Code .mcp/anvyc.json
tools:
  - name: anvyc_project_show
    description: "현재 project 의 모든 connection 정보"
  - name: anvyc_project_doctor
    description: "현재 project 의 connection 정합성 검증"
```

---

## 5. 개선 후보 (9 항목)

| # | 항목 | 영역 | 가치 | 비용 | 시기 |
|---|---|---|---|---|---|
| **P1** | `anvyc project show [--cwd\|--path P] [--json]` — 단일 project 통합 JSON | core | **HIGH** | 2h | v0.7.x |
| **P2** | `anvyc project list --json` — 전 project matrix | core | **HIGH** | 1.5h | v0.8.x |
| **P3** | Pulumi project adapter — `Pulumi.yaml` + `Pulumi.<stack>.yaml` 추적 | adapter | **HIGH** | 2h | v0.7.x |
| **P4** | GitHub remote analyzer — `.git/config remote.origin.url` → owner/repo + ssh alias 매핑 | core | **HIGH** | 1.5h | v0.7.x |
| **P5** | `anvyc tools list --json` / `anvyc config show --json` | UX | MEDIUM | 30m | v0.7.x |
| **P6** | MCP server (`anvyc serve --mcp`) — Claude Code / Cursor 호출 가능 tool export | integration | **HIGH** | 3h | v0.9.x |
| **P7** | `anvyc project doctor` — cwd connection 정합성 검증 | doctor | MEDIUM | 1.5h | v0.8.x |
| **P8** | `dev_env` adapter 의 전 export 변수 추적 확장 (AWS_PROFILE 외) | adapter | LOW | 1h | v0.9.x |
| **P9** | shell prompt 통합 (starship.toml + powerlevel10k 세그먼트) | UX | LOW | 1.5h | v0.9.x |

---

## 6. 우선순위 (확정)

| 우선순위 | 항목 | 영역 | 시기 |
|---|---|---|---|
| **HIGH** | **P1**: `anvyc project show` | core | v0.7.x |
| **HIGH** | **P3**: Pulumi project adapter | adapter | v0.7.x |
| **HIGH** | **P4**: GitHub remote analyzer | core | v0.7.x |
| **HIGH** | **P6**: MCP server | integration | v0.9.x |
| MEDIUM | **P2**: `anvyc project list` | core | v0.8.x |
| MEDIUM | **P5**: tools list / config show JSON | UX | v0.7.x |
| MEDIUM | **P7**: `anvyc project doctor` | doctor | v0.8.x |
| LOW | **P8**: dev_env 변수 확장 | adapter | v0.9.x |
| LOW | **P9**: shell prompt 통합 | UX | v0.9.x |

---

## 7. Wave 분배

### 7.1 Wave 7 — v0.7.3 → v0.8.0 — Project-Centric View (~6h)

**테마**: AI agent 가 cwd 의 모든 connection 정보를 1개 명령으로 받기.

```
P3   Pulumi project adapter                              2h
P4   GitHub remote analyzer                              1.5h
P1   anvyc project show (위 둘 + dev_env + aws 통합)     2h
P5   tools list / config show --json                     30m
```

P1 이 P3 + P4 의 통합 view 이므로 마지막에 진행. P5 는 deliverable 일관성 정리.

### 7.2 Wave 8 — v0.8.1 — Cross-Project + Audit (~3h)

```
P2   anvyc project list --json (matrix)                  1.5h
P7   anvyc project doctor (cwd 정합성)                   1.5h
```

P1 의 single-project view 가 fan-out 한 형태.

### 7.3 Wave 9 — v0.9.0 — AI Agent Integration (~5.5h)

```
P6   MCP server (anvyc serve --mcp)                      3h
P8   dev_env adapter 확장 (전 export 추적)               1h
P9   shell prompt 통합                                    1.5h
```

P6 가 핵심. P8/P9 는 UX 보강.

### 7.4 v1.0 (별도)

- PyPI 배포 (ux-review.md §8.4 의 I4)
- API stable (project show 의 JSON schema 정식화)
- documentation (CLI reference + MCP tool 명세)

---

## 8. 사용자에게 가장 맞는 권장 흐름 (예상)

```text
1. anvyc 가 정적 sync + audit 의 단일 source-of-truth
2. AI agent 는 anvyc 의 JSON output 또는 MCP tool 로 호출
3. 사용자 패턴:

   cd ~/Documents/my-project
   anvyc project show --json    # cwd 의 모든 connection
   → {
       "path": "/Users/.../my-project",
       "aws_profile": "company-dev",     # .envrc 에서
       "github": {
         "remote": "git@github.com-16bitdo:16bitdo/my-project.git",
         "owner": "16bitdo",
         "ssh_alias": "github.com-16bitdo"
       },
       "pulumi": {
         "project": "my-project",
         "stacks": ["dev", "prd"]
       },
       "dev_env": {
         "AWS_PROFILE": "company-dev",
         "NODE_ENV": "development"
       }
     }

4. AI agent (Claude Code MCP) 가 직접 호출:
   tool: anvyc_project_show
   args: { path: "." }
   → 위 JSON 반환

5. AI agent 가 작업 전 정합성 검증:
   tool: anvyc_project_doctor
   args: { path: "." }
   → {
       "aws_profile_defined": true,
       "github_remote_reachable": true,
       "pulumi_stack_exists": true,
       ...
     }
```

---

## 9. 핵심 인사이트

1. **anvyc 의 강점은 "정적 매핑 + 검증 단일 source"** — AI agent 가 이걸 직접
   호출하면 stdlib subprocess parse 없이 일관된 답 받음.
2. **cwd-aware 단일 명령이 가장 큰 가치 잠금 해제** — P1 만 있으면 시나리오
   1~3 모두 해소. P3+P4 는 P1 의 source 데이터를 채우는 backbone.
3. **MCP 는 AI agent 통합의 표준 인터페이스** — Claude Code / Cursor 모두 채택.
   P6 가 핵심 differentiator.
4. **Pulumi/GitHub project-level 추적은 anvyc 의 자연스러운 확장** — 이미
   adapter 추상화가 있어서 사용자 시점 변경 최소.
5. **scope 경계 명확**: anvyc 는 정적 매핑 + 검증, runtime credential 발급은
   여전히 1Password / aws-vault 의 영역.

---

## 10. 참고 자료

- [improvement-plan-ux-review.md](./improvement-plan-ux-review.md) — 자매 문서
  (설치/다중계정/설정 편의성)
- Claude Code MCP 명세: <https://docs.anthropic.com/en/docs/build-with-claude/claude-code/mcp>
- Cursor MCP support: <https://docs.cursor.com/context/model-context-protocol>
- Pulumi project structure: <https://www.pulumi.com/docs/concepts/projects/>
- chezmoi (참고 — AI agent integration 없음): <https://chezmoi.io/>

---

## 11. 본 문서 활용

- Wave 7~9 작업: §7 분배 표 기준으로 sub-plan 수립
- 변경 시: §5 후보 표 + §6 우선순위 표 + §7 분배 표 동기화
- 자매 문서 (`improvement-plan-ux-review.md`) 와 영역 분리:
  - ux-review: 설치 / 다중계정 (사용자 시점) / 설정 편의성
  - ai-agent (본 문서): cwd → connection / cross-project view / MCP / machine-readable

---

## 12. 결정 사항 (확정 후 채움)

| # | 항목 | 결정 |
|---|---|---|
| Q1 | Wave 7 진행 여부 | ✓ 진행 완료 (v0.8.0 tag) |
| Q2 | Wave 9 P6 (MCP server) 의 우선순위 | ✓ HIGH, 완료 (v0.9.0 tag) |
| Q3 | P1 의 output schema 정식화 시점 | ✓ v0.8.0 즉시 (DESIGN.md §32) |
| Q4 | shell prompt 통합 (P9) 의 scope | TBD — v0.9.x micro-release 또는 보류 |
| Q5 | anvyc 가 직접 처리할 dev_env 변수 범위 (P8) | ✓ 모든 export (D9 적용, Wave 7 미리 반영) |
| D11 | dev_env 의 secret 처리 (Wave 7 추가 결정) | ✓ D11c — PATTERNS 매칭 시 자동 ***REDACTED***, op:// 면제 |
| D20 | MCP 의존 격리 (Wave 9 결정) | ✓ `[mcp]` optional extra (Homebrew 영향 없음) |
| D21 | MCP 노출 tool 영역 | ✓ read-only 5종 (backup/apply/restore 제외) |
| D22 | MCP transport | ✓ stdio (Claude Code / Cursor 표준) |

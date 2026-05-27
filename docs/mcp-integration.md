# anvyc MCP integration (v0.9.0+)

> AI agent (Claude Code / Cursor / 다른 MCP 호환 client) 가 anvyc 의 8
> read-only tool 을 stdio Model Context Protocol 로 직접 호출.

자매 문서:
- [improvement-plan-ai-agent.md](./archive/improvement-plan-ai-agent.md) — Wave 9 plan
- [DESIGN.md §34](../DESIGN.md) — MCP server architecture

---

## 1. 설치

MCP integration 은 anvyc core 와 분리된 **optional extra** 입니다 (D20).
core 사용자는 영향 받지 않고, AI agent 가 anvyc 를 호출하려는 경우만 추가
의존성 설치.

```bash
# uv tool (권장):
uv tool install --upgrade 'anvyc[mcp]'

# pipx 도 가능:
pipx install --force 'anvyc[mcp]'

# 또는 source 에서:
pip install --upgrade '.[mcp]'
```

확인:

```bash
anvyc serve --help        # 'serve' subcommand 보이면 OK
anvyc --version           # v0.9.0 이상
```

`anvyc[mcp]` 미설치 환경에서 `anvyc serve --mcp` 실행 시:

```
error: anvyc MCP server requires the [mcp] extra. Install: pip install 'anvyc[mcp]'
```

---

## 2. Claude Code 설정

**권장: 자동 등록 (v0.16.0+)**

```bash
# dry-run plan
anvyc mcp install --ide claude

# 실제 작성 (atomic write, 기존 다른 server 보존)
anvyc mcp install --ide claude --apply --yes

# `CLAUDE_CONFIG_DIR=~/.claude-edward` set 환경에서는 그 경로에 자동 작성.
```

명령은 `~/.claude/mcp.json` (또는 `$CLAUDE_CONFIG_DIR/mcp.json`) 의 기존
mcpServers 를 보존한 채 `anvyc` entry 만 atomic 으로 추가. 등록 상태는
`anvyc mcp status` 로 확인.

**Manual (참조) — custom wrapper path 사용 시**

전역: `~/.claude/mcp.json` (또는 `$CLAUDE_CONFIG_DIR/mcp.json`)
project-local: `<project>/.mcp.json`

```json
{
  "mcpServers": {
    "anvyc": {
      "command": "anvyc",
      "args": ["serve", "--mcp"]
    }
  }
}
```

> **중요**: mcp.json 변경 후 **Claude Code 재시작** 필요 — Cmd+Q 후 재실행
> (또는 Cmd+Shift+P → "Developer: Reload Window"). `anvyc mcp install --apply`
> 도 동일 제약 (명령 끝에 안내 echo).

Claude Code 재시작 후 8 tool 사용 가능. 호출 예 (Claude Code 안):

```
> 이 프로젝트의 AWS profile 알려줘
[Claude → project_show(path=".") → ProjectInfo JSON]
→ AWS_PROFILE=company-dev

> ~/dev 의 모든 Pulumi project 알려줘
[project_list(roots=["~/dev"]) → filter pulumi != null]
→ workspace, pulumi-cloudflare-zt, ...
```

---

## 3. Cursor 설정

Claude Code 와 동일 패턴.

```bash
# 권장 — 자동 등록 (v0.16.0+)
anvyc mcp install --ide cursor --apply --yes

# Claude / Cursor 양쪽 동시
anvyc mcp install --ide both --apply --yes
```

Manual (참조) — `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "anvyc": {
      "command": "anvyc",
      "args": ["serve", "--mcp"]
    }
  }
}
```

전역 + project-local 양쪽 모두 위 형식. Cursor 재시작 필요.

---

## 4. 노출 tool (8 read-only)

| tool name | 매핑 anvyc 명령 | 입력 | 출력 schema |
|---|---|---|---|
| `project_show` | `anvyc project show` | `{path?, reveal_secrets?}` | ProjectInfo (DESIGN §32) |
| `project_list` | `anvyc project list` | `{roots?, reveal_secrets?}` | array of ProjectInfo (DESIGN §33.1) |
| `project_doctor` | `anvyc project doctor` | `{path?}` | `{path, results}` (DESIGN §33.2) |
| `doctor` | `anvyc doctor --json` | `{only?, skip?}` | `{results}` (20 check) |
| `tools_list` | `anvyc tools list --json` | `{}` | array of `{tool, enabled, detected, files, secrets}` |
| `activity_summary` | `anvyc activity --json` | `{agent?}` | `{total_sessions, total_events, total_tool_calls, total_duration_seconds, oldest, newest, tools_used}` (CP-1, CP-7) |
| `tool_call_stats` | (MCP 전용 — CLI 미노출) | `{top?, agent?}` | `{tool_call_ranking: [{name, count}], blocked: {total_blocks, by_hook, by_agent, oldest_block_at, newest_block_at}}` (CP-1, CP-8, CP-11) |
| `cost_summary` | `anvyc cost summary --json` | `{source?, period?, refresh?}` | `{total_amount_usd, currency, by_source, by_account, by_model, pricing_versions_seen, period, report_count}` ([CP-13](./design-axes/cp-13-cost.md)) |

### 4.1 의도적 미포함 (write 영역)

- `anvyc backup` — destructive (.anvyc/backups 생성)
- `anvyc apply` — target 파일 덮어쓰기
- `anvyc restore` — local-backup 후 적용
- `anvyc scan-secrets` — file system 접근 영역

→ AI agent 가 자율적으로 destructive 행동 못 함. 사용자가 CLI 로 명시 실행.

---

## 5. 보안 정책

### 5.1 D11c redaction default

```
input:  dev_env.GITHUB_TOKEN = "ghp_xxx..."
output: dev_env.GITHUB_TOKEN = "***REDACTED***"
```

anvyc 의 `security.patterns.PATTERNS` 매칭 시 자동 마스킹. `reveal_secrets=True`
명시할 때만 raw 값 노출 (agent / log 유출 위험 — 사용자 책임).

### 5.2 op:// 1Password reference 면제

```
input:  dev_env.GITHUB_TOKEN = "op://Personal/GitHub/token"
output: dev_env.GITHUB_TOKEN = "op://Personal/GitHub/token"  (그대로)
```

`op://` 는 placeholder signal — 실 secret 아님. redaction 면제.

### 5.3 raw secret 의 메모리 영역

- `anvyc project doctor` 의 `dev_env_secret_safety` check 는 raw 값을 메모리
  에서 사용 (검증 위함)
- 결과 message 에는 KEY 명만 노출 (`raw secret: GITHUB_TOKEN`) — value 미노출
- JSON 출력의 어떤 field 에도 raw secret 미포함

### 5.4 host machine 접근 범위

- read-only: anvyc 가 이미 알고 있는 영역 (`.envrc`, `.git/config`, `Pulumi.yaml`,
  `~/.aws/config`)
- 위 영역 외 임의 file 접근 X (path 기반 read 도 PROJECT_MARKERS 안의 표준
  파일만)

---

## 6. 사용 시나리오

### 6.1 Claude Code 가 multi-project 답변

```
사용자: 어떤 project 들이 company-dev profile 을 쓰는지 알려줘.

Claude: [project_list(roots=["~/dev"]) 호출]
       [JSON 응답 받음 — 32 projects]
       [filter: aws_profile == "company-dev"]
       → 3 projects: proj-a, proj-b, proj-c
```

### 6.2 Cursor 가 정합성 자동 점검

```
사용자가 cd ~/dev/new-proj.
Cursor: [현재 file 변경 시 project_doctor(path=".") 자동 호출]
       → CRITICAL: dev_env raw secret (GITHUB_TOKEN)
       → 사용자에게 1Password 사용 권장 alert
```

### 6.3 AI agent 가 backup 권유

```
사용자: 이 프로젝트의 .envrc 가 다른 머신에 sync 되어 있는지 봐.

Claude: [project_show(path=".") → dev_env 확인]
       [doctor(only=["project-aws-profile-mapping"]) → 정의 정합성]
       → "AWS_PROFILE=ws-dev 가 ~/.aws/config 에 정의 안 됨. 다음 명령으로
          backup 후 다른 머신에서 apply 권장: anvyc backup"
       (Claude 는 backup 을 직접 실행 안 함 — 사용자 명시 실행 권장)
```

---

## 7. 트러블슈팅

### 7.1 `anvyc serve --mcp` 가 즉시 종료

stdio transport 는 input 대기. 단독 실행 (`anvyc serve --mcp` 만) 은 정상이며
Claude Code / Cursor 가 client 로 연결할 때 정상 동작. 단독 검증:

```bash
# initialize 요청을 stdin 으로 보내고 stdout 응답 확인:
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  | anvyc serve --mcp
```

### 7.2 mcp.json 변경 후 적용 안 됨

Claude Code / Cursor 재시작 필요. 또는 IDE 의 reload command (Cmd+Shift+P → Reload).

### 7.3 `anvyc[mcp]` 설치가 maturin 빌드 fail

pydantic-core (Rust extension) 가 사용자 환경의 pre-built wheel 을 못 찾는
경우. 다음 환경에서 권장:
- macOS arm64 / x86 (PyPI wheel 제공)
- Linux x86_64 / aarch64 (PyPI wheel 제공)

source build 가 필요한 환경은 `pip install maturin` 선행 후 재시도.

### 7.4 Claude Code 가 tool 호출 안 함

- `~/.claude/mcp.json` 의 JSON 문법 확인
- `which anvyc` 가 정상 path 반환 확인 (uv tool / pipx / brew)
- `anvyc serve --help` 가 정상 출력 확인

---

## 8. 한계 / Roadmap

### 8.1 현재 (v0.15.2+ / CP-13 머지 시점)

- read-only 8 tool (5 project/doctor/tools + 2 CP-1 activity + 1 CP-13 cost)
- stdio transport 만
- D11c redaction default

### 8.2 future

- SSE / HTTP transport (Cursor 의 remote MCP 지원 시점)
- write 영역 tool (`anvyc backup` / `anvyc apply --dry-run` 등 안전 영역)
- per-tool authentication (현재는 stdio 신뢰 모델)
- prompt template (MCP `prompts` capability 활용)

---

## 9. 참고

- MCP 명세: <https://modelcontextprotocol.io/>
- Python SDK: <https://github.com/modelcontextprotocol/python-sdk>
- Claude Code MCP: <https://docs.anthropic.com/en/docs/build-with-claude/claude-code/mcp>
- Cursor MCP: <https://docs.cursor.com/context/model-context-protocol>

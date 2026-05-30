# §40 CP-14 Run ledger (L4 실행 엔진 원장 흡수)

> anvyc 의 역할: **read-only 집계자**. 실행 엔진 `anvyx` (L4) 가 emit 한 run-record 를
> 읽어 통계로 노출한다. anvyc 는 run 을 *기동하지 않는다* (읽기전용 불변식 보존).
>
> control plane 설계 1차 SoT 는 role-based-ruleset:
> - ADR: `docs/adr/v8-cp14-execution-engine.md`
> - C5 스키마: `metadata/run-record-schema.yaml` (schema_version:1)

## 1) 설계 원칙
- **emit→aggregate→display** (CP-8 패턴 재사용): emit=anvyx(L4) → aggregate=anvyc(L2) → display=cci(L3, statusline).
- **read-only**: anvyc 는 run-record 를 읽기만 한다. MCP tool `run_summary` 는 읽기전용 — 기동/중단은 anvyx CLI 의 책임.
- **fail-soft**: anvyx 미설치 / runs 디렉터리 부재 / 손상 라인은 silent skip (total_runs=0).

## 2) 데이터 소스
`~/.config/anvyx/runs/<YYYY-MM-DD>.jsonl` — anvyx 가 append (chmod 600). 1 line = 1 C5 run-record.

## 3) 구성 (anvyc/core/runs.py)
- `discover_run_files(runs_dir=None) -> list[Path]` — 날짜순 jsonl 목록.
- `iter_runs(runs_dir=None, *, agent=None) -> Iterator[Run]` — 파싱+필터 (손상 skip).
- `collect_runs(...) -> list[Run]` — started_at 오름차순 리스트.
- `aggregate_runs(list[Run]) -> dict` — total_runs / by_status / by_exit_reason / by_agent / total_cost_usd / total_tokens / total_tool_calls / oldest·newest_run_started_at.
- `Run` dataclass: run_id / status / agent / model / cwd / started_at / stopped_at / duration_s / exit_reason / exit_code / tool_calls / cost_usd / tokens_total / machine_id / error.

## 4) Command contract
- CLI `anvyc runs summary [--agent] [--json]` — 통합 통계 (table / JSON).
- CLI `anvyc runs list [--limit N] [--agent] [--json]` — 최근 run 목록 (내림차순).
- MCP `run_summary({agent?})` — `aggregate_runs(collect_runs(agent=agent))`.

## 5) Out of scope (후속)
- cci statusline run 세그먼트 (display leg — 별도 PR).
- budget_usd 가격표 연동 (anvyx mid-run usd 강제 — anvyc cost pricing 재사용).
- run-record retention / 압축 / cross-machine sync (CP-6 위).

## 6) 변경 이력
- v0.18.0 (2026-05-30): 최초 — reader + aggregate + `runs summary/list` CLI + `run_summary` MCP (Phase 3 원장 흡수). anvyx#1(Phase 1 emit) 페어.

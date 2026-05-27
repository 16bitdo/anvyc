# CP-6 — Cross-Machine State Sync 설계

> Control Plane **v3 의 첫 axis**. 여러 머신 간 control plane mutable
> state (CP-4 snapshot meta + CP-3 health JSON + CP-5 creds expiry timestamp)
> 동기화. 본 문서는 DESIGN §37 의 본문 분리본.
>
> SoT 트리오는 `role-based-ruleset` 측 (ROADMAP §4 CP-6 / DESIGN §7 / manifest).

## 1. 설계 원칙

- **L12 cross-axis schema 일관성 입증 시점**: CP-3 health JSON + CP-4
  snapshot meta + CP-5 CredentialsReport 가 모두 `schema_version: 1` 이라
  sync target adapter 가 일반화 가능. 본 axis 는 L12 의 sync 단위 안정성
  가치 입증.
- **단일 schema v1 (local/remote 양쪽 동일)**: SyncTargetManifest 가 local
  filesystem scan 으로 생성되고, remote target 에 동일 format 으로 저장.
  diff 는 두 manifest 의 set 연산 + sha256 비교만으로 결정 — 단순성.
- **kind 별 adapter** (1/3 MVP): `snapshot_meta` + `health_json` 만 지원.
  creds expiry timestamp 는 live computation 이라 후속 polish.
- **Remote target = filesystem path** (1/3): local mount (NFS/SMB) / git
  clone 디렉터리 / sync 폴더 (Dropbox / iCloud / Syncthing). HTTPS/S3
  backend abstraction 은 후속 polish — 본 axis 는 backend 결정 위임.
- **단방향 read-only first** (1/3): `sync status` 만. write (push/pull) 는
  2/3 으로 분리해 schema 안정화 후 진입.
- **machine_id 명시**: 사용자 명시 (`anvyc.yaml`) > env (`ANVYC_MACHINE_ID`)
  > default `<user>@<hostname>`.

## 2. SyncTargetManifest schema v1

```json
{
  "schema_version": 1,
  "machine_id": "edward@mbp-edward",
  "generated_at": "2026-05-25T10:00:00Z",
  "items": [
    {
      "kind": "snapshot_meta" | "health_json",
      "relative_path": "anvyc/snapshots/foo-<id>/meta.json",
      "size": 512,
      "sha256": "abc123...",
      "mtime": "2026-05-25T09:30:00Z"
    },
    ...
  ]
}
```

## 3. 명령 contract (CP-6 시리즈)

| 명령 | PR | 안전 등급 | 책임 |
|---|---|---|---|
| `anvyc sync status --target <path> [--machine-id X] [--json]` | 1/3 (#44, merged) | read-only | local manifest 생성 + remote manifest 비교 → SyncStatusReport. |
| `anvyc sync push --target <path> [--force] [--yes]` | 2/3 (#45, merged) | write | local → remote mirror (per-file atomic copy + manifest atomic write). conflict 기본 skip; `--force` overwrite. |
| `anvyc sync pull --target <path> [--force] [--yes]` | 2/3 (#45, merged) | write | remote → local mirror (relative_path 역매핑). conflict 기본 skip; `--force` local overwrite. |
| `anvyc sync conflict list --target <path>` | 3/3 (#46, merged) | read-only | 현재 diff (sha256 불일치) entries 만 표시. resolve 후보 인덱스. |
| `anvyc sync conflict resolve <relative_path> --target <…> --keep local\|remote` | 3/3 (#46, merged) | **destructive** | 단일 conflict 의 명시 해결 — keep=local → remote overwrite (+ manifest 갱신); keep=remote → local overwrite. confirm prompt + atomic copy. rbr rule `27-cross-machine-sync-policy` paired. |

## 4. Diff 알고리즘 (compute_sync_status)

local + remote manifest 를 `relative_path` key 로 dict 변환 후 set 연산:
- `local & remote`: 양쪽 모두 — sha256 일치 = `same`, 불일치 = `diff`
- `local - remote`: local 만 = `local_only` (push 후보)
- `remote - local`: remote 만 = `remote_only` (pull 후보)

복잡한 trie / 부분 매칭 없음 — relative_path 정확 일치만. mtime 은 정보용
(diff 판정 안 함 — sha256 이 권위).

## 5. Source 별 scan 전략

| Kind | Source path | Relative path 형태 |
|---|---|---|
| `snapshot_meta` | `<home>/dev/*/.anvyc/snapshots/<id>/meta.json` | `anvyc/snapshots/<workspace>-<id>/meta.json` |
| `health_json` | `<home>/.config/cc-inspect/health/*.json` | `cc-inspect/health/<date>.json` |

workspace prefix (`<workspace>-<id>`) 는 cross-workspace collision 회피.

## 6. Remote target layout

```
<remote_target>/
├── anvyc-sync-manifest.json    # 단일 machine 의 manifest (1/3 MVP)
├── anvyc/snapshots/<workspace>-<id>/meta.json
└── cc-inspect/health/<date>.json
```

**1/3 MVP 는 단일 machine 기준** — 다중 machine 통합 (예: `<remote>/<machine_id>/...`)
은 2/3 polish.

## 7. Out of scope (CP-6 axis 완결 기준)

- creds expiry timestamp sync (live computation — 후속 polish)
- HTTPS / S3 / git remote backend abstraction (현재는 filesystem path 만)
- 다중 machine_id 통합 (현재는 단일 remote 기준)
- token / secret 본문 sync (rule 26·27 위반 — 의도적 영구 제외)
- destructive deletion sync (push/pull/resolve 모두 삭제 안 함 — explicit cleanup 후속)
- **auto-policy / 3-way merge** (`--policy newer|machine-X`) — rule 27 명시 — 사용자 prompt 우선 (의도적 영구 제외)
- `--dry-run` flag (CLI 가 항상 plan 먼저 출력 + confirm prompt — 별 flag 불요)

## 8. 보안 경계

- sync 대상은 **content hash + 메타** 만 manifest 에 노출. 본문은 별 파일
  로 remote 에 저장 (path 기반).
- **token / secret 본문 sync 금지** — creds.json 같은 자격 본문은 sync
  대상 외 (rule 26-secrets-1password 준수).
- snapshot meta 의 `claude_session_id` 는 식별자라 본문 아님 — sync 안전.
- remote_target 은 사용자 책임 — Dropbox 같은 cloud sync 는 cloud 운영사
  policy 준수.

## 9. Push/Pull 안전 절차 ([CP-4 §7](./cp-04-snapshot.md) 패턴 미러)

push/pull 은 file write — snapshot restore 의 4-layer safety 미러.

1. **dry-run plan**: CLI 가 status entries 출력 (will_copy / will_skip_conflict
   카운트 + warning). plan 만 보고 종료 가능.
2. **confirm prompt**: `--yes` / `-y` 없으면 사용자 응답 요구.
3. **per-file atomic copy**: `tempfile.mkstemp` (dst.parent 와 동일
   filesystem) + chunked write + `os.replace`. partial write 시 cleanup.
4. **manifest atomic write** (push 만): 같은 tempfile + replace 패턴.

회복 채널:
- push 가 일부 file 실패 → `failed_paths` 에 기록. manifest 는 성공한
  entries 만 반영. 재실행 시 same/local_only 분류로 자연 재시도.
- pull 이 일부 file 실패 → 동일. local 측은 partial state 가능 — 재실행
  으로 보완.
- conflict (sha256 불일치) — 기본 skip + count, 사용자 결정으로 `--force`
  재실행 가능. 3/3 의 conflict resolution 이 정형화 도구.

**push/pull 모두 destructive deletion 금지** — remote-only / local-only
items 는 반대 방향 작업에서 자동 보존. 명시적 cleanup 명령은 후속 polish.

## 10. Conflict Resolution 정책 (rbr rule 27 paired)

push/pull 의 conflict 기본 skip + `--force` overwrite 만으로 부족한 시나리오:
**entry 별 명시 결정** 이 필요할 때. CP-6 3/3 의 `sync conflict {list,resolve}`
명령이 도구. 정책 본문은 `role-based-ruleset/common/rules/27-cross-machine-sync-policy`
에 명문화 (paired secondary).

### 10.1 정책 원칙

1. **자동 merge 영구 금지** — auto-policy (mtime / machine-X-우선 / etc.)
   는 본 axis 영구 out-of-scope. 사용자 prompt 가 권위.
2. **token / secret 본문 sync 영구 금지** — rule 26·27 동시 적용. sync
   대상은 metadata + non-secret content 만.
3. **entry 별 keep 선택**: `--keep local` (local→remote overwrite,
   manifest 갱신) | `--keep remote` (remote→local overwrite, local
   manifest 없음).
4. **dry-run + confirm prompt** — destructive operation 4-layer safety
   (L14) 준수. `--yes` 자동 수락 옵션.
5. **회복 채널** — resolve 가 잘못된 keep 선택했어도 반대 keep 으로 다시
   resolve 가능 (sync 는 idempotent). snapshot/restore ([CP-4 §7](./cp-04-snapshot.md))
   의 auto pre-restore 와 동등한 회복 단순성.

### 10.2 `sync conflict list` 출력 schema (인덱스용)

각 entry 는 1/3 의 `SyncDiffEntry` (relative_path / status=diff / local /
remote) 그대로. JSON 모드는 `[{relative_path, status, local: SyncItem,
remote: SyncItem}, ...]`.

### 10.3 `sync conflict resolve` 분기

| keep | 동작 | manifest |
|---|---|---|
| `local` | `local_source → remote_target/<rel>` atomic copy | remote manifest 의 해당 entry 만 local SyncItem 으로 교체 + atomic write |
| `remote` | `remote_target/<rel> → local_dst` atomic copy (역매핑) | local 측 manifest 없음 (anvyc 는 local manifest 저장 안 함) |

### 10.4 회복 시나리오

- resolve 실수로 잘못된 keep 선택 → 반대 keep 으로 다시 resolve. sync 자체
  가 idempotent — 두 머신 본문이 다른 한쪽으로 통일됨.
- resolve 중 copy 실패 → `SyncError` raise + 사용자 수동 점검.
- resolve 후 sync status 가 다시 `diff` 일 수 있음 (다른 머신이 동시 변경)
  → 정상 동작, 재실행으로 수렴.

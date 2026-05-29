# CP-15 — Secret Broker 설계

> 사용 편의성을 높이면서 **"anvyc 는 secret 평문을 보유하지 않는다"** 불변식을
> 유지하는 secret 관리 axis. 값 custody 는 외부 도구(op / sops / keychain /
> aws-vault)에 두고, anvyc 는 **레퍼런스 레지스트리 + 디스패처 + 검증 + 와이어링**
> 만 담당한다. §30(1Password Secret Reference)·§31(SOPS)·CP-5(creds) 의 확장이며,
> DESIGN §39 의 본문 분리본.

## 1. 설계 원칙

- **Broker, not Vault**: anvyc 는 "정적 설정 동기화 + 검증 + 권장 워크플로 가이드"
  역할이고 credential 자체 관리는 외부 도구가 한다 — 이미 명문화된 도구 경계
  ([docs/multi-account.md §1.4](../multi-account.md))를 secret 입력/조회까지 확장
  적용한다. anvyc 는 vault 가 아니라 broker.
- **No-plaintext-in-anvyc 불변식 유지**: 값 입력은 backend 의 네이티브 보안 입력
  (op TTY/biometric, sops `$EDITOR` 보호 버퍼, keychain/aws-vault 자체 프롬프트)을
  호출하고 anvyc 프로세스는 평문을 **메모리에도 보유하지 않는다**. → Phase 1·2 는
  `rule 26-secrets-1password` / `SECURITY.md` 위협모델을 **무수정**으로 만족한다.
  passthrough(Phase 3)만 예외이며 거버넌스 PR 선행을 강제한다(§8).
- **Reference Registry**: `anvyc.yaml` 에는 값이 아니라 **핸들(reference)** 만
  등록한다 → backup/git commit 안전(§30 의 `op://` 비-secret 속성을 모든 backend
  로 일반화). 레지스트리 유출은 secret 유출이 아니다.
- **Schema 우선 안정화** (CP-4/5 의 학습 L7 적용): `secrets:` 레지스트리
  `schema_version: 1` 을 1/N 머지 시점에 확정 → 이후 모든 backend / doctor /
  inject-wire 가 동일 schema 를 입력 contract 로 가정한다.
- **저장보다 주입(JIT)**: 회수 가능한 평문 사본을 만들지 않는 것이 가장 안전한
  UX — `.envrc`(dev_env 어댑터) / `op run` / `aws-vault exec` 로 실행 시점 주입을
  우선하고 `secret get` 은 보조 수단으로 둔다.

## 2. Secret Registry schema v1

`anvyc.yaml` 의 신규 `secrets:` 블록. **값은 없고 핸들만** 담는다.

```yaml
secrets:
  schema_version: 1
  get:
    default_sink: clipboard        # clipboard | reveal(거부 가능) — 기본 무출력
    clipboard_clear_seconds: 20
  entries:
    - name: AWS_ACCESS_KEY_ID
      backend: op
      ref: "op://Personal/AWS/access_key_id"
      wire: { target: "~/.zshrc", style: "op-read" }   # 선택 — JIT 주입 와이어링
    - name: pulumi/passphrase
      backend: sops
      file: "~/.pulumi/creds.json"
      key: "passphrase"            # inplace 모드의 dotted key (binary 모드는 생략)
    - name: DB_PW
      backend: keychain
      service: "anvyc"
      account: "db"
    - name: aws/prd
      backend: aws-vault
      profile: "my-prd"
```

| key | 의미 |
|---|---|
| `name` | 디스패처/사용자용 논리 이름 (레지스트리 내 고유) |
| `backend` | `op` \| `sops` \| `keychain` \| `aws-vault` |
| `ref` / `file`+`key` / `service`+`account` / `profile` | backend 별 핸들 — **값이 아님** |
| `wire` | (선택) JIT 주입 대상 + 스타일. 없으면 와이어링 미수행 |
| `get.*` | 조회 sink 기본값(§5) |

### 2.1 확장 호환 규칙 (CP-13 §2.1 동일)

- 미지의 `backend` / 미지의 key 는 **graceful skip + doctor INFO** — hard error
  금지. 신규 backend 추가는 minor 호환.
- `schema_version` 상향은 reader 가 하위 호환 유지(미지 필드 무시).

## 3. SecretBackend Protocol + 어댑터 lifecycle

`adapters/` 패턴을 재사용한다. 각 backend 는 **값을 반환하지 않는** 연산만 노출한다.

```python
class SecretBackend(Protocol):
    name: str
    def add(self, entry: SecretEntry, *, dry_run: bool) -> AddResult: ...
        # backend 네이티브 입력(op/sops/keychain/aws-vault 자체 프롬프트) 호출 →
        # 결과 "핸들"만 회수. 값은 anvyc 로 돌아오지 않는다.
    def reference(self, entry: SecretEntry) -> str: ...
        # 와이어링/표시용 비-secret 표현 (예: "op://...", "sops:<file>#<key>")
    def resolve_cmd(self, entry: SecretEntry) -> list[str]: ...
        # 주입/조회용 외부 명령. 값은 이 명령의 stdout 으로만 흐르고
        # anvyc 는 캡처/로깅하지 않는다 (sink 으로 직접 pipe).
    def verify(self, entry: SecretEntry) -> CheckResult: ...
        # doctor 용 — 핸들이 resolve 가능한지 (값 미노출).
    def supports_passthrough(self) -> bool: ...   # Phase 3 게이팅
```

| backend | add (입력 위임) | reference | resolve_cmd | verify (재사용) |
|---|---|---|---|---|
| `op` | `--generate`→`op item create --generate-password` (op이 난수 생성) / `--ref` 기존 item 등록 | `op://v/i/f` | `op read --no-newline <ref>` | `op-references-valid` (`checks/op_references.py`) |
| `sops` | `sops edit <file>` (`$EDITOR` 보호 버퍼) | `sops:<file>#<key>` | `sops -d --extract '["<key>"]' <file>` | `sops-keys-available` (`checks/sops_keys.py`) |
| `keychain` | `security add-generic-password`(stdin) / `keyring` | `keychain:<service>/<account>` | `security find-generic-password -w` (biometric) | 항목 존재 확인 |
| `aws-vault` | `aws-vault add <profile>` (자체 프롬프트) | `aws-vault:<profile>` | `aws-vault exec <profile> -- …` | `project-aws-profile-mapping` (`~/.aws/config` 정합) |

> 구현 메모: `op read` 의 stdout 폐기 패턴은 `checks/op_references.py:50-52` 에 이미
> 존재 — `resolve_cmd` 의 "값 비캡처" 계약과 동일 정신.

### 3.1 Phase 2 add / get 위임 메커니즘 (확정 2026-05-29)

**불변식 유지**: Phase 2 는 anvyc 가 secret 값을 메모리·argv·temp 어디에도 보유하지
않는다. 값 입력은 backend 네이티브 경로에 위임하며, **기존 값의 직접 타이핑
(hidden-input)은 Phase 2 범위 밖 — Phase 3(passthrough)** 이다. (op 의 assignment
statement 는 argv 노출, JSON 템플릿 stdin 은 anvyc 가 값 구성 → 둘 다 불변식 위반이라
Phase 2 에서 금지.)

#### add — `anvyc secret add <name> --backend <b> [핸들옵션] [--wire <dotfile>] [--apply]`

| backend | Phase 2 입력 위임 | anvyc 가 하는 일 (값 미접촉) |
|---|---|---|
| `op` | `--generate` → `op item create --generate-password`(op이 난수 생성·저장) / `--ref op://…` (기존 item) | 결과 `op://` reference 등록 + `op read` exit code 검증 |
| `sops` | `sops edit <file>` (`$EDITOR` 보호 버퍼 — sops가 암복호화, 값은 sops tmpfs 에만) | 편집 종료 후 `file`(+`key`) 등록 + SOPS metadata 검증 |
| `keychain` / `aws-vault` | Phase 2.5 (`security add-generic-password` 대화형 / `aws-vault add` 자체 프롬프트) | — (2.5) |

- **dry-run 기본**: plan(실행될 backend 명령 + 등록될 entry) 출력 후 종료. `--apply` 로 실행.
- 성공 시 `anvyc.yaml secrets.entries` 에 entry 추가 → `secret-registry-valid` 1회 자동 검증.
  anvyc.yaml 수정 전 local-backup (CP-4 §7 패턴).
- `--wire <dotfile>` 는 reference 를 dotfile 에 삽입(최소 형태). 스타일/.envrc 본격 주입은 `inject-wire`(Phase 2.5).

#### get — `anvyc secret get <name> [--reveal]`

- 기본 sink = **클립보드 + 자동 만료**: backend resolve 명령 stdout → `pbcopy` stdin **직접 파이프**
  (anvyc Python 은 값 미캡처/미문자열화). `secrets.get.clipboard_clear_seconds`(기본 20) 후 클립보드를
  빈 값으로 덮어 누출 최소화.
- **비-TTY(파이프/CI) → 거부** (`secret get | cat` 같은 캡처 차단). `--reveal` 은 TTY 한정 opt-in + 경고.
- resolve 명령: op `op read --no-newline op://…` / sops `sops -d --extract '["<key>"]' <file>`(inplace)·`sops -d <file>`(binary).
  keychain/aws-vault 는 Phase 2.5. pbcopy 부재(Linux) → `--reveal` 안내 + 거부(xclip/wl-copy 탐지는 polish).
- 접근 감사: `core/audit_log.py` redacted-event 재사용 — `name`+`ts` 만 (§5).

## 4. 명령 contract (CP-15 시리즈)

| 명령 | PR | 안전 등급 | 책임 |
|---|---|---|---|
| `anvyc secret list [--json]` | Phase 1 ✓ | read-only | 레지스트리 entry + 각 backend `verify()` 상태(`ok`/`expiring`/`unresolved`). **값 미출력.** |
| doctor `secret-registry-valid` | Phase 1 ✓ | read-only | 모든 entry `verify()` 묶음. unresolved→WARNING, 미지 backend→INFO. CP-3 scheduler 자연 포함. |
| `anvyc secret add <name> --backend <b> [--generate\|--ref\|--file] [--wire <dotfile>] [--apply]` | **Phase 2** | write (비-secret) | op: `--generate`/`--ref`, sops: `sops edit` 위임 → 핸들 등록. **값 미접촉**, dry-run 기본, local-backup 안전망. §3.1. |
| `anvyc secret get <name> [--reveal]` | **Phase 2** | read (게이팅) | 기본 클립보드(tool→pbcopy 직접 파이프)+자동 만료, stdout 미출력, 비-TTY 거부. `--reveal` TTY opt-in. §3.1/§5. |
| `anvyc secret inject-wire --target <.envrc> --name <name>` | Phase 2.5 | write (비-secret) | JIT 주입 구문 생성(dev_env 연계). reference 만 기록, 값 아님. keychain/aws-vault backend 동반. |
| `anvyc secret add … --passthrough` | N/N | **destructive 경계** | getpass→stdin 무보관 스트림. **거버넌스 PR 선행** + opt-in 플래그 + 런타임 경고(§8). |

각 `add` 는 §2 schema 의 entry 한 건을 추가/갱신하며, 성공 직후 `secret-registry-valid`
를 1회 자동 실행해 와이어링 오타를 즉시 검출한다.

## 5. 조회(get) 보안 설계

현행 anvyc 전반의 "secret 본문 미출력"(creds status / scanner / `RotateResult`
2KiB tail) 철학을 깨지 않는다.

- **기본 무출력**: 클립보드 복사 + `clipboard_clear_seconds` 후 자동 클리어. stdout
  에 평문을 찍지 않는다.
- **`--reveal`**: 명시 opt-in + 경고, **TTY 일 때만** 허용. 파이프/CI(비-TTY)면 거부.
- **biometric 게이팅**: op / keychain 경유 시 OS 인증(Touch ID 등)이 자연 게이트.
- **값 비캡처**: `resolve_cmd` 의 stdout 은 sink(클립보드 헬퍼)로 직접 pipe — anvyc
  가 Python 문자열로 보유/로깅하지 않는다.
- **접근 감사**: 값이 아니라 **접근 이벤트**만 기록한다. `core/audit_log.py` 의
  redacted-event 패턴(`command_redacted` 필드) 재사용 — `name` + `ts` 만 남기고
  인자는 redaction(타이밍/빈도 추론 채널 최소화).

## 6. doctor check 등록

- **`secret-registry-valid`** (신규): 각 entry 에 backend `verify()` 위임 —
  내부적으로 `op-references-valid` / `sops-keys-available` / `project-aws-profile-mapping`
  를 backend 별로 호출한다. unresolved/expired→WARNING, 미지 backend→INFO,
  도구 미설치/미인증→silent skip(사용자 환경 의존).
- 기존 **`mcp-tokens-warn`** 와 정합: raw token 발견 시 "secrets registry 에 등록
  + reference 치환" 으로 유도하는 suggestion 으로 확장.

## 7. Cross-axis 시너지

- **CP-5 creds**: `aws-vault` / `op` 회전을 `creds rotate` 의 native re-auth 위임
  패턴과 통합 — 회전 후 `secret-registry-valid` 재검증.
- **dev_env(.envrc)**: `inject-wire` 가 `.envrc` 추적 어댑터(`adapters/dev_env.py`)와
  직결 — 주입 구문 변경이 backup/diff 안전망에 자동 포함.
- **backup / sync**: 레지스트리는 핸들만 보유 → 기존 secret scan / `op://` 강등 /
  SOPS skip 규칙(`security/scanner.py`)이 그대로 적용. 신규 평문 노출면 없음.
- **CP-8 audit**: `get` 접근 이벤트를 audit jsonl 소비자가 함께 노출.

## 8. 보안 경계

- **Phase 1·2 (불변식 유지)**: `add` 는 backend 프롬프트 위임, `get` 은 게이팅,
  registry 는 값 미보유 → anvyc 평문 미접촉. `rule 26` / `SECURITY.md` **무수정**.
- **argv 금지**: 값을 명령 인자로 넘기는 backend 호출(`op item create k=v`,
  `sops --set '["k"]' '"v"'`, `security add-generic-password -w <pw>`)은 `ps`/`/proc`
  노출이므로 **금지** — stdin/네이티브 입력만 허용한다.
- **Phase 3 passthrough(opt-in)**: getpass→subprocess stdin 무보관 스트림.
  도입 전 **5원칙 강제**가 게이트다 —
  1. getpass(TTY 확인) → subprocess stdin 직결, argv·env·temp 미경유.
  2. 값은 단일 지역변수 + 사용 직후 `del`(가능하면 `bytearray` wipe).
  3. sops 경로는 tmpfs(0600) + secure-unlink, 디스크 평문 금지.
  4. 비대화형(CI) 차단 — op/sops/aws-vault 직접 사용 권장.
  5. no-stdout / no-logging — 예외 traceback 에 값이 섞이지 않도록 마스킹.
  + `rule 26` / `SECURITY.md` 위협모델을 **"no-at-rest-in-anvyc(입력 순간만 통과)"**
  로 재정의하는 **거버넌스 PR 선행**. 기본 비활성.

## 9. 실행 계획 (Phase)

| Phase | 범위 | 거버넌스 | 비고 |
|---|---|---|---|
| **Phase 1** | Registry schema v1 + `secret list` + `secret-registry-valid` doctor | 불요 | ✅ **구현됨** — 읽기 전용 (`core/secrets.py` + `checks/secret_registry.py`) |
| **Phase 2** | Broker `secret add`(op/sops 네이티브 입력 위임) + `secret get` 게이팅 | 불요 | ✅ **구현됨** — `core/secrets.py`(plan_add/register_entry/resolve_command) + CLI add/get. 값 미접촉 |
| **Phase 2.5a** | `keychain` / `aws-vault` backend (add/get) | 불요 | ✅ **구현됨** — keychain `security`(hidden 프롬프트/`-w` get), aws-vault `add`(get 은 exec 안내). 값 미접촉 |
| **Phase 2.5b** | `inject-wire`(dev_env/.envrc JIT 주입) | 불요 | ⬜ 예정 — `export X="$(resolve)"` / aws-vault exec 래퍼. at-rest 평문 0 |
| **Phase 3** | `--passthrough` 모드 | **필요** | rule 26 / SECURITY 재정의 PR + 누출 회귀 테스트 통과 후에만 |

권장 진행 순서: **Phase 1 → 2 → 2.5**(불변식 무수정 구간에서 최대 UX 확보) 후,
필요성이 입증되면 거버넌스 게이트를 거쳐 Phase 3.

## 10. Out of scope (CP-15 axis 완결 기준)

- anvyc 자체 secret store/vault 구현 — Broker 원칙상 **의도적 제외**.
- 비대화형(CI) hidden input — op/sops/aws-vault 직접 사용 권장.
- 자동 회전 자동화 — CP-5 creds 담당, 본 axis 는 연계만.
- HSM / Cloud KMS(AWS KMS, GCP KMS) backend — 후속 polish.
- secret 값 자체의 backup — 보안 위험이라 제외(§30/§31 정책 유지, 레지스트리는
  핸들만).

## 11. 변경 이력

| 버전 | 변경 |
|---|---|
| draft 2026-05-29 | CP-15 axis 신설 — Broker 패턴 + Registry schema v1 + SecretBackend protocol(4 backend) + 명령 contract + phased 실행 계획. DESIGN §39 등재. |
| fix 2026-05-29 | axis 번호 CP-14 → **CP-15** 재배정. CP-14 는 rbr `metadata/control-plane-roadmap.yaml` / `docs/control-plane-v7-l4-execution-engine.md` §10 에서 "실행 엔진(L4 autopilot executor)" 축으로 선예약됨 — 충돌 회피. rbr ROADMAP §4 + manifest 정식 등록 동반. |
| feat 2026-05-29 | **Phase 1 구현** — `secrets:` Registry schema v1(`core/config.py`) + `core/secrets.py`(SecretBackend verify, 값 미캡처) + `anvyc secret list [--json] [--no-probe]` + `secret-registry-valid` doctor check + `examples/anvyc.yaml` 샘플 + unit tests(16건). read-only, 불변식 무수정. (anvyc#113) |
| design 2026-05-29 | **Phase 2 설계 확정** (§3.1) — add: op `--generate`/`--ref` + sops `sops edit`($EDITOR) 위임(값 미접촉, hidden-input 은 Phase 3) / get: 클립보드(tool→pbcopy 직접 파이프)+자동 만료, `--reveal` TTY-only, 비-TTY 거부. op CLI 2.34 / sops 3.13 실측 기반. |
| feat 2026-05-29 | **Phase 2 구현** — `core/secrets.py`(plan_add/execute_add[stdio 상속]/register_entry[.bak]/resolve_command) + `anvyc secret add [--generate\|--ref\|--file --key] [--apply]` + `secret get [--reveal]`(pbcopy 직접 파이프 + 자동 클리어, 비-TTY reveal 거부) + unit tests(20건). 값 미캡처 — op item create/sops edit/resolve 모두 stdio 상속·파이프. |
| feat 2026-05-29 | **Phase 2.5a 구현** — `keychain` backend(add: `security add-generic-password -U … -w` hidden 프롬프트 / get: `find-generic-password -w`) + `aws-vault` backend(add: `aws-vault add`, get 은 exec 모델이라 안내 에러). `secret add --service/--account/--profile`. add/get 4-backend 완성. tests(9건). inject-wire(2.5b)는 후속. |

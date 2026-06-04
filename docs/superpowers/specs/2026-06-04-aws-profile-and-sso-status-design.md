# `anvyc aws profile` + 프로젝트 단위 AWS 계정 인증/연결 상태 점검 설계

- **날짜**: 2026-06-04
- **상태**: 승인됨 (구현 대기)
- **프로젝트**: anvyc (L2-environment)
- **관련**: `utils/aws_config.py`(profile/sso 파싱), `core/creds.py:269`(`detect_aws_sso`/`_classify`), `checks/creds_expiry.py`(역할 분리 대상), `checks/aws_profile_status.py`(shell-scope 선례), `core/project_info.py:101`(`resolve_cwd_aws_profiles`·`ProjectInfo.aws_profile`), `core/project_doctor.py`(`_check_aws_profile_defined` 선례·`run_project_doctor`), `core/doctor.py`(`_REGISTRY`), `core/project_roots_edit.py`+`core/yaml_io.py`(안전 쓰기 선례), `cli.py:116-129`(`config`/`project` 그룹 등록 선례)

## 1. 배경 / 문제

`anvyc doctor` 의 AWS 관련 표시는 현재 3축뿐이고, 모두 *"지금 이 프로젝트가 쓰는 계정에 연결 가능한가?"* 에 답하지 못한다.

| 위치 | 점검 | 스코프 | 한계 |
|------|------|--------|------|
| `doctor` `aws-profile-status` (`checks/aws_profile_status.py`) | `AWS_PROFILE` env 정의 여부 | **shell** | 로그인 상태가 아니라 env 변수만 |
| `doctor` `multi-account-detected` / `unused-aws-profiles` | `~/.aws/config` 전체 profile | **전역(머신)** | 프로젝트 무관 인벤토리 (12개 감지 / 11개 unused) |
| `doctor` `creds-expiry` (`checks/creds_expiry.py`) | `~/.aws/sso/cache/*.json` 만료 | **이미 프로젝트 스코프** (`ctx.current_project_aws_profiles`) | SSO 만 + 만료(expiring/expired)만, **캐시 없는 profile(미로그인)·valid·non-SSO 는 silent** |
| `project doctor` `aws_profile_defined` (`core/project_doctor.py`) | `.envrc AWS_PROFILE` ↔ `~/.aws/config` | **프로젝트** | 정의 여부만, 인증/연결 상태 없음 |

**문제 1 — 프로젝트 단위 계정 연결 상태 점검 부재.** 현재 프로젝트의 `.envrc AWS_PROFILE` 에 대해 *정의됨? → 어떤 인증 방식? → 그 방식 기준 상태(SSO 토큰 유효/만료/미로그인, static 키 존재, assume-role source 무결성, credential_process 명령 존재 …)?* 를 한 줄로 보여주는 점검이 없다. 특히 `core/creds.py:269` 의 `detect_aws_sso()` 는 **캐시 파일이 있는 SSO profile 만** 산출하므로 "미로그인" 과 **non-SSO 방식 일체**가 사각이다.

**문제 2 — AWS profile 관리 수단 부재.** profile 이 없거나 틀렸을 때 사용자가 고치는 방법은 `aws configure`(외부) 또는 `~/.aws/config` 손편집뿐이다. anvyc 는 profile 을 *읽기*(`load_aws_profile_names`)만 하고, 구조화된 생성/수정/삭제/조회 명령이 없다. 이는 문제 1 의 "프로젝트↔계정 매핑 확립/수복" 을 위한 enabler 다.

## 2. 목표 / Non-goals

**목표**:
- 현재 프로젝트가 쓰는 AWS profile 의 **인증 방식별 계정 상태 점검**을 `anvyc doctor`(전역, cwd 스코프)와 `anvyc project doctor`(path-aware) 양쪽에 추가 — **보고 전용**.
- 인증 방식을 **SSO / static / static-temporary / assume-role / credential_process / web_identity** 로 분류하고, 각 방식의 **오프라인 확인 가능 신호**(SSO 토큰 만료, static 키 존재, source_profile 무결성, 명령 binary 존재 등)를 보고. "미로그인"(SSO 캐시 없음) 을 1급으로 식별.
- 진짜 "연결/유효" 확인이 필요하면 **opt-in 네트워크 probe** — `anvyc aws profile show/list --probe`(`aws sts get-caller-identity`). doctor 는 절대 네트워크 안 함.
- AWS profile **CRUD** — `anvyc aws profile <list|show|create|edit|rm>`. SSO 우선 스캐폴딩 + 일반 키 수정.
- 변경(create/edit/rm)은 `~/.aws/config` 만 대상으로 **dry-run + `.bak` + 확인 + 재파싱 검증/롤백**.

**Non-goals**:
- doctor/project doctor **네트워크 안 함** — liveness probe 는 `aws profile` 명령의 **opt-in `--probe`** 에서만(read-only 원칙·CI/offline 안전).
- `aws sso login` **직접 실행 안 함** — 로그인은 `aws sso login --profile X` 제안만.
- `credential_process` **실행 안 함**(오프라인은 명령 binary 존재만; 실제 실행은 느림/프롬프트 — doctor 부적합. `--probe` 가 sts 로 우회 검증).
- `web_identity` **깊은 검증 안 함** — 방식 분류 + 토큰파일 존재만(JWT `exp` 파싱은 niche, 비용 과다).
- `~/.aws/credentials`(정적 키) **쓰기 불가침** — static 자격 입력은 거부하고 `aws configure` 안내만(읽기는 static 키 *존재 여부* 확인용으로만).
- 기존 전역 인벤토리 체크(`multi-account-detected`·`unused-aws-profiles`·`aws-profile-status`) **변경 안 함**.
- `creds-expiry` 에서 aws_sso **제거 안 함** — 만료 escalation 의 SoT 유지(anvyx gate·CP-3 scheduler 의존).
- 프로젝트당 **다중 AWS profile 안 함** — 현 모델(`.envrc` 단일 `AWS_PROFILE`) 유지.

## 3. 결정 (승인됨)

| 결정 | 선택 | 근거 |
|------|------|------|
| 담당 도구 | **anvyc** | 이미 profile 탐색·doctor 등록·creds 수명주기·프로젝트↔계정 라우팅 보유. anvyx(실행 엔진)·ccinspector(헬스 모니터링)는 별도 repo·다른 도메인 |
| 인증 방식 범위 | **SSO + static + static-temporary + assume-role + credential_process** 오프라인 확인, **web_identity** 분류만 | 실사용 패턴(SSO·aws-vault·다계정 assume-role) 총망라, niche 과투자 회피 |
| non-SSO liveness | **오프라인 분류/presence/무결성 (doctor)** + **opt-in `--probe`**(`sts get-caller-identity`, `aws profile` 명령에서만) | doctor offline 원칙(`creds_expiry` 의 `probe_github_expiry=False` 선례). 진짜 연결 확인은 사용자 명시 호출 |
| 변경 안전성 | **직접 변경 + 안전가드**(dry-run·`.bak`·확인·재검증) | `config roots edit`/`apply` 선례. rm 은 명시 확인 필수 |
| SSO 로그인 | **보고 전용** (login 제안만) | doctor read-only 원칙 유지 |
| CRUD 범위 | **SSO 우선** (`[sso-session]`+`[profile]` 스캐폴딩) + region/output 등 일반 키 | 목표가 계정 연결 상태 |
| `~/.aws/config` 쓰기 | **섹션 단위 surgical 텍스트 편집**(대상 섹션 라인만 추가/치환/삭제, 나머지 원문·주석 보존). `configparser` 는 파싱·검증 전용 | `~/.aws/config` 는 사용자 소유·주석 흔함. configparser 전체 재기록은 주석/서식 소실 — 안전 우선 위배. `.bak` 병행 |
| `creds-expiry` 관계 | **역할 분리** — `aws-account-status` 는 "인증 방식·연결 존재/유효성"(≤WARNING). 만료 escalation(WARNING/CRITICAL+회전)은 `creds-expiry` 유지 | blast radius 최소화(gate/scheduler 의존). 두 체크의 메시지·축이 다름 |
| 시크릿 | **`~/.aws/credentials` 쓰기 불가침** + `aws_access_key_id`/`secret`/`session_token` 입력 거부. probe 출력의 Account/Arn 은 식별자(비밀 아님)라 표기 허용 | anvyc 시크릿 비저장 규칙 |
| 명령 표면 | **신규 `aws` 그룹 → `profile` 하위** (PANEL_PROJECT) | `config roots`/`config projects` 2단 선례. 향후 `aws sso …` 확장 여지 |
| 체크 ID | 전역 **`aws-account-status`**(kebab) + project **`aws_account_status`**(snake), **공용 코어 1개** | SSO-한정이 아님을 이름에 반영, 두 네이밍 컨벤션 일치, 로직 중복 0 |
| 단계 | **Phase 1 보고(읽기, probe 포함) → Phase 2 CRUD(쓰기)** 별도 PR | Phase 1 이 사용자 핵심 요구(프로젝트 단위 계정 상태)를 저 blast radius 로 즉시 충족, Phase 2 가 위에 구축 |

## 4. 아키텍처

```
utils/aws_config.py        # (기존) load_aws_profile_names, load_aws_sso_index
                           #   + load_profile_config(profile, path=None) -> dict[str,str] | None    (신규) profile 섹션 키
                           #   + load_profile_sso_meta(profile, path=None) -> (sso_session|None, sso_start_url|None)|None  (신규)
                           #   + load_credentials_profile_names(path=None) -> set[str]               (신규) ~/.aws/credentials 의 [name] 섹션
core/aws_profile_state.py  # (신규) 순수 판정 — 읽기 전용, **네트워크 의존 0**
                           #   AUTH_* 상수, @dataclass AwsProfileState(profile, defined, auth_method, detail…)
                           #   detect_auth_method(keys, *, has_static) -> str
                           #   evaluate_profile_state(profile, *, home, now) -> AwsProfileState   # 방식별 오프라인 신호
                           #   state_to_result(state, *, check_name) -> CheckResult | None         # 공용 매퍼(≤WARNING)
core/aws_probe.py          # (신규) opt-in 네트워크 — `aws sts get-caller-identity --profile X --output json`(subprocess, timeout)
                           #   probe_caller_identity(profile) -> ProbeResult(ok, account, arn, error)  # CLI --probe 전용. doctor 不import
checks/aws_account_status.py # (신규, 전역) class AwsAccountStatusCheck: name="aws-account-status"
                           #   run(ctx): ctx.current_project_aws_profiles 각 profile → evaluate → state_to_result
core/doctor.py             # _REGISTRY 에 "aws-account-status": AwsAccountStatusCheck() 등록
core/project_doctor.py     # _check_aws_account_status(info) 추가(9번째) → run_project_doctor 에 wire
─────────────────────────── Phase 2 (쓰기) ───────────────────────────
core/ini_io.py             # (신규) atomic_write_text(text, path)  (tempfile.mkstemp + os.replace; yaml_io 형제)
                           #   + locate_section(lines, header) -> (start, end) | None  # 섹션 라인 범위
core/aws_config_edit.py    # (신규) 순수 CRUD 로직 — surgical 텍스트 편집 (project_roots_edit 패턴 이식)
                           #   create_profile / edit_profile / remove_profile -> *EditResult(diff, backup_path, …)
                           #   .bak 백업 + atomic 쓰기 + configparser 재파싱 검증 → 실패 시 롤백; static-cred 키 거부; orphan sso-session 경고
cli.py                     # aws_app = Typer(name="aws"); app.add_typer(aws_app, PANEL_PROJECT)
                           #   aws_profile_app = Typer(name="profile"); aws_app.add_typer(..., "profile")
                           #   profile: list / show (Phase 1, --probe opt-in) · create / edit / rm (Phase 2)
```

**오프라인 코어의 네트워크-free 보장**: `core/aws_profile_state.py`(doctor 가 import) 는 어떤 네트워크 호출도 안 한다. 네트워크는 `core/aws_probe.py` 로 **물리적 분리** — `aws profile --probe` CLI 경로에서만 import. → doctor/project doctor 가 구조적으로 offline.

**판정 흐름**(`evaluate_profile_state`, 읽기 전용):
```
profile 정의?(load_aws_profile_names)
  └ no  → AwsProfileState(defined=False, auth_method="undefined")
  └ yes → keys=load_profile_config(profile); has_static=profile∈load_credentials_profile_names() 또는 keys 에 키
          detect_auth_method(keys, has_static):
            sso(sso_session|sso_start_url)            → 캐시 startUrl 매칭(detect_aws_sso 인덱싱) → valid|expiring|expired|none|unknown
            assume_role(role_arn + source_profile|credential_source) → source_profile 존재?(load_aws_profile_names) 또는 credential_source 종류
            credential_process                        → 명령 첫 토큰(shlex) binary PATH 존재?(shutil.which)
            web_identity(web_identity_token_file)      → 토큰파일 존재 여부(분류만)
            static / static_temporary(aws_session_token) → static 키 존재?(credentials/config)
            그 외                                       → incomplete
```
- SSO 캐시 파싱은 `core/creds.py` 의 공개 `detect_aws_sso(home, warn_threshold_days=…, now=…)` 결과를 `identifier`(=startUrl) 키로 인덱싱해 **재사용**(중복 0).

**두 진입점·공용 코어** — `evaluate_profile_state` + `state_to_result` 는 코어 1쌍. 전역 체크는 `ctx.current_project_aws_profiles`(cwd walk-up, 이미 `CheckContext` 에 존재), project 체크는 `info.aws_profile`(명시 path 의 `.envrc`)로 호출. → 사용자 요구 "anvyc doctor에서 … 현재 프로젝트 기준으로" 를 cwd 스코프로 충족하고, `anvyc project doctor /path` 도 동일 판정.

## 5. 상태 → 결과 매핑 (공용 매퍼, 오프라인, ≤WARNING)

`state_to_result(state, *, check_name)` — CRITICAL 미발행(만료 escalation 은 `creds-expiry` 소유).

| auth_method | 오프라인 상태 | severity | 메시지(요지) | suggestion |
|---|---|---|---|---|
| (프로젝트에 AWS profile 없음) | — | (None — silent) | — | — |
| undefined | profile 미정의 | WARNING | `AWS profile 'X' 가 ~/.aws/config 에 미정의` | `anvyc aws profile create X --sso …` |
| sso | 토큰 valid/expiring | INFO | `SSO 연결됨 'X' (session S, ~Nh 남음)` | — |
| sso | 토큰 expired | WARNING | `SSO 세션 만료 'X' — 재로그인 필요` | `aws sso login --profile X` |
| sso | 캐시 없음(미로그인) | WARNING | `미로그인 'X' (session S) — SSO 로그인 필요` | `aws sso login --profile X` |
| sso | expiresAt 파싱 실패 | INFO | `SSO 토큰 상태 불명 'X'` | — |
| static | 정적 키 존재 | INFO | `정적 키 구성됨 'X' (만료 없음)` | (장기 키 — SSO 권장 중립 안내 옵션) |
| static | 키 없음(config엔 정적이나 credentials 키 부재) | WARNING | `정적 자격 'X' 인데 ~/.aws/credentials 에 키 없음` | `aws configure --profile X` |
| static_temporary | `aws_session_token` 존재 (+만료필드 있으면 valid/expired, 없으면 불명) | INFO/WARNING | `임시 자격 'X' (만료 <표기/불명>)` | 만료 시 재발급 |
| assume_role | source_profile 존재 | INFO | `역할 위임 'X' (source: Y)` | — |
| assume_role | source_profile 미정의 | WARNING | `'X' 의 source_profile 'Y' 미정의` | source profile 생성/수정 |
| assume_role | credential_source(Ec2/Ecs/Environment) | INFO | `'X' 환경 기반 위임 (<source>)` | — |
| credential_process | 명령 binary 존재 | INFO | `credential_process 구성됨 'X' (<cmd>)` | — |
| credential_process | 명령 미발견 | WARNING | `'X' 의 credential_process 명령 미발견: <cmd>` | 도구 설치/PATH 확인 |
| web_identity | (분류만, 토큰파일 존재 시 표기) | INFO | `web identity 'X' (token_file <존재/부재>)` | — |
| incomplete | 섹션 있으나 인증키 없음 | WARNING | `'X' 인증 구성 불완전` | profile 키 보완 |

- SSO "연결됨" = **토큰 존재 + 미만료**(valid/expiring). expiring 의 WARNING 격상은 `creds-expiry` 가 담당하므로 여기선 INFO → "지금 연결 가능?" crisp yes/no.
- **`--probe` 오버레이**(opt-in, `aws profile` 명령 한정): 위 오프라인 상태에 더해 `sts get-caller-identity` 결과를 라이브로 덧붙임 — `connected (account A, arn …)` / `denied` / `expired` / `error(aws CLI 부재 등)`. doctor 결과에는 **반영 안 함**.

## 6. 명령 스펙 — `anvyc aws profile`

전부 `~/.aws/config`(고정; `--aws-config PATH` 로 override 가능 — 테스트용. anvyc 전역 `--config`=anvyc.yaml 와 충돌 회피) 대상. 출력 규약은 doctor 와 동일(Panel 미사용, Rich `escape()`+`soft_wrap`).

### 6.1 조회 (Phase 1, 읽기)

| 명령 | 인자/플래그 | 동작 |
|------|-------------|------|
| `aws profile list` | `[--json] [--status/--no-status] [--probe]` | profile 목록 + region + auth_method + (기본 on) **오프라인 상태**(§5). `--no-status` 로 상태 판정 생략. `--probe` 로 각 profile `sts get-caller-identity`(네트워크, opt-in) |
| `aws profile show <name>` | `[--json] [--probe]` | 단일 profile 해석 키 + auth_method + 연결된 `[sso-session]` 블록 + 오프라인 상태 (+`--probe` 시 라이브 verdict) |

`list --json` 예:
```json
{"profiles": [
  {"name": "ws-dev", "region": "ap-northeast-2", "auth_method": "sso", "sso_session": "ws",
   "status": "valid", "expires_at": "2026-06-04T09:00:00Z", "probe": null},
  {"name": "legacy", "region": "us-east-1", "auth_method": "static",
   "status": "present", "expires_at": null, "probe": {"ok": true, "account": "123456789012"}},
  {"name": "deploy", "region": "us-east-1", "auth_method": "assume_role",
   "status": "source_ok", "source_profile": "legacy", "probe": null}
]}
```
`--probe` 미지정 시 `probe` 필드는 `null`(네트워크 미수행). `status` 는 **auth_method 의존 문자열**(§5 의 방식별 상태 — sso: `valid`/`expiring`/`expired`/`none`/`unknown`, static: `present`/`missing`, assume_role: `source_ok`/`source_missing`/`env`, credential_process: `cmd_ok`/`cmd_missing`, web_identity: `classified`, undefined/incomplete 동명). 정확한 enum 은 구현 계획에서 확정.

### 6.2 변경 (Phase 2, 쓰기)

| 명령 | 인자/플래그 | 동작 |
|------|-------------|------|
| `aws profile create <name>` | `--sso-session S` · `--start-url URL` · `--sso-region R` · `--account-id A` · `--role-name R` · `--region R` · `--output FMT` · `--dry-run` · `--yes` | SSO 우선 생성: `[sso-session S]`(없으면 생성, 있으면 참조) + `[profile name]`(sso_session·sso_account_id·sso_role_name·region·output) 을 **EOF 에 append**. TTY 면 누락 필수값 프롬프트, 비대화면 플래그 필수 |
| `aws profile edit <name>` | `--set key=value …` · `--sso-session S` · `--region R` · `--output FMT` · `--dry-run` · `--yes` | 대상 섹션 라인 범위 내 키 in-place 치환(없으면 섹션 끝에 삽입), 나머지 라인·주석 보존 |
| `aws profile rm <name>` | `[--dry-run] [--yes]` | `[profile name]` 섹션 라인 범위 삭제, 나머지 보존. 해당 profile 의 `sso_session` 이 더 이상 참조 안 되면 **orphan 경고(자동 삭제 X)**. 확인 필수 |

**공통 안전 절차**(create/edit/rm): 변경 전/후 텍스트의 **unified diff(difflib) 미리보기** → `--dry-run` 이면 출력 후 exit 0(무변경); 아니면 확인 프롬프트(`--yes` 로 생략) → `.bak` 백업 → atomic 쓰기 → `configparser` 재파싱 성공 검증 → 실패 시 `.bak` 복구 + exit 1.

**시크릿 가드**: `--set` 또는 어떤 경로로든 `aws_access_key_id` / `aws_secret_access_key` / `aws_session_token` 키가 들어오면 **거부**(exit 1) + "정적 자격은 `~/.aws/credentials` 대상이며 anvyc 가 쓰지 않음 — `aws configure --profile X` 사용" 안내.

## 7. 핵심 의미론

- **auth_method 탐지 우선순위**(§4 흐름): sso → assume_role → credential_process → web_identity → static/static_temporary → incomplete. 한 profile 이 복수 키를 가지면 위 순서가 우선(AWS SDK 의 해석 우선순위와 정합).
- **`~/.aws/credentials` 파싱**: config 와 달리 섹션이 `[profilename]`(접두사 `profile ` 없음). static 키 존재 확인 전용 — `load_credentials_profile_names()`. **값(키 자체)은 읽지 않음**(존재만).
- **profile↔SSO 역추적**(`load_profile_sso_meta`): `[profile X]` 의 `sso_session=S` → `[sso-session S]` 의 `sso_start_url`(신형). `[profile X]` 가 `sso_start_url` 직접 보유 시 그대로(구형). `load_aws_sso_index` 의 역방향.
- **assume_role 무결성**: `source_profile=Y` 가 `load_aws_profile_names()` 에 존재하는지 1-hop 만 확인(체인 깊이 재귀 안 함). `credential_source` 면 종류만 보고.
- **credential_process 명령 확인**: 값 `shlex.split` 후 첫 토큰을 `shutil.which` — 절대경로면 존재 확인. **실행 안 함**.
- **`default` profile 특례**: 헤더가 `[default]`(타 profile 은 `[profile X]`). show/edit/rm 은 헤더 차이 처리. create 는 명시 이름만(default 생성 비권장 — 경고).
- **probe 안전**(`core/aws_probe.py`): `subprocess` 로 `aws sts get-caller-identity --profile X --output json`, timeout(예: 8s), `aws` 부재/실패 시 graceful(`ProbeResult(ok=False, error=…)`). 출력의 Account/Arn/UserId 는 식별자(로그에 흔함, 비밀 아님)라 표기. 자격(키/토큰)은 어떤 경우에도 출력 안 함.
- **섹션 라인 범위**(`locate_section`, Phase 2): 헤더 정규식 `^\s*\[(?P<name>[^\]]+)\]\s*$` 로 시작 인덱스 탐지, 다음 헤더 직전(또는 EOF)까지. rm 시 직후 연속 빈 줄 1개까지 정리.
- **검증 후 쓰기**(Phase 2): `_write_roots` 와 동형 — 쓰기 후 `configparser.RawConfigParser().read()` throw 시 `.bak` 복구.

## 8. 엣지 / 에러 처리

- `~/.aws/config` 부재: `list`/`show` → 빈/없음 안내. `create` → 파일(+필요 시 `~/.aws/`) 생성.
- `~/.aws/credentials` 부재: 모든 static profile → "키 없음"(WARNING) 일관 처리.
- `~/.aws/sso/cache` 부재: 모든 SSO profile → `none`(미로그인).
- `aws` CLI 부재(`--probe`): probe 미수행, "probe 불가 — aws CLI 필요" 안내(오프라인 상태는 그대로 표시). doctor 는 애초에 probe 안 하므로 무영향.
- credential_process 값에 인자/공백: `shlex.split` 첫 토큰만 검사. 따옴표/환경변수 확장은 안 함(과해석 회피).
- assume_role 체인: 1-hop 만(순환/깊은 체인 미추적).
- 토큰 만료시각 파싱 실패(`_classify` → unknown): `unknown` → INFO(상태 불명), 차단 안 함.
- 동시성: profile 쓰기 중 외부 `aws sso login` 은 캐시만 건드림 — atomic 쓰기로 부분쓰기 방지.
- 전역 doctor 에서 cwd 가 프로젝트 밖(home 등): `current_project_aws_profiles`=∅ → silent.

## 9. 단계 계획

**Phase 1 — 보고(읽기 전용, `--probe` 포함)**
- 산출물: `utils/aws_config.py`(`load_profile_config`·`load_profile_sso_meta`·`load_credentials_profile_names`), `core/aws_profile_state.py`(`AwsProfileState`·`detect_auth_method`·`evaluate_profile_state`·`state_to_result`), `core/aws_probe.py`(opt-in), `checks/aws_account_status.py`+`core/doctor.py` 등록, `core/project_doctor.py` 9번째 체크 wire, `cli.py` `aws_app`/`aws_profile_app` + `list`/`show`(`--probe`), 문서.
- blast radius 작음(읽기·신규 체크). `creds-expiry` 무변경. **사용자 핵심 요구(프로젝트 단위 계정 상태) 즉시 충족.**

**Phase 2 — CRUD(쓰기)**
- 산출물: `core/ini_io.py`(`atomic_write_text`·`locate_section`), `core/aws_config_edit.py`(create/edit/remove + 안전가드), `cli.py` `create`/`edit`/`rm`, 문서.
- 쓰기 안전 가드(diff·`.bak`·확인·재검증) + 시크릿 가드.

스펙은 하나(통합), 구현 계획에서 두 Phase 로 시퀀싱(각 별도 PR). 향후(별도) 후보: `aws-account-status`↔`creds-expiry` dedupe, `aws profile use`(`.envrc` 작성 연동), web_identity JWT exp.

## 10. 테스트 전략 (TDD)

- **단위 `core/aws_profile_state`**: §5 전 행 — tmp `~/.aws/config`(신형/구형 SSO·static·assume-role·credential_process·web_identity·incomplete) + tmp `~/.aws/credentials` + tmp `sso/cache/*.json` + 주입 `now`. `detect_auth_method` 우선순위, `state_to_result` severity/메시지/None(silent), **CRITICAL 미발행**, **네트워크 호출 0**(probe import 안 함) 확인.
- **단위 `utils/aws_config`**: `load_profile_config`, `load_profile_sso_meta`(신형/구형/비-SSO/미존재), `load_credentials_profile_names`(접두사 없는 섹션).
- **단위 `core/aws_probe`**: `subprocess` mock — ok/denied/expired/aws-부재/timeout. 자격 미출력 단언.
- **단위 `core/aws_config_edit`**(Phase 2): create EOF append, 기존 sso-session 참조(블록 무변경), edit in-place 키 치환(섹션 외 주석 보존), rm 섹션 삭제(주석 보존), orphan sso-session 경고, static-cred 키 거부, `.bak` 생성, 재파싱 실패→롤백.
- **단위 `core/ini_io.locate_section`**(Phase 2): 헤더 탐지·범위·EOF·default 헤더.
- **CLI(`CliRunner`)**: `list`/`show`(`--json`·`--no-status`·`--probe` mock), `create`/`edit`/`rm`(`--dry-run` 무변경·`--yes`·확인 중단). tmp config + HOME monkeypatch.
- **doctor 회귀**: `anvyc doctor --json` 에 `aws-account-status` check_name 노출, **schema 자체 불변**(하위호환). `project doctor` 결과에 `aws_account_status` 포함(8→9 체크).

## 11. 문서 갱신

- `README.md` §11(다수 계정 관리): `anvyc aws profile` 사용 예 + 인증 방식별 계정 상태 점검 + `--probe` 안내.
- `docs/multi-account.md`: profile CRUD + 인증 방식별 상태 + opt-in probe 흐름.
- `docs/design-axes/cp-05-creds.md`: `creds-expiry` 와 `aws-account-status` 역할 분리 명기.
- `docs/doctor-json-schema.md`: 새 check_name(`aws-account-status`) 추가 — schema 불변 명시.
- `DESIGN.md`: `project doctor` 체크 목록(8→9), 신규 `aws` 명령군.
- `examples/`: SSO/assume-role profile 예시(있으면).
- `CONTEXT.md` / `RELEASE_NOTES.md`: 진행/릴리스 반영.

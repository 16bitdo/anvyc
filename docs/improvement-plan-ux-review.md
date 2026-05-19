# anvyc UX 개선 계획 — 설치 / 다수 계정 / 설정 편의성

> 작성일: 2026-05-19
> 대상 버전: v0.5.3 (마지막 release) 기준 → v0.6.x / v0.7+ 로드맵
> 검토 범위: 로컬 PC 설치 용이성, 다수 계정 변경 편의성, 도구 설정 편의성
> 참고 도구: chezmoi, yadm, mackup, dotbot, direnv, aws-vault

---

## 1. 검토 동기

오픈소스 공개를 앞두고 anvyc 의 사용자 경험을 유사 도구들과 비교해 부족한 영역과 개선 후보를 식별한다. 단순 기능 비교가 아니라 **사용자 실 워크플로** (특히 multi-account 환경) 기준으로 평가한다.

### 1.1 사용자 환경 grounded 데이터 (2026-05-19 실측)

| 항목 | 값 |
|---|---|
| `~/.aws/config` profile | **12개** (default + 11) — `pulumi-dev`, `ws-{mgmt,prd,dev}`, `<company>-{dev,audit,terraform,logs,demo,prd,agency}` |
| profile 명명 규칙 | `<group>-<env>` 패턴 (`ws-*`, `<company>-*`) — 그룹 + 환경 분리 |
| direnv | **2.37.1 설치, zsh hook 활성** |
| `~/Documents` 의 `.envrc` 파일 | **0건** — direnv 가 dev-env 자동화에 활용 X |
| 현재 shell 의 `AWS_PROFILE` | **미설정** — session 시작 시 default 또는 매번 명시 |
| `~/Documents` 의 `.cursor/` 디렉터리 | **46개** — multi-project 워크스페이스 |
| GitHub 계정 | `16bitdo`, `secondary` 둘 다 활성 (SSH key alias 분리) |
| Cursor IDE | `edward` + `aliasuser → edward` symlink alias |

→ 검토는 이 실제 환경을 기준으로 grounded 함.

---

## 2. 비교 대상 도구

| 도구 | 영역 | anvyc 와의 관계 |
|---|---|---|
| **chezmoi** | dotfile manager (Go 단일 바이너리) | DESIGN.md §2 에서 영감 명시. 가장 직접적 참조 |
| **yadm** | dotfile manager (bash + git wrapper) | bash thin layer |
| **mackup** | macOS 앱 설정 동기화 (Python) | macOS 특화 점에서 유사 |
| **dotbot** | yaml-driven dotfile installer | symlink 중심 |
| **direnv** | cwd 기반 env 자동 load | 사용자 이미 설치, multi-profile 표준 답 |
| **aws-vault** | AWS profile 격리 + MFA 강제 + 임시 자격 | secret 관리 영역 |
| **home-manager** (Nix) | declarative full env | scope 가 다름 (overkill 비교) |

---

## 3. 기능 비교 매트릭스

| 항목 | anvyc v0.5.3 | chezmoi | yadm | mackup |
|---|---|---|---|---|
| 설치 (3rd-party) | ❌ git clone + uv build (6 단계) | ✓ brew, curl 1-liner | ✓ brew | ✓ brew/pip |
| 단일 바이너리 | ❌ Python | ✓ Go | ⚠ bash + git | ❌ Python |
| 새 머신 부트스트랩 | 6 단계 | **3 단계** (`init <url>` → `apply`) | 2 단계 | 3 단계 |
| 다중 머신 분기 (host/OS별) | ❌ 명시적 yaml 편집 | ✓ Go template (`hostname/os/email`) | ⚠ branch | ❌ |
| 다중 계정 (같은 도구) | ⚠ 직접 yaml 정의 | ✓ template + `.chezmoidata` 변수 | ⚠ branch | ❌ |
| 1Password ref (`op://`) | ✓ scanner 인식 + doctor check | ✓ template 내장 | ❌ 별도 yadm-encrypt | ❌ |
| SOPS 통합 | ✓ inplace + binary, per-file/per-tool | ✓ template + sops fn | ❌ | ❌ |
| diff / dry-run | ✓ apply --dry-run + diff | ✓ chezmoi diff | ❌ | ❌ |
| Backup / rollback | ✓ local-backup 자동 | ❌ (source ↔ target 단방향) | ❌ | ⚠ 1단계만 |
| macOS plist safe subset | ✓ iTerm2 (31 키 정밀 추출) | ❌ full plist (위험) | ❌ | ⚠ 일부 |
| pre-commit hook (secret 차단) | ✓ 내장 | ⚠ 사용자 설정 | ❌ | ❌ |
| 멀티-도구 adapter 분리 | ✓ 8 adapter | ❌ unified | ❌ | ❌ |
| Doctor health check | ✓ 7 checks | ✓ chezmoi doctor | ❌ | ❌ |

### 3.1 요약

- **anvyc 강점**: backup/rollback 안전망, safe subset (iTerm2/Cursor), 도구별 adapter, pre-commit hook 자동, SOPS 통합 (per-file/per-tool), 풍부한 doctor check
- **anvyc 약점**: 설치 단계 수, host/OS 별 분기, 인터랙티브 설정 편의성, 새 머신 부트스트랩 명령 길이

---

## 4. 개선 영역 A: 설치 용이성

### 4.1 현재 상황

```bash
# anvyc (v0.5.3)
git clone git@github.com:16bitdo/anvyc.git
cd anvyc
uv build
uv tool install dist/anvyc-0.1.0-py3-none-any.whl
anvyc --version

# chezmoi (basis)
brew install chezmoi
chezmoi init https://github.com/USER/dotfiles.git --apply
```

### 4.2 개선 후보

| # | 개선 | 가치 | 비용 | 시기 |
|---|---|---|---|---|
| **I1** | Homebrew tap (`16bitdo/anvyc`) — `brew install 16bitdo/anvyc/anvyc` | 매우 높음 | 2h | v0.6.x |
| **I2** | `anvyc init --from-git <url>` 명령 — git remote 에서 `.anvyc/` 직접 clone + apply | 높음 | 1.5h | v0.6.x |
| **I3** | One-liner install script — `curl https://anvyc.dev/install.sh | bash` | 중간 (보안 트레이드오프) | 1h + 도메인 | v0.7+ |
| **I4** | PyPI 배포 — `pipx install anvyc` | 높음 | 빌드 1h + PyPI 등록 | v1.0 |

**권장**: I2 (`init --from-git`) + I1 (Homebrew tap) → chezmoi 와 대등한 1줄 부트스트랩.

---

## 5. 개선 영역 B: 다수 계정 변경 편의성

### 5.1 현재 상황

- anvyc 는 `tools.<X>.files` 에 절대 경로 명시. 머신별 분기 없음
- 같은 머신의 multi-account 는 도구 자체가 처리 (aws `[profile X]`, ssh host alias, gh auth 다계정) — anvyc 는 파일을 통째로 백업하므로 자동 지원
- **다른 머신**에서 다른 account set 을 원할 때 → 별도 anvyc.yaml 수동 편집

### 5.2 사용자 multi-account 환경 (실측)

- **GitHub**: `16bitdo` + `secondary` (SSH key alias `github.com-16bitdo`, `github.com-secondary` 분리)
- **AWS**: 12 profile (default + ws-*, <company>-* 그룹)
- **Cursor**: `edward` + `aliasuser → edward` symlink alias
- **1Password**: op CLI 단일 계정

### 5.3 추가 시나리오 — 프로젝트/PR 단위 AWS profile 전환

이 사용자의 실제 워크플로 (검토 중 식별):

#### 시나리오 A: 프로젝트별 정해진 1개 AWS profile
- `~/Documents/<company>-dev-project` → `AWS_PROFILE=<company>-dev` 고정
- `~/Documents/<company>-audit-project` → `AWS_PROFILE=<company>-audit` 고정
- 현재 사용자 워크플로 (추정): 매번 수동 `export AWS_PROFILE=X` 또는 README 외움

#### 시나리오 B: PR마다 1~3 profile 교체
- PR 개발: `export AWS_PROFILE=<company>-dev`
- PR 테스트: `export AWS_PROFILE=<company>-audit`
- PR 검증: `export AWS_PROFILE=<company>-prd` (readonly)
- 머지 후 원복: `unset AWS_PROFILE`

### 5.4 유사 도구 비교 (시나리오별)

#### 시나리오 A 처리 비교

| 도구 | 접근 |
|---|---|
| **direnv** (사용자 이미 설치됨) | `<project>/.envrc` 에 `export AWS_PROFILE=X`. cd 시 자동 load. **표준 답** |
| **aws-vault** | `~/.aws/config` profile 별 격리 + MFA 강제. 명시적 `aws-vault exec X --` |
| **mise / asdf** | 도구 버전 + env. AWS profile 도 가능 |
| **chezmoi** | template 으로 profile mapping. 동적 전환은 X |
| **anvyc 현재** | profile mapping 모름. 정적 sync 만 |

#### 시나리오 B 처리 비교

| 도구 | 접근 |
|---|---|
| **shell alias/function** | `alias awsdev='export AWS_PROFILE=<company>-dev'` 식 |
| **aws-vault exec** | 명시적 명령 단위 격리 |
| **starship/p10k prompt** | 현재 AWS_PROFILE 을 prompt 에 표시. 인식만 |
| **anvyc 현재** | runtime switching X (scope 외) |

### 5.5 anvyc 기여 후보

| # | 개선 | 시나리오 | 가치 | 비용 |
|---|---|---|---|---|
| **A1** | doctor check `project-aws-profile-mapping` — `~/Documents/*/`.envrc` 의 `AWS_PROFILE` 값들이 `~/.aws/config` 에 정의되어 있는지 검증 | A | **HIGH** | 1.5h |
| **A2** | README §11 신규 — "프로젝트별 AWS profile 관리 권장 패턴" (direnv + .envrc + anvyc backup) | A | **HIGH** | 30~45m |
| **A3** | 신규 `dev_env` 어댑터 또는 cursor.projects 모드 확장 — `.envrc`, `.tool-versions`, `.python-version`, `.nvmrc` 추적 | A | MEDIUM | 2h |
| **A4** | doctor check `unused-aws-profiles` — `.aws/config` 에 정의됐지만 어떤 프로젝트 `.envrc` 도 사용 안 하는 profile (INFO) | A | LOW (cleanup 용) | 1h |
| **B1** | doctor check `aws-profile-status` — 현재 `AWS_PROFILE` env var + `~/.aws/config` 정합성 | B | **MEDIUM** | 1h |
| **B2** | `anvyc aws profile <name>` eval helper — `eval "$(anvyc aws profile X)"` 출력 | B | LOW (direnv 와 중복) | 1h |
| **B3** | `anvyc backup` metadata 에 active profile 기록 (informational) | B | LOW | 30m |
| **M1** | 호스트별 `anvyc.yaml.<hostname>` overlay (chezmoi template 대안) | multi-host | **MEDIUM** | 2h |
| **M3** | doctor check `multi-account-detected` — ssh/aws/gh 통합 안내 | multi-account | **MEDIUM** | 1.5h |

### 5.6 scope 경계

| anvyc 가 해야 할 영역 | anvyc 가 안 해야 할 영역 |
|---|---|
| 정적 설정 파일 sync (~/.aws/config, .envrc) | runtime profile switching |
| profile mapping 검증 (doctor check) | credential 자체 관리 |
| 권장 워크플로 가이드 (README) | shell session state 추적 |
| 변경 안전망 (backup/rollback) | session 간 상태 전송 |

→ direnv/aws-vault 가 더 잘 하는 영역에 anvyc 가 들어가면 도구 경계 모호.
→ A2 (README 가이드) + A1/B1 (doctor check) 가 anvyc 의 자연스러운 기여.

---

## 6. 개선 영역 C: 설정 편의성

### 6.1 현재 상황

- `anvyc init` → 정적 `templates.py` yaml 생성
- 사용자가 yaml 직접 편집
- 검증은 `anvyc doctor` 또는 `anvyc backup` 시점에 간접적
- 8개 도구의 enable/disable 상태를 한눈에 보기 어려움

### 6.2 chezmoi 비교

- `chezmoi edit-config` — $EDITOR 로 schema-aware 편집
- `chezmoi managed` — 추적 파일 목록
- `chezmoi cd` — source dir 빠른 이동

### 6.3 개선 후보

| # | 개선 | 가치 | 비용 |
|---|---|---|---|
| **C1** | `anvyc config edit` — $EDITOR 로 anvyc.yaml 열고 종료 시 schema 검증 | **HIGH** | 1h |
| **C2** | `anvyc config show [--effective]` — 현재 활성 yaml 또는 default 적용 후 effective 값 | MEDIUM | 1h |
| **C3** | `anvyc tools list` — 각 tool 의 enabled / detect / file-count + 미지원 도구 안내 | **HIGH** | 1h |
| **C4** | `anvyc init --interactive` wizard — 각 도구 enable 여부 + path 입력 | LOW | 2h |
| **C5** | 에러 메시지 일관성 — 모든 비즈니스 예외 (BackupBlocked, ApplyBlocked) 가 "관련 doctor check 또는 next step" 제시 | MEDIUM | 1.5h |

**권장**: C1 (`config edit`) + C3 (`tools list`) → chezmoi 의 `edit-config` + `managed` 와 대등.

---

## 7. 종합 우선순위 (확정)

| 우선순위 | 항목 | 영역 | 시기 |
|---|---|---|---|
| **HIGH** | **A2**: README §11 multi-AWS-profile 가이드 | 다중 계정 / 문서 | **v0.6.0** (OSS 공개와 함께) |
| **HIGH** | **A1**: doctor `project-aws-profile-mapping` | 다중 계정 | v0.6.x |
| **HIGH** | **I2**: `anvyc init --from-git <url>` | 설치 | v0.6.x |
| **HIGH** | **C1**: `anvyc config edit` | 설정 | v0.6.x |
| **HIGH** | **C3**: `anvyc tools list` | 설정 | v0.6.x |
| **HIGH** | **M1**: 호스트별 anvyc.yaml overlay | 다중 계정 | v0.6.x |
| MEDIUM | **I1**: Homebrew tap | 설치 | v0.6.x |
| MEDIUM | **B1**: doctor `aws-profile-status` | 다중 계정 | v0.6.x |
| MEDIUM | **M3**: doctor `multi-account-detected` (ssh/aws/gh) | 다중 계정 | v0.6.x |
| MEDIUM | **C2**: `anvyc config show --effective` | 설정 | v0.6.x |
| MEDIUM | **C5**: 에러 메시지 일관성 | 설정 | v0.6.x |
| MEDIUM | **A3**: `dev_env` 어댑터 (.envrc/.tool-versions/.nvmrc) | 다중 계정 | v0.7+ |
| LOW | **C4**: interactive init wizard | 설정 | v0.7+ |
| LOW | **B2/B3**: runtime profile switching | 다중 계정 | scope 모호, 보류 |
| LOW | **A4**: unused profile cleanup | 다중 계정 | v0.7+ |
| LOW | **I3**: curl one-liner install | 설치 | v0.7+ |
| DEFERRED | **I4**: PyPI 배포 | 설치 | v1.0 |

---

## 8. v0.6.0 / v0.6.x / v0.7+ 분배

### 8.1 v0.6.0 (OSS 공개와 함께)

**범위**: OSS 공개 준비 (B 안 plan 의 Phase A~C) + **A2 만 추가**

```
Phase A.1   git secret audit
Phase A.2   Co-Authored-By 제거 (history rewrite)
Phase A.3   LICENSE + .gitignore 확장
Phase B     CONTRIBUTING.md / SECURITY.md / pyproject.toml / --help
Phase B'    README §11 multi-AWS-profile 가이드 (A2)  ← 본 검토에서 추가
Phase C     RELEASE_NOTES + tag v0.6.0
```

추정: ~7.25h (OSS 6.5h + A2 0.75h)

### 8.2 v0.6.x (OSS 공개 후 순차)

UX 개선 묶음. 사용자 의사에 따라 순서 조정 가능:

```
A1   doctor project-aws-profile-mapping       1.5h
B1   doctor aws-profile-status                 1h
M3   doctor multi-account-detected             1.5h
I2   anvyc init --from-git                     1.5h
I1   Homebrew tap                              2h
C1   anvyc config edit                         1h
C3   anvyc tools list                          1h
M1   호스트별 anvyc.yaml overlay              2h
C2   anvyc config show --effective             1h
C5   에러 메시지 일관성                        1.5h
─────────────────────────────────────────
v0.6.x 합계 ≈ 14h
```

### 8.3 v0.7+ (post-v0.6 안정화 후)

```
A3   dev_env 어댑터 (.envrc/.tool-versions/.nvmrc 추적)
A4   unused-aws-profiles INFO
C4   interactive init wizard
I3   curl install script (+ 도메인)
```

### 8.4 v1.0 (API stable, PyPI)

```
I4   PyPI 배포
B2/B3 runtime profile switching (scope 재검토 후)
```

---

## 9. 사용자에게 가장 맞는 권장 흐름 (요약)

```text
1. anvyc 가 직접 도구가 되지 않는다 — direnv/aws-vault 가 표준 답
2. anvyc 는 검증 + 가이드 + 추적
3. 사용자 패턴 권장:

   ~/Documents/<group>/<project>/.envrc:
       export AWS_PROFILE=<company>-dev    # 프로젝트 1개 fix
       # 또는 PR 별 교체용 helper function

   anvyc.yaml:
     tools:
       aws:
         enabled: true
         files: ["~/.aws/config"]
       dev_env:               # 신규 어댑터 (v0.7+)
         project_roots: ["~/Documents"]
         patterns: [".envrc", ".tool-versions", ".python-version", ".nvmrc"]

   anvyc doctor (v0.6.x):
     project-aws-profile-mapping  → .envrc 의 profile 들 중 누락된 정의 안내
     aws-profile-status           → 현재 active profile 정합성
     unused-aws-profiles          → .aws/config 에만 있고 사용 X 한 profile
```

---

## 10. 핵심 인사이트

1. **anvyc 의 차별점은 "도구별 safe adapter + backup/rollback 안전망"** — chezmoi 가 못 하는 영역. README/마케팅에서 강조해야 함.
2. **설치 편의성이 가장 큰 약점**. I2 (`init --from-git`) + I1 (Homebrew tap) 로 chezmoi 수준 부트스트랩 가능.
3. **multi-account 의 현실**: 사용자의 실제 환경 (GitHub 2계정, AWS 12 profile, Cursor alias) 은 **도구가 이미 처리** 하고 있어 anvyc 가 추가로 할 일은 "안내 (doctor check) + 호스트별 overlay" 정도.
4. **direnv 가 설치돼 있지만 활용 안 됨** — A2 (README §11 가이드) 의 즉각적 가치 높음.
5. **설정 편의성**: chezmoi 의 `edit-config` / `managed` 같은 1차 UX 가 anvyc 에 부재. C1+C3 으로 정합.

---

## 11. 참고 자료

- chezmoi: <https://chezmoi.io/>
- chezmoi GitHub: <https://github.com/twpayne/chezmoi>
- yadm: <https://yadm.io/>
- mackup: <https://github.com/lra/mackup>
- dotbot: <https://github.com/anishathalye/dotbot>
- direnv: <https://direnv.net/>
- aws-vault: <https://github.com/99designs/aws-vault>
- SOPS: <https://github.com/getsops/sops>
- 1Password CLI: <https://developer.1password.com/docs/cli/>

---

## 12. 본 문서 활용

- v0.6.0 작업 (OSS 공개 + A2): Phase B' 작성 시 §5 (다중 계정) / §9 (권장 흐름) 직접 인용
- v0.6.x 작업: §8.2 의 우선순위 표 기준으로 sub-plan 수립
- 변경 시: 본 문서 §7 우선순위 표 + §8 분배 표 동기화

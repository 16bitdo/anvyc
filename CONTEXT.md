# CONTEXT.md — anvyc 진행 상태와 결정 기록

> 본 문서는 전역 규칙 "CONTEXT.md 우선 참조"에 따라, 진행 중인 결정/가정/상태를 한 곳에 모은다.
> 새로운 결정이 추가될 때마다 본 문서를 우선 갱신한 뒤 README/DESIGN을 반영한다.

---

## 1. 현재 상태 (2026-05-18 기준)

| 항목 | 상태 |
|---|---|
| 설계 문서 (DESIGN.md) | v0.2 — 손상 섹션 복원 완료 |
| README.md | 초안 작성됨 |
| pyproject.toml | 초안 작성됨 (의존성 정의만, 미설치) |
| 소스 스켈레톤 (`src/anvyc/`) | 디렉터리/`__init__.py`/`cli.py` placeholder |
| Adapter 구현 | 미착수 |
| Secret scanner | 미착수 |
| 테스트 | 미착수 |
| `.anvyc/` runtime 디렉터리 | 미생성 (실 사용자 환경에서 `anvyc init` 호출 시 생성 예정) |
| Git 저장소 초기화 | 미수행 |
| 패키지 설치/배포 | 미수행 |

---

## 2. 확정 결정 (Decisions)

| 일자 | 결정 | 근거 |
|---|---|---|
| 2026-05-17 | MVP 언어로 Python 채택 | adapter 실험/반복 속도, plist/yaml/json 처리 라이브러리 풍부 |
| 2026-05-17 | chezmoi는 직접 사용하지 않고 안전 원칙만 참고 | Claude/Cursor/iTerm2 특화 정책 필요 |
| 2026-05-17 | secret 기본 제외 | credentials 유출 시 비용/계정 위험 |
| 2026-05-17 | apply 전 local backup 의무화 | 부분 적용 실패 시 복구 가능성 확보 |
| 2026-05-17 | iTerm2 전체 plist 동기화 금지 | window state/recent sessions/local path 등 장비별 휘발 데이터 포함 |
| 2026-05-17 | MVP target: macOS only | 1차 사용자는 Mac 개발자 |
| 2026-05-18 | DESIGN.md v0.2 재작성 | v0.1의 일부 섹션 텍스트 손상으로 정합성 부족 |
| 2026-05-18 | Cursor adapter 3-layer 모델 채택 (A: ~/.cursor, B: Library/User, C: project-local opt-in) | 실제 디렉터리 토폴로지 조사 결과 단일 평면 목록으로는 secret/캐시/symlink 처리 정책을 표현하기 부족 |
| 2026-05-18 | `~/.cursor/cli-config.json` 기본 제외 | 0600 perms + 토큰 가능성 확인. v0.1 잘못된 include 정정 |
| 2026-05-18 | Cursor symlink follow=false 기본, metadata만 기록 | 실측: `rules.bak-* → 외부 repo(role-based-ruleset)` 패턴 존재. 의도치 않은 외부 컨텐츠 백업 방지 |
| 2026-05-18 | Doctor `cross-user` check 도입, 5단계 severity (info/info-aliased/warning-foreign/warning-dangling/critical) | 실측: `/Users/aliasuser → /Users/edward` symlink. `~/.cursor/projects/`의 13/20이 alias 경로, SSH config 6라인이 alias 경로. 같은 머신에서는 동작하지만 다른 머신에 적용하면 broken |
| 2026-05-18 | Doctor는 read-only, `--fix` 모드는 v0.2 이후 | 자동 수정은 부작용이 크고 사용자 의도와 어긋날 수 있음. 1차는 진단/제안만 |
| 2026-05-18 | `src/anvyc/checks/` 신규 패키지 도입 | Check 컴포넌트를 doctor·adapter validate·scan-secrets 등에서 재사용. 단일 CheckResult 타입으로 통합 보고 |
| 2026-05-18 | `Finding` → `CheckResult` 통합 (#16) | adapter validate 결과를 doctor 리포트로 직접 합치기 위해 타입 일원화. `adapters/base.py:Finding` 제거 |
| 2026-05-18 | Shell adapter end-to-end backup PoC 완성 | DESIGN.md §12.1 절차를 실 동작으로 검증. shell → security scan → copy → hash → metadata.json → current symlink. 다른 adapter 추가 시 ADAPTERS 레지스트리에 등록만 하면 동일 파이프라인 |
| 2026-05-18 | Backup 정책: secret scan 결과 critical/high 또는 medium(force 미지정)에서 차단 | DESIGN.md §13.2 정책 그대로. shell 파일은 통상 generic_secret 패턴에 걸리는 export 라인이 있을 수 있어 `--force` 안내가 UX 상 중요 |
| 2026-05-18 | macOS venv 트랩 회피: `chflags -R nohidden .venv` 필수 | Python 3.13 site.py 가 UF_HIDDEN flag 있는 .pth 를 스킵. `.`-prefix 디렉터리는 macOS 에서 자동으로 hidden flag 가 붙어 editable install 의 .pth 가 무시됨 (https://github.com/python/cpython/issues/116727). README/doctor 가 안내해야 함 |
| 2026-05-18 | v0.1.0 MVP 필수 경로 = Phase 1 + Phase 2 + Phase 6 | apply/restore → 어댑터 6개 → 테스트/패키징. Git sync / Doctor 보강 / encryption 은 v0.2 |
| 2026-05-18 | Phase 1 (apply/restore) 가 Phase 2 의 선행 | apply 기본 구현이 있어야 새 어댑터가 즉시 backup+apply 양쪽 동작. 새 어댑터마다 별도 apply 구현 불필요 |
| 2026-05-18 | 어댑터 추가 순서: aws → gh → pulumi → claude → iterm2 → cursor | 단순 단일 파일 → 디렉터리 재귀 → plist → 3-layer 순으로 복잡도 점증. claude 에서 디렉터리 재귀 수집 인벤토리 구조를 1회 검증 |

---

## 3. 열린 결정 (Open Questions)

| 항목 | 후보 | 메모 |
|---|---|---|
| 암호화 도구 | `age` vs `cryptography` | chezmoi와의 호환성 고려 시 `age` 우세 |
| 패키지 배포 채널 | `pipx` vs `uv tool install` vs `Homebrew tap` | 우선 `pipx`로 검증, 이후 Homebrew tap 검토 |
| password manager 연동 | 1Password CLI(`op`) | MVP 이후 |
| 다중 계정 처리 모델 | profile-per-host vs profile-per-account | 사용 사례 수집 후 결정 |
| Cursor globalStorage allowlist 기본값 | empty vs 추천 extension 5종 | 사용자 피드백 수집 후 결정 |
| Cursor `mcp.json` 토큰 처리 | 마스킹 후 별도 secret store / 항상 제외 / scan만 | 우선 마스킹 + secret store 방향(`mask_mcp_tokens: true` 기본) |
| Cursor `plans/` 포함 여부 | 포함(기본) vs 제외 | 개인 plan에 민감 정보 포함 시 risk. 1차는 포함 + scan, 사용 후 재검토 |
| Layer C(projects) 활성화 UX | yaml 직접 편집 vs `anvyc cursor project add <path>` | 사용 빈도 보고 결정 |
| Doctor `--fix` 모드 자동 정규화 범위 | SSH config의 `/Users/<alias>/` → `~/` 정규화만 / 전체 dotfile 일괄 정규화 | v0.2에서 결정. 1차는 SSH config만 후보 |
| Cross-user alias auto-detect | `/Users/<x> → /Users/<y>` symlink를 자동 감지해 alias로 인정 vs 명시 선언만 인정 | 보수적으로 명시 선언만 인정 (오탐 가능성 차단) |
| Phase 3 (Git sync) v0.1.0 포함 여부 | 포함 / v0.2 연기 | DESIGN.md §29.6 Q1. 사용 패턴 결정 |
| iterm2 safe subset 키 목록 확정 시점 | DESIGN.md §14.2 그대로 / 실사용자 환경 기준 재조정 | DESIGN.md §29.6 Q2. P2.5 시작 전 결정 |
| Cursor projects 모드 default roots 기본값 | empty 유지 / 자동 감지 후 제안 | DESIGN.md §29.6 Q3. P2.6 시작 전 결정 |
| v0.1.0 secret encryption 제공 범위 | 없음 (수동 `~/.anvyc-secrets/` 가이드) / age 기본 통합 | DESIGN.md §29.6 Q4. Phase 5 일정 영향 |
| CLI 진입점 이름 | `anvyc` (확정) | 단어 변경 없음 |

---

## 4. 가정 (Assumptions)

1. 1차 사용자는 macOS 26+를 사용한다.
2. shell은 zsh이다. (bash는 향후 확장)
3. Cursor/Claude Code는 사용자별 단일 설치를 가정한다.
4. iTerm2는 v3.5+ plist 구조를 따른다.
5. AWS CLI v2, GitHub CLI 최신 stable, Pulumi 최신 stable을 가정한다.
6. Python 3.11 이상이 시스템에 존재한다.
7. backup repo는 사용자가 직접 소유한 private Git repo다.

---

## 5. 작업 우선순위 (Roadmap snapshot)

### 5.1 즉시 (D+0 ~ D+3)

1. ~~DESIGN.md v0.2 정합성 확보~~ (완료)
2. ~~README.md / CONTEXT.md / pyproject.toml 생성~~ (완료)
3. ~~`src/anvyc/` 스켈레톤 생성~~ (완료)
4. `anvyc init` / `anvyc doctor` 최소 동작 구현
5. 설정 로더 (`anvyc.yaml`) 구현

### 5.2 1주차

- shell / git / aws adapter 1차 구현
- secret scanner v0 (패턴 6종)
- `backup` 명령 end-to-end

### 5.3 2주차

- cursor / claude / iterm2 adapter
- `diff` / `apply --dry-run` / `apply`
- `restore` 및 local-backup 의무화
- pre-commit hook 통합

### 5.4 3주차

- 테스트 보강 (unit/integration)
- 실제 Mac 2대 end-to-end 검증
- pipx 패키징 및 v0.1.0 릴리즈

---

## 6. 작업 흐름 규칙

- 디렉터리/파일 구조 또는 정책 변경 시 본 문서 → DESIGN.md → README.md 순서로 갱신한다.
- adapter 추가/제거 시 §1 현재 상태 표와 §5 로드맵을 동시에 갱신한다.
- 외부 라이브러리 채택은 §2 결정 표에 일자/근거와 함께 추가한다.

---

## 7. 참고 자료

- chezmoi: https://chezmoi.io/
- chezmoi GitHub: https://github.com/twpayne/chezmoi
- chezmoi age 암호화: https://chezmoi.io/user-guide/encryption/age/
- chezmoi password manager integration: https://chezmoi.io/user-guide/password-managers/
- Typer: https://typer.tiangolo.com/
- Rich: https://rich.readthedocs.io/
- pydantic: https://docs.pydantic.dev/
- plistlib: https://docs.python.org/3/library/plistlib.html

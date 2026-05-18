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

---

## 3. 열린 결정 (Open Questions)

| 항목 | 후보 | 메모 |
|---|---|---|
| 암호화 도구 | `age` vs `cryptography` | chezmoi와의 호환성 고려 시 `age` 우세 |
| 패키지 배포 채널 | `pipx` vs `uv tool install` vs `Homebrew tap` | 우선 `pipx`로 검증, 이후 Homebrew tap 검토 |
| password manager 연동 | 1Password CLI(`op`) | MVP 이후 |
| 다중 계정 처리 모델 | profile-per-host vs profile-per-account | 사용 사례 수집 후 결정 |
| Cursor globalStorage allowlist 기본값 | empty vs 추천 extension 5종 | 사용자 피드백 수집 후 결정 |
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

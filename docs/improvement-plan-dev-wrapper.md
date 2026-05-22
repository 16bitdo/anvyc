# anvyc 개선 계획 — dev wrapper 의 경로·Python 버전 하드코딩 제거

> 작성일: 2026-05-21
> 대상 버전: v0.11.0 기준
> 검토 범위: `~/.local/bin/anvyc` self-heal wrapper + 이를 안내·문서화한 문서 (`docs/troubleshooting-macos.md` §4, README §5.6, CONTRIBUTING.md §2.2, `docs/mcp-integration.md`)
> 배경: 프로젝트 `~/Documents/anvyc` → `~/dev/anvyc` 이전 시 wrapper 의 절대경로 하드코딩(`VENV=/Users/edward/Documents/anvyc/.venv`)이 끊겨 `anvyc` 명령 전체가 `No such file or directory` 로 실행 불능이 됨. 2026-05-21 재설치(`~/dev/anvyc/.venv` editable 재생성 + wrapper `VENV` 경로 수정)로 응급 복구 완료. 본 문서는 재발 방지를 위한 구조 개선 계획.
> 상태: **리뷰 완료 / 수정 미착수** — 본 문서를 인계 기준으로 후속 PR 진행.

---

## 0. TL;DR

anvyc 의 dev self-heal wrapper(`~/.local/bin/anvyc`)는 venv 절대경로·Python 마이너 버전·사용자명을 모두 하드코딩한다. 디렉터리 이전이나 Python 업그레이드 한 번에 `anvyc` 명령 전체가 죽고, 그중 **Python 버전 불일치는 에러 없이 침묵 실패**한다.

- **근본 문제 2가지**: (1) wrapper 가 README/CONTRIBUTING 어디에도 생성 절차가 없는 **수작업 산출물** — 손으로 만들고 손으로 고쳐 좌표가 굳음. (2) wrapper 본문이 정적 절대좌표 — `$HOME`·glob 같은 동적 해석을 전혀 안 씀.
- **침묵 실패**: `PTH` 의 `python3.13` 하드코딩 → venv 를 다른 마이너 버전으로 만들면 `[[ -e "$PTH" ]]` 가 False → self-heal 을 조용히 건너뜀. anvyc 는 깨지는데 wrapper 는 정상 종료 코드를 반환.
- **권장**: 단순 경로 치환이 아니라 (a) wrapper 본문을 환경 비의존(동적 탐색)으로 재작성 + (b) contributor 설치를 `scripts/dev-install.sh` 로 자동화 + (c) wrapper 정본을 저장소 코드로 SoT 단일화. 그래야 다음 이전·업그레이드 때 재발하지 않음.

---

## 1. 심각도별 인벤토리

조사 기준: `~/.local/bin/anvyc` 실파일 + `git grep` (v0.11.0, 2026-05-21, HEAD `1bc1f84`).

### 🔴 Tier 1 — 침묵 실패 / 실행 불능 (실질 버그)

| 위치 | 내용 |
|---|---|
| `~/.local/bin/anvyc:11` | `VENV="/Users/edward/dev/anvyc/.venv"` — venv 절대경로 하드코딩. 디렉터리 이전 시 `exec "$VENV/bin/anvyc"` 가 `No such file or directory` → **anvyc 명령 전체 실행 불능**. 2026-05-21 실제 발생. |
| `~/.local/bin/anvyc:12` | `PTH=".../lib/python3.13/site-packages/_editable_impl_anvyc.pth"` — Python 마이너 버전 하드코딩. venv 를 3.12/3.14 로 만들면 경로 불일치 → `[[ -e "$PTH" ]]` False → **self-heal 침묵 무력화**. anvyc 는 `ModuleNotFoundError` 로 깨지는데 wrapper 는 정상 종료 — 진단 난이도 최악. |

- `~/.local/bin/anvyc` 는 **git 비추적 로컬 파일**. 이 결함은 머신별로 잠복하며 저장소 CI/리뷰로 잡히지 않는다.
- `set -e` + `[[ -e "$PTH" ]]` 가드 때문에 `.pth` 부재는 에러를 안 내고, venv 부재는 `exec` 단계에서야 실패한다. 두 하드코딩 모두 "있으면 조용, 어긋나면 갑자기" 패턴.

### 🟠 Tier 2 — 이식성 / SoT 결함

| 위치 | 내용 | 비고 |
|---|---|---|
| `~/.local/bin/anvyc:11` | `VENV` 가 `/Users/edward/...` 풀 절대경로 — 사용자명 `edward` 하드코딩 | 다른 머신/사용자 비이식. troubleshooting §4.2 예시는 `$HOME` 을 쓰는데 **실제 설치본이 문서보다 더 나쁨** |
| 생성 절차 부재 | README §5.6·CONTRIBUTING §2.2 둘 다 `source .venv/bin/activate` 만 안내, wrapper 생성 단계 없음 | wrapper 는 troubleshooting §4.2 예시를 보고 수동 작성 — 자동화·검증 없음 |
| `docs/troubleshooting-macos.md:96-97` | 문서의 wrapper 예시가 `$HOME/Documents/anvyc/.venv` (구 경로) + `python3.13` | 경로 이전 미반영. `improvement-plan-scan-root.md` Tier 3 에도 `troubleshooting-macos.md:96` 등재 — 본 계획은 단순 치환을 넘어 동적화로 대체 |

### 🟡 Tier 3 — 문서 분산 / 경미

| 위치 | 내용 |
|---|---|
| `docs/mcp-integration.md` §2·§3 | MCP command 를 `"anvyc"` (PATH 의존) 로 등록 — wrapper 직접 의존은 아니나, troubleshooting §4.2 가 "MCP 도 `~/.local/bin/anvyc` 절대경로로 등록 권장" 이라 안내. wrapper 가 깨지면 MCP server 도 동반 사망 |
| `docs/troubleshooting-macos.md` §4.3 | venv 재생성 예시가 `~/Documents` 기준 (`improvement-plan-scan-root.md` 와 중복 인지) |
| README §5.6 / CONTRIBUTING §2.2 | contributor 설치가 2곳에 각각 서술 (`python -m venv` vs `uv venv`) — 약한 SoT 분산 |

### ✅ 모범 선례 — 변경 불요

`install.sh` 는 정식(릴리스) 설치를 `uv tool install` / `pipx install` 로 위임 — 격리 tool venv 라 `.pth` 미사용, UF_HIDDEN 트랩 무관(troubleshooting §5 표). 즉 **일반 사용자 경로는 이미 견고**하다. 본 결함은 editable 을 쓰는 **개발(contributor) 경로에 국한**된다.

---

## 2. 설계 지적

1. **wrapper 가 수작업 산출물**: 생성·갱신을 자동화하는 스크립트/명령이 없다. 손으로 만들므로 "현재 환경의 절대 좌표"가 그대로 박힌다. 환경이 바뀌면 또 손으로 고쳐야 하고, 고치는 걸 잊으면 침묵 실패.
2. **wrapper 본문이 정적**: `$HOME`, `python3.*` glob, 환경변수 override 같은 동적 해석을 전혀 안 쓴다. 단 한 줄도 환경 변화에 적응하지 못한다.
3. **침묵 실패 모드**: `.pth` 경로 불일치 시 wrapper 는 에러를 내지 않는다. self-heal 의 목적(깨짐 자동 복구)과 정반대로, "복구도 안 되고 경고도 없는" 상태를 만든다.
4. **SoT 부재**: wrapper 의 정본 형태가 troubleshooting §4.2 예시 1곳에만 있고, README·CONTRIBUTING 은 wrapper 를 아예 모른다. `improvement-plan-scan-root.md` 가 지적한 것과 같은 "동일 개념 다곳 분산" 패턴.
5. **(근본) `.pth` 의존 자체가 트랩의 입구**: UF_HIDDEN 이 문제 되는 건 editable 이 `.pth` 로 `sys.path` 를 조작하기 때문이다. self-heal 은 증상 대응(`.pth` 를 계속 nohidden 으로 유지)이다. `.pth` 를 거치지 않는 경로(PYTHONPATH 주입)면 트랩 자체가 사라진다 — §3.4.

---

## 3. 권장 수정 계획

### 3.1 핵심 — wrapper 본문을 환경 비의존으로 재작성 (High)

현재 wrapper 의 모든 하드코딩을 동적 해석으로 교체. 새 wrapper 초안(`scripts/anvyc-wrapper.sh` 로 저장소에 두고 버전 관리):

```bash
#!/bin/bash
# anvyc dev wrapper — editable .pth 의 macOS UF_HIDDEN self-heal.
# 경로·Python 버전 비의존: $HOME + glob + ANVYC_VENV override.
set -euo pipefail

# 1) venv 위치: ANVYC_VENV 우선, 없으면 알려진 후보 탐색.
venv="${ANVYC_VENV:-}"
if [[ -z "$venv" ]]; then
  for cand in "$HOME/dev/anvyc/.venv" "$HOME/Documents/anvyc/.venv"; do
    [[ -x "$cand/bin/anvyc" ]] && { venv="$cand"; break; }
  done
fi
if [[ -z "$venv" || ! -x "$venv/bin/anvyc" ]]; then
  echo "anvyc: venv 를 찾지 못했습니다. ANVYC_VENV 로 .venv 경로를 지정하세요." >&2
  exit 1
fi

# 2) editable .pth self-heal — Python 버전 무관 glob, 파일명 변형 모두 대응.
shopt -s nullglob
for pth in "$venv"/lib/python3.*/site-packages/_editable_impl_anvyc.pth \
           "$venv"/lib/python3.*/site-packages/__editable__.anvyc-*.pth; do
  chflags nohidden "$pth" 2>/dev/null || true
done
shopt -u nullglob

exec "$venv/bin/anvyc" "$@"
```

개선점:
- `$HOME` → 사용자명 하드코딩 제거 (Tier 2)
- `python3.*` glob → Python 마이너 버전 무관 (Tier 1 #2)
- `ANVYC_VENV` env override + 후보 탐색 → 디렉터리 이전 내성 (Tier 1 #1)
- venv 부재 시 **명시적 stderr 에러 + 비정상 종료** → 침묵 실패 제거
- `_editable_impl_*` / `__editable__.*` 양쪽 glob → hatchling 버전별 파일명 변형 대응 (troubleshooting §2)

> 주의: 새 wrapper 도 결국 로컬 파일이다. §3.2 의 스크립트가 이 본문을 **그대로 설치**하게 하여 SoT 를 코드화한다.

### 3.2 핵심 — contributor 개발 설치 자동화 `scripts/dev-install.sh` (High)

저장소에 `scripts/` 디렉터리(현재 부재)를 신설하고 멱등 스크립트 `dev-install.sh` 추가. 한 번 실행으로 다음을 처리:

1. venv 생성 — `python3 -m venv .venv` (또는 `uv venv`). 기존 venv 있으면 재사용.
2. editable 설치 — `pip install -e ".[dev]"`.
3. §3.1 의 동적 wrapper(`scripts/anvyc-wrapper.sh`)를 `~/.local/bin/anvyc` 로 복사(+`chmod +x`). 기존 파일은 `anvyc.bak-<ts>` 로 백업.
4. `~/.local/bin` 이 PATH 에 없으면 경고.
5. 설치 검증 — `anvyc --version` 호출.

효과: 디렉터리 이전·Python 업그레이드·머신 교체 시 **스크립트 재실행 한 번**으로 복구. wrapper 본문이 저장소에서 버전 관리됨 → 리뷰·CI 대상이 됨.

- README §5.6 / CONTRIBUTING §2.2 를 이 스크립트 호출 기준으로 갱신.
- CLI 서브커맨드(`anvyc dev install-wrapper`)로 넣는 방안도 있으나, anvyc 가 깨졌을 때 자기 자신으로 복구할 수 없는 순환 의존 → **셸 스크립트가 적절**.

### 3.3 문서 SoT 통합 (Medium)

- wrapper 정본을 `scripts/anvyc-wrapper.sh` (코드)로 단일화. `troubleshooting-macos.md` §4.2 는 그 파일을 **인용/링크**만 한다.
- `troubleshooting-macos.md` §4.2·§4.3 의 `~/Documents` → `~/dev` 및 `python3.13` → glob 갱신 (`improvement-plan-scan-root.md` Tier 3 와 동일 PR 에서 처리 가능).
- README §5.6 / CONTRIBUTING §2.2 에 "macOS contributor 는 `scripts/dev-install.sh` 사용" 1줄 추가.
- `mcp-integration.md` 에 "editable 개발 환경의 MCP 등록은 wrapper 절대경로 사용" 주석 — wrapper 경로가 §3.1 로 안정화되므로 권고 강도 유지 가능.

### 3.4 (탐색) `.pth` 트랩 근본 회피 — PYTHONPATH 주입 (Low / 별도 spike)

self-heal 은 증상 대응이다. wrapper 가 `.pth` 대신 `PYTHONPATH` 로 src 를 주입하면 UF_HIDDEN 트랩 자체가 사라진다:

```bash
exec env PYTHONPATH="$repo/src" "$venv/bin/python" -m anvyc "$@"
```

선행 조건 / 검증 필요:
- **`src/anvyc/__main__.py` 부재** — 현재 `python -m anvyc` 불가. `__main__.py`(`from anvyc.cli import app; app()`) 추가 필요.
- editable `.pth` 와 `PYTHONPATH` 동시 존재 시 `sys.path` 우선순위·중복 임포트 확인.
- 채택 시 `chflags` 자체가 불필요해져 wrapper 가 크게 단순화된다. 단 동작 변경 폭이 커 **별도 spike PR 로 검증** 후 판단.

### 3.5 작업 분리 권장

- **PR 1 (High)**: §3.1 동적 wrapper 템플릿 + §3.2 `scripts/dev-install.sh` + README/CONTRIBUTING 갱신.
- **PR 2 (Medium)**: §3.3 문서 SoT 통합 — `improvement-plan-scan-root.md` 의 `~/Documents`→`~/dev` 문서 치환과 합쳐 1 PR 가능.
- **PR 3 (Low, 선택)**: §3.4 PYTHONPATH 우회 spike — `__main__.py` 추가 포함.
- anvyc 룰: 구조 변경 시 README·CONTEXT.md·DESIGN.md 동기 갱신. DESIGN.md 에 dev wrapper 설계 항 추가 검토(현재 `venv-hidden-flag` check 만 §27.1.1 등재).

---

## 4. 검증 방법

```bash
cd ~/dev/anvyc

# 1) dev-install 스크립트 멱등성 — 두 번 실행해도 동일 결과
bash scripts/dev-install.sh && bash scripts/dev-install.sh
anvyc --version          # v0.11.0

# 2) Python 버전 비의존 — 다른 마이너로 venv 재생성 후에도 self-heal 동작
rm -rf .venv && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
chflags hidden .venv/lib/python3.*/site-packages/_editable_impl_anvyc.pth
anvyc --version          # wrapper glob 이 3.12 경로를 잡아 self-heal → 정상

# 3) 디렉터리 이전 내성 — venv 경로가 바뀌어도 ANVYC_VENV 로 복구
ANVYC_VENV=$PWD/.venv anvyc --version

# 4) 침묵 실패 제거 — venv 없을 때 명시적 에러 + 비정상 종료
( ANVYC_VENV=/nonexistent anvyc --version; echo "exit=$?" )
# 기대: stderr 에러 메시지 + exit=1

# 5) self-heal 실효 — verbose trace 에 "Skipping hidden" 이 안 보여야
.venv/bin/python -v -c pass 2>&1 | grep -c "Skipping hidden .pth"   # 0
```

기대: venv 를 어느 Python 마이너로 만들든·어디로 옮기든 `anvyc` 가 동작하고, 복구 불가 상황에서는 침묵 대신 명시적 에러를 낸다.

---

## 5. 리스크 / 주의

| 리스크 | 완화 |
|---|---|
| `~/.local/bin/anvyc` 는 git 비추적 — 스크립트가 기존 파일을 덮어씀 | 설치 전 기존 파일 백업(`anvyc.bak-<ts>`), diff 표시 후 교체 |
| 후보 경로 탐색이 엉뚱한 venv(다른 프로젝트)를 잡을 가능성 | 후보를 anvyc 전용 경로로 한정 + `bin/anvyc` 존재까지 확인. `ANVYC_VENV` 가 항상 최우선 |
| `set -u` 도입 시 미정의 변수에서 즉시 종료 | 초안은 `${ANVYC_VENV:-}` 로 기본값 처리 — 검토 완료 |
| §3.4 PYTHONPATH 우회가 editable `.pth` 와 충돌 | 별도 spike PR 로 격리 검증, PR 1 에는 미포함 |
| MCP 등록이 구 wrapper 절대경로를 가리킨 채로 남음 | dev-install 스크립트가 wrapper 를 같은 경로(`~/.local/bin/anvyc`)에 재설치 → MCP 설정 불변. 경로 안정성 확보 |

---

## 6. 부록 — 출처

- 발단: 2026-05-21 `anvyc` 재설치 작업 — `~/Documents/anvyc/.venv` 부재로 wrapper 실행 불능 확인, `~/dev/anvyc/.venv` editable 재생성 + wrapper `VENV` 경로 수정으로 응급 복구.
- 관련 문서: `docs/troubleshooting-macos.md` (UF_HIDDEN 원인·self-heal 패턴), `docs/archive/improvement-plan-scan-root.md` (동일 `~/Documents`→`~/dev` 이전 맥락, 문서 치환 범위 공유).
- 조사 시점 anvyc: v0.11.0, branch `main`, HEAD `1bc1f84`.

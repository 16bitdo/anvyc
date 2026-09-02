# Homebrew 로 anvyc 설치 / 검증 가이드

> **누구를 위한 문서**: `anvyc` 를 macOS 머신에 처음 설치하거나, 새 머신 부트스트랩 시 정상 동작을 확인하려는 **사용자** (=consumer) 관점 가이드.
>
> **publisher (=anvyc 메인테이너) 관점**의 release / Formula 갱신 절차는 [docs/homebrew-publishing.md](homebrew-publishing.md) 참조.

---

## 1) 사전 요구

| 항목 | 요구 |
|---|---|
| OS | macOS (Intel / Apple Silicon 모두) |
| Homebrew | 최신 (`brew --version` 으로 확인, 미설치 시 [brew.sh](https://brew.sh) 참고) |
| Python | `python@3.13` (Formula 가 `depends_on` 으로 자동 설치) |
| 네트워크 | GitHub Releases (`github.com`) + PyPI 파일 호스트 (`files.pythonhosted.org`) 접근 가능 |

확인:

```bash
brew --version
sw_vers -productName  # macOS
sw_vers -productVersion  # macOS 버전
```

---

## 2) 최초 설치

```bash
# 1. tap 추가 (한 번만)
brew tap 16bitdo/anvyc

# 2. tap 신뢰 (한 번만 — Homebrew 6.x 부터 필수)
brew trust --tap 16bitdo/anvyc

# 3. 설치
brew install anvyc

# 4. 검증
anvyc --version
# 기대 출력: anvyc vX.Y.Z (릴리스 빌드는 커밋 SHA 를 붙이지 않는다)
```

> **2번을 건너뛰면 설치가 되지 않는다.** Homebrew 6.x 는 비공식 tap 의 formula
> 로드를 기본 차단하므로 `Error: Refusing to load formula 16bitdo/anvyc/anvyc
> from untrusted tap` 이 뜬다. 신뢰 항목은 `~/.homebrew/trust.json` 에 저장된다.

`brew install anvyc` 가 자동으로:
- `python@3.13` (의존성) 설치
- anvyc sdist (`anvyc-X.Y.Z.tar.gz`) 다운로드 + sha256 검증
- Python 의존 패키지 (`typer` / `rich` / `pyyaml` / `pathspec` + transitive deps) 다운로드 + sha256 검증
- virtualenv 생성 후 anvyc 설치

소요 시간 ~30초 ~ 2분 (네트워크 / 캐시 상태 의존).

---

## 3) 새 머신 부트스트랩 시뮬레이션

기존 머신에서 새 머신과 동일한 절차 검증:

```bash
# 1. 기존 tap / 설치 제거 (있는 경우만)
brew uninstall anvyc 2>/dev/null || true
brew untap 16bitdo/anvyc 2>/dev/null || true

# 2. 캐시 비우기 (선택, sha256 캐시 누적이 의심될 때)
brew cleanup --prune=all

# 3. 부트스트랩 절차 그대로
brew tap 16bitdo/anvyc
brew trust --tap 16bitdo/anvyc
brew install anvyc

# 4. 검증
anvyc --version
which anvyc
# 기대: /opt/homebrew/bin/anvyc (Apple Silicon) 또는 /usr/local/bin/anvyc (Intel)
```

새 머신 = 본 절차에서 (1) 만 skip 한 시퀀스.

---

## 4) 사후 검증 체크리스트

| 검증 | 명령 | 기대 결과 |
|---|---|---|
| 버전 | `anvyc --version` | `anvyc vX.Y.Z` (릴리스 빌드는 SHA 미표기) |
| 위치 | `which anvyc` | `$(brew --prefix)/bin/anvyc` |
| Python 결합 | `head -1 "$(which anvyc)"` | `#!` 로 시작하는 brew python@3.13 경로 |
| 환경 health | `anvyc doctor` | 모든 check `OK` (실패 시 §6 참조) |
| MCP server | `anvyc mcp --help` | usage 출력 (MCP 활용 시 `[mcp]` extras 추가 설치 필요할 수 있음) |
| backup target list | `anvyc backup --list-targets` 또는 `anvyc init --interactive` | tools/projects 카탈로그 출력 |

> `anvyc doctor` 가 실패하면 본 패키지 결함이 아닌 **사용자 머신의 환경 정합성 문제** 가 대부분. doctor 출력의 각 check 항목별 권고를 따라간 후 다시 확인.

---

## 5) 업데이트 (새 anvyc 버전 출시 시)

```bash
# 1. Formula 최신 받기
brew update

# 2. anvyc 업그레이드
brew upgrade anvyc

# 3. 검증
anvyc --version  # 새 버전
```

특정 버전 강제 / 다운그레이드는 Homebrew 정책상 권장되지 않음. 이전 버전 필요 시 anvyc Release 페이지에서 wheel 다운로드 후 venv 에 `pip install` (Homebrew 외 별도 환경).

---

## 6) 트러블슈팅

### sha256 mismatch

```
Error: SHA256 mismatch
Expected: 16ed6555...
  Actual: <다른 값>
```

원인 후보:
- 네트워크 중간자 (회사 프록시) 가 GitHub Releases 응답 변조
- Homebrew 캐시에 옛 release 파일 잔존
- anvyc 메인테이너가 release artifact 를 재빌드 (드물지만 가능)

해결:

```bash
brew cleanup --prune=all
brew untap 16bitdo/anvyc
brew tap 16bitdo/anvyc
brew trust --tap 16bitdo/anvyc
brew install anvyc
```

여전히 실패하면 [anvyc Issues](https://github.com/16bitdo/anvyc/issues) 에 위 actual sha256 + macOS 버전 + Homebrew prefix (`brew --prefix`) 포함 보고.

### virtualenv_install_with_resources 실패

```
Error: resource '<pkg>' failed
```

원인: anvyc 의 `pyproject.toml` 과 Formula 의 `resource` block 이 불일치 (메인테이너 측 버그 — release 직후 발견되면 패치 release 로 빠르게 수정됨).

해결: 즉시 [anvyc Issues](https://github.com/16bitdo/anvyc/issues) 보고 (실패 패키지 이름 + brew install 출력 전문). 임시 회피는 wheel 직접 설치:

```bash
python3.13 -m venv ~/.local/anvyc-venv
~/.local/anvyc-venv/bin/pip install \
  "https://github.com/16bitdo/anvyc/releases/download/vX.Y.Z/anvyc-X.Y.Z-py3-none-any.whl"
ln -s ~/.local/anvyc-venv/bin/anvyc ~/.local/bin/anvyc
```

### 설치는 성공했는데 `anvyc` 실행이 `ModuleNotFoundError` 로 죽는다

```
$ anvyc --version
ModuleNotFoundError: No module named 'typer._click'
```

원인: Formula 의 `resource` 가 낡아 의존 라이브러리가 너무 오래된 버전으로
설치된 경우다. **설치는 rc=0 으로 끝나고 sha256 도 맞으므로 실패처럼 보이지
않는다** — 실행할 때만 드러난다.

먼저 최신 formula 를 받았는지 확인한다:

```bash
brew update && brew upgrade anvyc
```

그래도 재현되면 메인테이너 측 결함이다.
[anvyc Issues](https://github.com/16bitdo/anvyc/issues) 에 `--version` 출력
전문과 `brew info anvyc` 를 함께 보고한다. 임시 회피는 위의 wheel 직접 설치.

> 실사례 — v0.21.0~v0.22.0 이 이 상태였다(2026-09-02 수정, homebrew-anvyc#8).
> resource 가 초기 formula 이후 갱신되지 않아 typer 가 0.12.5 에 고정돼 있었다.

### `python@3.13: command not found` (드물게)

```bash
brew install python@3.13
brew reinstall anvyc
```

### `anvyc --version` 출력이 옛 버전

- 다른 경로에 옛 anvyc 가 있을 가능성. `which -a anvyc` 로 모든 경로 확인.
- pyenv / asdf / 수동 venv 에 설치한 anvyc 가 `$PATH` 상 우선이라면 정리 또는 `brew` 경로를 `$PATH` 앞쪽으로.

```bash
which -a anvyc
echo "$PATH" | tr ':' '\n' | head -20
```

### Apple Silicon vs Intel 경로 차이

| 머신 | brew prefix | anvyc 경로 |
|---|---|---|
| Apple Silicon (M1/M2/...) | `/opt/homebrew` | `/opt/homebrew/bin/anvyc` |
| Intel | `/usr/local` | `/usr/local/bin/anvyc` |
| Rosetta 2 환경 (Intel brew on Apple Silicon) | `/usr/local` | `/usr/local/bin/anvyc` (혼선 주의) |

혼선 회피: `which anvyc` 와 `brew --prefix` 의 prefix 가 일치하는지 확인. 두 brew 가 공존하는 환경에서는 의도한 한쪽만 사용.

---

## 7) 제거

```bash
# 1. 패키지 제거
brew uninstall anvyc

# 2. tap 제거 (선택)
brew untap 16bitdo/anvyc

# 3. 사용자 데이터 정리 (선택, anvyc backup state 제거)
# 주의: ~/.anvyc/ 에 anvyc backup 데이터 보관됨. 본인 backup 본은 다른 머신에서 pull 가능한지 확인 후 삭제.
ls -la ~/.anvyc/
# rm -rf ~/.anvyc/   # 명시 확인 후 직접 실행
```

`~/.anvyc/` 는 anvyc 가 관리하는 사용자 backup 영역. brew uninstall 은 본 디렉터리를 건드리지 않음 — 영구 삭제는 사용자가 명시적으로 결정.

---

## 관련 문서

- [docs/homebrew-publishing.md](homebrew-publishing.md) — anvyc 메인테이너의 release / Formula 갱신 절차
- [DESIGN.md](../DESIGN.md) — anvyc 의 전반 설계 / 도구 카탈로그
- [RELEASE_NOTES.md](../RELEASE_NOTES.md) — 버전별 변경사항
- [anvyc Issues](https://github.com/16bitdo/anvyc/issues) — 설치 / 동작 이슈 보고

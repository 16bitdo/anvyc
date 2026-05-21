# anvyc troubleshooting — macOS UF_HIDDEN + Python 3.13 editable install

> macOS + Python 3.13.13+ + uv 조합에서 editable install (`pip install -e .` /
> `uv pip install -e .`) 의 `.pth` 가 silent skip 되어 anvyc CLI 가 `ModuleNotFoundError`
> 로 깨지는 이슈와 self-heal wrapper 패턴.

자매 문서:
- [mcp-integration.md](./mcp-integration.md) — Claude Code / Cursor MCP 등록
- [DESIGN.md §27](../DESIGN.md) — doctor / 환경 진단

---

## 1. 증상

```
$ anvyc --version
Traceback (most recent call last):
  File "/path/to/.venv/bin/anvyc", line 4, in <module>
    from anvyc.cli import app
ModuleNotFoundError: No module named 'anvyc.cli'
```

editable install 직후에는 정상 동작하다가, 수 분 ~ 수십 분 후 갑자기 깨지는
패턴. `uv pip install -e .` 재실행하면 일시 복구되지만 다시 깨짐.

영향 범위:
- macOS (UF_HIDDEN flag 보유)
- Python **3.13.13 이상** (site.addpackage hidden-skip 정책 적용 버전)
- `.venv` 디렉터리 안의 editable install (`_editable_impl_<name>.pth`)
- non-editable install (`pip install anvyc`) 은 영향 없음

---

## 2. 원인

Python 3.13.13 의 `site.addpackage()` ([Lib/site.py:177-180](https://github.com/python/cpython/blob/v3.13.13/Lib/site.py#L177-L180)) 는
macOS `UF_HIDDEN` (또는 Windows `FILE_ATTRIBUTE_HIDDEN`) flag 가 설정된 `.pth`
파일을 silent skip 한다 — supply chain attack 방지 목적의 새 정책.

```python
if ((getattr(st, 'st_flags', 0) & stat.UF_HIDDEN) or
    (getattr(st, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_HIDDEN)):
    _trace(f"Skipping hidden .pth file: {fullname!r}")
    return
```

macOS 의 백그라운드 프로세스 (Spotlight `mds` / Time Machine / 다른 LaunchAgent
추정) 가 `.venv` 같은 dotfile 트리 하위 항목에 `UF_HIDDEN` flag 를 주기적으로
재적용한다. 결과적으로 hatchling 이 만든 editable shim (`_editable_impl_<name>.pth`,
`__editable__.<name>.pth` 등) 이 처리되지 못해 `sys.path` 에 소스 경로가
추가되지 않는다.

uv 자체는 hidden flag 를 붙이지 않는다 — `uv pip install` 로 새로 만들어진
파일은 깨끗한 상태로 시작한다. 시간이 지나며 macOS 가 마킹한다.

---

## 3. 진단

```bash
PTH="$(find .venv/lib/python*/site-packages -name '_editable_impl_*.pth' -o -name '__editable__*.pth' | head -1)"

# (1) hidden flag 확인 — ls -lO 의 5번째 컬럼이 "hidden" 이면 문제
ls -lO "$PTH"
# 예: -rw-r--r--@ 1 edward staff hidden 33 ... _editable_impl_anvyc.pth

# (2) site.py 가 실제로 skip 하는지 verbose trace
.venv/bin/python -v -c pass 2>&1 | grep -E "Skipping hidden|editable_impl"
# "Skipping hidden .pth file: '.../_editable_impl_anvyc.pth'" 가 보이면 확정

# (3) sys.path 에 src 가 빠졌는지
.venv/bin/python -c "import sys; print('\n'.join(sys.path))" | grep -i src
# 빈 출력이면 .pth 가 처리되지 않은 것
```

---

## 4. 해결책

### 4.1 즉시 fix (2ms)

```bash
chflags nohidden .venv/lib/python*/site-packages/_editable_impl_anvyc.pth
```

이 한 줄로 즉시 복구된다. `chflags` 는 root 권한 불필요, 파일 메타데이터만 변경.

### 4.2 영구 fix (self-heal wrapper)

`uv pip install -e .` 으로 임시 복구해도 macOS 가 다시 hidden flag 를
재적용한다. 가장 견고한 패턴은 **호출 시점에 자동 self-heal 하는 wrapper** 이며,
anvyc 저장소가 정본을 제공한다 — `scripts/anvyc-wrapper.sh`. contributor 는 직접
만들지 말고 `bash scripts/dev-install.sh` 로 설치한다 (venv·editable 설치도 함께
처리).

스크립트가 설치하는 wrapper 는 venv 경로·Python 마이너 버전에 비의존이다
(`$HOME` + glob + `ANVYC_VENV` override) — 디렉터리 이전이나 Python 업그레이드에도
깨지지 않는다. `~/.local/bin` 이 PATH 에 있으면 `which anvyc` 가 wrapper 를
가리킨다. 호출당 overhead ~2ms.

**MCP 사용자도 wrapper 경로로 등록 권장:**

```bash
claude mcp remove anvyc
claude mcp add -s user anvyc -- ~/.local/bin/anvyc serve --mcp
# Cursor: ~/.cursor/mcp.json 의 "command" 필드를 wrapper 경로로 교체
```

### 4.3 venv 재생성 (최후 수단)

`.venv` 자체가 multi-package corrupt (예: `rich._unicode_data`, `pathspec._backends`
누락) 상태면 단일 chflags 로는 회복 불가. 통째로 재생성:

```bash
mv .venv ".venv.broken-$(date +%Y%m%d-%H%M%S)"
uv venv .venv --python python3.13
uv pip install -e ".[mcp]" --python .venv/bin/python
```

새 `.venv` 는 깨끗한 상태로 시작 — hidden flag 재적용 전까지는 정상 동작.
이후 4.2 wrapper 로 영구 fix.

---

## 5. 영향 받지 않는 설치 방식

| 설치 방식 | 영향 |
|----------|-----|
| `uv tool install anvyc` (또는 `anvyc[mcp]`) | ✗ 영향 없음 (격리된 tool venv 안에 일반 install — `.pth` 불사용) |
| `pipx install anvyc` | ✗ 영향 없음 (동일 이유) |
| `pip install anvyc` (system / user) | ✗ 영향 없음 |
| `pip install -e .` (editable) | ✓ **영향** — Python 3.13.13+ on macOS |
| `uv pip install -e .` (editable) | ✓ **영향** — 동일 |

→ contributor / dev 환경이 아니라 **사용자 환경에서는 `uv tool install anvyc[mcp]`
권장** (README §5.1 ~ §5.3). editable 은 anvyc 소스 코드를 직접 수정할 때만.

---

## 6. 관련 자료

- CPython site.py 의 hidden-skip 도입 — Python 3.13.13 changelog
- macOS `chflags(1)` — `nohidden`, `hidden`, `nochange`, `uchg` flags
- hatchling editable 메커니즘 — `_editable_impl_<name>.pth` shim

---

## 7. 다른 프로젝트 일괄 정리 (선택)

같은 머신의 다른 editable venv 도 같은 증상일 가능성:

```bash
find ~/Documents -path '*/.venv/lib/python*/site-packages/_editable_impl_*.pth' -flags hidden \
  -exec chflags nohidden {} \;
find ~/Documents -path '*/.venv/lib/python*/site-packages/__editable__*.pth' -flags hidden \
  -exec chflags nohidden {} \;
```

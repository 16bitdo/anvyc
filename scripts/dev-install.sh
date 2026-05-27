#!/usr/bin/env bash
# anvyc — contributor 개발 환경 설치 (editable + PYTHONPATH dev wrapper).
#
# Usage:
#   bash scripts/dev-install.sh
#   ANVYC_PYTHON=python3.12 bash scripts/dev-install.sh   # 인터프리터 지정
#   ANVYC_EXTRAS="dev,encryption,mcp" bash scripts/dev-install.sh   # 기본값 "dev,mcp"
#
# 멱등: 재실행 안전. venv 는 인터프리터 버전이 맞으면 재사용, 아니면 재생성.
# wrapper 정본은 scripts/anvyc-wrapper.sh — 이 스크립트가 ~/.local/bin/anvyc 로 설치.
set -euo pipefail

# ----- helpers (install.sh 와 동일 패턴) -----
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m→\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33mnote:\033[0m %s\n' "$*"; }

# ----- 경로 계산 -----
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO_ROOT/.venv"
WRAPPER_SRC="$SCRIPT_DIR/anvyc-wrapper.sh"
BIN_DIR="$HOME/.local/bin"
WRAPPER_DST="$BIN_DIR/anvyc"
EXTRAS="${ANVYC_EXTRAS:-dev,mcp}"

[[ -f "$REPO_ROOT/pyproject.toml" ]] || die "pyproject.toml 없음 — anvyc 저장소 루트에서 실행하세요 ($REPO_ROOT)"
[[ -f "$WRAPPER_SRC" ]] || die "wrapper 정본 없음: $WRAPPER_SRC"

# ----- 1) Python 인터프리터 선택 -----
# 우선순위: ANVYC_PYTHON > python3.13(bare) > uv 관리 3.13 > python3(bare).
# python3.13 이 bare 명령으로 없을 때 uv 가 관리하는 3.13 으로 폴백한다 — pyenv
# shim 의 python3(구 마이너 버전)으로 의도치 않게 다운그레이드되는 것을 방지.
pick_python() {
  if [[ -n "${ANVYC_PYTHON:-}" ]]; then
    command -v "$ANVYC_PYTHON" >/dev/null 2>&1 || die "ANVYC_PYTHON 인터프리터 없음: $ANVYC_PYTHON"
    echo "$ANVYC_PYTHON"
    return
  fi
  if command -v python3.13 >/dev/null 2>&1; then
    echo "python3.13"
    return
  fi
  if command -v uv >/dev/null 2>&1; then
    local uv_py
    uv_py="$(uv python find 3.13 2>/dev/null || true)"
    if [[ -n "$uv_py" && -x "$uv_py" ]]; then
      echo "$uv_py"
      return
    fi
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  die "python3 를 찾지 못했습니다."
}
PYTHON="$(pick_python)"
PY_MINOR="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
info "인터프리터: $PYTHON (Python $PY_MINOR)"

# ----- 2) venv 생성 / 재사용 (인터프리터 마이너 버전 일치 시 재사용) -----
venv_minor() {
  [[ -x "$VENV/bin/python" ]] || { echo ""; return; }
  "$VENV/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo ""
}
if [[ -d "$VENV" ]]; then
  EXISTING_MINOR="$(venv_minor)"
  if [[ "$EXISTING_MINOR" == "$PY_MINOR" ]]; then
    info "기존 venv 재사용 (.venv, Python $EXISTING_MINOR)"
  else
    TS="$(date +%Y%m%d-%H%M%S)"
    warn "기존 venv 의 Python(${EXISTING_MINOR:-unknown}) ≠ 요청($PY_MINOR) — 재생성"
    mv "$VENV" "$VENV.bak-$TS"
    info "기존 venv 백업: .venv.bak-$TS"
    "$PYTHON" -m venv "$VENV" || die "venv 생성 실패"
    ok "venv 재생성 (.venv)"
  fi
else
  "$PYTHON" -m venv "$VENV" || die "venv 생성 실패"
  ok "venv 생성 (.venv)"
fi

# ----- 3) editable 설치 (멱등 — 매 실행 재적용해 의존성 drift 흡수) -----
info "editable 설치: pip install -e \".[$EXTRAS]\""
"$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install --quiet -e "${REPO_ROOT}[$EXTRAS]" \
  || die "editable 설치 실패 (extras: $EXTRAS)"
ok "editable 설치 완료"

# ----- 4) wrapper 설치 (~/.local/bin/anvyc) — 내용이 다를 때만 백업 -----
mkdir -p "$BIN_DIR"
if [[ -e "$WRAPPER_DST" ]]; then
  if cmp -s "$WRAPPER_SRC" "$WRAPPER_DST"; then
    info "wrapper 최신 상태 — 교체 생략 ($WRAPPER_DST)"
  else
    TS="$(date +%Y%m%d-%H%M%S)"
    cp "$WRAPPER_DST" "$WRAPPER_DST.bak-$TS"
    info "기존 wrapper 백업: anvyc.bak-$TS"
    info "변경 내용 (- 기존 / + 신규):"
    diff -u "$WRAPPER_DST.bak-$TS" "$WRAPPER_SRC" || true
    cp "$WRAPPER_SRC" "$WRAPPER_DST"
    chmod 755 "$WRAPPER_DST"
    ok "wrapper 갱신: $WRAPPER_DST"
  fi
else
  cp "$WRAPPER_SRC" "$WRAPPER_DST"
  chmod 755 "$WRAPPER_DST"
  ok "wrapper 설치: $WRAPPER_DST"
fi

# ----- 5) PATH 경고 -----
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) warn "$BIN_DIR 가 PATH 에 없습니다. 셸 rc 에 추가하세요:
       export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

# ----- 6) git hooks 설치 (pre-push) — 멱등 -----
# .git 없으면 (예: sdist tarball 환경) skip. 실패해도 dev-install 자체는 계속.
if [[ -d "$REPO_ROOT/.git" ]]; then
  bash "$SCRIPT_DIR/install-git-hooks.sh" || warn "git hooks 설치 실패 — 수동 실행: bash scripts/install-git-hooks.sh"
fi

# ----- 7) 설치 검증 -----
info "검증: anvyc --version"
if VER_OUT="$("$WRAPPER_DST" --version 2>&1)"; then
  ok "설치 완료 — $VER_OUT"
else
  die "검증 실패 — wrapper 가 anvyc 를 실행하지 못함:
$VER_OUT"
fi

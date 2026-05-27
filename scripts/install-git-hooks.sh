#!/usr/bin/env bash
# .git/hooks/* 를 scripts/hooks/* SoT 로부터 (재)설치 — 멱등.
#
# 동일 내용이면 교체 생략, 다르면 .bak-YYYYMMDD-HHMMSS 백업 후 교체.
# 현재는 pre-push 만 관리. .git/hooks/pre-commit (personal-config-guard,
# role-based-ruleset 외부 SoT 가 설치) 은 손대지 않는다 — 별도 도메인.
#
# Usage:
#   bash scripts/install-git-hooks.sh
set -euo pipefail

# ----- helpers (dev-install.sh 와 동일 패턴) -----
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m→\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
HOOKS_SRC="$SCRIPT_DIR/hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

[[ -d "$REPO_ROOT/.git" ]] || die ".git 디렉터리 없음 — git 저장소 루트에서 실행하세요 ($REPO_ROOT)"
[[ -d "$HOOKS_SRC" ]] || die "hook source 디렉터리 없음: $HOOKS_SRC"

install_one() {
  local hook_name="$1"
  local src="$HOOKS_SRC/${hook_name}.sh"
  local dst="$HOOKS_DST/$hook_name"

  [[ -f "$src" ]] || die "hook source 없음: $src"

  if [[ -e "$dst" ]] && cmp -s "$src" "$dst"; then
    info "$hook_name 최신 상태 — 교체 생략 ($dst)"
    return
  fi

  if [[ -e "$dst" ]]; then
    local ts
    ts="$(date +%Y%m%d-%H%M%S)"
    cp "$dst" "$dst.bak-$ts"
    info "기존 $hook_name 백업: $hook_name.bak-$ts"
  fi

  cp "$src" "$dst"
  chmod 755 "$dst"
  ok "$hook_name 설치: $dst"
}

install_one pre-push

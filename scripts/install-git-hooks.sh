#!/usr/bin/env bash
# .git/hooks/* 를 scripts/hooks/* SoT 로부터 (재)설치 — 멱등.
#
# 동일 내용이면 교체 생략, 다르면 .bak-YYYYMMDD-HHMMSS 백업 후 교체.
# 현재는 pre-push 만 관리. .git/hooks/pre-commit 은 손대지 않는다 — 그 자리는
# pre-commit framework(.pre-commit-config.yaml) 가 쓴다. personal-config-guard 는
# 그 framework 의 local 훅으로 배선돼 tracked scripts/hooks/pre-commit 을 호출한다
# (2026-08-18). 예전 서술의 "외부 SoT 가 .git/hooks 에 직접 설치" 전제는 폐기됐다.
#
# **외부 managed-block 보존** (2026-08-27): 설치 대상 훅에는 anvyc 가 소유하지 않는
# 블록이 들어올 수 있다 — role-based-ruleset 의 `claude-md-freshness` 가 그 예다.
# 통째 교체는 그것을 조용히 지운다(실사고: CLAUDE.md stale 게이트가 push 에서 빠졌고
# 아무도 알아채지 못했다). 그래서 교체 전에 preserve_managed_blocks.py 로 "기존에만
# 있는" 블록을 SoT 뒤에 재부착한다. anvyc 소유 블록(anvyc-pr-guard)은 SoT 에 이미
# 들어 있으므로 중복되지 않는다.
#
# Usage:
#   bash scripts/install-git-hooks.sh
set -euo pipefail

# ----- helpers (dev-install.sh 와 동일 패턴) -----
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m→\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33mnote:\033[0m %s\n' "$*"; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
HOOKS_SRC="$SCRIPT_DIR/hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"
PRESERVE="$SCRIPT_DIR/preserve_managed_blocks.py"

[[ -d "$REPO_ROOT/.git" ]] || die ".git 디렉터리 없음 — git 저장소 루트에서 실행하세요 ($REPO_ROOT)"
[[ -d "$HOOKS_SRC" ]] || die "hook source 디렉터리 없음: $HOOKS_SRC"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

install_one() {
  local hook_name="$1"
  local src="$HOOKS_SRC/${hook_name}.sh"
  local dst="$HOOKS_DST/$hook_name"
  local merged="$WORK/$hook_name"

  [[ -f "$src" ]] || die "hook source 없음: $src"

  # 설치할 최종 내용 = SoT + (기존 훅에만 있는 외부 managed-block).
  if command -v python3 >/dev/null 2>&1 && [[ -f "$PRESERVE" ]]; then
    python3 "$PRESERVE" --existing "$dst" --new "$src" >"$merged" \
      || die "managed-block 병합 실패: $PRESERVE"
  else
    warn "python3 또는 preserve_managed_blocks.py 부재 — 외부 managed-block 이 보존되지 않습니다."
    cp "$src" "$merged"
  fi

  if [[ -e "$dst" ]] && cmp -s "$merged" "$dst"; then
    info "$hook_name 최신 상태 — 교체 생략 ($dst)"
    return
  fi

  if [[ -e "$dst" ]]; then
    local ts
    ts="$(date +%Y%m%d-%H%M%S)"
    cp "$dst" "$dst.bak-$ts"
    info "기존 $hook_name 백업: $hook_name.bak-$ts"
  fi

  cp "$merged" "$dst"
  chmod 755 "$dst"
  ok "$hook_name 설치: $dst"
}

install_one pre-push

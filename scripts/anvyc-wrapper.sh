#!/usr/bin/env bash
# anvyc dev wrapper — editable .pth 의 macOS UF_HIDDEN self-heal.
#
# 배경: Python 3.13.13+ 의 site.addpackage() 가 UF_HIDDEN flag 가 붙은 .pth 를
# silent skip 한다. macOS 백그라운드 프로세스가 .venv 하위 editable .pth 에
# hidden flag 를 주기적으로 재적용해 anvyc 가 ModuleNotFoundError 로 깨진다.
# 매 호출 시 chflags nohidden 으로 self-heal (~2ms 오버헤드).
#
# 경로·Python 버전 비의존: $HOME + glob + ANVYC_VENV override.
# 정본은 저장소의 scripts/anvyc-wrapper.sh — 직접 편집 금지, dev-install.sh 로 갱신.
set -euo pipefail

# 1) venv 위치 결정: ANVYC_VENV 우선, 없으면 알려진 후보 탐색.
venv="${ANVYC_VENV:-}"
if [[ -z "$venv" ]]; then
  for cand in "$HOME/dev/anvyc/.venv" "$HOME/Documents/anvyc/.venv"; do
    if [[ -x "$cand/bin/anvyc" ]]; then
      venv="$cand"
      break
    fi
  done
fi

if [[ -z "$venv" || ! -x "$venv/bin/anvyc" ]]; then
  printf 'anvyc: dev venv 를 찾지 못했습니다.\n' >&2
  printf '  탐색 후보: ~/dev/anvyc/.venv, ~/Documents/anvyc/.venv\n' >&2
  printf '  해결: 저장소에서 bash scripts/dev-install.sh 실행,\n' >&2
  printf '        또는 ANVYC_VENV 로 .venv 절대경로를 직접 지정하세요.\n' >&2
  exit 1
fi

# 2) editable .pth self-heal — Python 마이너 버전 무관 glob,
#    hatchling 버전별 파일명 변형(_editable_impl_* / __editable__.*) 모두 대응.
shopt -s nullglob
for pth in \
  "$venv"/lib/python3.*/site-packages/_editable_impl_anvyc.pth \
  "$venv"/lib/python3.*/site-packages/__editable__.anvyc-*.pth
do
  chflags nohidden "$pth" 2>/dev/null || true
done
shopt -u nullglob

# 3) 실제 anvyc 진입점으로 PID 교체.
exec "$venv/bin/anvyc" "$@"

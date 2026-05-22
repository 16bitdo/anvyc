#!/usr/bin/env bash
# anvyc dev wrapper — editable 개발 설치를 PYTHONPATH 로 실행.
#
# 배경: editable 설치(`pip install -e .`)는 .venv 안에 .pth 파일을 만들어 src/ 를
# sys.path 에 추가한다. macOS + Python 3.13.13+ 의 UF_HIDDEN trap (hidden flag 가
# 붙은 .pth 를 site.py 가 silent skip) 으로 이 .pth 가 무력화되면 anvyc 가
# ModuleNotFoundError 로 깨진다 (상세: docs/troubleshooting-macos.md).
#
# 본 wrapper 는 .pth 에 의존하지 않는다 — repo 의 src/ 를 PYTHONPATH 로 직접
# 주입하고 `python -m anvyc` 로 실행해 UF_HIDDEN trap 자체를 회피한다.
# (chflags self-heal 불필요 — improvement-plan-dev-wrapper §3.4.)
#
# 경로·Python 버전 비의존: $HOME + ANVYC_VENV override.
# 정본은 저장소의 scripts/anvyc-wrapper.sh — 직접 편집 금지, dev-install.sh 로 갱신.
set -euo pipefail

# 1) venv 위치 결정: ANVYC_VENV 우선, 없으면 알려진 후보 탐색.
#    후보는 anvyc repo 안의 .venv 만 인정 — sibling src/anvyc 존재로 확인.
venv="${ANVYC_VENV:-}"
if [[ -z "$venv" ]]; then
  for cand in "$HOME/dev/anvyc/.venv" "$HOME/Documents/anvyc/.venv"; do
    if [[ -x "$cand/bin/python" && -d "${cand%/.venv}/src/anvyc" ]]; then
      venv="$cand"
      break
    fi
  done
fi

if [[ -z "$venv" || ! -x "$venv/bin/python" ]]; then
  printf 'anvyc: dev venv 를 찾지 못했습니다.\n' >&2
  printf '  탐색 후보: ~/dev/anvyc/.venv, ~/Documents/anvyc/.venv\n' >&2
  printf '  해결: 저장소에서 bash scripts/dev-install.sh 실행,\n' >&2
  printf '        또는 ANVYC_VENV 로 anvyc repo 의 .venv 절대경로를 지정하세요.\n' >&2
  exit 1
fi

# 2) repo 의 src/ 확인 — venv 와 같은 repo 안에 있어야 한다.
repo="$(cd -- "$(dirname -- "$venv")" && pwd)"
if [[ ! -d "$repo/src/anvyc" ]]; then
  printf 'anvyc: %s/src/anvyc 를 찾지 못했습니다.\n' "$repo" >&2
  printf '  ANVYC_VENV 는 anvyc repo 안의 .venv 를 가리켜야 합니다.\n' >&2
  exit 1
fi

# 3) src/ 를 PYTHONPATH 로 주입해 `python -m anvyc` 로 PID 교체.
#    editable .pth 에 의존하지 않으므로 macOS UF_HIDDEN trap 과 무관하다.
exec env PYTHONPATH="$repo/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$venv/bin/python" -m anvyc "$@"

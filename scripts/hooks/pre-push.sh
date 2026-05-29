#!/usr/bin/env bash
# anvyc pre-push hook: CI 게이트 (lint + type + unit test) 를 push 직전 1 회 실행.
#
# CI(ci.yml) 의 'Lint and type-check'(ruff + mypy) + 'Pytest (unit, fast-fail)' 와
# 동일 명령을 push 직전 실행한다. 목적 2가지:
#   1) CI red 를 기다리는 ~2~5 분 절약 (fast-fail).
#   2) 타입/린트 회귀를 머지 전에 차단 — 과거 src 만 로컬 mypy 돌려 tests/ 의
#      type-arg 에러가 CI 에서야 잡힌 사고(v0.17.0 cut 중 발견) 재발 방지.
# integration test (sops/age 등 외부 바이너리 의존) 는 의도적 제외 — 로컬 부담 최소화.
#
# 순서: ruff(빠름) → mypy → pytest. 앞 단계 실패 시 즉시 차단(뒤 단계 skip).
# 우회: git push --no-verify
#
# SoT: scripts/hooks/pre-push.sh (git 추적). 설치: bash scripts/install-git-hooks.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
VENV="$REPO_ROOT/.venv/bin"
RUFF="$VENV/ruff"
MYPY="$VENV/mypy"
PYTEST="$VENV/pytest"

# dev venv 미설치(sdist / headless) 환경에선 skip — dev-install 전제.
for bin in "$RUFF" "$MYPY" "$PYTEST"; do
  if [[ ! -x "$bin" ]]; then
    echo "anvyc pre-push: $(basename "$bin") (.venv) 없음 — scripts/dev-install.sh 미실행. skip." >&2
    exit 0
  fi
done

cd "$REPO_ROOT"

fail() {
  # $1: 단계 라벨, $2: 로컬 재현 명령
  echo "" >&2
  echo "anvyc pre-push: ✗ $1 실패 — push 차단." >&2
  echo "  로컬 재현: $2" >&2
  echo "  의도적 우회: git push --no-verify" >&2
  exit 1
}

echo "anvyc pre-push: [1/3] ruff check src/ tests/ ..."
"$RUFF" check src/ tests/ || fail "ruff (lint)" '.venv/bin/ruff check src/ tests/'

echo "anvyc pre-push: [2/3] mypy src/anvyc/ tests/ ..."
"$MYPY" src/anvyc/ tests/ || fail "mypy (type)" '.venv/bin/mypy src/anvyc/ tests/'

echo "anvyc pre-push: [3/3] pytest -m \"not integration\" (unit fast-fail) ..."
"$PYTEST" -m "not integration" -q || fail "pytest (unit)" '.venv/bin/pytest -m "not integration"'

echo "anvyc pre-push: ✓ lint + type + unit gate 통과"

#!/usr/bin/env bash
# anvyc pre-push hook: unit fast-fail gate.
#
# CI 의 'Pytest (unit, fast-fail gate)' step 과 동일 명령을 push 직전 1 회
# 실행해 CI red 를 기다리는 ~2~5 분을 절약. integration test (sops/age 등
# 외부 바이너리 의존) 는 의도적으로 제외 — 로컬 부담 최소화.
#
# 우회: git push --no-verify
#
# SoT: scripts/hooks/pre-push.sh (git 추적).
# 설치: bash scripts/install-git-hooks.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTEST="$REPO_ROOT/.venv/bin/pytest"

if [[ ! -x "$PYTEST" ]]; then
  echo "anvyc pre-push: .venv/bin/pytest 없음 — scripts/dev-install.sh 미실행. skip." >&2
  exit 0
fi

echo "anvyc pre-push: pytest -m \"not integration\" (unit fast-fail gate)..."
cd "$REPO_ROOT"
if "$PYTEST" -m "not integration" -q; then
  echo "anvyc pre-push: ✓ unit gate 통과"
else
  rc=$?
  echo "" >&2
  echo "anvyc pre-push: ✗ unit test 실패 — push 차단." >&2
  echo "  로컬 재현: .venv/bin/pytest -m \"not integration\"" >&2
  echo "  의도적 우회: git push --no-verify" >&2
  exit "$rc"
fi

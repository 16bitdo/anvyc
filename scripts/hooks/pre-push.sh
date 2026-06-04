#!/usr/bin/env bash
# anvyc pre-push hook: ① branch 가드(보호 브랜치 직접 push 차단) + ② CI 게이트
# (lint + type + unit test) 를 push 직전 1 회 실행한다.
#
# ① branch 가드 — `anvyc guard install` 이 생성하는 anvyc-pr-guard marker 블록을
#    이 tracked SoT 에 임베드한다(아래 GUARD_BEGIN/END). 두 설치 경로
#    (install-git-hooks.sh ↔ anvyc guard install)가 단일 pre-push 를 두고 서로
#    덮어쓰던 충돌을 제거 — SoT 에 가드를 포함시켜 재설치에도 공존시킨다.
#    policy: role-based-ruleset/metadata/branch-strategies.yaml (anvyc:
#    protected=main, push_to_main_allowed=false). 블록 본문은 render_guard_block
#    출력과 byte-identical → doctor `project-branch-protection` 가 marker 인식.
#    정책 변경 시: `anvyc guard install` 재실행(surgical 갱신) 후 본 SoT 동기화.
#
# ② CI 게이트 — CI(ci.yml) 의 'Lint and type-check'(ruff + mypy) +
#    'Pytest (unit, fast-fail)' 와 동일 명령을 push 직전 실행. 목적 2가지:
#   1) CI red 를 기다리는 ~2~5 분 절약 (fast-fail).
#   2) 타입/린트 회귀를 머지 전에 차단 — 과거 src 만 로컬 mypy 돌려 tests/ 의
#      type-arg 에러가 CI 에서야 잡힌 사고(v0.17.0 cut 중 발견) 재발 방지.
# integration test (sops/age 등 외부 바이너리 의존) 는 의도적 제외 — 로컬 부담 최소화.
#
# 순서: 가드(즉시 차단) → ruff(빠름) → mypy → pytest. 앞 단계 실패 시 즉시 차단.
# 우회: git push --no-verify
#
# SoT: scripts/hooks/pre-push.sh (git 추적). 설치: bash scripts/install-git-hooks.sh
set -euo pipefail

# >>> anvyc-pr-guard >>>
# auto-generated; managed by `anvyc guard install`. policy_source=manifest
__anvyc_protected="main"
__anvyc_allowed="false"
if [ "$__anvyc_allowed" != "true" ]; then
  while read -r _lref _lsha _rref _rsha; do
    for _b in $__anvyc_protected; do
      if [ "$_rref" = "refs/heads/$_b" ]; then
        echo "" >&2
        echo "anvyc guard: '$_b' 직접 push 차단 (push_to_main_allowed=false)." >&2
        echo "  작업 브랜치 + PR 로 진행하세요:" >&2
        echo "    git switch -c feat/<topic> && git push -u origin feat/<topic> && gh pr create --fill" >&2
        exit 1
      fi
    done
  done
fi
# <<< anvyc-pr-guard <<<

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

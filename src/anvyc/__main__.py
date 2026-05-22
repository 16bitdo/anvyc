"""`python -m anvyc` 진입점.

`[project.scripts]` 의 `anvyc` 콘솔 스크립트와 동등한 진입점. dev wrapper
(`scripts/anvyc-wrapper.sh`)가 editable `.pth` 대신 `PYTHONPATH` 로 `src/` 를
주입하고 `python -m anvyc` 로 실행할 때 사용된다 — macOS UF_HIDDEN `.pth` 트랩
회피 (docs/archive/improvement-plan-dev-wrapper.md §3.4).
"""
from anvyc.cli import app

if __name__ == "__main__":
    app()

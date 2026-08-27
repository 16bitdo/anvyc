#!/usr/bin/env python3
"""hook 을 SoT 로 교체할 때 외부 도구가 주입한 managed-block 을 보존한다.

`install-git-hooks.sh` 는 `.git/hooks/pre-push` 를 tracked SoT 로 교체한다. 그런데
그 파일에는 anvyc 가 소유하지 않는 블록이 들어올 수 있다 — role-based-ruleset 의
`claude-md-freshness` 가 그 예다. 통째 교체는 그런 블록을 조용히 지운다(2026-08-27
실사고: CLAUDE.md stale 게이트가 push 에서 빠졌고, 아무도 알아채지 못했다).

anvyc 소유 블록(`anvyc-pr-guard`)은 SoT 에 임베드해 해결했지만 그 해법은 **내용의
주인이 다른 저장소**인 블록에는 쓸 수 없다. 그래서 이름 기준으로 일반화한다 —
"기존 훅에는 있고 SoT 에는 없는" 블록만 뒤에 재부착한다.

블록 문법 (rbr·anvyc 관례 공통):

    # >>> <name> [설명] >>>
    ...
    # <<< <name> <<<

사용:
  python3 scripts/preserve_managed_blocks.py --existing .git/hooks/pre-push \\
      --new scripts/hooks/pre-push.sh          # 병합 결과 → stdout, 알림 → stderr
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# `(\S+)` 가 이름, 뒤의 `.*` 가 선택적 설명 — rbr 은 `(managed by role-based-ruleset)`
# 같은 꼬리를 붙이고 anvyc 는 붙이지 않는다. 양쪽을 한 패턴으로 받는다.
BEGIN_RE = re.compile(r"^# >>> (\S+).*>>>\s*$")
END_RE = re.compile(r"^# <<< (\S+) <<<\s*$")


@dataclass
class MergeResult:
    """병합 결과. `preserved` 는 재부착한 블록 이름, `warnings` 는 버린 것들의 사유."""

    text: str
    preserved: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Scan:
    blocks: dict[str, str]
    order: list[str]
    warnings: list[str]


def _scan(text: str) -> _Scan:
    """짝이 맞는 managed-block 만 수집한다. 짝이 없으면 버리고 사유를 남긴다.

    깨진 마커를 그대로 옮기면 실행 불가능한 훅이 만들어진다 — 잃는 것보다 나쁘다.
    그렇다고 조용히 버리지도 않는다: 사라졌다는 사실이 보여야 사람이 판단한다.
    """
    blocks: dict[str, str] = {}
    order: list[str] = []
    warnings: list[str] = []
    open_name: str | None = None
    buf: list[str] = []

    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\n")
        begin = BEGIN_RE.match(bare)
        end = END_RE.match(bare)

        if open_name is None:
            if begin:
                open_name, buf = begin.group(1), [line]
            elif end:
                warnings.append(f"여는 마커가 없어 무시: {end.group(1)}")
            continue

        buf.append(line)
        if end and end.group(1) == open_name:
            blocks[open_name] = "".join(buf)
            order.append(open_name)
            open_name, buf = None, []

    if open_name is not None:
        warnings.append(f"닫는 마커가 없어 보존하지 않음: {open_name}")
    return _Scan(blocks, order, warnings)


def merge_preserving_blocks(existing: str, new: str) -> MergeResult:
    """`new`(SoT) 에 `existing` 에만 있는 managed-block 을 덧붙인다.

    이름이 SoT 에 이미 있으면 재부착하지 않는다 — SoT 가 그 블록의 주인이고,
    덧붙이면 같은 가드가 두 번 도는 훅이 된다.
    """
    old, sot = _scan(existing), _scan(new)
    warnings = old.warnings + sot.warnings
    preserved = [name for name in old.order if name not in sot.blocks]
    if not preserved:
        return MergeResult(new, [], warnings)

    parts = [new if new.endswith("\n") else new + "\n"]
    parts += [f"\n{old.blocks[name]}" for name in preserved]
    return MergeResult("".join(parts), preserved, warnings)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--existing", required=True, type=Path, help="교체 대상(기존 훅)")
    p.add_argument("--new", required=True, type=Path, help="SoT (scripts/hooks/*.sh)")
    args = p.parse_args(argv)

    new = args.new.read_text(encoding="utf-8")
    if not args.existing.is_file():
        sys.stdout.write(new)  # 첫 설치 — 보존할 것이 없다
        return 0

    result = merge_preserving_blocks(args.existing.read_text(encoding="utf-8"), new)
    for w in result.warnings:
        print(f"warn: {w}", file=sys.stderr)
    if result.preserved:
        print(f"외부 managed-block 보존: {', '.join(result.preserved)}", file=sys.stderr)
    sys.stdout.write(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

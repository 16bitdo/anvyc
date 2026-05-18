"""Secret 패턴 정의.

DESIGN.md §13.1 참조. 패턴이 추가/수정될 때마다 본 모듈만 손대면 되도록 격리한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretPattern:
    name: str
    severity: str  # "critical" | "high" | "medium" | "low"
    regex: re.Pattern[str]


PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern("aws_access_key", "critical", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    SecretPattern("github_token", "high", re.compile(r"\b(ghp_|github_pat_)[A-Za-z0-9_]{20,}\b")),
    SecretPattern("openai_key", "high", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    SecretPattern("anthropic_key", "high", re.compile(r"\bsk-ant-[A-Za-z0-9-]{20,}\b")),
    SecretPattern("pulumi_token", "high", re.compile(r"\bpul-[A-Fa-f0-9]{40,}\b")),
    SecretPattern("private_key", "critical", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    SecretPattern(
        "generic_secret",
        "medium",
        re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}"),
    ),
)

# 1Password Secret Reference URI 인식. PATTERNS 와 별개 — 매칭 자체가 finding 이 아니라
# 같은 라인의 다른 secret 매칭을 "low" 로 강등시키는 signal (DESIGN.md §30).
#  op://<vault>/<item>/<field>  (optional sub-field 1단계 허용)
OP_REFERENCE_RE: re.Pattern[str] = re.compile(
    r"\bop://[^/\s\"']+/[^/\s\"']+/[^/\s\"']+(?:/[^/\s\"']+)?"
)

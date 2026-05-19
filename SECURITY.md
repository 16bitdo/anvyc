# Security Policy

anvyc 는 사용자 secret/credential 을 다루는 도구입니다. 보안 이슈를 진지하게
다루며, 책임 있는 공개를 위한 절차를 다음과 같이 안내합니다.

## 지원 버전 (Supported Versions)

| 버전 | 지원 여부 |
|---|---|
| 0.5.x (latest minor) | ✅ 보안 패치 |
| 0.4.x 이하 | ❌ — latest minor 로 업그레이드 권장 |

v1.0.0 안정 release 이전에는 latest minor 만 보안 패치를 제공합니다.

## 취약점 신고 (Reporting a Vulnerability)

**공개 Issue 로 보고하지 마세요.** 다음 비공개 채널 중 하나를 이용해 주세요:

1. **GitHub Security Advisory (권장)**
   - <https://github.com/16bitdo/anvyc/security/advisories/new>
   - 비공개 토론 가능, 자동 CVE 발급 지원
2. **이메일**: `16bitdo@gmail.com` (제목 prefix `[anvyc-security]`)

### 신고에 포함할 내용

- 영향 범위 (어떤 명령/기능에서 발생)
- 재현 단계 (가능하면 최소 reproducer)
- 영향 정도 (token leak / RCE / DoS / 경로 우회 등)
- 발견한 anvyc 버전
- (선택) 패치 아이디어

## 응답 시간 (Disclosure Timeline)

| 단계 | 목표 |
|---|---|
| 접수 확인 | 48 시간 이내 |
| 1차 평가 | 7 일 이내 |
| 패치 + 공개 advisory | 30~60 일 (심각도에 따라 조정) |

## Scope — 다루는 취약점 유형

다음은 anvyc 의 핵심 보안 약속 영역입니다:

| 영역 | 예시 취약점 |
|---|---|
| Secret 노출 | scanner 가 놓치는 패턴, op:// downgrade 우회, SOPS 인식 실패로 평문 노출 |
| Path traversal | adapter 의 `target_path` 가 backup 디렉터리 밖 쓰기 허용 |
| 권한 상승 | 임의 코드 실행 (예: pre-commit hook 인젝션, mcp.json 악용) |
| Force-overwrite | apply 가 local-backup 없이 무단 덮어쓰기 |
| Secret-bearing 파일 누락 | scanner 가 알려진 secret 파일을 통과시킴 (`~/.aws/credentials` 등) |
| Backup 무결성 | metadata sha256 우회, symlink target 검증 우회 |
| pre-commit hook 우회 | `--no-verify` 외 방법으로 raw secret commit |

## Out of Scope — 다루지 않는 영역

- **사용자 환경 자체의 취약점** — 사용자의 `~/.aws/credentials` 파일 권한, SSH key 관리 등
- **3rd-party 도구의 취약점** — sops, age, 1Password CLI, direnv 자체의 보안 이슈
- **Social engineering** — 사용자가 자발적으로 raw secret 을 anvyc.yaml 에 넣은 경우
- **Physical access** — 머신에 물리적으로 접근한 공격자
- **SOPS 의 동작 자체** — anvyc 는 sops 를 subprocess 로 호출만 함
- **macOS 외 플랫폼** — 현재 macOS-only. v1.0 까지 Windows/Linux 지원 X
- **PoC 한계로 명시된 제약** — RELEASE_NOTES 의 알려진 한계 항목

## 모범 사례 (Best Practices for Users)

anvyc 를 안전하게 사용하려면:

1. **secret 기본 제외 정책 유지** — `~/.aws/credentials`, `~/.pulumi/credentials.json`,
   `~/.config/gh/hosts.yml` 등 anvyc 가 자동 제외하는 파일을 yaml 의
   `files` 에 직접 추가하지 마세요.
2. **`op://` reference 활용** — raw token 대신 1Password Secret Reference (`op://`)
   를 dotfile 에 사용. 자세한 내용 README §9.1.
3. **SOPS 로 secret 묶음 암호화** — `.env`, `.toml` 등 secret 다수 파일은
   `secret_files:` 로 SOPS 암호화. README §9.2.
4. **pre-commit hook 활성** — `anvyc git init` 이 자동 설치. `--no-verify`
   우회는 권장 X.
5. **doctor 정기 실행** — `anvyc doctor --strict` 를 CI 또는 정기적으로 실행해
   취약 패턴 (raw token, broken symlink, cross-user path) 감지.

## 보안 변경 이력 (Security Changelog)

보안 관련 변경은 RELEASE_NOTES.md 의 각 release 섹션에 별도 표기됩니다.

## 라이선스

본 정책 자체는 [MIT License](./LICENSE) 하에 배포됩니다.

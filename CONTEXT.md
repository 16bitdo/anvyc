# CONTEXT.md — anvyc 진행 상태와 결정 기록

> 본 문서는 전역 규칙 "CONTEXT.md 우선 참조"에 따라, 진행 중인 결정/가정/상태를 한 곳에 모은다.
> 새로운 결정이 추가될 때마다 본 문서를 우선 갱신한 뒤 README/DESIGN을 반영한다.

---

## 1. 현재 상태 (2026-05-21 기준)

| 항목 | 상태 |
|---|---|
| 버전 | v0.13.0 — git tag `v0.13.0` 릴리스 게시 완료 (GitHub Release, 직전 release v0.12.0) |
| 어댑터 | 10개 (shell·git·aws·gh·cursor·claude·iterm2·pulumi·dev_env·shell_prompt) |
| CLI | init·doctor·backup·status·diff·apply·restore·list·scan-secrets·config·tools·project(show/list/doctor)·prompt·serve·git·sops |
| Doctor checks | 14개 (cross-user / op-references / sops-keys / project-aws·gh·claude·pulumi-mapping 등) |
| Secret scanner | 구현 완료 — 패턴 매칭 + 1Password `op://` + SOPS 통합 |
| MCP server | 구현 완료 — `anvyc serve --mcp` (read-only 5 tool) |
| 테스트 | 210 passed / 1 skipped (unit + integration, Python 3.11~3.13 matrix) |
| 패키징/배포 | Homebrew tap · `install.sh` one-liner · GitHub Release wheel |
| Git 저장소 | `16bitdo/anvyc` (GitHub) — main 직접 push 차단, PR 경유 |
| 로드맵 | README §13 이 SoT |

---

## 2. 확정 결정 (Decisions)

| 일자 | 결정 | 근거 |
|---|---|---|
| 2026-05-17 | MVP 언어로 Python 채택 | adapter 실험/반복 속도, plist/yaml/json 처리 라이브러리 풍부 |
| 2026-05-17 | chezmoi는 직접 사용하지 않고 안전 원칙만 참고 | Claude/Cursor/iTerm2 특화 정책 필요 |
| 2026-05-17 | secret 기본 제외 | credentials 유출 시 비용/계정 위험 |
| 2026-05-17 | apply 전 local backup 의무화 | 부분 적용 실패 시 복구 가능성 확보 |
| 2026-05-17 | iTerm2 전체 plist 동기화 금지 | window state/recent sessions/local path 등 장비별 휘발 데이터 포함 |
| 2026-05-17 | MVP target: macOS only | 1차 사용자는 Mac 개발자 |
| 2026-05-18 | DESIGN.md v0.2 재작성 | v0.1의 일부 섹션 텍스트 손상으로 정합성 부족 |
| 2026-05-18 | Cursor adapter 3-layer 모델 채택 (A: ~/.cursor, B: Library/User, C: project-local opt-in) | 실제 디렉터리 토폴로지 조사 결과 단일 평면 목록으로는 secret/캐시/symlink 처리 정책을 표현하기 부족 |
| 2026-05-18 | `~/.cursor/cli-config.json` 기본 제외 | 0600 perms + 토큰 가능성 확인. v0.1 잘못된 include 정정 |
| 2026-05-18 | Cursor symlink follow=false 기본, metadata만 기록 | 실측: `rules.bak-* → 외부 repo(role-based-ruleset)` 패턴 존재. 의도치 않은 외부 컨텐츠 백업 방지 |
| 2026-05-18 | Doctor `cross-user` check 도입, 5단계 severity (info/info-aliased/warning-foreign/warning-dangling/critical) | 실측: `/Users/aliasuser → /Users/edward` symlink. `~/.cursor/projects/`의 13/20이 alias 경로, SSH config 6라인이 alias 경로. 같은 머신에서는 동작하지만 다른 머신에 적용하면 broken |
| 2026-05-18 | Doctor는 read-only, `--fix` 모드는 v0.2 이후 | 자동 수정은 부작용이 크고 사용자 의도와 어긋날 수 있음. 1차는 진단/제안만 |
| 2026-05-18 | `src/anvyc/checks/` 신규 패키지 도입 | Check 컴포넌트를 doctor·adapter validate·scan-secrets 등에서 재사용. 단일 CheckResult 타입으로 통합 보고 |
| 2026-05-18 | `Finding` → `CheckResult` 통합 (#16) | adapter validate 결과를 doctor 리포트로 직접 합치기 위해 타입 일원화. `adapters/base.py:Finding` 제거 |
| 2026-05-18 | Shell adapter end-to-end backup PoC 완성 | DESIGN.md §12.1 절차를 실 동작으로 검증. shell → security scan → copy → hash → metadata.json → current symlink. 다른 adapter 추가 시 ADAPTERS 레지스트리에 등록만 하면 동일 파이프라인 |
| 2026-05-18 | Backup 정책: secret scan 결과 critical/high 또는 medium(force 미지정)에서 차단 | DESIGN.md §13.2 정책 그대로. shell 파일은 통상 generic_secret 패턴에 걸리는 export 라인이 있을 수 있어 `--force` 안내가 UX 상 중요 |
| 2026-05-18 | macOS venv 트랩 회피: `chflags -R nohidden .venv` 필수 | Python 3.13 site.py 가 UF_HIDDEN flag 있는 .pth 를 스킵. `.`-prefix 디렉터리는 macOS 에서 자동으로 hidden flag 가 붙어 editable install 의 .pth 가 무시됨 (https://github.com/python/cpython/issues/116727). README/doctor 가 안내해야 함 |
| 2026-05-18 | v0.1.0 MVP 필수 경로 = Phase 1 + Phase 2 + Phase 6 | apply/restore → 어댑터 6개 → 테스트/패키징. Git sync / Doctor 보강 / encryption 은 v0.2 |
| 2026-05-18 | Phase 1 (apply/restore) 가 Phase 2 의 선행 | apply 기본 구현이 있어야 새 어댑터가 즉시 backup+apply 양쪽 동작. 새 어댑터마다 별도 apply 구현 불필요 |
| 2026-05-18 | 어댑터 추가 순서: aws → gh → pulumi → claude → iterm2 → cursor | 단순 단일 파일 → 디렉터리 재귀 → plist → 3-layer 순으로 복잡도 점증. claude 에서 디렉터리 재귀 수집 인벤토리 구조를 1회 검증 |
| 2026-05-18 | Q1 확정: Phase 3 (Git sync) v0.1.0 포함 | 사용자 핵심 사용 시나리오. `.anvyc/` 를 private repo 로 push 하는 흐름이 v0.1.0 MVP 의 1차 가치 |
| 2026-05-18 | Q2 확정: iterm2 safe subset 을 사용자 plist 실측 기반으로 재조정 | 102 keys 분석 후 §14.2 (안전 포함 22항목) + §14.3 (제외 8 카테고리) 로 확정. AI 통합 12개 키도 포함 |
| 2026-05-18 | Q3 확정: cursor projects 모드 default roots = 자동 감지 후 제안 | 사용자 `~/Documents/` 에 46개의 `.cursor/` 디렉터리. `cursor-projects-suggest` doctor check 가 INFO 로 출력하고 사용자가 yaml 편집해 활성화 |
| 2026-05-18 | Q4 확정: v0.1.0 secret 분리 = 1Password Secret Reference (`op://`), v0.2 = SOPS | `op` CLI 설치 확인됨 (v2.34.0). reference 자체는 비-secret 이므로 Git commit 안전. raw secret 은 scanner 가 계속 차단 |
| 2026-05-18 | 1Password Secret Reference 패턴: scanner 에서 op:// 를 false-positive 강등 | 같은 라인의 다른 secret 패턴은 reference 가 있으면 placeholder 로 간주. raw secret-only 라인은 그대로 차단 |
| 2026-05-18 | iTerm2 adapter: backup 은 XML plist safe subset, apply 는 binary plist deep-merge | DESIGN.md §14 정책. 사용자 plist 의 31 safe keys 만 추출. apply 시 target 의 위험 키(NSWindow Frame, NoSyncInstallationId 등)는 보존 |
| 2026-05-18 | iTerm2 status 가 항상 modified 로 표시되는 PoC 한계 | sha256(backup XML safe subset) ≠ sha256(target binary plist 전체). 동작 안전성에는 영향 없음. 향후 adapter 별 custom compute_target_hash() 도입으로 정합화 가능 |
| 2026-05-18 | adapter.apply() dispatch: apply.py 가 adapter 의 custom apply 우선 시도, NotImplementedError 시에만 _default_apply 폴백 | iterm2 처럼 plist merge 가 필요한 도구는 adapter.apply() 가 동작. 다른 어댑터는 그대로 default copy. 어댑터 추가 시 별도 등록 불필요 |
| 2026-05-18 | Cursor adapter C1 확정: mcp.json 자동 마스킹 v0.1.0 비포함 | 사용자 mcp.json 에 raw token 없음 (envFile/headers 패턴). v0.1.0 은 scanner 차단만, mask 동작은 v0.2 |
| 2026-05-18 | Cursor adapter C2 확정: ~/.cursor/plugins 전체 포함, marketplaces 만 제외 | local/blocklist/known_marketplaces 등 user-curated 보존. 14M 중 marketplaces clone(재현 가능) 제외 |
| 2026-05-18 | Cursor adapter C3 확정: symlink target 부재 시 WARNING + skip (안전) | rules.bak-* 같은 외부 repo 경로가 다른 머신에서 부재할 때 apply 실패 X. 사용자 검토 후 수동 처리 |
| 2026-05-18 | Cursor adapter C4 확정: Layer C project-name = root last segment | `~/Documents/anvyc` → `anvyc`. 충돌 시 후속 작업에서 slugify 폴백 검토 |
| 2026-05-18 | ManagedFile.symlink_target 필드 도입 (cursor adapter 지원) | symlink 백업: 콘텐츠 복사 X, metadata.json 에 symlinkTarget 만 기록. apply 시 os.symlink 재생성 |
| 2026-05-18 | v0.2 SOPS 통합 V1 확정: SOPS 파일을 .anvyc/ 안에 git-tracked 로 저장 | SOPS 본래 목적 — 암호화 자체가 안전. 별도 ~/.anvyc-secrets/ 분리 영역은 도입 보류 |
| 2026-05-18 | v0.2 SOPS 통합 V2 확정: 키 backend = age | clean slate (sops/age 모두 미설치) → 가장 단순한 cross-platform 옵션 |
| 2026-05-18 | v0.2 SOPS 통합 V3 확정: mcp.json 자동 마스킹은 v0.2.1 분리 | SOPS 와 결이 다른 문제. v0.2 는 SOPS 단일 주제로 집중 |
| 2026-05-18 | v0.2 SOPS 통합 V4 확정: 1Password Reference 와 양립 | 단일 raw secret → op:// , 다수 secret 묶음 (.env/.toml) → SOPS. scanner 가 양쪽 인식 |
| 2026-05-18 | v0.5 sops CLI W1 확정: encrypt/decrypt default output = auto suffix file (stdout 은 `-o -` 옵트인) | shell 파이프 보다는 파일 자동 생성이 더 직관적 |
| 2026-05-18 | v0.5 sops CLI W2 확정: rotate-keys 기본 범위 = 모든 backup, --backup-id 로 제한 가능 | dry-run 으로 사전 검증 가능 |
| 2026-05-18 | v0.5 sops CLI W3 확정: rotate 구현 = anvyc 의 decrypt+encrypt+atomic-replace | sops updatekeys 는 .sops.yaml 의존, anvyc 의 단일 source of truth (anvyc.yaml) 와 충돌. 명시적 swap 채택 |
| 2026-05-18 | v0.5 sops CLI W4 확정: rotate 실패는 continue + 요약 (default), --strict 로 fail-fast 옵트인 | 1건 실패가 전체 차단하지 않음, 부분 진행 가능 |
| 2026-05-18 | v0.5.1 iTerm2 status 정합화 X1 확정: 메서드 명 = `target_hash` | 간결, sha256_file 과 자연스러운 대구 |
| 2026-05-18 | v0.5.1 X2 확정: NotImplementedError fallback dispatch | adapter.apply() 의 dispatch 패턴과 일관 |
| 2026-05-18 | v0.5.1 X3 확정: iTerm2 만 override, 다른 adapter 는 default | YAGNI — cursor/claude 디렉터리 재귀는 file-level hash 가 자연스러움 |
| 2026-05-18 | v0.5.2 Y1 확정: secret_files schema = mixed string/dict | string 형식 backward compat + dict 형식으로 file 단위 옵션 가능 |
| 2026-05-18 | v0.5.2 Y2 확정: format chain = file > tool > global > default | 가장 구체적인 설정이 이긴다 — 일반 config 우선순위 패턴 |
| 2026-05-18 | v0.5.2 Y3 확정: dict 의 추가 필드 = format 만 | per-file recipients/identity 는 보안 모델 복잡화. v0.6+ 검토 |
| 2026-05-19 | macOS UF_HIDDEN 이슈 README 안내 완료, self-heal wrapper 패턴 권장 | 2026-05-18 결정의 후속 — `chflags -R nohidden` 1회로는 영구 fix 불가 (백그라운드가 주기적 재적용). `~/.local/bin/anvyc` wrapper 가 매 호출 시 `chflags nohidden $PTH` + exec 으로 self-heal. docs/troubleshooting-macos.md 신설, README §5.6 cross-link. doctor 자동 안내는 미구현 |
| 2026-05-20 | v0.11.0 per-project gh 계정 라우팅 인식 — `project_show.gh_account` 필드 + doctor 검사 `project-gh-account-mapping` (+ `project_doctor` cwd 단위 검사) | `gh` 의 single global active account 가 16bitdo/whatap 계정 전환 시 whack-a-mole 유발. `.envrc` 의 `GH_CONFIG_DIR`(`~/.config/gh-<account>`) 라우팅을 anvyc 가 인식·검증. `aws_profile` 패턴의 GitHub 아날로그 |
| 2026-05-21 | v0.11.0 프로젝트 루트 SoT 단일화 — `core/project_roots.py`(`DEFAULT_PROJECT_ROOTS` `~/dev` 선두 7-루트 + `resolve_project_roots`), `doctor.project_roots` config 키 도입 | `~/Documents`→`~/dev` 이전으로 `project-aws-profile-mapping`·`project-gh-account-mapping` 이 빈 결과/stale. 두 체크는 config override 경로가 없던 실버그 — `load_anvyc_config()` 직접 호출(`cursor-projects-suggest` 선례)로 멀티 루트 config-aware 전환. docs/archive/improvement-plan-scan-root.md §3.1·§3.2 (PR 1) |
| 2026-05-21 | v0.11.0 프로젝트 루트 SoT 수렴 완결 (PR 1-b) — `project_discovery`·`dev_env`·`cursor-projects-suggest` 의 중복 `~/Documents` 상수를 `DEFAULT_PROJECT_ROOTS` 로 수렴, `project list`/MCP `project_list` 를 `resolve_project_roots()` config-aware 로 전환, config 키 `doctor.project_roots` → top-level `project_roots` 승격 | PR 1(`e00b00d`)이 §3.1 소비처 수렴을 누락 — `anvyc project list` 무인자가 24개 대신 1개만 반환하는 버그 잔존. v0.11.0 미릴리스라 키 승격 마이그레이션 비용 0. docs/archive/improvement-plan-scan-root.md §3.1 완결 |
| 2026-05-21 | scan-root §3.3 (Tier 2/3, PR 2) 완료 — `anvyc init` wizard·`DEFAULT_ANVYC_YAML` 템플릿 default `~/Documents`→`~/dev`, `multi-account-detected` 의 Cursor user-alias 정규식을 last-segment-agnostic(`^Users-[^-]+-`)으로 일반화, README/DESIGN/mcp-integration/examples 현재상태 서술 sweep | 신규 `anvyc init` 사용자가 구 경로 상속, `dev` 기반 Cursor alias 미감지. improvement-plan 문서·RELEASE_NOTES·결정표는 시점 기록이라 보존. docs/archive/improvement-plan-scan-root.md §3.3 완료 |
| 2026-05-21 | account-routing 계획 §3.3 — Cursor 계정 라우팅은 옵션 A(제외) 확정 | Cursor 멀티 계정은 `cursor --user-data-dir=` 실행 플래그뿐 — `.envrc` env var 신호가 없어 anvyc 의 AWS/gh/Claude 라우팅 패턴(도구가 네이티브로 읽는 env var 검증)이 성립하지 않음. 검증할 SoT 부재. account-routing 확장은 Claude(Phase 1)·Pulumi(Phase 2)만 진행, Phase 3 Cursor PR 불요. 재검토 조건: Cursor 가 `CURSOR_CONFIG_DIR` 류 env var 지원 또는 `--user-data-dir` wrapper alias 표준 운용 채택. docs/archive/improvement-plan-account-routing.md §3.3 |
| 2026-05-21 | v0.12.0 per-project Claude Code 계정 라우팅 인식 (account-routing Phase 1, PR 1) — `project_info.claude_account` 필드(`_derive_claude_account` — `CLAUDE_CONFIG_DIR` basename 의 `.claude-` prefix strip) + global doctor check `project-claude-account-mapping` + per-cwd check `claude_account_dir_exists` + `multi-account-detected` 의 `~/.claude-*` 감지 + `expand_envrc_path` 공용 헬퍼 | `CLAUDE_CONFIG_DIR` 은 Claude Code 가 네이티브로 읽는 env var (`GH_CONFIG_DIR` 직접 analog). gh 와 달리 cross-check 할 remote 부재 → 검증은 디렉터리 존재 확인(1-way). 핵심 가치는 `project show`/MCP 에 `claude_account` 노출. docs/archive/improvement-plan-account-routing.md §3.1 |
| 2026-05-21 | v0.12.0 per-project Pulumi backend 라우팅 인식 (account-routing Phase 2, PR 2) — `pulumi_project.PulumiProjectInfo.backend_url`(`Pulumi.yaml` 의 `backend.url` 파싱) → `pulumi["backend"]` 노출 + `normalize_backend_url` 공용 헬퍼 + per-cwd check `pulumi_backend_routing` + global check `project-pulumi-backend-mapping` | Pulumi "계정" = backend(state 저장 위치 + org). `Pulumi.yaml backend.url`(1순위) ↔ `.envrc PULUMI_BACKEND_URL`(env override) 2-way 정합성 검증. `backend` 키 부재 = Pulumi Cloud default — 명시 선언만 추적. `PULUMI_ACCESS_TOKEN` 은 D11c `pulumi_token` 패턴으로 자동 마스킹. credentials.json cross-check 는 safety-first 로 제외. docs/archive/improvement-plan-account-routing.md §3.2 |
| 2026-05-22 | v0.12.0 릴리스 = v0.10.0 이후 단일 통합 릴리스 — 버전 0.11.0→0.12.0 bump (pyproject·`__init__`·test_smoke), RELEASE_NOTES v0.12.0 섹션 추가 | v0.11.0 은 버전 파일·RELEASE_NOTES 만 준비되고 git 태그 없이 미릴리스 상태였음 → v0.12.0 하나로 v0.10.0 이후 전체(scan-root SoT·gh·Claude·Pulumi routing) 통합 배포. shell prompt 통합은 미착수 → v0.13.0 으로 분리, v0.12.0 은 account-routing 만으로 릴리스. 태그 push·GitHub Release 게시(`release.yml`)는 release-prep PR 머지 후 별도 게이트 |
| 2026-05-22 | v0.13.0 shell prompt 통합 scope = 둘 다 (anvyc prompt 세그먼트 명령 + starship/p10k config 어댑터), PR 2개 분리 | 원래 P9(`docs/archive/improvement-plan-ai-agent.md`)의 Q4 scope 가 TBD 였음 — 사용자 확정. PR 1(완료): `anvyc prompt` — `collect_project_info` 재사용해 cwd 의 aws/gh/claude/pulumi 라우팅을 prompt 용 `key:value` 한 줄 출력 (~70ms, 오류 시 빈 출력+exit 0). starship/p10k 연동은 `docs/shell-prompt.md`. PR 2(완료): `shell_prompt` 어댑터 — `~/.config/starship.toml`+`~/.p10k.zsh` 를 어댑터 1개로 묶음 (`GhAdapter` 패턴, file-based, `enabled: true`). 어댑터 10개 |
| 2026-05-22 | v0.13.0 릴리스 준비 — 버전 0.12.0→0.13.0 bump (pyproject·`__init__`·test_smoke), RELEASE_NOTES v0.13.0 섹션 추가 | v0.13.0 = shell prompt 통합(`anvyc prompt` + `shell_prompt` 어댑터) + 개발 환경/CI 정비(dev wrapper PYTHONPATH 전환·`dev-install.sh` uv 폴백·CI macOS 과금 65% 절감·mypy `platform=darwin`). 태그 push·GitHub Release 게시(`release.yml`)는 release-prep PR 머지 후 별도 게이트 (v0.12.0 절차 재사용) |
| 2026-05-22 | anvyc 저장소 private 유지 — Homebrew tap 은 최신 버전으로 정렬만 (실제 brew install 비동작 수용) | `16bitdo/anvyc` 가 private 이라 GitHub Release asset 익명 다운로드가 HTTP 404 → `brew install`·`install.sh`·`uv tool install <release-url>` 등 익명 다운로드 설치 경로가 모두 비동작. Phase C 에서 in-repo formula(`packaging/homebrew/Formula/anvyc.rb`)와 tap repo(`16bitdo/homebrew-anvyc`) Formula 를 v0.12.0(`url`/`sha256`)으로 정렬 — public 전환 시 즉시 동작. 실제 공개 배포는 repo public 전환 또는 PyPI 배포(v1.0) 결정 필요 |

---

## 3. 열린 결정 (Open Questions)

| 항목 | 후보 | 메모 |
|---|---|---|
| 암호화 도구 | `age` vs `cryptography` | chezmoi와의 호환성 고려 시 `age` 우세 |
| 패키지 배포 채널 | `pipx` vs `uv tool install` vs `Homebrew tap` | 우선 `pipx`로 검증, 이후 Homebrew tap 검토 |
| password manager 연동 | 1Password CLI(`op`) | MVP 이후 |
| 다중 계정 처리 모델 | profile-per-host vs profile-per-account | 사용 사례 수집 후 결정 |
| Cursor globalStorage allowlist 기본값 | empty vs 추천 extension 5종 | 사용자 피드백 수집 후 결정 |
| Cursor `mcp.json` 토큰 처리 | 마스킹 후 별도 secret store / 항상 제외 / scan만 | 우선 마스킹 + secret store 방향(`mask_mcp_tokens: true` 기본) |
| Cursor `plans/` 포함 여부 | 포함(기본) vs 제외 | 개인 plan에 민감 정보 포함 시 risk. 1차는 포함 + scan, 사용 후 재검토 |
| Layer C(projects) 활성화 UX | yaml 직접 편집 vs `anvyc cursor project add <path>` | 사용 빈도 보고 결정 |
| Doctor `--fix` 모드 자동 정규화 범위 | SSH config의 `/Users/<alias>/` → `~/` 정규화만 / 전체 dotfile 일괄 정규화 | v0.2에서 결정. 1차는 SSH config만 후보 |
| Cross-user alias auto-detect | `/Users/<x> → /Users/<y>` symlink를 자동 감지해 alias로 인정 vs 명시 선언만 인정 | 보수적으로 명시 선언만 인정 (오탐 가능성 차단) |
| Phase 3 (Git sync) v0.1.0 포함 여부 | 포함 / v0.2 연기 | DESIGN.md §29.6 Q1. 사용 패턴 결정 |
| iterm2 safe subset 키 목록 확정 시점 | DESIGN.md §14.2 그대로 / 실사용자 환경 기준 재조정 | DESIGN.md §29.6 Q2. P2.5 시작 전 결정 |
| Cursor projects 모드 default roots 기본값 | empty 유지 / 자동 감지 후 제안 | DESIGN.md §29.6 Q3. P2.6 시작 전 결정 |
| v0.1.0 secret encryption 제공 범위 | 없음 (수동 `~/.anvyc-secrets/` 가이드) / age 기본 통합 | DESIGN.md §29.6 Q4. Phase 5 일정 영향 |
| CLI 진입점 이름 | `anvyc` (확정) | 단어 변경 없음 |

---

## 4. 가정 (Assumptions)

1. 1차 사용자는 macOS 26+를 사용한다.
2. shell은 zsh이다. (bash는 향후 확장)
3. Cursor/Claude Code는 사용자별 단일 설치를 가정한다.
4. iTerm2는 v3.5+ plist 구조를 따른다.
5. AWS CLI v2, GitHub CLI 최신 stable, Pulumi 최신 stable을 가정한다.
6. Python 3.11 이상이 시스템에 존재한다.
7. backup repo는 사용자가 직접 소유한 private Git repo다.

---

## 5. 작업 우선순위

릴리스 로드맵의 SoT 는 README §13. 본 절은 단기 우선순위만 추적한다.

- **진행 중 작업**: v0.13.0 릴리스 게시 완료 — `git tag v0.13.0` → `release.yml` 가 wheel/sdist/SHA256SUMS 빌드 + GitHub Release 게시. 남은 단계: Homebrew tap(`16bitdo/homebrew-anvyc`) Formula `url`/`sha256` 을 v0.13.0 으로 갱신. sdist sha256 = `9ea00338e2eb8673a354f634718c16345a2d8bbb4ea131075bb1458615e07c00`. (⚠️ anvyc repo private 라 익명 설치 경로 비동작, §2 2026-05-22 결정 참조.)
- **다음 후보 (우선순위 낮음)**: 없음 — 소진된 구 개선 계획 문서 4종(ai-agent·ux-review·account-routing·scan-root)은 `docs/archive/` 로 이동 완료 (2026-05-22).
- **로드맵**: README §13 — v0.12.0(Claude·Pulumi 계정 라우팅) → v0.13.0(shell prompt 통합) → v1.0(API stable, PyPI 배포).

---

## 6. 작업 흐름 규칙

- 디렉터리/파일 구조 또는 정책 변경 시 본 문서 → DESIGN.md → README.md 순서로 갱신한다.
- adapter 추가/제거 시 §1 현재 상태 표와 §5 로드맵을 동시에 갱신한다.
- 외부 라이브러리 채택은 §2 결정 표에 일자/근거와 함께 추가한다.

---

## 7. 참고 자료

- chezmoi: https://chezmoi.io/
- chezmoi GitHub: https://github.com/twpayne/chezmoi
- chezmoi age 암호화: https://chezmoi.io/user-guide/encryption/age/
- chezmoi password manager integration: https://chezmoi.io/user-guide/password-managers/
- Typer: https://typer.tiangolo.com/
- Rich: https://rich.readthedocs.io/
- pydantic: https://docs.pydantic.dev/
- plistlib: https://docs.python.org/3/library/plistlib.html

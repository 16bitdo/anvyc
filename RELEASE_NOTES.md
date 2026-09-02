# anvyc 릴리즈 노트

## v0.22.1 — 2026-09-02 (patch — 배포본이 실행되지 않던 문제 + doctor 가 회귀 명령을 안내하던 문제)

v0.22.0 당일 발행 직후 실동작 확인에서 드러난 두 결함을 고친 patch. 둘 다 **설치·안내는
성공하는데 결과만 틀린** 종류다.

### Homebrew 배포본이 실행되지 않았다

`brew install anvyc` 로 설치한 **v0.21.0~v0.22.0 이 CLI import 단계에서 죽었다.**

```
$ anvyc --version
ModuleNotFoundError: No module named 'typer._click'
```

설치는 rc=0 이고 sha256 도 일치했다 — 실행만 안 됐고 약 2주간 아무도 몰랐다.

직접 원인은 tap formula 의 resource 가 initial formula(v0.7.1) 이후 한 번도 갱신되지 않아
typer 가 `0.12.5` 에 고정된 것이고, **이미 수정됐다**([homebrew-anvyc#8](https://github.com/16bitdo/homebrew-anvyc/pull/8)).
그 pin 을 정당화한 것이 이쪽의 느슨한 선언이다.

- **`typer>=0.12` → `>=0.26`** — `cli.py` 는 2026-06-05(#175)부터 `import typer._click` 을
  하는데, 그 패키지는 typer 0.26.0(2026-05-26)이 click 을 vendoring 하며 도입했다. 코드가
  요구하는 것과 선언한 것이 4개월 어긋나 있었다.
- **`pyyaml>=6.0` → `>=6.0.1`** — 검증 중 함께 드러났다. pyyaml 6.0 은 Python 3.13 에서
  빌드가 실패한다(Cython `'build_ext' object has no attribute 'cython_sources'`).
  `requires-python = ">=3.11"` 이므로 6.0 은 애초에 선언 가능한 값이 아니었다.

느슨한 하한은 개발 환경에서 무해하다 — 상한이 없으니 늘 최신이 깔리고 CI 도 그렇다.
대가는 그 선언을 믿고 해석하는 쪽이 치른다: formula resource, 배포판 패키징, 타인의 lockfile.

**재발 방지 — CI `deps-lowest` 잡.** `uv pip install --resolution lowest-direct` 로 선언한
하한을 실제로 설치해 import + CLI smoke 를 돌린다. 이 조합이 곧 Homebrew formula 가 만드는
환경이다(런타임 의존만 설치 후 CLI 실행). 두 결함을 각각 다른 단계에서 잡는다 — pyyaml 은
설치에서, typer 는 import 에서.

### doctor 가 회귀를 유발하는 명령을 안내했다

`claude-md-freshness` 의 조치 안내가 `generate_claude_md.py --apply 후 각 repo 커밋` 이었다.
그런데 role-based-ruleset 스크립트 **자신이** `--check` 실패 시 이렇게 답한다:

```
FAIL: stale — .cursor/rules(생성기 입력)가 SoT 보다 뒤처지면 단독 --apply 는
누락 룰을 인덱스에서 drop 한다(회귀). 안전 순서:
  1) deploy_cursor_rules.py --role <role> --target-dir <project> --apply --yes
  2) generate_claude_md.py --apply
```

anvyc 가 안내한 것이 정확히 그 위험한 단독 `--apply` 였다. 1단계(재배포)를 포함한 순서로
교체했다.

### 재생성됐지만 커밋 안 된 CLAUDE.md 를 관측한다 (INFO)

같은 check 가 fresh 일 때 그 다음 구간을 본다. 각 프로젝트에서 룰셋의 **유일한 추적 기록이
CLAUDE.md** 이므로(`.cursor/` 는 대개 gitignore 대상), 커밋이 빠지면 다음 세션이 옛 인덱스를
보고 저장소만으로는 어느 룰셋 버전 기준으로 작업했는지 알 수 없다.

- **tracked 게이트가 먼저** — gitignored/untracked repo 는 커밋 자체가 대상이 아니라
  재생성이 정본이므로 침묵한다(무오탐).
- **fresh 일 때만** — stale 이면 답이 "재생성하라"이고 미커밋 보고는 그 위에 얹혀 소음이 된다.
- **INFO 다** — WARNING 은 `is_blocking` 이라 `doctor --strict` 가 exit 1 이 되고, 그 값을
  소비하는 L4 anvyx C6 pre-run gate 가 autopilot 을 막는다. 커밋 누락은 실행을 차단할 사유가
  아니다.

생성물 판별은 첫 줄의 `auto-generated from .cursor/rules/` 마커로만 한다 — 이름 규칙이나
경로로 추정하면 사람이 쓴 CLAUDE.md 를 삼킨다.

### 문서

검증 절차 자체가 낡아 있던 것 셋을 고쳤다.

- **`install-via-homebrew`** — `brew trust --tap 16bitdo/anvyc` 단계 신설. Homebrew 6.x 는
  비공식 tap 을 기본 차단하므로 **이 단계 없이는 설치가 되지 않는다**. "설치는 성공했는데
  실행이 죽는" 유형도 트러블슈팅에 추가.
- **`homebrew-publishing` §4** — resource 갱신을 "의존이 바뀔 때만"에서 **매 릴리스 확인**
  으로. 제약이 `>=` 라 `dependencies` 가 그대로여도 resource 는 낡는다. 개별 sha256 산출
  대신 `brew update-python-resources` 로 전체 재생성 — 최신 typer 가 click 을 vendoring 하며
  **resource 목록 자체가 바뀌었다**(`click`·`typing-extensions` 제거, `annotated-doc` 추가).
- **`homebrew-publishing` §5** — `brew install --build-from-source ./Formula/anvyc.rb` 는
  Homebrew 6.x 가 거부한다(tap 밖 formula). tap 클론 임시 적용 + 원복 절차로 교체하고,
  dev wrapper shadow 때문에 절대경로로 검증해야 함을 명시.

### 업그레이드

```bash
brew update && brew upgrade anvyc     # 또는: uv tool upgrade anvyc
```

**Homebrew 사용자는 `brew update` 를 먼저 해야 한다** — 고쳐진 formula 를 받아야 하기
때문이다. tap 을 처음 쓰는 경우 `brew trust --tap 16bitdo/anvyc` 가 필요하다(Homebrew 6.x).

typer 0.26 미만 환경은 업그레이드가 필요하지만, 그 버전에서는 anvyc 가 애초에 실행되지
않았으므로 실질적인 breaking 은 없다.

## v0.22.0 — 2026-09-02 (minor — 훅 소유권 · 버전 정직성 · 룰이 따라오는 worktree)

v0.21.0 이후 12 커밋(feat 4 · fix 5 · docs 2 · chore 1)을 모은 릴리스. 축은 셋이다 —
**① 훅을 "내 것만 건드린다" 는 원칙으로 재정렬**, **② 설치본이 어느 커밋인지 정직하게
답하게 함**, **③ worktree 격리가 룰을 잃지 않게 함**.

세 축의 공통 주제는 **조용한 실패의 제거**다. 전부 "동작하지 않는데 아무도 모르는"
상태를 실측으로 발견해 드러낸 것이고, 기능 추가보다 관측 가능성 쪽 사이클이다.

### 훅 소유권 — 남의 블록을 파괴하지 않는다

- **`scripts/preserve_managed_blocks.py` 신설 (#210)** — `# >>> <name> … <<<` 마커 블록을
  파싱해 "기존에만 있고 SoT 에 없는" 블록만 재부착한다. `install-git-hooks.sh` 가
  `.git/hooks/pre-push` 를 tracked SoT 로 통째 교체하며 **role-based-ruleset 의
  `claude-md-freshness` 블록을 삼키던** 문제(2026-08-27 실측 — CLAUDE.md stale 게이트가
  push 에서 빠진 채 아무도 알아채지 못했다)를 이름 기준으로 일반화해 차단한다.
  stdlib only + `python3` 직접 실행 — 훅 설치가 "동작하는 anvyc" 에 의존하면 부트스트랩이
  역전되기 때문이다. 짝이 맞지 않는 마커는 보존하지 않고 stderr 로 알린다.
- **`guard install --force` 가 "덮어쓴다" 에서 "삽입한다" 로 (#211)** — anvyc 블록이 없는
  훅을 통째 교체하던 동작을 폐기했다. **삽입 위치는 취향이 아니라 정확성이다** — pre-push 는
  stdin 으로 ref 목록을 받고 가드는 `while read` 로 그것을 소비하므로, 뒤에 붙이면 앞 본문이
  stdin 을 이미 먹었을 때 가드가 빈 목록을 읽고 **아무것도 차단하지 않으면서 성공한 것처럼**
  보인다. `_insert_after_preamble()` 로 shebang 직후에 넣고, 이미 stdin 을 읽는 훅에는
  `skipped-stdin-consumer` 로 손대지 않는다. 백업(`pre-push.pre-anvyc`)은 그대로 남는다.
- **skip 이 막다른 길이 아니게 (#212)** — `skipped-stdin-consumer`/`skipped-foreign` 의
  detail 이 훅 경로뿐이라 받은 사람은 왜 안 되는지도, 무엇을 하면 되는지도 알 수 없었다.
  3단계 이식 절차 + byte-identity 제약 + 참조 구현(anvyx `githooks/pre-push`) 경로를 담았다.
  안내는 `markup=False` 로 출력한다 — rich 가 `[ -t 0 ]` 를 스타일 태그로 삼키면 안내가
  조용히 훼손된다.
- **tracked `hooksPath` 정합 오판 차단 (#201)** — `_hook_installed()` 가 `core.hooksPath` 가
  worktree 내부(tracked)면 훅 내용을 보지 않고 True 를 반환해, **아무도 가드를 넣지 않은
  repo 가 초록으로 보고**됐다(실측 4곳 — anvyc 자신 포함). `_hook_problem()` 으로 교체해
  tracked 여부와 무관하게 실효 훅의 가드 블록을 검사하고, 해소책을 문제별로 분리한다.
  tracked 에는 `guard install` 을 안내하지 않는다(그 명령은 no-op 이다).
- **personal-config-guard 재배선 (#202)** — `core.hooksPath` 오설정을 해제해 pre-push 게이트를
  되살렸더니, 그때까지 hooksPath 덕에 유일하게 돌던 이 가드가 **아무 신호 없이 실행되지 않게**
  됐다. gitleaks 는 내용 기반이라 인식 가능한 패턴이 없는 개인화 파일(`.envrc`·`kubeconfig*`·
  `.claude*/`)은 통과시키므로 대체가 되지 않는다. 로컬은 `.pre-commit-config.yaml` local 훅,
  server-side 는 `personal-config-guard.yml` 워크플로로 배선하되 **양쪽 다 같은 tracked
  스크립트를 재호출**해 SoT 를 하나로 유지한다. `ci.yml` 에 얹지 않은 이유는 그 워크플로의
  `paths-ignore: ['**.md']` 가 차단 대상인 CLAUDE.md·CONTEXT.md 를 정확히 비켜가기 때문이다.
- **가드 스크립트를 현행 SoT 로 (#208)** — tracked 사본이 `efd640f` 에 멈춰 하위경로 시크릿
  (`sub/.env` · `billing/admin.api.env` · `docs/.ssh/id_rsa`)을 통과시키고 있었다.
  role-based-ruleset installer 의 framework 분기(rbr#300)로 갱신했다.

### 버전 정직성 — 설치본이 어느 커밋인지 답한다

- **빌드 시 소스 커밋 각인 (#206)** — `hatch_build.py` 신설. 릴리스 배치 버저닝이라 한 version 이
  여러 커밋을 덮으므로, 로컬 디렉터리를 tool venv 로 설치해 쓰면 "지금 깔린 게 어느 커밋인가" 를
  답할 수 없었다. 빌드 시 git 커밋을 `src/anvyc/_build_info.py` 에 기록하고, `--version` 이
  릴리스 빌드가 아닐 때만 병기한다. `__version__` 은 무변경(기존 소비자 보호), git 부재/실패 시
  아무것도 쓰지 않는다.
- **소스 실행은 런타임 git 이 권위 (#209)** — dev wrapper 는 산출물이 아니라 repo 의 `src/` 를
  실행하므로 설치 시점에 얼어붙은 스탬프는 `git pull` 직후 **실행되지도 않는 커밋을 자신 있게
  출력**한다. 틀린 커밋 표시는 미표시보다 위험하다. `build_commit()` 이 소스 트리면 런타임
  `git rev-parse` + `status` 를, 아니면 빌드 스탬프를 쓴다. `.git` 이 파일인 linked
  worktree(`anvyc worktree add`)도 소스 트리로 인식하고, git 비용은 `--version` 경로에서만 낸다.
  editable 빌드는 아예 스탬프하지 않는다.
- 결과 — **A(dev wrapper) 의 SHA 는 HEAD 와 항상 일치**하며 불일치는 낙후가 아니라 버그다.
  `+dirty` 가 미커밋 변경을, `(… source)` 유무가 A/B 를 가른다.
- **갱신 절차를 설치 방식으로 분기 (#205 · #207)** — `head -1 "$(command -v anvyc)"` 의 shebang
  한 줄로 A(dev wrapper)/B(uv tool)를 가르는 판별을 CONTRIBUTING §2.5 첫머리에 세웠다. dev
  wrapper 환경에서 uv tool 절차를 실행하면 uv 가 `~/.local/bin/anvyc` 를 자기 런처로 덮어써
  wrapper 가 사라지는데 명령 자체는 정상 종료한다. 그리고 **`--force` 만으로는 조용히 실패한다** —
  로컬 소스는 커밋이 바뀌어도 version 이 같으면 uv 캐시 키가 같아져 낡은 빌드가 재사용되고
  rc=0 으로 끝난다. `--reinstall --refresh` 가 필요하다.

### worktree — 룰이 따라온다

- **`anvyc worktree add` (#204)** — `git worktree add` 로 만든 트리에는 에이전트가 읽어야 할 룰이
  전부 빠진다(CLAUDE.md·`.cursor/rules`·`.cursor/skills`·`.envrc` 는 대개 gitignore 대상이라
  체크아웃되지 않는다). 정작 rule 18 은 worktree-per-task 격리를 권장하므로 **권장을 따르면 그
  권장을 담은 룰이 사라지는 모순**이 생긴다. 래퍼가 add 이후 룰 자산을 **symlink** 로 연결한다 —
  복사가 아니다. 복사본은 만든 순간부터 stale 해지고, 실측에서 CLAUDE.md 는 하루 세 번 재생성돼
  격리 사본이 본 저장소보다 최신이 되는 역전까지 일어났다. 격리할 것은 코드지 룰이 아니다.
  상대 경로 링크라 worktree 를 옮겨도 살아 있고, 이미 있는 파일은 건드리지 않으며, `.envrc` 는
  안내만 한다(direnv 승인은 경로별 보안 경계라 자동으로 열지 않는다).
- **`worktree_rule_links` project doctor check** — 래퍼는 강제할 수 없다. 직접 `git worktree add`
  를 쓰면 룰 없이 굴러가는데 신호가 없었다. linked worktree 에서만 검사해 미연결이면 WARNING +
  해소 명령을 내고, 원본 체크아웃에서는 침묵한다.

### 신원 가드 — 선언 부재 자체를 보고한다

- **`ownership_declared` (#203)** — `commit_identity_actual` 은 선언된 커밋 이메일과 실체를
  대조하는데, 선언이 없으면 기준이 없어 조용히 건너뛴다. 그런데 **신원이 잘못 박히는 경로가 바로
  그 "선언 없음"** 이다. 2026-08-18 에 16bitdo 소유 저장소 12곳에서 148개 커밋이 다른 신원으로
  기록됐고, 그 12곳은 전부 manifest 미선언이라 기존 check 가 한 번도 실행되지 않았다 — 가드가
  켜지는 조건과 사고가 나는 조건이 정확히 배타였다. origin 있는 저장소만 대상으로, 미선언이거나
  L2 바인딩에 `commit_email` 이 없으면 WARNING(`project doctor --strict` 시 exit 1).
- **`public_repo_email_exposure` (#203)** — `16bitdo/homebrew-anvyc` 가 PUBLIC 인데 개인 주소로
  커밋하고 있었다. 같은 계정의 `anvyc` 는 noreply 로 막고 있었으니 규칙을 어긴 게 아니라 **규칙이
  코드에 없어서** 한쪽만 지켜진 것이다. 판정 근거를 `-public` 같은 이름 규칙이 아니라 실제
  가시성에 둔다. 커밋에 한 번 박히면 히스토리 재작성 전까지 남고 그사이 색인된다.
- `project doctor` check 11 → **14** (`ownership_declared` · `public_repo_email_exposure` ·
  `worktree_rule_links`). 계수·목록 정합은 drift guard 테스트가 강제한다.

### 업그레이드

```bash
uv tool upgrade anvyc     # 또는: brew upgrade anvyc
```

dev wrapper(editable) 사용자는 `git pull` 이 곧 갱신이다 — `--version` 의 SHA 가 HEAD 와
일치하는지로 확인한다(CONTRIBUTING §2.5). 로컬 소스를 tool venv 에 설치한 경우 `--force` 만으로는
캐시가 재사용되므로 `--reinstall --refresh` 를 쓴다.

훅이 있는 저장소에 `anvyc guard install --force` 를 다시 돌리면, 이제 기존 훅을 덮지 않고 shebang
직후에 가드 블록을 **삽입**한다. 이미 stdin 을 읽는 훅은 건드리지 않고 이식 절차를 안내하므로,
이전 동작(통째 교체)을 기대한 스크립트가 있다면 결과가 달라진다.

## v0.21.0 — 2026-08-17 (minor — 가드/계정 라우팅 서브시스템 + doctor 출력 개편)

v0.20.0 이후 70 커밋(feat 29 · fix 20 · docs 13 · 기타 8)을 모은 릴리스. 축은 셋이다 —
**① 브랜치 보호·pre-push 가드 서브시스템 신설**, **② GitHub/AWS 계정 라우팅을 "라벨"이
아니라 "실체"로 검증**, **③ doctor 출력을 claude doctor 스타일로 개편**.

### 가드 — 브랜치 보호 · pre-push (신규 서브시스템)

- **`anvyc guard install`** — pre-push 가드 렌더/설치. marker 기반이라 foreign hook 을
  보존하고 `core.hooksPath` 를 존중한다. `--project/--root/--dry-run/--force`.
  worktree-safe (`--git-common-dir`).
- **`anvyc guard protect`** — GitHub repository ruleset 적용 CLI. **기본 dry-run**,
  `--apply` 로만 실제 반영. LIST rc 를 직접 분기해 중복 POST·오판을 막고,
  `required_reviews` 를 dry-run detail 에 표시해 적용 전 확인 가능 (#171).
- **`project-branch-protection` doctor check** — ruleset/hook drift 관측. 접근 불가
  repo 는 silent, admin 권한 게이트(`repo_admin`)로 read-only public repo 의 영구
  WARNING/403 제거, archived repo 는 대상에서 제외 (#196).
- **pre-push SoT 에 `anvyc-pr-guard` 임베드** — CI 게이트와 공존 (#164).
- `branch_policy` 는 ruleset lookup 으로 해소하고 실패 시 안전 fallback.

### 계정 라우팅 — 라벨이 아니라 실체 검증

- **`anvyc gh`** — race-immune gh account 라우팅 (#160). cwd origin 의 SSH alias 에서
  account 를 도출해 `GH_TOKEN` 으로 주입하므로, 다른 셸 세션의 `gh auth switch` 가
  전역 active 를 바꿔도 영향받지 않는다. account 도출 불가 시 silent fallback 없이 비0 exit.
- **`account-identity-actual` check** (#188) — 선언된 `gh_config_dir` 프로필의 토큰이
  실제로 그 `github_login` 에 귀속되는지 `gh api user` 역조회로 대조. 라벨 정합만 보던
  기존 체크와 달리 실체를 본다. 조회 실패는 미보고(모름≠불일치), 불일치만 CRITICAL.
  L4 anvyx C6 pre-run gate 가 `doctor --strict --json` 의 `summary.critical` 로 소비.
- **`anvyc github account`** — GitHub 계정 통합 뷰 (#179).
- **`project-gh-account-mapping` 확장** — owner↔alias 정합 검증 static+dynamic (#158),
  그리고 **별칭 미사용 origin 검출** (#198) — plain `github.com`·https origin 인데 owner 가
  `doctor.gh_owner_accounts` 에 등록돼 있으면 WARNING. 미등록 owner 는 silent(무오탐).
  매핑 미설정 시 owner 기반 검증이 전부 skip 되므로 summary INFO 에 그 사실을 표기한다.
- **`anvyc project init`** — per-project gh 라우팅 `.envrc` 스캐폴딩 (#176).

### AWS 계정

- **`aws-account-status`** 전역 doctor check + `project doctor` `aws_account_status`,
  **`anvyc aws profile list/show`** (`--probe` opt-in) — Phase 1 읽기 전용 (#173).
- **`anvyc aws profile create/edit/rm`** — `~/.aws/config` CRUD (#174). surgical 텍스트
  편집 + diff/dry-run/`.bak`/재파싱 검증, 정적 시크릿 불가침, orphan sso-session 경고.
- **scope 정책 정리** — `creds-expiry` 와 `cost-aws-explorer-iam` 를 **실행 중인 프로젝트의
  AWS profile 로 scope**. 도구 repo 등 AWS 미사용 프로젝트에서는 silent 가 기본 동작이 되어
  구조적 spurious warning 이 사라진다.

### doctor 출력 개편

- **claude doctor 스타일** (#161) — 글리프 + check 그룹핑 + verdict 한 줄. `project doctor`
  도 동일 형식으로 통일하고 escape 버그 수정 (#162).
- 비-TTY 에서 80열 강제 개행되던 `soft_wrap` 문제, Rich 가 `[cost-aws]` 같은 대괄호를
  markup 으로 먹어 **복붙 명령이 깨지던** escape 문제 수정 (각각 회귀 테스트 동반).
- cost suggestion 에서 `pip --user` 제거 — venv 안에서 실패하던 플래그.

### 신규 doctor check

`container-runtime-health` (colima(vz) 손상 조기 포착, #157) ·
`ruleset-deploy-drift` (배포 ruleset stale 관측, #182) ·
`claude-md-freshness` (fleet CLAUDE.md content-fresh, #183) ·
`project-branch-protection` · `aws-account-status` · `account-identity-actual`.

### 설정 · 스코프 관리

- **`anvyc config roots`** — 컨테이너 프로젝트 root CRUD (#167).
- **`anvyc config projects`** — 개별 프로젝트 포함/제외 (#169).
- deprecated `~/Documents` 를 스캔 SoT 에서 제거 (#163).

### CLI UX

- 전역 help 단어 별칭 — `anvyc … help` = `--help` (#175).
- no-args 그룹 호출 시 도움말 출력 일관화 — 서브그룹도 루트와 동일 (#177).

### 기타 수정

- `cost-github-pat-scope` — user 별 검증·404 판정 정확화 (#194), suggestion 을 scope
  추가 우선으로 (#193).
- gh 인증 실패를 '권한 없음' 과 구분 — 조용한 거짓 음성 차단 (#195).
- `creds` CLI 가 per-kind 임계를 적용 — 표와 doctor 판정 불일치 해소 (#191).
- `aws_sso` creds 경고에 `sso_session`/profiles 표시 (startUrl 역매핑, #146).
- CP-16 P2A `run_summary` 확장 — `self_status` 분포·percentile·blocked + repo scope (#147).
- `mcp` 를 `<2` 로 상한 고정 — CI red 해소 (#186).
- mypy strict 부채 해소 (`gh_probe`/`gh_account_view`, #181).
- `personal-config-guard` pre-commit 을 tracked 로 전환 (#185).

### 업그레이드

```bash
uv tool upgrade anvyc     # 또는: brew upgrade anvyc
```

`project-gh-account-mapping` 의 별칭 미사용 origin 검출은 `~/.anvyc/anvyc.yaml` 의
`doctor.gh_owner_accounts` 를 설정해야 동작한다(미설정 시 종전과 동일하게 silent).

## v0.20.0 — 2026-05-30 (minor — creds-expiry 임계 anvyc.yaml config화)

per-kind creds-expiry 임계를 코드 기본값에서 **org 별 설정 가능**으로 확장. SSO 세션
TTL 이나 회전 리드타임이 org 마다 달라 단일 고정값으론 한계가 있었다(이 머신 ~1h vs
타 org 8~12h).

- **`anvyc.yaml` `doctor.creds_expiry.warn_thresholds` (kind → 초)**: aws_sso /
  github / claude_oauth 별 "expiring" 경고 임계를 override. 예:
  ```yaml
  doctor:
    creds_expiry:
      warn_thresholds: { aws_sso: 1800, github: 1209600 }   # 30min / 14d
  ```
- 미지정 kind 는 **코드 기본값 유지**(aws_sso 15min / 그 외 7d) — 하위호환.
  expired(CRITICAL)는 임계와 무관.
- 배선: config(초) → `DoctorConfig.creds_warn_thresholds` → `CheckContext` →
  `creds-expiry` 체크가 일 단위 변환 후 `collect_credentials(kind_warn_days=…)` 에 merge.
- `anvyc creds status --warn-days N` CLI 동작 불변 (per-kind 는 doctor 체크 한정).

## v0.19.1 — 2026-05-30 (patch — creds-expiry aws_sso 임계 재튜닝 1h→15min)

v0.19.0 의 aws_sso per-kind 임계(1h)가 실측상 여전히 과민했다 — 일부 org 의 SSO
access token TTL 이 ~1h 라 갓 `aws sso login` 한 직후에도 "expires soon" warning 이
떴다(token 이 access token 만료 시점부터 거의 1h 내내 임계에 걸림).

- **aws_sso 임계 1h → 15min (run-risk window)**: SSO access token 은 짧게 만료되고
  등록 토큰으로 refresh-on-demand 되므로, "곧 시작할 run 도중 죽을 정도로 임박"할
  때만(잔여 ≤ 15min) 경고한다. fresh 토큰(~1h 잔여)은 valid → 로그인 직후 영구 경고
  해소. org TTL 이 더 길면 그만큼 더 오래 valid. expired(CRITICAL)는 임계 무관 그대로.
- `DEFAULT_KIND_WARN_DAYS[aws_sso]` = `900/86400`. github/claude_oauth 7d 불변.
- autopilot C6 게이트에서 SSO 자격이 거의 항상 spurious warning 으로 strict 차단되던
  현상 완화 (CP-14 게이트 정책 옵션 `--gate-skip creds-expiry` 와 병행 사용 가능).

## v0.19.0 — 2026-05-30 (minor — creds-expiry per-kind 임계 + 체크 리네임)

CP-14 게이트 정책 옵션화(anvyx)와 병행한 CP-5 근본 원인 수정. AWS SSO 세션 TTL(수
시간) < 기존 7일 임계라 갓 로그인해도 `aws_sso expires soon` 영구 warning → SSO
환경에서 `doctor --strict` 가 영영 clean 이 안 됨(autopilot 게이트 구조적 차단).

### creds-expiry per-kind 임계 (CP-5)
- **doctor 체크 리네임**: `creds-expiry-within-7d` → **`creds-expiry`** (임계가 더 이상
  단일 7일이 아님). doctor check 개수 20 불변. ⚠️ `anvyc doctor --only/--skip
  creds-expiry-within-7d` 를 쓰던 스크립트는 `creds-expiry` 로 갱신 필요.
- **per-kind 임계**: `core/creds.py` `collect_credentials(kind_warn_days=…)` 추가 —
  aws_sso 는 **1h**(세션 TTL 짧고 `aws sso login` 즉시 갱신 → "임박" 경고는 노이즈,
  run 중 만료 위험만 의미), github/claude_oauth 는 **7d**(수동 회전 리드타임). expired
  (CRITICAL)는 임계 무관하게 그대로 잡힘. `DEFAULT_KIND_WARN_DAYS`.
- `anvyc creds status --warn-days N` CLI 동작 불변 (per-kind 는 doctor 체크만 opt-in).
- 효과: 로그인된 SSO 세션이 doctor/statusline/scheduler 전반에서 더 이상 spurious
  warning 을 내지 않음 → C6 게이트(anvyx) 통과 가능.

## v0.18.0 — 2026-05-30 (minor — CP-14 L4 실행 엔진 run 원장 흡수)

control plane CP-14 (L4 실행 엔진 `anvyx`) 의 **원장 흡수** (Phase 3). anvyx 가
`~/.config/anvyx/runs/<YYYY-MM-DD>.jsonl` 에 emit 하는 C5 run-record 를 anvyc 가
read-only 로 읽어 집계한다 (CP-8 emit→aggregate→display 패턴 재사용).

### CP-14 run ledger (anvyx#1 페어)
- `anvyc/core/runs.py` — run-record reader (`discover_run_files` / `iter_runs` / `collect_runs`) + `aggregate_runs` (총 run 수 / status·exit_reason·agent 분포 / 총 비용·토큰·tool call). 손상 라인/파일 skip, agent 필터.
- `anvyc runs summary [--agent] [--json]` — 통합 통계 (table / JSON).
- `anvyc runs list [--limit] [--agent] [--json]` — 최근 run 목록 (started_at 내림차순).
- MCP tool `run_summary` (read-only) — `aggregate_runs(collect_runs(agent=...))`. 읽기전용 불변식 보존.
- C5 스키마 SoT: role-based-ruleset `metadata/run-record-schema.yaml` (schema_version:1).
- DESIGN §40 → `docs/design-axes/cp-14-run-ledger.md`.

## v0.17.0 — 2026-05-30 (minor — 동반 도구 발견성 + Tools selection UX + CP-15 Secret Broker)

[v0.16.0 → v0.17.0 통합 release] v0.16.0 cut 이후 unreleased 였던 3 axis 를 묶어 publish:
동반 도구(companion tools) 발견성 (anvyc#127~#131), Tools selection UX (anvyc#120~#125),
CP-15 Secret Broker (anvyc#111~#117). **breaking change 없음** — 모두 신규 명령/조회·문서·
내부 SoT 정리이며 기존 동작과 호환된다.

### 동반 도구(companion tools) 발견성 — 외부 CLI·extra 인지/조회 (anvyc#127~#131)

anvyc 의 일부 기능(secret_files / cost / MCP / TUI 등)은 외부 CLI(sops/age/op/…)·pip
extra(boto3/httpx/textual/…)가 있어야 동작하지만, 그 존재·설치법이 코드 곳곳에 흩어져
인지하기 어려웠다. 의존성을 단일 SoT 로 통합하고 **인지(install) → 진단(doctor) →
조회·선택(extras)** 전 동선에 노출.

- **`anvyc extras` 신규** — 동반 도구(외부 CLI + pip extra)의 설치 상태·잠금 기능·설치
  명령을 한 표로. `--json` / `--missing`(미설치만) / `--check`(필수 누락 시 exit 1).
  설치된 extra 는 버전, 미설치는 ✗ + 설치 명령. (anvyc#130)
- **`ExtraReq` SoT** (`src/anvyc/core/extras.py` `EXTRAS_REGISTRY`) — 외부 CLI 8종 +
  pip extra 5종의 메타·설치 안내 단일화 (AdapterMeta 패턴 미러). 흩어져 불일치하던
  `shutil.which`+`brew install` 안내(`core/sops.py`·`core/secrets.py`·`checks/*`·`cli.py`)를
  `is_available()`/`install_hint()` 참조로 통합. README §4.1 표는 `scripts/gen_extras.py`
  가 SoT 에서 생성(`--check` drift 가드). DESIGN §11.2. (anvyc#127)
- **`anvyc doctor` 발견성** — 요약 Top findings 를 severity 내림차순(critical→warning→info)
  정렬해 심각 항목이 info 에 묻히지 않게 하고, blocking finding 은 remediation(설치법)을
  기본 출력에서 `→ …` 한 줄로 노출 (기존엔 `--verbose` 표에서만). (anvyc#128)
- **dev-install 동반 도구 요약** — `scripts/dev-install.sh` 말미에 설치 현황(설치 N/M +
  미설치 목록) + `anvyc extras` 안내를 출력해 첫 설치 시점에 인지. (anvyc#131)

### Tools selection UX — 지원 도구 목록 → 선택 → 구성 (anvyc#120~#125)

도구 메타데이터를 adapter 의 `AdapterMeta` **단일 SoT** 로 통합하고, list / configure /
wizard / MCP / README 가 이를 공유하도록 정리. "지원 도구를 보고 골라서 구성"하는 흐름 강화.
설계/진행: `docs/archive/improvement-plan-tools-selection.md`.

- **`anvyc tools list` 강화** — `label / category / 요약 / 기본 포함·제외 / enabled / detect`
  표시. `--json` 은 포함/제외 등 전체 메타 (기존 키 유지 = 하위호환). MCP `tools_list` 도 합류.
- **`anvyc tools configure` 신규** — 재실행형 enable/disable 선택. `[tui]` extra(textual) +
  TTY 면 체크박스 TUI, 아니면 번호 토글 메뉴(비-TTY/헤드리스 자동 폴백). 저장 전 변경
  미리보기 + 원본 `.bak` + atomic write, 무관 섹션·각 도구의 다른 키 보존, **secret 미접촉**.
- **`AdapterMeta` SoT** — 10 adapter 가 label/summary/category/includes/excludes/
  default_enabled/config_kind/since 노출. README §4 표는 `scripts/gen_supported_tools.py`
  가 SoT 에서 생성(`--check` drift 가드). `init --interactive` wizard 도 SoT 소비
  (`_WIZARD_FILE_DEFAULTS` / `_WIZARD_DEV_ENV_DEFAULTS` 중복 제거).
- **doctor `tui-extra-importable`** (INFO — textual 미설치는 기능 강등이지 실패 아님) → 총 21 check.

### CP-15 Secret Broker — secret 입력/조회 broker (anvyc#111~#117)

"anvyc 는 secret 평문을 보유하지 않는다" 불변식을 유지하며 secret 입력/조회 편의를
추가. 값 custody 는 외부 도구(op / sops / keychain / aws-vault)에 두고 anvyc 는
**reference 레지스트리 + 검증 + JIT 와이어링**만 담당 (Broker, not Vault).
설계: `docs/design-axes/cp-15-secret-broker.md` (DESIGN §39).

- **`anvyc secret list [--json] [--no-probe]`** — `anvyc.yaml` 의 `secrets:` 레지스트리
  (값 없는 핸들) 조회 + backend verify 상태. **값 미출력.**
- **`anvyc secret add <name> -b <op|sops|keychain|aws-vault> … [--apply]`** — 값 입력은
  backend 네이티브 프롬프트 위임 (op `--generate`/`--ref`, sops `sops edit`, keychain
  `security` hidden 프롬프트, aws-vault `aws-vault add`). dry-run 기본 + 쓰기 전 `.bak`.
  **anvyc 는 값 미접촉** (backend 명령 stdio 상속).
- **`anvyc secret get <name> [--reveal]`** — 기본 클립보드(backend stdout → `pbcopy`
  직접 파이프, Python 미캡처) + 자동 만료. `--reveal` 은 TTY 한정(비-TTY 거부).
- **`anvyc secret inject-wire <name> --target <.envrc> [--env-var]`** — `export VAR="$(…)"`
  JIT 주입 라인 생성(값 미저장 — direnv 로드 시 backend resolve). aws-vault 는 exec 가이드.
- **doctor `secret-registry-valid`** + `anvyc.yaml` `secrets:` 블록 schema v1.
- 기존 값의 hidden 입력은 backend 네이티브 프롬프트(keychain/aws-vault / sops `$EDITOR`)로
  충족 — anvyc 자체 `getpass` 방안(과거 Phase 3 후보)은 **폐기**(불변식 비용 부당, 설계 §8).

## v0.16.0 — 2026-05-27 (minor — cost observability MVP + UX 친화도 개선)

[v0.15.2 → v0.16.0 — 15 PR 통합 release] CP-13 cost observability (8 PR),
UX 친화도 개선 (3 PR), docs slim (4 PR) 의 3 axis 가 모두 v0.15.2 cut-over 이후
unreleased 상태였음. 통합 publish.

### Breaking changes (1건)

- **`anvyc apply` default = dry-run** (anvyc#94). 이전 v0.15.x: 즉시 적용.
  - 마이그레이션: `anvyc apply` → `anvyc apply --apply`. `--dry-run` 옵션 제거.
  - 근거: `snapshot restore` / `creds rotate` / `cost gc` / `sync push/pull` 의
    default dry-run + opt-in 패턴과 정합. v0.x.x SemVer 적합.
  - 옛 호출 (`anvyc apply` 단독) 은 데이터 손실 없이 dry-run plan + hint 1줄.

```
v0.15.x                       │ v0.16.0+
─────────────────────────────────────────────────────────────
anvyc apply                   │ anvyc apply --apply
anvyc apply --dry-run         │ anvyc apply (default dry-run)
anvyc apply --only shell      │ anvyc apply --only shell --apply
```

### 사용자 영향 변경 (non-breaking)

- **`anvyc mcp install/uninstall/status` 신규** (anvyc#93) — Claude Code /
  Cursor 의 `mcp.json` 자동 등록. atomic write, 기존 다른 server entry 보존,
  `CLAUDE_CONFIG_DIR` env 인지, `.bak` 자동 생성, IDE 재시작 안내.
- **`anvyc --help` 5-panel 카테고리** (anvyc#95) — Core / Project view /
  Control plane / MCP / serve / External tools. 21 commands 의 첫 화면
  가독성 개선.
- **`anvyc init` 끝 next-step echo** — default / `--from-git` / wizard 3 경로
  통일. doctor / backup / apply (default dry-run) 3 step + AI agent 통합
  안내 (anvyc mcp install).
- **wizard 10 도구** (이전 9) — shell_prompt 누락 fix.
- **shell completion 활성화** — `anvyc --install-completion zsh` 가능 (typer
  `add_completion=False` 제거).
- **`anvyc cost {collect|summary|ledger|gc}` 신규** (CP-13 series, anvyc#79~#88) —
  Anthropic (i) session jsonl channel + AWS Cost Explorer + GitHub Enhanced
  Billing 통합 합산. KRW 표시 (`open.er-api.com` fx), MTD / EOM forecast,
  budget 평가, ledger gc (90d retention).
- **MCP `cost_summary` tool 신규** (anvyc#81) — period 별 source / account
  합산 (8 read-only MCP tools 총합).
- **doctor 14 → 20 check** — `cost-aws-explorer-iam` (PR-13C) /
  `cost-github-pat-scope` (PR-13D) / `mcp-extra-importable` (v0.15.2) /
  `creds-expiry-within-7d` (v0.14.0) / `hook-integrity-risk-gate` (CP-8) /
  `work-cwd-track-wired` (v0.15.0) — 누적 정합화 (anvyc#90).
- **`anvyc.yaml` `cost.github.accounts` override** (anvyc#88) — fine-grained
  PAT 의 Resource owner 가 org 인 경우 user-level endpoint 403 회복 (예시:
  `accounts: ["16bitdo", "heisgone@whatap"]`).

### Cost observability MVP (CP-13, 8 PR — anvyc#79~#88)

ADR SoT: [role-based-ruleset/docs/adr/v6-cp13-cost-observability.md](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/adr/v6-cp13-cost-observability.md)
(Accepted v1.2, 2026-05-27). 구조 SoT: [docs/design-axes/cp-13-cost.md](./docs/design-axes/cp-13-cost.md).

| PR | 내용 |
|---|---|
| anvyc#79 | `pricing/anthropic.yaml` SoT + loader (PR-13A0) |
| anvyc#80 | Session cost dimension + aggregate (PR-13A) |
| anvyc#81 | Anthropic (i) channel adapter + CLI/MCP cost summary (PR-13B1) |
| anvyc#82 | fx (open.er-api) + budgets + ledger/gc + KRW display (PR-13B2) |
| anvyc#83 | budget_evaluations in summary_payload (PR-13E2-anvyc) |
| anvyc#84 | AWS Cost Explorer adapter + doctor check (PR-13C) |
| anvyc#85 | GitHub Billing adapter + doctor check (PR-13D) |
| anvyc#86 | summarize_reports 의 collected_at_latest 노출 (polish #3) |
| anvyc#87 | DESIGN §38.5 의 cost-window.json 위치 정정 (PR-13F chore) |
| anvyc#88 | anvyc.yaml 의 cost.github.accounts override (polish CP-13H) |

핵심 결정:
- `CostReport schema v1` — `source` / `account` / `period (UTC)` / `currency=USD` /
  `breakdown` / `meta.measurement_cost_usd` / `meta.pricing_version` / `meta.org_id`
- 원통화 USD 저장 / 표시 시 KRW 변환 (`fx_rate_basis` 캡처, 회계 재현성)
- admin API (ii) channel **v0.2 deferred** — Anthropic 공식 endpoint 미공개
- 6h rolling window state 권위 위치 = `~/.config/cc-inspect/cost-window.json`
  (ccinspector owner)
- optional dep 격리 — `[cost-aws]` (boto3) / `[cost-github]` (httpx).
  미설치 시 silent skip (graceful degradation).

```bash
# 설치
uv tool install --upgrade 'anvyc[cost-aws,cost-github,mcp]'

# 사용
anvyc cost collect --source anthropic --period mtd
anvyc cost summary --period 2026-05
anvyc cost ledger --source anthropic --meta
anvyc cost gc --apply
```

### UX 친화도 개선 (3 PR — anvyc#93~#95)

UX 4 관점 (설치 / 도구 설정 / 명령어 / Claude 연결) 진단 결과의 High/Medium
friction 5건 동시 해소.

| PR | 친화도 |
|---|---|
| anvyc#93 | `anvyc mcp install/uninstall/status` — Claude/Cursor mcp.json 자동 등록 |
| anvyc#94 | `anvyc apply` default = dry-run (breaking — 다른 destructive 명령과 정합) |
| anvyc#95 | `--help` 5-panel + init next-step echo + wizard 10 도구 + shell completion |

### Docs slim (4 PR — anvyc#89~#92)

| PR | 영역 |
|---|---|
| anvyc#89 | README 912 → 512 / DESIGN 2562 → 1983 / RELEASE_NOTES 1475 → 955 슬림화 + docs/ 10 파일 분리 + DESIGN 결번 (§17a / §27.10) 정정 |
| anvyc#90 | DESIGN §27.1.1 doctor check 목록 14 → 20 + 5 카테고리 sub-grouping |
| anvyc#91 | mcp/server.py + mcp-integration.md 의 stale 표기 갱신 |
| anvyc#92 | mcp-integration.md §4 표 3 row 신설 + 5 → 8 표기 통일 |

신설 docs (`docs/`):
- `multi-account.md` — AWS / GitHub / Claude / Pulumi per-project 라우팅
- `security-policy.md` — 1Password + SOPS
- `doctor-json-schema.md` — CI 통합용 schema
- `control-plane.md` — axis 요약 + cost 빠른 사용
- `design-axes/cp-04-snapshot.md` / `cp-05-creds.md` / `cp-06-sync.md` / `cp-13-cost.md`
- `RELEASE_NOTES_v0.1-v0.6.md` (archive)

### 변경된 사용자 워크플로

| 시나리오 | v0.15.2 | v0.16.0 |
|---|---|---|
| Claude/Cursor MCP 설정 | mcp.json 수동 편집 | `anvyc mcp install --apply --yes` 한 줄 |
| 다른 머신에서 apply | `anvyc apply --dry-run && anvyc apply` | `anvyc apply` (plan) → `anvyc apply --apply` (실 적용) |
| 첫 사용 onboarding | `anvyc init` 후 사용자가 README 봐야 | init 끝에 doctor → backup → apply next-step 자동 echo |
| `anvyc --help` 첫 화면 | 21 commands flat list | 5 panel 카테고리 (Core / Project view / Control plane / MCP / serve / External tools) |
| Cost 가시화 | 미지원 | `anvyc cost summary --period mtd` (Anthropic + AWS + GitHub) |

### 검증

```bash
$ anvyc --version
anvyc v0.16.0

$ anvyc --help                                 # 5 panel 노출
$ anvyc doctor                                 # 20 check 등록
$ anvyc serve --mcp                            # 8 read-only tool 노출
$ anvyc mcp install --apply --yes              # 자동 등록
$ anvyc apply                                  # dry-run plan (breaking 회귀 안전)
$ anvyc cost summary --period mtd              # cost observability
```

### upgrade

```bash
# Homebrew
brew upgrade anvyc

# uv tool (권장)
uv tool install --reinstall \
  https://github.com/16bitdo/anvyc/releases/download/v0.16.0/anvyc-0.16.0-py3-none-any.whl

# 또는 install.sh
ANVYC_VERSION=v0.16.0 bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)
```

### apply 사용자 migration 1 step

```bash
# v0.15.x
anvyc apply               # 즉시 적용
anvyc apply --dry-run     # 계획만

# v0.16.0
anvyc apply               # 계획만 (default dry-run)
anvyc apply --apply       # 실 적용
```

---

## v0.15.2 — 2026-05-26 (patch — MCP integration silent-failure hardening)

[End-to-end 보호 매트릭스] 신규 머신 dev 셋업에서 `anvyc serve --mcp` 가 silent 하게 `Failed to connect` 로 떨어지던 케이스를 트리거로, **dev 셋업 → 런타임 진단 → 에러 메시지 정확성 → CI 드리프트 → 문서화** 5 layer 를 일괄 정비. functional 변경 없음 — 사용자 영향은 셋업/진단/에러 안내 UX 개선과 신규 doctor check 1건.

### 사용자 영향 변경

- **`scripts/dev-install.sh`**: `ANVYC_EXTRAS` 기본값 `dev` → `dev,mcp` (anvyc#69). 신규 contributor 가 추가 설치 없이 `anvyc serve --mcp` 즉시 사용 가능.
- **`anvyc doctor`**: 18 check 로 증가 (17 → 18). 신규 **`mcp-extra-importable`** check 가 `mcp` 패키지 미설치를 WARNING 으로 즉시 감지 + 정확한 설치 명령 안내 (anvyc#72).
- **에러 메시지 — `anvyc serve --mcp`**: `[mcp]` 표기 silent strip 버그 fix (anvyc#71). `pip install 'anvyc[mcp]'` 안내가 정확히 노출.

```
BEFORE: error anvyc MCP server requires the  extra. Install: pip install 'anvyc'
AFTER:  error anvyc MCP server requires the [mcp] extra. Install: pip install 'anvyc[mcp]'
```

### 내부 hardening (사용자 직접 영향 없음)

- **`src/anvyc/utils/errors.py`**: `print_error()` / `safe_msg()` 헬퍼 신설 (anvyc#74). `cli.py` 의 15 exception interpolation + 3 diff coloring 사이트를 헬퍼 경유로 통일 → Rich markup strip 사고 재발 차단.
- **pre-commit mypy 범위 확장**: `src/anvyc/` → `src/anvyc/ tests/` (anvyc#73). CI 의 `Lint and type-check` job 과 동일 범위 — test 파일의 strict 위반이 push 전에 잡힘. 본 변경으로 PR-12E/PR-12F 가 머지 후 main 의 lint job 을 4 commit 연속 fail 상태로 방치하던 사건 패턴 차단.
- **test type annotation 정리**: `tests/unit/test_workctx.py` / `test_work_cwd_track_check.py` 의 32 mypy errors 해소 (anvyc#70). pre-existing main fail 상태 회복의 직접 원인.

### 문서

- **`CONTRIBUTING.md`** §4.4 정정 (mypy 범위) + §4.5 신규 — CLI 사용자 출력 `console.print` 가이드 (anvyc#75). `print_error()` / `safe_msg()` 사용 규칙과 절대 작성 금지 안티패턴 3건을 표/코드로 문서화.

### 변경된 사용자 워크플로

| 시나리오 | v0.15.1 | v0.15.2 |
|---|---|---|
| 신규 머신 dev 셋업 | `bash scripts/dev-install.sh` 후 `pip install -e '.[mcp]'` 별도 필요 | `bash scripts/dev-install.sh` 만으로 MCP 즉시 사용 |
| `mcp` extra 누락 진단 | 사용자가 `anvyc serve --mcp` 직접 호출해 SystemExit 메시지로 추적 | `anvyc doctor` 가 WARNING 으로 즉시 감지 + 설치 명령 안내 |
| MCP 미설치 시 안내 | `error ... requires the  extra. Install: pip install 'anvyc'` (잘못된 명령) | `error ... requires the [mcp] extra. Install: pip install 'anvyc[mcp]'` (정확한 명령) |

### 검증

```bash
$ anvyc --version
anvyc v0.15.2

$ anvyc doctor   # 18 check 등록 확인
```

### upgrade

functional 변경 없음 (셋업/진단/UX 개선만). 즉시 upgrade 권장.

```bash
uv tool install --reinstall https://github.com/16bitdo/anvyc/releases/download/v0.15.2/anvyc-0.15.2-py3-none-any.whl
```

---

## v0.15.1 — 2026-05-26 (patch — `__version__` 동적 lookup refactor)

[Display drift 영구 차단] v0.15.0 release PR (anvyc#67) 이 `pyproject.toml` 의 version 만 0.14.0 → 0.15.0 bump 하고 `src/anvyc/__init__.py:3` 의 hardcode `__version__ = "0.14.0"` 갱신 누락. 결과 — wheel artifact + editable install 양쪽에서 `anvyc --version` 이 `v0.14.0` 표시되는 display drift. functional 영향 없음 (workctx CLI / doctor check 모두 정상 작동) 이지만 향후 release 의 hardcode 갱신 잊음 방지 위해 **동적 lookup 으로 refactor**.

### 변경

- **`src/anvyc/__init__.py`**: hardcode `__version__` → `importlib.metadata.version("anvyc")` 동적 lookup. `PackageNotFoundError` fallback `"0.0.0+unknown"` (source 실행 등 metadata 부재 케이스).
- **`pyproject.toml`**: version `0.15.0` → `0.15.1`. **pyproject 가 SoT** — 향후 release 는 본 파일 1줄만 bump 하면 `__version__` 자동 동기화.

### 검증

```bash
$ anvyc --version
anvyc v0.15.1
```

editable install + wheel install 양쪽 모두 pyproject version 그대로 표시.

### upgrade

v0.15.0 → v0.15.1 의 functional 변경 없음 — display 정정만. 즉시 upgrade 권장.

```bash
uv tool install --reinstall https://github.com/16bitdo/anvyc/releases/download/v0.15.1/anvyc-0.15.1-py3-none-any.whl
```

---

## v0.15.0 — 2026-05-26 (Control Plane v6 — CP-12 agent work-cwd tracking)

[Control Plane v6 합류] anvyc 가 `role-based-ruleset` × `ccinspector` 와 함께 CP-12 (agent work-cwd tracking) axis 의 **L2 Environment layer 책임 2건** 완결. v0.14.0 직후 단일 axis 의 2 PR 묶음 release — CP-12 의 7-PR cross-repo 시퀀스 중 anvyc 측 산출물.

control plane SoT 위치: [role-based-ruleset/ROADMAP.md §4 CP-12](https://github.com/16bitdo/role-based-ruleset/blob/main/ROADMAP.md) + [docs/control-plane-v1-recap.md §13](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/control-plane-v1-recap.md) (v6 cut-over + v6.1 polish 회고, 누적 12 axes / 30 learnings).

### CP-12: agent work-cwd tracking (v6 axis)

launch dir 에 고정된 statusline 의 한계 해소 — agent 의 실 작업 디렉터리 (Bash `cd` / file Read·Write·Edit·MultiEdit / 명시 override) 가 cache (`.work-cwd-cache` schema v1) 에 누적되어 statusline `🔀` swap 으로 실시간 반영. anvyc 측 책임 2건:

- **`anvyc workctx` CLI** ([#65](https://github.com/16bitdo/anvyc/pull/65)) — explicit override 채널. Bash `cd` 가 불가능한 시나리오 (1Password sandbox / sub-shell 격리 / 명시 의도) 에서 statusline / cache 의 work 컨텍스트 강제 전환.
  - `anvyc workctx switch <path> [--ttl 1800]` — explicit row 작성, TTL 기본 1800s (soft expiry — statusline reader 는 row 존재 시 valid 로 간주, anvyc CLI 호출 시점에 lazy cleanup).
  - `anvyc workctx clear` — explicit row 만 제거 (activity row 는 보존).
  - `anvyc workctx show [--json]` — current effective work-cwd (statusline resolver 와 동일 priority: latest non-expired explicit > latest activity within 60s > stale → launch).
  - `core/workctx.py` 신규 — cache schema v1 호환 reader/writer + TTL 관리 (17 unit tests).

```bash
$ anvyc workctx switch ~/dev/anvyc --ttl 60
workctx switch → /Users/edward/dev/anvyc (ttl=60s, expires_at=1779781211)
  cache: /Users/edward/.claude-edward/.work-cwd-cache

$ anvyc workctx show
cache : /Users/edward/.claude-edward/.work-cwd-cache
rows  : 20
 kind           explicit
 path           /Users/edward/dev/anvyc
 expires_at     1779781211
 remaining_sec  47s
```

- **doctor check `work-cwd-track-wired`** ([#66](https://github.com/16bitdo/anvyc/pull/66)) — 3 profile (`.claude` / `.claude-edward` / `.claude-jklee`) 의 hook 배선 + `env.WORK_CWD_CACHE` 주입을 자동 검증. ccinspector `module_verify` (work-cwd-track) 의 **read-only mirror** — 단방향 의존 (DESIGN §7.7) 으로 별 채널 cross-validation. 검증 항목 3건: hooks.CwdChanged (Phase A 필수), hooks.PostToolUse (Phase B 권장), env.WORK_CWD_CACHE (필수). 누락 시 `Severity.WARNING` + 누락 항목 명시.

```bash
$ anvyc doctor --json | jq '.results[] | select(.check_name=="work-cwd-track-wired")'
# (3 profile 모두 wire 정합 시 결과 없음 — 정상)
```

### Cross-repo 페어 (CP-12 7-PR + v6.1 polish)

본 release 의 anvyc 2 PR 외 trace:

- **rbr#83** (PR-12A): `CwdChanged` event hook 본문 + cache schema v1 (Phase A writer).
- **cci#16** (PR-12B): `wire-hooks-cwd-changed.py` + `module_work_cwd_track` (cci install 자동화).
- **cci#17** (PR-12C): `core/statusline.sh` work_cwd_resolve + 🔀 swap 표시 (reader).
- **rbr#84** (PR-12D): PostToolUse Phase B (`Read|Write|Edit|MultiEdit` matcher, `file_op` row writer).
- **cci#18** (PR-12D'): `wire-hooks-posttooluse.py` + Phase B wire 확장.
- **anvyc#65** (PR-12E): **본 release — workctx CLI**.
- **anvyc#66** (PR-12F): **본 release — doctor check**.
- **rbr#85** (PR-12G): `common/rules/28-work-cwd-tracking.mdc` paired chore.

v6.1 polish (multi-session pollution 해소, 같은 일자 ~30 분):
- **rbr#87** (PR-X1): hook 2개 의 `session_id` row writer.
- **cci#19** (PR-X2): statusline 의 `session_id` filter.
- **rbr#88** (PR-X4): rule 28 트러블슈팅 + 회고 §13.7 L30 (workflow 6-step 패턴).

### 신규 학습 (L27~L30, 누적 30)

- **L27**: hook schema 미확정 시 claude-code-guide agent 1-shot 사전 검증 (axis planning 의 표준 step 후보).
- **L28**: axis 내부 cross-repo 시퀀스는 in-session 효율적 — axes 간 분할만 session 분리 trigger.
- **L29**: settings.json 실시간 reload — cci install 후 현 세션의 다음 tool call 부터 새 hook 자동 fire.
- **L30**: L27 의 실 적용 사례 (multi-session pollution polish). **workflow 6 step 패턴** — 사용자 발견 issue → 진단 → 옵션 비교 → 사전 검증 → writer/reader 짝 PR → live 검증 + chore.

### upgrade 가이드

- 사용자: `brew upgrade anvyc` 또는 `pip install --user --upgrade anvyc==0.15.0` 또는 GitHub Release wheel 직접 install.
- 설치 후: `anvyc workctx --help` 로 새 CLI 가용성 확인 + `anvyc doctor` 가 `work-cwd-track-wired` check 자동 포함.
- 기존 사용자 (CP-12 미사용): `anvyc workctx` 명령은 opt-in — cci `module_work_cwd_track=1` 활성화 + `cc-inspect install.sh` 재실행 후 hook + statusline swap 활성. v0.14.0 동작과 100% backward-compat (workctx CLI 호출 안 하면 영향 없음).

---

## v0.14.0 — 2026-05-25 (Control Plane v1+v2 — CP-1 audit · CP-4 snapshot · CP-5 creds)

[Control Plane 통합] anvyc 가 `role-based-ruleset` × `ccinspector` 와 함께 AI agent autopilot **control plane** 의 **L2 Environment layer** 로 정착. v0.13.0 직후 9 axis PR + 1 fix = **10 PR** 으로 3 axis (CP-1·4·5) 완결.

control plane SoT 위치: [role-based-ruleset/ROADMAP.md §4](https://github.com/16bitdo/role-based-ruleset/blob/main/ROADMAP.md) (사람 가독) + [metadata/control-plane-roadmap.yaml](https://github.com/16bitdo/role-based-ruleset/blob/main/metadata/control-plane-roadmap.yaml) (기계 가독) + [docs/control-plane-v1-recap.md](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/control-plane-v1-recap.md) (회고). 5축 (CP-1~CP-5) 전체 done, v1+v2 milestone closed.

### CP-1: 실행 audit / observability (v1 axis, anvyc primary)

Claude Code session transcript (`~/.claude*/projects/*/*.jsonl`) 의 read-only 집계 — autopilot 모드 사후 추적 가능.

- **`anvyc activity` CLI** ([#32](https://github.com/16bitdo/anvyc/pull/32)) — session 별 메타 + tool 호출 카운트 표/JSON 출력 (`--json` / `--limit`).
- **Collector module** (`core/activity.py`, [#31](https://github.com/16bitdo/anvyc/pull/31)) — 멀티계정 환경 (`.claude` / `.claude-edward` / `.claude-jklee`) session 묶음 처리.
- **MCP tools 노출** ([#33](https://github.com/16bitdo/anvyc/pull/33)) — `activity_summary` + `tool_call_stats` (총 7 tool) 로 외부 agent 가 직접 조회.

```bash
$ anvyc activity --limit 3
3 session(s) found  cwd=…  top tools: Bash=12 Read=8 Edit=5
```

### CP-4: 작업 회복 (snapshot / rollback) (v2 axis, anvyc primary)

autopilot 의 실수 (브랜치 30 파일 수정 등) 를 명시적 marker → restore 가능. **4-layer safety** (dry-run / confirm / auto pre-restore / tail capture).

- **`anvyc snapshot create [--label X]`** ([#34](https://github.com/16bitdo/anvyc/pull/34)) — `git stash + meta schema v1` (`schema_version: 1`, claude session id 포함). `.anvyc/snapshots/<id>/meta.json` + `refs/anvyc-snapshots/<id>` anchor.
- **`anvyc snapshot list` / `diff <id> [--against <other>]`** ([#35](https://github.com/16bitdo/anvyc/pull/35)) — read-only query. created_at 내림차순, 손상 entry silently skip.
- **`anvyc snapshot restore <id> [--force] [--yes]`** ([#36](https://github.com/16bitdo/anvyc/pull/36)) — destructive. 기본 dry-run, `--force` + confirm + **auto pre-restore snapshot** 자동 생성 + conflict 시 회복 채널 안내. DESIGN.md §35.7 (Restore 안전 절차 6단계) 신설.
- **fix: untracked 파일 capture** ([#40](https://github.com/16bitdo/anvyc/pull/40)) — `git stash create` 의 `-u` silent 무시 제한 회피 — `_capture_stash` 를 `git stash push -u` + 즉시 `pop --index` 4-step 으로 재작성. v2 cut-over 후 **라이브 시연** 에서 발견된 behavior gap 즉시 fix (회귀 테스트 2건 추가).

```bash
$ anvyc snapshot create --label before-refactor
snapshot created  id=20260525T120000Z-a1b2c3  branch:main  uncommitted:3

$ anvyc snapshot restore 20260525T120000Z-a1b2c3 --force --yes
restore plan ... auto pre-restore: yes (label=pre-restore-...)
restored  target=...
```

### CP-5: 자격 lifecycle (creds rotation) (v2 axis, anvyc primary)

GitHub PAT / AWS SSO / Claude OAuth 토큰의 만료 사전 감지 + 회전. **CP-3 scheduler 와 자연 시너지** (별 wire 작업 없이 doctor check 자동 합류).

- **`anvyc creds status`** ([#37](https://github.com/16bitdo/anvyc/pull/37)) — 3 kind detection (`aws_sso` from `~/.aws/sso/cache/*.json`, `github` from `~/.config/gh/hosts.yml` + 선택 gh probe, `claude_oauth` from `~/.claude*.json`) + `CredentialsReport` schema v1 + status (`valid`/`expiring`/`expired`/`unknown`) 분류.
- **doctor 의 `creds-expiry-within-7d` check** ([#38](https://github.com/16bitdo/anvyc/pull/38)) — 등록만으로 ccinspector 의 CP-3 scheduler 가 `anvyc doctor --strict --json` 호출 시 자동 포함 (L13 cross-axis 자동 합류 패턴). expired → `Severity.CRITICAL`, expiring → `Severity.WARNING`.
- **`anvyc creds rotate <kind> [--force]`** ([#39](https://github.com/16bitdo/anvyc/pull/39)) — destructive native re-auth 위임 (`aws sso login` / `gh auth refresh` / claude_oauth 는 사용자 수동 안내). CP-4 restore §35.7 패턴 미러 4-layer safety. token 본문 노출 회피 (stdout/stderr tail 2 KiB). DESIGN.md §36.8 (Rotate 안전 절차) 신설.

```bash
$ anvyc creds status --no-probe
4 credential(s) — expired=1 expiring=0 (threshold=7d)
  aws_sso       https://d-...../start     2026-05-10T15:13...  -15d (past)  expired
  ...

$ anvyc doctor --only creds-expiry-within-7d
critical — aws_sso 'https://d-...' expired
```

### DESIGN 갱신

- **§35** (Snapshot/Rollback) 신설 — 7 subsection (원칙 / schema v1 / 명령 contract / stash anchor / out-of-scope / 보안 / 안전 절차 §35.7)
- **§36** (Credentials Lifecycle) 신설 — 8 subsection (원칙 / schema v1 / 명령 contract / source detection / scheduler 자연 시너지 / out-of-scope / 보안 / 안전 절차 §36.8)

### 테스트

v0.13.0 대비 +66 hermetic assertion + 라이브 시연 검증:
- snapshot 33 (create 8 + 2 fix / list+diff 13 / restore 10) + creds 35 (status 15 + check 8 + rotate 12) = **68 신규**
- 라이브 시연: 4 demo / 17 케이스 / 1 behavior gap 발견 + fix

### Control Plane 자산 (외부 참조)

- 회고: [control-plane-v1-recap.md](https://github.com/16bitdo/role-based-ruleset/blob/main/docs/control-plane-v1-recap.md) — v1 §1~§8 + v2 §9 (5/5 axis 완결 + 15 learnings 누적)
- 페어 secondary 작업: [rbr#56](https://github.com/16bitdo/role-based-ruleset/pull/56) (rule 18-git-codebase-sync, CP-4) + [rbr#58](https://github.com/16bitdo/role-based-ruleset/pull/58) (rule 26-secrets-1password, CP-5)
- ccinspector 측 CP-3 scheduler (`modules/scheduler/`): `anvyc doctor --strict --json` 을 일1회 호출 → 본 release 의 `creds-expiry-within-7d` check 가 자동 합류 (cross-axis 시너지 L13)


## v0.13.0 — 2026-05-22 (shell prompt 통합 + 개발 환경/CI 정비)

[shell prompt 통합] anvyc 의 per-project 계정 라우팅(AWS/GitHub/Claude/Pulumi)을
shell prompt 에 바로 노출하고, prompt 도구(starship/powerlevel10k) 의 설정
파일도 백업 대상에 추가한다.

### `anvyc prompt` — 계정 라우팅 세그먼트 명령

현재 디렉터리의 계정 라우팅을 shell prompt 용 한 줄로 출력한다 — `project show`
를 매번 실행하지 않고도 prompt 에 상시 표시.

- 설정된 필드만 공백 구분 `key:value` 출력 (`aws` / `gh` / `claude` / `pulumi`),
  없으면 빈 출력. `--json` 보조.
- prompt 컨텍스트라 **어떤 오류도 셸을 깨지 않는다** — 빈 출력 + exit 0.
- starship custom command / powerlevel10k 세그먼트 연동: `docs/shell-prompt.md`.

```bash
$ anvyc prompt
aws:company-dev gh:16bitdo claude:edward
```

### `shell_prompt` 어댑터 — starship/p10k 설정 백업

starship(`~/.config/starship.toml`)·powerlevel10k(`~/.p10k.zsh`) 의 prompt
설정 파일을 백업/동기화 대상에 추가한다 (어댑터 9 → 10). 두 도구를 단일
`shell_prompt` 어댑터로 묶어 존재하는 파일만 collect 한다 (`enabled: true`).

### 개발 환경 / CI 정비

- **dev wrapper PYTHONPATH 전환** — `~/.local/bin/anvyc` dev wrapper 가 editable
  `.pth` 대신 `PYTHONPATH` 로 `src/` 를 주입하고 `python -m anvyc` 로 실행 →
  macOS UF_HIDDEN trap 을 근본 회피 (chflags self-heal 제거). `src/anvyc/__main__.py`
  진입점 추가.
- **`dev-install.sh` 인터프리터 탐지 보강** — `python3.13` bare 명령 부재 시
  `uv python find 3.13` 으로 폴백해 의도치 않은 Python 버전 다운그레이드 방지.
- **CI macOS 과금 ~65% 절감** — lint·test matrix 를 `ubuntu-latest` 로 이전하고
  macOS 는 test 3.13 한 잡만 유지. mypy `platform = "darwin"` 고정으로 ubuntu
  에서도 `os.chflags` 등 macOS-only API 를 정상 인식.

---

## v0.12.0 — 2026-05-22 (per-project Claude/Pulumi 계정 라우팅)

[account-routing 확장 — anvyc 의 per-project 계정 라우팅 인식을 Claude Code 와
Pulumi 로 확장] anvyc 은 AWS(`AWS_PROFILE`)·GitHub(`GH_CONFIG_DIR`) 의
per-project 계정 라우팅을 인식·검증해 왔다. v0.12.0 은 같은 모델을 Claude Code
와 Pulumi 로 확장한다 (계획: `docs/improvement-plan-account-routing.md`).

> v0.11.0 cycle 변경분(scan-root 프로젝트 루트 SoT 단일화 `~/dev` 이전 +
> per-project gh-account routing 인식)도 본 릴리스에 함께 포함된다 — v0.11.0
> 은 별도 태깅 없이 v0.12.0 으로 통합 배포한다. 상세는 아래 v0.11.0 섹션 참조.

### Claude Code 계정 라우팅 (Phase 1)

`.envrc` 의 `export CLAUDE_CONFIG_DIR="$HOME/.claude-<account>"` 는 Claude Code
가 네이티브로 읽는 env var (`GH_CONFIG_DIR` 의 직접 analog) 다. anvyc 이 이
라우팅을 인식·검증한다.

- `ProjectInfo.claude_account` 필드 — `project show` / `project list` / MCP JSON
  에 추가. `CLAUDE_CONFIG_DIR` basename 의 `.claude-` prefix 제거로 도출
  (`$HOME/.claude-edward` → `edward`).
- 신규 global doctor check `project-claude-account-mapping` — `project_roots`
  아래 `.envrc` 의 `CLAUDE_CONFIG_DIR` 가 가리키는 config 디렉터리 존재 검증.
- 신규 per-cwd check `claude_account_dir_exists` (`anvyc project doctor`).
- `multi-account-detected` 가 `~/.claude-*` 계정별 디렉터리도 감지.

gh 와 달리 cross-check 할 remote 가 없어 검증은 디렉터리 존재 확인(1-way)이다.

```bash
$ anvyc project show --json | jq .claude_account
"edward"
```

### Pulumi backend 라우팅 (Phase 2)

Pulumi 의 "계정"은 단일 username 이 아니라 **backend**(state 저장 위치 + org)
다. `Pulumi.yaml` 의 `backend.url`(1순위 SoT)과 `.envrc` 의 `PULUMI_BACKEND_URL`
(env override) 정합성을 검증한다.

- `ProjectInfo.pulumi.backend` 필드 — `Pulumi.yaml` 의 `backend.url` 노출.
  `backend` 키 부재(Pulumi Cloud default)는 추적하지 않는다.
- 신규 global doctor check `project-pulumi-backend-mapping`.
- 신규 per-cwd check `pulumi_backend_routing` — 2-way 정합성 (URL 정규화 후 비교).
- `PULUMI_ACCESS_TOKEN` 은 secret → `dev_env` 에서 자동 마스킹 (값 추적 안 함).

### Cursor — 라우팅 제외 결정

Cursor 멀티 계정은 `cursor --user-data-dir=` 실행 플래그뿐 — `.envrc` env var
신호가 없어 anvyc 의 라우팅 패턴이 성립하지 않는다. account-routing 계획 §3.3
에서 옵션 A(제외)로 확정.

### doctor check 확장

- global `anvyc doctor` — 12 → **14 check** (`project-claude-account-mapping`,
  `project-pulumi-backend-mapping` 추가).
- `anvyc project doctor` — 6 → **8 check** (`claude_account_dir_exists`,
  `pulumi_backend_routing` 추가).

---

## v0.11.0 — 2026-05-20 (per-project gh-account routing 인식)

[Phase 2 — anvyc 의 기존 per-project AWS profile 기능을 GitHub 으로 미러링]
여러 GitHub 계정 (`16bitdo` 개인 / `secondary` org 봇) 을 쓰는 환경에서
`gh` CLI 의 single global active account 가 "whack-a-mole" false warning 을
유발한다. 해결책으로 project 별 `.envrc` 가
`export GH_CONFIG_DIR="$HOME/.config/gh-<account>"` 를 export 해 direnv 로
계정을 라우팅한다. v0.11.0 은 anvyc 가 이 라우팅을 인식하도록 확장한다.

### `ProjectInfo.gh_account` 필드 (P1)

`anvyc project show` / `project list` / MCP `project_show` 의 JSON 에
`gh_account` 키 추가. `.envrc` 의 `GH_CONFIG_DIR` 경로 값에서 basename 의
`gh-` prefix 를 제거해 도출 (`$HOME/.config/gh-16bitdo` → `16bitdo`).
`AWS_PROFILE` 과 달리 경로 값이라 basename 추출 한 단계를 더 거친다.
`GH_CONFIG_DIR` 부재 / basename 이 `gh-<name>` 형식 아님 → `null`.

```bash
$ anvyc project show --path ~/Documents/proj --json
{
  "path": "/Users/edward/Documents/proj",
  "aws_profile": "company-dev",
  "gh_account": "16bitdo",
  ...
}
```

### 신규 global doctor check: `project-gh-account-mapping` (P2)

`~/Documents/**/.git` 의 GitHub `origin` 이 ssh alias (`github.com-<alias>`)
를 쓰는 project 가, 같은 디렉터리 `.envrc` 의 `GH_CONFIG_DIR` 로 일치하는
gh 계정 라우팅을 선언했는지 검증 (`project-aws-profile-mapping` 의 GitHub
아날로그).

- routing OK (gh 계정 == ssh alias) → INFO 1건 (summary)
- `.envrc` 에 `GH_CONFIG_DIR` 없음 → project 마다 WARNING
- gh 계정 ≠ ssh alias → mismatch 마다 WARNING
- ssh alias 쓰는 GitHub origin 없음 → 결과 0건 (silent)

```bash
anvyc doctor --only project-gh-account-mapping
```

### `project doctor` 신규 per-cwd check: `gh_account_routing` (P3)

cwd 의 origin ssh alias ↔ `.envrc` `GH_CONFIG_DIR` 정합성 검증
(`github_remote_parseable` 와 동일 패턴). `project doctor` 가 5 check →
6 check 로 확장. plain `github.com` origin (ssh alias 없음) 은 silent skip.

### 신규 / 수정 파일

- `src/anvyc/checks/project_gh_account.py` (신규)
- `src/anvyc/core/project_info.py` (`gh_account` 필드 + `_derive_gh_account`)
- `src/anvyc/core/doctor.py` (`_REGISTRY` 등록)
- `src/anvyc/core/project_doctor.py` (`_check_gh_account_routing`)
- `src/anvyc/cli.py` (project show/list 의 `gh_account` 렌더링)
- `src/anvyc/mcp/server.py` (project_doctor docstring 5→6 check)
- `tests/unit/test_project_gh_account.py` (신규, 9 case)
- `tests/integration/test_project_show.py` / `test_project_doctor.py` /
  `test_project_list.py` / `test_mcp_server.py` (`gh_account` schema 반영)
- `DESIGN.md §27 / §32 / §33`, `README.md §11.6`, `CONTEXT.md`
- `pyproject.toml`, `src/anvyc/__init__.py` — version 0.10.0 → 0.11.0

### Backward compatibility

- JSON schema 는 key 추가만 (`gh_account`) — minor 변경, backward-compat
  (DESIGN §32.7 정책 그대로).
- 신규 check 추가 — 기존 doctor / project doctor check 동작 변경 없음.
- `GH_CONFIG_DIR` 미사용 환경은 모든 신규 check 가 silent (결과 0건).

### 통계

- pytest 기존 195 + 신규 14 (unit 9 + project doctor 4 + show 1) = 209
- ruff check / mypy (src + tests) green
- uv build → `anvyc-0.11.0-py3-none-any.whl` 정상

---

## v0.10.0 — 2026-05-19 (MCP tool naming cleanup — breaking)

[follow-up of v0.9.0 회귀 테스트 — `mcp__anvyc__anvyc_*` 의 redundant prefix
관찰됨. tool 이름에서 `anvyc_` prefix 제거]

### Breaking change — MCP tool 이름

| v0.9.0 | v0.10.0 |
|---|---|
| `anvyc_project_show` | `project_show` |
| `anvyc_project_list` | `project_list` |
| `anvyc_project_doctor` | `project_doctor` |
| `anvyc_doctor` | `doctor` |
| `anvyc_tools_list` | `tools_list` |

agent 가 호출하는 실제 이름은 server name 까지 포함되어 `mcp__anvyc__*`
→ v0.10.0 에서는 `mcp__anvyc__project_show` (이전: `mcp__anvyc__anvyc_project_show`).

### Migration

- agent / IDE 가 tool 이름을 직접 하드코딩한 경우만 영향.
- Claude Code / Cursor 의 mcp.json 자체는 변경 불필요 (server name `anvyc` 유지).
- v0.10.0 wheel 재설치만으로 새 이름 자동 노출 — agent 가 다시 tool 목록 fetch.
- 검증: `printf '...initialize+tools/list...' | anvyc serve --mcp` →
  `tools[].name` 이 `project_show` 등 5개.

### Schema 안정성 정정

DESIGN §34.9 — v0.9.0 첫 MCP release 의 tool 이름은 cleanup deferred 였음.
v0.10.0 부터 5 tool 이름 + input/output schema 는 **public API**. minor 변경
(key 추가) 만 backward-compat, breaking 은 v1.0+ 까지 보류.

### 신규 / 수정 파일

- `src/anvyc/mcp/server.py` — 5 tool name + dispatch 분기 + docstring
- `tests/integration/test_mcp_server.py` — _dispatch 인자
- `docs/mcp-integration.md`, `DESIGN.md §34`, `docs/improvement-plan-ai-agent.md`
- `pyproject.toml`, `src/anvyc/__init__.py` — version 0.9.0 → 0.10.0

### Backward compatibility

- 기존 14 CLI 명령 동작 변경 없음.
- 이전 v0.9.0 tool 이름은 **invalid** — `_dispatch("anvyc_project_show", ...)` 호출 시
  `ValueError: unknown tool`.

### 통계

- 1 commit (server + 5 docs + version + RELEASE_NOTES)
- pytest 영향 없음 (테스트 _dispatch 인자도 새 이름)

---

## v0.9.0 — 2026-05-19 (MCP server — AI agent direct integration)

[Wave 9 of docs/improvement-plan-ai-agent.md §7.3 — AI Agent Integration]
Claude Code / Cursor 가 anvyc 의 5 read-only tool 을 stdio Model Context
Protocol 로 직접 호출. subprocess + stdout parse 우회.

### 신규 명령: `anvyc serve --mcp` (P6)

```bash
# 설치 (optional extra):
uv tool install --upgrade 'anvyc[mcp]'

# Claude Code (~/.claude/mcp.json) 또는 Cursor (~/.cursor/mcp.json):
{
  "mcpServers": {
    "anvyc": {"command": "anvyc", "args": ["serve", "--mcp"]}
  }
}
```

### 노출 tool (5 read-only, D21)

| tool | 매핑 | 출력 |
|---|---|---|
| `project_show` | `anvyc project show` | ProjectInfo (DESIGN §32) |
| `project_list` | `anvyc project list` | array of ProjectInfo |
| `project_doctor` | `anvyc project doctor` | `{path, results}` |
| `doctor` | `anvyc doctor --json` | `{results}` (12 check) |
| `tools_list` | `anvyc tools list --json` | array of tool entries |

write 영역 (`backup`/`apply`/`restore`) 은 의도적 미포함 — agent 가
destructive 실행 못 함.

### 의존성 격리 — `[mcp]` optional extra (D20)

| 설치 | 의존 |
|---|---|
| core anvyc (default) | typer / rich / pathspec / pyyaml (4) — 변경 없음 |
| `anvyc[mcp]` | core + mcp + (pydantic, anyio, httpx, jsonschema, ...) |

- Homebrew Formula 영향 **없음** (core 만 build)
- MCP 사용자는 별도 `uv tool install 'anvyc[mcp]'`
- mcp 미설치 환경에서 `anvyc serve --mcp` → clean error + install 안내

### 보안 정책

- D11c redaction default — secret 패턴 매칭 → `***REDACTED***`
- `op://` 1Password reference 는 placeholder signal → redaction 면제
- `reveal_secrets=true` 명시 시만 raw 값 노출 (agent/log 유출 주의)
- raw secret 은 `project_doctor` 검증 시 메모리에만, message 에는 KEY 명만

### 신규 / 수정 파일

- `src/anvyc/mcp/__init__.py` (신규)
- `src/anvyc/mcp/server.py` (신규, 5 tool dispatch + stdio entry)
- `src/anvyc/cli.py` — `@app.command("serve")` 신규
- `pyproject.toml` — `[project.optional-dependencies] mcp` 추가
- `tests/integration/test_mcp_server.py` (9 case, importorskip)
- `docs/mcp-integration.md` (신규, Claude/Cursor 설정 + 사용 예 + 트러블슈팅)
- `DESIGN.md §34` (신규, MCP architecture)
- `README.md §5.5` (MCP install) + `§8` (serve 명령) + `§13` 로드맵

### Backward compatibility

- 신규 명령만 추가 (`anvyc serve`), 기존 14 명령 동작 변경 없음
- `[mcp]` extra 미설치 환경은 영향 없음 (default install 그대로)
- `ProjectInfo` / `DoctorReport` schema 재사용

### Schema 안정성

DESIGN §34.9 — v0.9.0 부터 5 tool 의 input/output schema 는 **public API**.
minor 변경 (key 추가) 만 backward-compat, breaking 은 v1.0+.

### 통계

- 4 commits (mcp extra + server + tests + docs/version-bump)
- pytest 기존 ~176 + 신규 9 = ~185 (mcp 설치 환경, 미설치 시 skip)
- core wheel `anvyc-0.9.0-py3-none-any.whl` size 변동 작음 (mcp 미포함)

---

## v0.8.1 — 2026-05-19 (Cross-Project + Audit)

[Wave 8 of docs/improvement-plan-ai-agent.md §7.2 — Cross-Project + Audit]
Wave 7 의 `anvyc project show` (single project) 를 fan-out + audit 로 확장.

### 신규 명령

| 명령 | 동작 |
|---|---|
| `anvyc project list [--root R...] [--json]` | 입력 root 아래 모든 project 의 connection matrix |
| `anvyc project doctor [--path P] [--json] [--strict]` | cwd connection 정합성 5 check |

### `anvyc project list` (P2)

```bash
$ anvyc project list --json | jq 'map(select(.pulumi != null)) | length'
4    # ~/Documents/ 의 Pulumi project 수

$ anvyc project list --json | jq 'map({path, aws_profile, github: .github[0].owner})'
[...]
```

- discovery rule (D12): `.git` 또는 `Pulumi.yaml` marker 보유 디렉터리 (depth ≤ 2)
- 각 entry 는 `anvyc project show` 와 **동일 schema** (DESIGN §32 재사용)
- D11c redaction 동일 적용 — `--reveal-secrets` opt-in
- `--root` 반복 가능 (default: `~/Documents`)

### `anvyc project doctor` (P7)

```bash
$ anvyc project doctor --json
{
  "path": "/.../proj",
  "results": [
    {"check_name": "aws_profile_defined", "severity": "info", ...},
    {"check_name": "github_remote_parseable", "severity": "info", ...},
    {"check_name": "pulumi_stacks_valid", "severity": "info", ...},
    {"check_name": "dev_env_secret_safety", "severity": "info", ...},
    {"check_name": "tool_versions_installed", "severity": "info", ...}
  ]
}
```

5 check (D14):

| check | trigger | issue severity |
|---|---|---|
| `aws_profile_defined` | `.envrc` AWS_PROFILE 있을 때만 | WARNING |
| `github_remote_parseable` | `.git/config` 있을 때만 | (parse 가능한 것만 INFO) |
| `pulumi_stacks_valid` | `Pulumi.yaml` 있을 때만 | WARNING |
| `dev_env_secret_safety` | `.envrc` 의 export 있을 때만 | **CRITICAL** (raw secret) |
| `tool_versions_installed` | `.python-version`/`.nvmrc`/`.tool-versions` 있을 때만 | WARNING |

- source 가 없으면 silent skip (bare path → `{"results": []}`)
- `--strict` 시 warning 이상 발견 → exit 1
- 기존 `anvyc doctor` (global) 와 별개 — `project doctor` 는 path-aware

### DESIGN §33 신규 (schema 정식화)

`project list` + `project doctor` 의 외부 호환 보장. `project list` 는 §32
ProjectInfo schema 재사용, `project doctor` 는 doctor `--json` 의 result entry
와 동일 6-field 형식.

### 신규 / 수정 파일

- `src/anvyc/core/project_discovery.py` (신규) — discover_projects
- `src/anvyc/core/project_doctor.py` (신규) — 5 check + ProjectDoctorReport
- `src/anvyc/cli.py` — project_app:list + project_app:doctor
- `tests/unit/test_project_discovery.py` (8 case)
- `tests/integration/test_project_list.py` (5 case)
- `tests/integration/test_project_doctor.py` (8 case)
- `DESIGN.md §33` 신규
- `README.md §8` 명령어 + `§13` 로드맵

### 안전 가드

- `project doctor` 가 raw secret 메모리 사용 — message 에는 KEY 명만 (raw 미포함)
- discovery 가 marker 발견 디렉터리 하위는 더 안 들어감 (성능)
- symlink 디렉터리는 alias 가능성으로 자동 skip
- bare path / missing source → silent (noise 없음)

### Backward compatibility

- 신규 명령만 추가 (`project list`, `project doctor`)
- 기존 13 명령 (project show 포함) 동작 변경 없음
- `ProjectInfo` schema (DESIGN §32) 재사용 — `project list` 와 `project show` 가 동일 schema

### 통계

- 3 commits (project list + project doctor + docs/version-bump)
- pytest 기존 ~155 + 신규 21 (8 + 5 + 8) = ~176
- uv build → `anvyc-0.8.1-py3-none-any.whl` 정상

---

## v0.8.0 — 2026-05-19 (Project-Centric View — AI agent integration)

[Wave 7 of docs/improvement-plan-ai-agent.md §7.1 — Project-Centric View]
AI agent (Claude Code / Cursor / ChatGPT) 가 cwd 의 모든 connection 정보
(AWS profile / GitHub remote / Pulumi project / dev_env / tool versions) 를
단일 JSON 으로 받기 위한 통합 view + machine-readable 확장.

### 신규 명령: `anvyc project show` (P1)

```bash
$ anvyc project show --path ~/Documents/proj --json
{
  "path": "/Users/edward/Documents/proj",
  "aws_profile": "company-dev",
  "github": [
    {
      "name": "origin",
      "url": "git@github.com-16bitdo:16bitdo/proj.git",
      "host": "github.com-16bitdo",
      "owner": "16bitdo",
      "repo": "proj",
      "ssh_alias": "16bitdo",
      "protocol": "ssh"
    }
  ],
  "pulumi": {
    "project_name": "proj",
    "runtime": "python",
    "stacks": ["dev", "prd"],
    "yaml_path": "/Users/edward/Documents/proj/Pulumi.yaml"
  },
  "dev_env": {
    "AWS_PROFILE": "company-dev",
    "NODE_ENV": "development",
    "GITHUB_TOKEN": "***REDACTED***"
  },
  "tool_versions": {"python": "3.13", "node": "20.10.0"}
}
```

- `--path P` 로 임의 path 지정 (default: cwd)
- `--json` 으로 machine-readable JSON 출력 (없으면 human rendering)
- **D11c**: dev_env 의 값에 anvyc `security.patterns.PATTERNS` 매칭 시
  자동 `***REDACTED***` 마스킹
- `op://` 1Password reference 는 placeholder signal 이므로 redaction 면제
- `--reveal-secrets` 명시 시 raw 값 노출 (agent/log 유출 주의)

### 신규 utility (P3 + P4)

| 모듈 | 동작 |
|---|---|
| `src/anvyc/utils/pulumi_project.py` | `<project>/Pulumi.yaml` + `Pulumi.<stack>.yaml` 추출 (name/runtime/stacks) |
| `src/anvyc/utils/git_remote.py` | `<project>/.git/config` 의 [remote "X"] 파싱 (SSH/HTTPS URL → owner/repo/ssh_alias) |
| `src/anvyc/core/project_info.py` | 위 둘 + dev_env + tool_versions 통합 + redaction |

backup 영역과 분리 — read-only utility, `anvyc project show` 의 backend.

### 신규 JSON output (P5)

- `anvyc tools list --json` — `[{tool, enabled, detected, files, secrets}]` 9 row
- `anvyc config show --effective --json` — AnvycConfig dataclass dict (default 채워짐)

기존 raw text 출력 backward compat — `--json` 미지정 시 동일.

### DESIGN.md §32 신규 (schema 정식화)

`anvyc project show --json` 의 외부 호환 보장. v0.8.0 부터 schema 는
**public API** — minor 변경 (key 추가) 만 허용, breaking 변경은 v1.0+.

### 신규 / 수정 파일

- `src/anvyc/utils/pulumi_project.py` (신규)
- `src/anvyc/utils/git_remote.py` (신규)
- `src/anvyc/core/project_info.py` (신규)
- `src/anvyc/cli.py` (project_app subcommand + tools_list/config_show --json)
- `tests/unit/test_pulumi_project_util.py` (8 case)
- `tests/unit/test_git_remote_util.py` (8 case)
- `tests/integration/test_project_show.py` (7 case)
- `tests/integration/test_tools_list_json.py` (2 case)
- `tests/integration/test_config_show_json.py` (2 case)
- `DESIGN.md §32` 신규
- `README.md §8` (명령어 요약) + `§13` 로드맵
- `docs/improvement-plan-ai-agent.md §12` Q1=완료, Q3=v0.8.0 정식화

### Backward compatibility

- 신규 명령만 추가 (`project show`), 기존 9 명령 동작 변경 없음
- `tools list` / `config show` 는 raw 출력 그대로, `--json` 만 신규 옵션
- doctor `--json` schema 와 별개 (각각 독립 정식화)

### 통계

- 3 commits (impl utilities + project show + JSON outputs + docs/version-bump)
- pytest 기존 ~128 + 신규 ~27 (8+8+7+2+2) = ~155
- uv build → `anvyc-0.8.0-py3-none-any.whl` 정상

---

## v0.7.2 — 2026-05-19 (dependency cleanup: pydantic removed)

### 배경

`brew install anvyc` 가 `pydantic-core 2.16.3` 의 Rust extension 빌드에서
실패. Homebrew Python virtualenv 의 install 단계는:
- `pip install --no-binary :all:` (wheel 금지)
- 빌드 단계 네트워크 sandbox

→ `pydantic-core` 의 build 의존성 `maturin` 다운로드 실패.

### 발견

`grep` 결과: anvyc 코드 어디에서도 `pydantic` 을 import 하지 않음.
v0.1.0 의 초기 schema 계획 때 declare 됐지만 실제 구현은 `dataclass` 로 진행
되어 잔존 의존성 (`pyproject.toml:dependencies` 만).

### 변경

- `pyproject.toml`: `pydantic>=2.6` dependency 제거
- Homebrew Formula: `annotated-types`, `pydantic`, `pydantic-core` resource
  3개 제거 (13 → 10 resources)

### Backward compatibility

- 코드/CLI 동작 변경 없음 (pydantic 미사용이라 영향 zero)
- 기존 `pip install anvyc` / `uv tool install` 도 그대로 작동 (의존성 감소만)

### 통계

- 1 commit (impl: pyproject + version + RELEASE_NOTES, Formula 는 별도 commit)
- pytest 영향 없음 (test suite 가 pydantic 미사용)

---

## v0.7.1 — 2026-05-19 (onboarding wizard + install one-liner)

[Wave 6 of docs/improvement-plan-ux-review.md §8.3 — onboarding]
새 사용자가 9 도구 설정을 한 번에 끝낼 수 있는 대화형 wizard + 외부 설치
스크립트.

### 신규 명령: `anvyc init --interactive` (alias `-i`)

```
$ anvyc init -i
anvyc init wizard — 9개 도구 설정

Enable shell? [Y/n]:
  files for shell [~/.zshrc, ~/.zprofile]:
Enable git? [Y/n]:
  files for git [~/.gitconfig, ~/.gitignore_global]:
...
Enable dev_env? [y/N]:           # ← default disabled (안전)
  project_roots [~/Documents]:
  patterns [.envrc, .tool-versions, .python-version, .nvmrc]:

preview:
  version: 1
  storage: { root: .anvyc, keep_backups: 5 }
  tools: { ... }

Write to .anvyc/anvyc.yaml? [Y/n]:
✓ wrote .anvyc/anvyc.yaml
```

- 9 도구 (8 default-enabled + dev_env default-disabled) prompt
- file-based adapter (shell/git/aws/gh/pulumi) 는 file path 입력
- dev_env 는 project_roots + patterns 입력
- cursor/claude/iterm2 는 default 설정 (path prompt skip)
- yaml preview 후 최종 확인 → 작성
- `--from-git` 과 mutual exclusion (exit 1)

### 신규 파일: `install.sh` (one-liner installer)

```bash
curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh | bash
```

- `set -euo pipefail` strict mode
- GitHub Release wheel + `SHA256SUMS` 자동 검증
- `uv tool` 또는 `pipx` 자동 감지 (없으면 명시 안내 + exit 1)
- env 옵션:
  - `ANVYC_VERSION=v0.7.1` (default: latest)
  - `ANVYC_METHOD=uv|pipx|auto` (default: auto)
- macOS (`shasum`) + Linux (`sha256sum`) 양쪽 호환
- shellcheck 통과

> **현재 repo 는 private 이라 raw URL 이 404.** Z4 (PUBLIC 전환) follow-up 후 활성화.

### 신규 / 수정 파일

- `src/anvyc/cli.py` — init 함수에 `--interactive` 옵션 + `_run_init_wizard()` 헬퍼
- `install.sh` — bash strict mode one-liner installer
- `tests/integration/test_init_interactive.py` (4 case)
- `tests/test_install_script.py` (6 case — syntax / strict / verify / shellcheck)

### 안전 가드

- wizard 가 기존 anvyc.yaml 위에 작성 시도 → fail-fast (`--force` 필요)
- `--interactive --from-git` 동시 지정 → exit 1 (의미 충돌)
- install.sh SHA256 mismatch → exit 1 + 명시 메시지
- install.sh trap 으로 temp dir cleanup (실패 경로 포함)
- install.sh 가 uv/pipx 둘 다 없으면 `pip install <wheel>` 안내 후 exit 1

### Backward compatibility

- `anvyc init` (no `--interactive`) 동작 v0.7.0 그대로
- install.sh 는 본 repo 안의 새 파일 (다른 코드 영향 없음)

### 통계

- 3 commits (wizard + install.sh + docs/version-bump)
- pytest 118 → 128 (+10: wizard 4 + install 6)
- uv build → `anvyc-0.7.1-py3-none-any.whl` 정상

---

## v0.7.0 — 2026-05-19 (dev_env adapter + AWS profile cleanup)

[Wave 5 of docs/improvement-plan-ux-review.md §8.3 — dev_env 묶음]
v0.6.0 부터 README §11 에 안내한 multi-AWS-profile 워크플로 (direnv + .envrc)
를 실제 코드로 묶음. 사용자 환경 (direnv 2.37.1 설치) 에서 즉시 가치.

### 신규 어댑터: `dev_env` (8 → 9 adapter)

`~/Documents/**` 같은 project root 아래에서 다음 패턴 추적:

| 패턴 | 도구 |
|---|---|
| `.envrc` | direnv (AWS_PROFILE / NODE_ENV / API_URL 등) |
| `.tool-versions` | asdf |
| `.python-version` | pyenv |
| `.nvmrc` | nvm |

기본 설정 (anvyc.yaml):

```yaml
tools:
  dev_env:
    enabled: false              # 안전 default — 사용자가 명시 enable
    project_roots:
      - "~/Documents"
    patterns:
      - ".envrc"
      - ".tool-versions"
      - ".python-version"
      - ".nvmrc"
    exclude:
      - "**/node_modules/**"
      - "**/.venv/**"
      - "**/.git/**"
```

- depth ≤ 3 (project root 기준 — 성능 보호)
- exclude pathspec (`gitignore` 형식)
- secret 정책: 기존 scanner 가 `.envrc` 안의 raw token 차단

사용 예:

```bash
$ anvyc backup --only dev_env
backup .anvyc/backups/20260519-140000
  dev_env  ~/Documents/proj-a/.envrc    a3f5b2c1...
  dev_env  ~/Documents/proj-b/.envrc    9d8e7f6a...
  dev_env  ~/Documents/proj-c/.tool-versions  4b2a1c8d...
```

### 신규 doctor check: `unused-aws-profiles` (10 → 11 check)

`~/.aws/config` 에 정의됐지만 `~/Documents/**/.envrc` 의 `AWS_PROFILE` 값으로
사용되지 않는 profile 을 INFO 로 안내 (cleanup 용, 강제력 없음).

`project-aws-profile-mapping` (v0.6.1) 의 reverse — A1 은 .envrc → config
검증, 본 check 는 config → .envrc 사용량 검증.

```bash
$ anvyc doctor --only unused-aws-profiles
info — 11 AWS profile(s) defined but not referenced in any .envrc:
       pulumi-dev, company-agency, company-audit, company-demo, ws-dev, ... (+6)
```

`[default]` profile 은 fallback 으로 가정되어 unused 판정에서 제외.

### 신규 / 수정 파일

- `src/anvyc/adapters/dev_env.py` — DevEnvAdapter
- `src/anvyc/checks/unused_aws_profiles.py` — UnusedAwsProfilesCheck
- `src/anvyc/core/backup.py` — ADAPTERS 등록 + `_select_adapters` dev_env 분기
- `src/anvyc/core/doctor.py` — _REGISTRY 등록
- `src/anvyc/templates.py` — dev_env 기본 yaml section (disabled by default)
- `tests/unit/test_dev_env_adapter.py` (7 case)
- `tests/integration/test_dev_env_backup.py` (2 case)
- `tests/unit/test_unused_aws_profiles.py` (5 case)
- README §4 (지원 도구 9), §13 로드맵

### Backward compatibility

- 신규 dev_env adapter 는 default `enabled: false` — 자동으로 사용자의 ~/Documents 를 스캔하지 않음 (안전)
- unused-aws-profiles check 는 다른 check 처럼 `--only` / `--skip` 으로 선택 가능
- 기존 어댑터 / check 동작 변경 없음

### 통계

- 2 commits (impl + docs/version-bump)
- pytest 104 → 118 (+14: dev_env 9 + unused-aws 5)
- adapters: 8 → 9
- doctor checks: 10 → 11
- uv build → `anvyc-0.7.0-py3-none-any.whl` 정상


---

## 아카이브 (v0.1.0 ~ v0.6.4)

v0.6.4 이하 릴리스의 상세 노트는
[docs/RELEASE_NOTES_v0.1-v0.6.md](./docs/RELEASE_NOTES_v0.1-v0.6.md) 에 보관.

| 버전 | 일자 | 한줄 요약 |
|---|---|---|
| v0.6.4 | 2026-05-19 | host overlay (`anvyc.<hostname>.yaml`) |
| v0.6.3 | 2026-05-19 | `anvyc config edit/show` + `tools list` |
| v0.6.2 | 2026-05-19 | `anvyc init --from-git` + Homebrew Formula 초안 |
| v0.6.1 | 2026-05-19 | multi-account doctor checks |
| v0.6.0 | 2026-05-19 | OSS 공개 준비 (LICENSE/SECURITY 등) |
| v0.2.0 | 2026-05-18 | scanner 정밀도 강화 + Cursor adapter 확장 |
| v0.1.0 | 2026-05-18 | MVP — 6 adapter + 핵심 backup/apply/restore |

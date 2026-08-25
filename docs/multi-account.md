# 다수 계정 관리 가이드 (multi-account workflow)

> AWS profile / GitHub / Claude Code / Pulumi 의 per-project 계정 라우팅을
> `.envrc` (direnv) 로 선언하고 anvyc 의 doctor check 로 정합성을 검증한다.

anvyc 는 **정적 설정 sync 도구**다. runtime profile switching 은 표준 도구
([direnv](https://direnv.net/), [aws-vault](https://github.com/99designs/aws-vault))
에 맡기고 anvyc 는 그 설정을 백업·동기화하는 역할에 집중한다.

## 1. AWS profile 라우팅

### 1.1 권장 패턴: direnv + .envrc (프로젝트별 1개 profile)

```bash
# 1) direnv 설치 + zsh hook
brew install direnv
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc

# 2) 프로젝트 디렉터리에 .envrc 작성
cat > ~/dev/my-dev-project/.envrc <<'EOF'
export AWS_PROFILE=my-dev
EOF

# 3) 새 .envrc 신뢰 (보안)
cd ~/dev/my-dev-project
direnv allow

# 4) 이후로는 cd 시 AWS_PROFILE 자동 설정
cd ~/dev/my-dev-project   # → AWS_PROFILE=my-dev 자동 export
cd ~/                     # → AWS_PROFILE 자동 unset
```

### 1.2 PR 별 임시 전환 (1~3 profile 교체)

```bash
# ~/.zshrc 에 helper function:
awsp() { export AWS_PROFILE="$1"; aws sts get-caller-identity; }

# PR 작업 중:
awsp my-dev      # 개발
awsp my-audit    # 로그 확인
awsp my-prd      # 운영 readonly
unset AWS_PROFILE  # 원복
```

또는 [aws-vault](https://github.com/99designs/aws-vault) (MFA 강제 + 격리):

```bash
aws-vault exec my-prd -- terraform plan
```

### 1.3 anvyc 가 추적하는 것

```yaml
# anvyc.yaml
tools:
  aws:
    enabled: true
    files: ["~/.aws/config"]        # 모든 profile 정의 백업
    # ~/.aws/credentials 는 secret 으로 기본 제외
    # SOPS 통합 시 secret_files 로:
    # secret_files: ["~/.aws/credentials"]

  dev_env:                          # v0.7.0+
    project_roots: ["~/dev"]
    patterns: [".envrc", ".tool-versions", ".python-version", ".nvmrc"]
```

### 1.4 anvyc 의 scope (책임 경계)

| anvyc 가 해야 할 | anvyc 가 안 해야 할 |
|---|---|
| `~/.aws/config` profile 정의 sync | runtime profile switching |
| `.envrc` 파일 추적 (`dev_env` 어댑터) | credential 자체 관리 |
| profile mapping 검증 (doctor check) | shell session state 추적 |
| 변경 안전망 (local-backup) | AWS API 호출 자체 |

direnv 와 aws-vault 가 더 잘 하는 영역에 anvyc 가 들어가면 도구 경계가
모호해진다. anvyc 는 **정적 설정 동기화 + 검증 + 권장 워크플로 가이드** 역할.

### 1.5 doctor checks (AWS)

| Check | 동작 | 상태 |
|---|---|---|
| `project-aws-profile-mapping` | `project_roots` 아래 `.envrc` 의 `AWS_PROFILE` 값 ↔ `~/.aws/config` 정합성 | ✓ v0.6.1 |
| `aws-profile-status` | 현재 active `AWS_PROFILE` env var ↔ 정의 검증 | ✓ v0.6.1 |
| `multi-account-detected` | ssh / aws / cursor / claude alias 의 multi-account 환경 자동 안내 (INFO) | ✓ v0.6.1, v0.12.0 확장 |
| `unused-aws-profiles` | `.aws/config` 에만 있고 어디서도 안 쓰는 profile (INFO) | ✓ v0.7.0 |

```bash
# 개별 실행
anvyc doctor --only project-aws-profile-mapping
anvyc doctor --only aws-profile-status
anvyc doctor --only multi-account-detected
```

### 1.6 AWS profile 인증/연결 상태 (`anvyc aws profile`, v0.21.0+)

profile 이 존재할 때 인증 방식과 연결 상태를 read-only 로 보고한다.
`doctor` / `project doctor` 는 **완전 오프라인** — 네트워크 호출 없음.
`--probe` 만 `aws sts get-caller-identity` 를 실행해 라이브 verdict 를 추가한다.

```bash
# 전체 profile 목록 + 인증 방식 + 오프라인 상태
anvyc aws profile list

# JSON 출력
anvyc aws profile list --json

# 상태 판정 생략 (이름 목록만)
anvyc aws profile list --no-status

# 네트워크 liveness 확인 포함
anvyc aws profile list --probe

# 단일 profile 상세 (keys + 인증 방식 + 상태)
anvyc aws profile show ws-dev

# 단일 profile + liveness
anvyc aws profile show ws-dev --probe
```

| 인증 방식 | 판정 기준 | status 예시 |
|---|---|---|
| `sso` | `~/.aws/config` 의 `sso_session` 또는 `sso_start_url` + SSO 캐시 | `valid` / `expiring` / `expired` / `unknown` / `none` |
| `static` | `~/.aws/credentials` 에 섹션 존재 | `present` |
| `assume_role` | `role_arn` + `source_profile` 선언 | `source_ok` / `source_missing` / `env` |
| `credential_process` | `credential_process` 키 존재 | `cmd_ok` / `cmd_missing` |
| `web_identity` | `web_identity_token_file` 키 존재 | `classified` |
| `undefined` | 인증 키 없음 | `missing` |
| `incomplete` | config 섹션 존재하지만 인증 키 전무 | `incomplete` |

SSO 로그인 만료 시 doctor 가 suggestion 으로 `aws sso login` 을 안내하지만 실행은 하지 않는다.

### 1.7 profile CRUD (`anvyc aws profile create/edit/rm`, v0.21.0 Phase 2)

`~/.aws/config` 의 profile 을 surgical 텍스트 편집으로 생성·수정·삭제한다.

```bash
anvyc aws profile create ws-dev --sso-session ws --start-url https://d-x.awsapps.com/start \
  --sso-region ap-northeast-2 --account-id 111122223333 --role-name Dev \
  --region ap-northeast-2 --dry-run      # 미리보기 (쓰기 안 함)
anvyc aws profile create ws-dev --sso-session ws --region ap-northeast-2 -y   # 적용
anvyc aws profile edit ws-dev --set region=us-east-1 -y   # 키 수정 (in-place, 주석 보존)
anvyc aws profile rm ws-dev                               # 삭제 (확인 후 적용)
```

안전 절차: 변경 전 unified diff 미리보기 → `--dry-run` 확인 → `.bak` 백업 → atomic write → 재파싱 검증 → 실패 시 원본 자동 복구. `~/.aws/credentials`(정적 시크릿)는 절대 건드리지 않으며 `aws_access_key_id`/`aws_secret_access_key`/`aws_session_token` 입력을 거부한다. profile 삭제 시 참조하던 sso-session 이 고아가 되면 경고만 출력하고 자동 삭제는 하지 않는다.

## 2. GitHub 계정 라우팅 (v0.11.0+)

> ⚠️ **`GH_CONFIG_DIR` 은 config 파일만 격리하고 자격은 격리하지 않는다.**
> gh 가 활성 토큰을 키체인에서 hostname 만으로 조회하기 때문이다
> ([cli/cli#10136](https://github.com/cli/cli/issues/10136), gh 2.73.0 재현).
> 아래 예시대로 두 계정을 각각 로그인하면 **나중 로그인이 앞의 것을 무력화**한다.
>
> `.envrc` 의 `GH_CONFIG_DIR` 은 여전히 유용하다 — config 파일(호스트 설정·기본 프로토콜)
> 은 분리된다. 다만 **어느 계정으로 인증되는가는 결정하지 못한다.**
>
> 계정을 명시적으로 고르려면 `GH_TOKEN` 을 쓴다. 키체인의 계정별 토큰은 온전하다:
>
> ```bash
> GH_TOKEN=$(gh auth token --user 16bitdo) gh pr create ...
> ```

AWS profile 과 같은 문제가 GitHub 계정에도 있다. `gh` CLI 는 **single global
active account** 만 가지므로, 여러 계정 (개인 / org 별 봇 계정 등) 을 오가면
잘못된 계정으로 동작하거나 false warning 이 발생한다. AWS 의 `.envrc` +
`AWS_PROFILE` 과 **형태는 같지만 격리 수준은 다르다** — AWS 는 profile 별
자격이 실제로 격리되지만, gh 는 위 경고대로 config 파일만 격리되고 활성
자격(토큰)은 격리되지 않는다. 그럼에도 project 별 `.envrc` 에 `GH_CONFIG_DIR`
을 선언해두면 호스트 설정 분리와 함께 "이 프로젝트가 어느 계정으로 라우팅
되어야 하는지" 를 direnv 로 명시할 수 있다 — 실제 계정 전환은 `GH_TOKEN` 이
담당한다.

```bash
# 1) 계정별 gh config 디렉터리 준비 (convention: ~/.config/gh-<account>)
#    두 로그인 다 필요하다 — 키체인에 계정별 토큰이 저장된다(아래 GH_TOKEN 의 전제).
GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"  gh auth login   # 개인 계정
GH_CONFIG_DIR="$HOME/.config/gh-secondary" gh auth login  # org 봇 계정
#    ⚠️ 그러나 "활성" 계정은 마지막 로그인(여기선 secondary)으로 전역 고정된다.
#    이후 GH_CONFIG_DIR 를 바꿔도 활성 계정은 따라오지 않는다(위 §2 경고 참고).

# 2) 프로젝트 .envrc 에 라우팅 선언 (origin ssh alias 와 일치시킬 것)
#    이 선언은 "의도"만 기록하고 config 파일(호스트 설정)을 분리할 뿐,
#    활성 계정을 바꾸지는 않는다.
cat >> ~/dev/my-personal-repo/.envrc <<'EOF'
export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"
EOF

# 3) 새 .envrc 신뢰
cd ~/dev/my-personal-repo
direnv allow

# 4) cd 만으로는 계정이 자동으로 갈리지 않는다 — GH_CONFIG_DIR 는 라우팅
#    "의도"를 표시할 뿐이다. 실제로 그 계정을 쓰려면 호출마다 GH_TOKEN 을 명시:
cd ~/dev/my-personal-repo
GH_TOKEN=$(gh auth token --user 16bitdo) gh api user --jq .login   # → 16bitdo
```

권장: `GH_CONFIG_DIR` 의 계정 이름을 git `origin` 의 ssh alias
(`git@github.com-<alias>:...`) 와 동일하게 맞춘다. anvyc 의 doctor check 가
이 일치를 검증한다.

| Check | 동작 | 상태 |
|---|---|---|
| `project-gh-account-mapping` | `project_roots` 아래 `.envrc` 의 `GH_CONFIG_DIR` ↔ GitHub `origin` ssh alias 정합성 (global) | ✓ v0.11.0 |
| `gh_account_routing` | cwd 의 `GH_CONFIG_DIR` ↔ origin ssh alias 정합성 (`anvyc project doctor` 의 per-cwd check) | ✓ v0.11.0 |
| `gh_identity_actual` | `.envrc` 라벨 프로필을 `gh api user` 로 역참조해 얻은 **자격 실체**를 **manifest ownership** 과 대조 — 조회 대상은 라벨 프로필("지금 실제로 쓰일 프로필"), 비교 대상은 ownership(L1 SoT). 라벨끼리 비교하면 `.envrc` 드리프트만으로 게이트가 무력화된다 | ✓ 신규 |

```bash
anvyc doctor --only project-gh-account-mapping
anvyc project doctor              # cwd 에 gh_account_routing 포함 14 check
```

`anvyc project show --json` 의 `gh_account` 필드로 project 의 라우팅 계정을
machine-readable 하게 확인할 수 있다 (DESIGN §32.4a). 계정 인증 자체는 `gh`
가 관리하며, anvyc 는 정적 설정 동기화 + 검증 역할.

### 2.1 계정 통합 뷰 (`anvyc github account`, Phase 1)

`aws profile list/show` 의 GitHub 대응물. 머신의 gh 계정 인벤토리 + 로그인 +
(opt-in) 토큰 만료 + 현재 프로젝트 라우팅을 한 명령으로 본다. `anvyc gh` 는
passthrough 실행이므로 조회/관리는 별도 `anvyc github` 그룹이다(읽기 전용).

```bash
anvyc github account list            # 계정 + 로그인 + 라우팅(owners / ✓cwd)
anvyc github account show 16bitdo    # 단일 계정 상세 (--json)
anvyc github account list --probe    # 토큰 만료 (gh api, opt-in 네트워크)
```

| 필드 | 의미 |
|---|---|
| `logged_in` | `~/.config/gh-<account>/hosts.yml` 존재 (stat; 토큰 미독) |
| `expiry_status` | `--probe` 시 `gh api` 만료 헤더 — valid/expiring/expired/unknown |
| `routed_owners` / `cwd_routed` | `anvyc.yaml` `doctor.gh_owner_accounts` 매핑(설정 시에만 값 사용 — 기본값은 빈 dict, 이 경우 owner 라우팅 skip) + cwd origin alias 일치 |

**Secret 경계**: 토큰을 읽거나 저장·출력하지 않는다(hosts.yml 의 host/user +
만료 헤더만). 계정 생성·로그인·회전은 `gh auth` / 1Password 위임.

## 3. Claude Code 계정 라우팅 (v0.12.0+)

Claude Code 도 단일 계정 config 를 쓰므로, 개인 / 업무 계정을 오가면 잘못된
계정으로 동작할 수 있다. `CLAUDE_CONFIG_DIR` 은 Claude Code 가 네이티브로 읽는
env var (`GH_CONFIG_DIR` 의 직접 analog) 이므로, `.envrc` 에 선언하면 direnv 가
project 별 계정 (config + auth 토큰) 을 라우팅한다.

> ⚠️ 이 "analog" 는 env var 로 config 디렉터리를 지정하는 **형태**의 유사성이다.
> §2 의 `GH_CONFIG_DIR` 자격 격리 결함이 `CLAUDE_CONFIG_DIR` 에도 동일하게
> 적용되는지는 이번 조사에서 **검증하지 않았다**.

```bash
# 1) 계정별 config 디렉터리 준비 (convention: ~/.claude-<account>)
CLAUDE_CONFIG_DIR="$HOME/.claude-16bitdo" claude   # 개인 계정 로그인
CLAUDE_CONFIG_DIR="$HOME/.claude-work"    claude   # 업무 계정 로그인

# 2) 프로젝트 .envrc 에 라우팅 선언
cat >> ~/dev/my-personal-repo/.envrc <<'EOF'
export CLAUDE_CONFIG_DIR="$HOME/.claude-16bitdo"
EOF

# 3) 새 .envrc 신뢰
cd ~/dev/my-personal-repo
direnv allow
```

| Check | 동작 | 상태 |
|---|---|---|
| `project-claude-account-mapping` | `project_roots` 아래 `.envrc` 의 `CLAUDE_CONFIG_DIR` 가 가리키는 config 디렉터리 존재 검증 (global) | ✓ v0.12.0 |
| `claude_account_dir_exists` | cwd 의 `CLAUDE_CONFIG_DIR` config 디렉터리 존재 (`anvyc project doctor` 의 per-cwd check) | ✓ v0.12.0 |

```bash
anvyc doctor --only project-claude-account-mapping
anvyc project doctor              # cwd 에 claude_account_dir_exists 포함 9 check
```

`anvyc project show --json` 의 `claude_account` 필드로 라우팅 계정을 확인할 수
있다 (DESIGN §32.4b). gh 와 달리 cross-check 할 remote 가 없어 검증은 **디렉터리
존재 확인 (1-way)** 만 한다 — 핵심 가치는 AI agent / 사용자가 "이 프로젝트가 어느
Claude 계정으로 라우팅되는지" 를 알 수 있는 것이다.

## 4. Pulumi backend 라우팅 (v0.12.0+)

Pulumi 의 "계정"은 AWS profile / gh 계정 같은 단일 username 이 아니라 **backend**
(state 저장 위치 + org/account) 개념이다. project 별로 다른 backend 를 쓰면
`Pulumi.yaml` 의 `backend.url` 로 선언하고, 필요 시 `.envrc` 의
`PULUMI_BACKEND_URL` 로 override 한다.

```yaml
# Pulumi.yaml — state backend 선언 (커밋되는 SoT)
name: my-infra
runtime: python
backend:
  url: s3://acme-pulumi-state
```

```bash
# (선택) .envrc 로 backend env override — Pulumi.yaml 과 일치시킬 것
cat >> ~/dev/my-infra/.envrc <<'EOF'
export PULUMI_BACKEND_URL="s3://acme-pulumi-state"
EOF
direnv allow
```

| Check | 동작 | 상태 |
|---|---|---|
| `project-pulumi-backend-mapping` | `project_roots` 아래 `Pulumi.yaml` backend ↔ `.envrc` `PULUMI_BACKEND_URL` 정합성 (global) | ✓ v0.12.0 |
| `pulumi_backend_routing` | cwd 의 `Pulumi.yaml` backend ↔ `.envrc` `PULUMI_BACKEND_URL` 정합성 (`anvyc project doctor` 의 per-cwd check) | ✓ v0.12.0 |

```bash
anvyc doctor --only project-pulumi-backend-mapping
anvyc project doctor              # cwd 에 pulumi_backend_routing 포함 9 check
```

`anvyc project show --json` 의 `pulumi.backend` 필드로 backend 를 확인할 수 있다
(DESIGN §32.4c). `backend` 키를 명시하지 않으면 Pulumi Cloud default 이며 anvyc 은
명시 선언만 추적한다. `PULUMI_ACCESS_TOKEN` 은 secret 이라 `dev_env` 에서 자동
마스킹되고, anvyc 은 값을 추적하지 않는다.

## 5. shell prompt 통합 (`anvyc prompt`, v0.13.0+)

`anvyc prompt` 는 현재 디렉터리의 계정 라우팅을 shell prompt 용 한 줄로
출력한다 — `project show` 를 매번 치지 않고 prompt 에서 바로 확인.

```bash
$ anvyc prompt
aws:company-dev gh:16bitdo claude:edward
```

설정된 필드만 공백 구분 `key:value` 로 출력하고 없으면 빈 출력이다. starship
custom command / powerlevel10k 세그먼트 연동 방법은
[shell-prompt.md](./shell-prompt.md) 참고.

## 신규 프로젝트 gh 라우팅 셋업

owner 가 16bitdo/whatap 인 repo 를 새로 clone 하면 per-project `.envrc` 라우팅을 1회 명령으로 만든다:

```bash
cd ~/dev/<new-repo>
anvyc project init        # origin alias 에서 계정 도출 → 확인(Enter) → .envrc + .gitignore + direnv allow
```

- origin SSH alias(`github.com-<account>`)가 있으면 계정 자동 도출, 없으면 입력 요청.
- `--account <name>` 으로 직접 지정, `--yes` 로 비대화, `--no-allow` 로 direnv allow skip.
- `anvyc project doctor` 의 `gh_account_routing` check 가 누락을 감지하면 이 명령으로 교정한다.

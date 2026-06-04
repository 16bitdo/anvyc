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

## 2. GitHub 계정 라우팅 (v0.11.0+)

AWS profile 과 같은 문제가 GitHub 계정에도 있다. `gh` CLI 는 **single global
active account** 만 가지므로, 여러 계정 (개인 / org 별 봇 계정 등) 을 오가면
잘못된 계정으로 동작하거나 false warning 이 발생한다. AWS 의 `.envrc` +
`AWS_PROFILE` 패턴과 동일하게, project 별 `.envrc` 에 `GH_CONFIG_DIR` 을
선언해 direnv 가 계정을 라우팅하게 한다.

```bash
# 1) 계정별 gh config 디렉터리 준비 (convention: ~/.config/gh-<account>)
GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"  gh auth login   # 개인 계정
GH_CONFIG_DIR="$HOME/.config/gh-secondary" gh auth login  # org 봇 계정

# 2) 프로젝트 .envrc 에 라우팅 선언 (origin ssh alias 와 일치시킬 것)
cat >> ~/dev/my-personal-repo/.envrc <<'EOF'
export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"
EOF

# 3) 새 .envrc 신뢰
cd ~/dev/my-personal-repo
direnv allow

# 4) 이후 cd 시 gh 가 올바른 계정 자동 사용
cd ~/dev/my-personal-repo   # → gh 가 gh-16bitdo config 사용
```

권장: `GH_CONFIG_DIR` 의 계정 이름을 git `origin` 의 ssh alias
(`git@github.com-<alias>:...`) 와 동일하게 맞춘다. anvyc 의 doctor check 가
이 일치를 검증한다.

| Check | 동작 | 상태 |
|---|---|---|
| `project-gh-account-mapping` | `project_roots` 아래 `.envrc` 의 `GH_CONFIG_DIR` ↔ GitHub `origin` ssh alias 정합성 (global) | ✓ v0.11.0 |
| `gh_account_routing` | cwd 의 `GH_CONFIG_DIR` ↔ origin ssh alias 정합성 (`anvyc project doctor` 의 per-cwd check) | ✓ v0.11.0 |

```bash
anvyc doctor --only project-gh-account-mapping
anvyc project doctor              # cwd 에 gh_account_routing 포함 9 check
```

`anvyc project show --json` 의 `gh_account` 필드로 project 의 라우팅 계정을
machine-readable 하게 확인할 수 있다 (DESIGN §32.4a). 계정 인증 자체는 `gh`
가 관리하며, anvyc 는 정적 설정 동기화 + 검증 역할.

## 3. Claude Code 계정 라우팅 (v0.12.0+)

Claude Code 도 단일 계정 config 를 쓰므로, 개인 / 업무 계정을 오가면 잘못된
계정으로 동작할 수 있다. `CLAUDE_CONFIG_DIR` 은 Claude Code 가 네이티브로 읽는
env var (`GH_CONFIG_DIR` 의 직접 analog) 이므로, `.envrc` 에 선언하면 direnv 가
project 별 계정 (config + auth 토큰) 을 라우팅한다.

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

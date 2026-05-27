# Secret 분리 정책 — 1Password Secret Reference + SOPS

> anvyc 의 두 가지 secret 분리 채널 — single 변수는 1Password reference, 다수
> 묶음은 SOPS encryption-at-rest. 두 채널 공존 가능. README §9 의 보안 등급
> 표 + scanner 의 false-positive 강등 규칙은 README 본체 유지.

## 1. 1Password Secret Reference (v0.1.0)

raw secret 대신 [1Password Secret Reference](https://developer.1password.com/docs/cli/secret-references/)
`op://<vault>/<item>/<field>` 를 사용한다. reference 자체는 비-secret 이므로
backup / Git commit 안전.

```bash
# .zshrc 예
export AWS_ACCESS_KEY_ID="op://Personal/AWS/access_key_id"
export GITHUB_TOKEN="op://Personal/GitHub/token"
```

### 1.1 사용 흐름

```bash
# 1) 1Password CLI 설치 + 로그인
brew install 1password-cli      # macOS
op signin

# 2) 민감 값을 1Password 에 등록 (또는 기존 항목 사용)
op item create --category=login --title='AWS' \
    access_key_id=AKIA... secret_access_key=...

# 3) dotfile 에서 raw secret 을 op:// reference 로 치환

# 4) backup — reference 는 그대로 들어감
anvyc backup

# 5) 다른 머신에서 apply 후 1Password 로그인만 하면 동일 환경
op signin           # 새 머신에서
anvyc apply --apply   # v0.16.0+: default 가 dry-run 이라 --apply 명시
```

### 1.2 scanner 의 false-positive 강등

같은 라인에 `op://` 가 있으면 다른 secret 패턴 매칭이 `low` 로 강등된다
(placeholder 신호로 간주). 따라서 위 `.zshrc` 예시는 backup 시 차단되지 않는다.

### 1.3 doctor 의 reference 검증

`anvyc doctor --only op-references-valid` 가 발견된 모든 `op://` URI 를
`op read` 로 resolve 시도한다. 실패 시 WARNING. `op` CLI 미설치/미인증 시
안전 skip.

---

## 2. SOPS encryption-at-rest (v0.2)

다수 secret 묶음 (`.env`, `.toml`, 바이너리 키 등) 은
[SOPS](https://github.com/getsops/sops) 로 암호화하여 백업한다. age 키 backend
기본 지원.

```bash
# 1) sops + age 설치
brew install sops age

# 2) age key 생성 (한 번만)
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
# Public key: age1abc... ← anvyc.yaml 에 추가

# 3) anvyc.yaml 설정
cat >> .anvyc/anvyc.yaml <<EOF
security:
  sops:
    enabled: true
    age_recipients:
      - "age1abc...edward-mac"
    age_identity_file: "~/.config/sops/age/keys.txt"

tools:
  pulumi:
    enabled: true
    files: ["~/.pulumi/config.json"]
    secret_files: ["~/.pulumi/credentials.json"]
EOF

# 4) backup — secret_files 는 자동으로 SOPS 암호화
anvyc backup
# → backup_dir/pulumi/sops/credentials.json.sops.json (encrypted)

# 5) 다른 머신에서 — 같은 age private key 가 있어야 복호화
anvyc apply --apply   # SOPS 자동 복호화 후 target 에 평문 저장 (v0.16.0+: --apply 명시)
```

### 2.1 두 채널 공존

- 단일 변수 raw secret → `op://` reference (§1)
- 다수 secret 묶음 (`.env` 등) → SOPS `secret_files`

### 2.2 doctor 점검

`anvyc doctor --only sops-keys-available` 가 sops/age binary 와 age identity
file 부재를 자동 안내.

### 2.3 scanner 통합

SOPS 로 암호화된 파일 (`.sops.json` 또는 `sops:` metadata 보유) 은 secret scan
통과 — 암호화된 상태에서 base64 가 secret 패턴에 매치되는 false positive 차단.

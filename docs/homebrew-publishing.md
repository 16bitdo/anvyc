# Homebrew tap 갱신 절차

> anvyc 의 Homebrew tap (`16bitdo/homebrew-anvyc`) 을 새 anvyc 버전으로 동기화
> 하는 follow-up 가이드. 본 절차는 anvyc release 후 **수동으로 1회** 실행한다.

---

## 사전 준비 (1회)

### 1. tap repo 생성

```bash
# GitHub 에 빈 repo 생성: 16bitdo/homebrew-anvyc (public)
# 로컬에 clone:
git clone git@github.com-16bitdo:16bitdo/homebrew-anvyc.git
cd homebrew-anvyc
mkdir Formula
# anvyc repo 의 packaging/homebrew/Formula/anvyc.rb 를 복사
cp ../anvyc/packaging/homebrew/Formula/anvyc.rb Formula/anvyc.rb
git add Formula/anvyc.rb
git commit -m "feat: initial anvyc formula"
git push -u origin main
```

이후 사용자 측에서:

```bash
brew tap 16bitdo/anvyc
brew install anvyc
```

---

## 새 anvyc 버전 release 후 갱신

### 1. anvyc 측: release artifact 생성 확인

anvyc repo 에서 `vX.Y.Z` tag 가 push 되면 `.github/workflows/release.yml`
가 자동으로 다음을 생성한다:

- `dist/anvyc-X.Y.Z-py3-none-any.whl`
- `dist/anvyc-X.Y.Z.tar.gz`
- `dist/SHA256SUMS`

`https://github.com/16bitdo/anvyc/releases/tag/vX.Y.Z` 에서 확인.

### 2. anvyc sdist 의 sha256 복사

```bash
# Release page 에서 SHA256SUMS 다운로드 후 anvyc-X.Y.Z.tar.gz 줄 확인
# 또는 직접 계산:
curl -L https://github.com/16bitdo/anvyc/releases/download/vX.Y.Z/anvyc-X.Y.Z.tar.gz \
  -o /tmp/anvyc-X.Y.Z.tar.gz
shasum -a 256 /tmp/anvyc-X.Y.Z.tar.gz
```

### 3. Formula 갱신

`16bitdo/homebrew-anvyc/Formula/anvyc.rb` 수정:

```ruby
url "https://github.com/16bitdo/anvyc/releases/download/vX.Y.Z/anvyc-X.Y.Z.tar.gz"
sha256 "<위에서-계산한-sha256>"
```

### 4. resource sha256 갱신 (의존 라이브러리 새 버전 시만)

`pyproject.toml` 의 `dependencies` 가 변경됐다면 각 resource 의 `url` + `sha256`
도 함께 갱신한다. 산출 방법:

#### 방법 A: PyPI Web UI
1. `https://pypi.org/project/<pkg>/<version>/#files` 접속
2. **Source Distribution** (`.tar.gz`) 항목의 SHA256 복사

#### 방법 B: pip download
```bash
mkdir -p /tmp/dl && rm -f /tmp/dl/*
pip download typer==0.12.5 \
  --no-deps --no-binary=:all: -d /tmp/dl
shasum -a 256 /tmp/dl/*.tar.gz
```

#### 방법 C: poet / dottie (자동화 도구)
```bash
brew install homebrew/cask/poet  # 또는 nodenv 기반 dottie
poet -r anvyc -V X.Y.Z
# resource block 들을 자동 출력
```

### 5. 로컬 검증

```bash
cd 16bitdo-homebrew-anvyc
brew install --build-from-source ./Formula/anvyc.rb
anvyc --version
anvyc doctor
brew uninstall anvyc
```

### 6. tap repo 에 push

```bash
git add Formula/anvyc.rb
git commit -m "chore: anvyc X.Y.Z"
git push origin main
```

### 7. 사용자 환경 검증

```bash
brew untap 16bitdo/anvyc
brew tap 16bitdo/anvyc
brew install anvyc
anvyc --version  # X.Y.Z
```

> 사용자 관점의 상세 가이드 (사후 검증 체크리스트 / 트러블슈팅 / 제거 절차) 는 [docs/install-via-homebrew.md](install-via-homebrew.md) 참조.

---

## 트러블슈팅

### sha256 mismatch

- release artifact 가 GitHub Actions 에서 다시 빌드된 경우 (재실행 등) 새 sha256
  를 다시 계산해야 한다. `.github/workflows/release.yml` 는 매번 동일한 input 으로
  reproducible 빌드를 시도하지만, GitHub Release upload 의 timestamp 등 부수
  영향으로 다를 수 있다.

### virtualenv_install_with_resources 실패

- `pyproject.toml` 의 `dependencies` 와 Formula 의 `resource` block 이 **일치
  하지 않으면 실패**한다. anvyc 의존 변경 시 양쪽 동기화 필요.

### depends_on python@3.13 미설치

- macOS 사용자에 `brew install python@3.13` 자동 수행됨. 별도 조치 불필요.

---

## 추후 자동화 후보 (v0.7+)

- GitHub Actions 가 release 후 자동으로 tap repo 의 Formula 도 갱신 (PR
  생성) — 현재는 PAT 권한 보안 검토 필요로 수동 유지.
- `poet` 또는 `dottie` 같은 도구를 release.yml 에 통합하여 resource sha256
  자동 산출.

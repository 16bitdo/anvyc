#!/usr/bin/env bash
# anvyc — one-liner installer.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh | bash
#   ANVYC_VERSION=v0.20.0 bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)
#   ANVYC_METHOD=pipx bash <(...)
#   ANVYC_EXTRAS=mcp,tui bash <(...)
#
# Environment:
#   ANVYC_VERSION  release tag (default: latest)
#   ANVYC_METHOD   uv | pipx | auto  (default: auto — uv 우선)
#   ANVYC_EXTRAS   comma-separated extras, e.g. mcp,tui (default: none)
#
# Verifies SHA256 against the SHA256SUMS asset attached to the release.
# Requires: curl, shasum (macOS) or sha256sum (Linux), uv or pipx.
#
# Upgrade = re-run. Pass the same ANVYC_EXTRAS every time — a run without it
# reinstalls the bare wheel and drops the extras' dependencies.
# anvyc is not on PyPI: name-based commands like `uv tool install 'anvyc[mcp]'`
# fail on a fresh machine and would install whatever claims that name.

set -euo pipefail

REPO="16bitdo/anvyc"
VERSION="${ANVYC_VERSION:-latest}"
METHOD="${ANVYC_METHOD:-auto}"
EXTRAS="${ANVYC_EXTRAS:-}"

# ----- helpers -----

die() {
  printf '\033[31merror:\033[0m %s\n' "$*" >&2
  exit 1
}

info() {
  printf '\033[36m→\033[0m %s\n' "$*"
}

ok() {
  printf '\033[32m✓\033[0m %s\n' "$*"
}

hash_cmd() {
  if command -v shasum >/dev/null 2>&1; then
    echo "shasum -a 256"
  elif command -v sha256sum >/dev/null 2>&1; then
    echo "sha256sum"
  else
    die "neither shasum nor sha256sum found — cannot verify hash"
  fi
}

# ----- preflight -----

command -v curl >/dev/null 2>&1 || die "curl not found"

# extras 는 PEP 508 요구 문자열에 그대로 들어가므로 내려받기 전에 거른다.
# 범위식([a-z])은 bash 3.2 에서 로케일 정렬을 따르므로 문자를 나열한다.
if [ -n "$EXTRAS" ]; then
  case "$EXTRAS" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789,-]* | ,* | *, | *,,*)
      die "ANVYC_EXTRAS must be comma-separated extra names [a-z0-9-] (got: $EXTRAS)"
      ;;
  esac
fi

# ----- resolve version -----

if [ "$VERSION" = "latest" ]; then
  info "resolving latest release tag…"
  VERSION=$(
    curl -sSL "https://api.github.com/repos/$REPO/releases/latest" \
      | grep '"tag_name":' \
      | head -1 \
      | sed -E 's/.*"tag_name":[[:space:]]*"([^"]+)".*/\1/'
  ) || die "failed to resolve latest tag (GitHub API rate limit?)"
  [ -n "$VERSION" ] || die "GitHub API returned empty tag"
fi

case "$VERSION" in
  v*) ;;
  *) die "VERSION must start with 'v' (got: $VERSION)" ;;
esac

PLAIN_VERSION="${VERSION#v}"
WHEEL_NAME="anvyc-${PLAIN_VERSION}-py3-none-any.whl"
WHEEL_URL="https://github.com/$REPO/releases/download/$VERSION/$WHEEL_NAME"
SUMS_URL="https://github.com/$REPO/releases/download/$VERSION/SHA256SUMS"

info "version: $VERSION"
info "wheel:   $WHEEL_NAME"

# ----- download -----

TMP="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '$TMP'" EXIT INT TERM

info "downloading wheel and SHA256SUMS…"
curl -fsSL "$WHEEL_URL" -o "$TMP/$WHEEL_NAME" || die "wheel download failed ($WHEEL_URL)"
curl -fsSL "$SUMS_URL"  -o "$TMP/SHA256SUMS"  || die "SHA256SUMS download failed ($SUMS_URL)"

# ----- verify -----

HASHER="$(hash_cmd)"
EXPECTED="$(grep " ${WHEEL_NAME}\$" "$TMP/SHA256SUMS" | awk '{print $1}' || true)"
[ -n "$EXPECTED" ] || die "wheel hash not listed in SHA256SUMS"

ACTUAL="$($HASHER "$TMP/$WHEEL_NAME" | awk '{print $1}')"
if [ "$EXPECTED" != "$ACTUAL" ]; then
  die "SHA256 mismatch: expected=$EXPECTED actual=$ACTUAL"
fi
ok "SHA256 verified"

# ----- install -----

resolve_method() {
  case "$METHOD" in
    uv)
      command -v uv >/dev/null 2>&1 || die "uv not found"
      echo "uv tool install --force"
      ;;
    pipx)
      command -v pipx >/dev/null 2>&1 || die "pipx not found"
      echo "pipx install --force"
      ;;
    auto)
      if command -v uv >/dev/null 2>&1; then
        echo "uv tool install --force"
      elif command -v pipx >/dev/null 2>&1; then
        echo "pipx install --force"
      else
        die "neither uv nor pipx found — install one then re-run, or use: pip install '$TMP/$WHEEL_NAME'"
      fi
      ;;
    *)
      die "unknown ANVYC_METHOD: $METHOD (expected: uv | pipx | auto)"
      ;;
  esac
}

INSTALL_CMD="$(resolve_method)"

# extras 는 방금 검증한 wheel 에 PEP 508 직접 참조로 붙인다 — 이름만으로는 PyPI 를 찾는다.
# 파일 URL 이라 % 와 공백을 인코딩한다(Linux 의 mktemp 는 TMPDIR 를 따른다).
SPEC="$TMP/$WHEEL_NAME"
if [ -n "$EXTRAS" ]; then
  URL_PATH="${SPEC//%/%25}"
  URL_PATH="${URL_PATH// /%20}"
  SPEC="anvyc[$EXTRAS] @ file://$URL_PATH"
  info "extras:  $EXTRAS"
fi

info "installing via: ${INSTALL_CMD%% *}"
# shellcheck disable=SC2086
$INSTALL_CMD "$SPEC"

ok "anvyc $VERSION installed"

if command -v anvyc >/dev/null 2>&1; then
  anvyc --version
else
  printf '\033[33mnote:\033[0m anvyc binary not found on PATH. Check your installer (uv/pipx) shim directory.\n'
fi

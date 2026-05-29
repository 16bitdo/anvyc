#!/usr/bin/env bash
# anvyc — one-liner installer.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh | bash
#   ANVYC_VERSION=v0.17.0 bash <(curl -sSL https://raw.githubusercontent.com/16bitdo/anvyc/main/install.sh)
#   ANVYC_METHOD=pipx bash <(...)
#
# Environment:
#   ANVYC_VERSION  release tag (default: latest)
#   ANVYC_METHOD   uv | pipx | auto  (default: auto — uv 우선)
#
# Verifies SHA256 against the SHA256SUMS asset attached to the release.
# Requires: curl, shasum (macOS) or sha256sum (Linux), uv or pipx.

set -euo pipefail

REPO="16bitdo/anvyc"
VERSION="${ANVYC_VERSION:-latest}"
METHOD="${ANVYC_METHOD:-auto}"

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
info "installing via: ${INSTALL_CMD%% *}"
# shellcheck disable=SC2086
$INSTALL_CMD "$TMP/$WHEEL_NAME"

ok "anvyc $VERSION installed"

if command -v anvyc >/dev/null 2>&1; then
  anvyc --version
else
  printf '\033[33mnote:\033[0m anvyc binary not found on PATH. Check your installer (uv/pipx) shim directory.\n'
fi

#!/usr/bin/env bash
set -euo pipefail

# Build-time only helper.  The resulting payload is copied into the macOS app
# by DeepSeekChat.spec; end users do not need Node.js, npm, or npx installed.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARNESS_PACKAGE="${HARNESS_PACKAGE:-@deepseek-ai/dsh@0.1.5-rc.1}"
NODE_VERSION="${DEEPSEEK_NODE_VERSION:-v22.19.0}"
ARCH="$(uname -m)"

case "$ARCH" in
  arm64) NODE_ARCH="arm64" ;;
  x86_64) NODE_ARCH="x64" ;;
  *)
    echo "Unsupported macOS architecture: $ARCH" >&2
    exit 1
    ;;
esac

BUNDLE_DIR="$ROOT_DIR/vendor/harness"
CLI="$BUNDLE_DIR/node_modules/@deepseek-ai/dsh/lib/bin.js"
NODE="$BUNDLE_DIR/node/bin/node"

if [ -x "$NODE" ] && [ -f "$CLI" ]; then
  echo ">> Harness runtime already bundled: $BUNDLE_DIR"
  exit 0
fi

if [ -e "$BUNDLE_DIR" ]; then
  echo "Incomplete Harness bundle exists at $BUNDLE_DIR; remove that build artifact and retry." >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/build"
STAGE_DIR="$(mktemp -d "$ROOT_DIR/build/harness-vendor.XXXXXX")"
cleanup() {
  if [ -d "$STAGE_DIR" ]; then
    rm -rf "$STAGE_DIR"
  fi
}
trap cleanup EXIT

NODE_ARCHIVE="node-${NODE_VERSION}-darwin-${NODE_ARCH}.tar.gz"
NODE_URL="https://nodejs.org/dist/${NODE_VERSION}/${NODE_ARCHIVE}"
ARCHIVE_PATH="$STAGE_DIR/$NODE_ARCHIVE"

echo ">> Downloading Node.js ${NODE_VERSION} (${NODE_ARCH})"
curl --fail --location --retry 3 --output "$ARCHIVE_PATH" "$NODE_URL"
tar -xzf "$ARCHIVE_PATH" -C "$STAGE_DIR"
mv "$STAGE_DIR/node-${NODE_VERSION}-darwin-${NODE_ARCH}" "$STAGE_DIR/node"
rm -f "$ARCHIVE_PATH"

export npm_config_cache="$STAGE_DIR/npm-cache"
echo ">> Installing ${HARNESS_PACKAGE} into the local app payload"
"$STAGE_DIR/node/bin/npm" install \
  --prefix "$STAGE_DIR" \
  --no-save \
  --no-package-lock \
  --omit=dev \
  --ignore-scripts \
  "$HARNESS_PACKAGE"

if [ ! -f "$CLI" ]; then
  # CLI is still inside the staging tree at this point; use the staging path
  # for the validation before the final move.
  STAGED_CLI="$STAGE_DIR/node_modules/@deepseek-ai/dsh/lib/bin.js"
  if [ ! -f "$STAGED_CLI" ]; then
    echo "Harness package installed but its CLI entry was not found." >&2
    exit 1
  fi
fi

mkdir -p "$ROOT_DIR/vendor"
# npm's download cache is useful while assembling the payload but must not be
# shipped inside the final application (the first-party modules are enough at
# runtime and the cache would add hundreds of megabytes).
rm -rf "$STAGE_DIR/npm-cache"
mv "$STAGE_DIR" "$BUNDLE_DIR"
trap - EXIT
echo ">> Harness runtime ready: $BUNDLE_DIR"

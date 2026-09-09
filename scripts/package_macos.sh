#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${DEEPSEEK_PYTHON:-/opt/anaconda3/envs/deepseek-chat/bin/python}"
APP_NAME="DeepSeek Chat"

cd "$ROOT_DIR"

VERSION="$("$PYTHON_BIN" - "$ROOT_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from app import __version__
print(__version__)
PY
)"
ARCH="$(uname -m)"

SPEC_FILE="$ROOT_DIR/DeepSeekChat.spec"
DIST_APP="$ROOT_DIR/dist/${APP_NAME}.app"
RELEASE_DIR="$ROOT_DIR/release"
STAGE_DIR="$ROOT_DIR/build/dmg-stage"
DMG_NAME="DeepSeek-Chat-${VERSION}-macos-${ARCH}.dmg"
DMG_PATH="$RELEASE_DIR/$DMG_NAME"

echo ">> Building ${APP_NAME}.app with PyInstaller"
"$PYTHON_BIN" -m PyInstaller --clean --noconfirm "$SPEC_FILE"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR" "$RELEASE_DIR"

echo ">> Staging DMG contents"
cp -R "$DIST_APP" "$STAGE_DIR/"
ln -s /Applications "$STAGE_DIR/Applications"

rm -f "$DMG_PATH"
echo ">> Creating ${DMG_NAME}"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo ">> Done: ${DMG_PATH}"

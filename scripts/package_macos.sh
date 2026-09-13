#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${DEEPSEEK_PYTHON:-/opt/anaconda3/envs/deepseek-chat/bin/python}"
APP_NAME="DeepSeek"

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
BUILD_DIR="${DEEPSEEK_BUILD_DIR:-$ROOT_DIR/build}"
DIST_DIR="${DEEPSEEK_DIST_DIR:-$ROOT_DIR/dist}"
RELEASE_DIR="${DEEPSEEK_RELEASE_DIR:-$ROOT_DIR/release}"
DIST_APP="$DIST_DIR/${APP_NAME}.app"
STAGE_DIR="$BUILD_DIR/dmg-stage"
DMG_NAME="DeepSeek-${VERSION}-macos-${ARCH}.dmg"
DMG_PATH="$RELEASE_DIR/$DMG_NAME"

echo ">> Building ${APP_NAME}.app with PyInstaller"
if [ "${DEEPSEEK_SKIP_HARNESS_BUNDLE:-0}" != "1" ]; then
  "$ROOT_DIR/scripts/vendor_harness.sh"
else
  echo ">> Skipping bundled Harness runtime (DEEPSEEK_SKIP_HARNESS_BUNDLE=1)"
fi
"$PYTHON_BIN" -m PyInstaller --clean --noconfirm \
  --workpath "$BUILD_DIR" --distpath "$DIST_DIR" "$SPEC_FILE"

# PyInstaller 6.22 can relocate the extra QtWebEngineCore framework
# resources into ``Versions/Resources``.  That layout leaves the framework's
# top-level Resources/Helpers links dangling and makes the app fail recursive
# code-signature validation.  Restore the layout shipped by PySide6 before
# staging the bundle, then sign the repaired bundle again.
QT_WEBENGINE_FRAMEWORK="$DIST_APP/Contents/Frameworks/PySide6/Qt/lib/QtWebEngineCore.framework"
QT_WEBENGINE_EXTRA="$QT_WEBENGINE_FRAMEWORK/Versions/Resources"
if [ -d "$QT_WEBENGINE_EXTRA" ]; then
  echo ">> Restoring QtWebEngineCore framework resources"
  cp -R "$QT_WEBENGINE_EXTRA/Resources/." \
    "$QT_WEBENGINE_FRAMEWORK/Versions/A/Resources/"
  mkdir -p "$QT_WEBENGINE_FRAMEWORK/Versions/A/Helpers"
  cp -R "$QT_WEBENGINE_EXTRA/Helpers/." \
    "$QT_WEBENGINE_FRAMEWORK/Versions/A/Helpers/"
  rm -rf "$QT_WEBENGINE_EXTRA"
  echo ">> Re-signing repaired app bundle"
  codesign --force --sign - \
    "$QT_WEBENGINE_FRAMEWORK/Versions/A/Helpers/QtWebEngineProcess.app"
  codesign --force --sign - "$QT_WEBENGINE_FRAMEWORK"
  codesign --deep --force --sign - "$DIST_APP"
fi

HARNESS_NODE="$DIST_APP/Contents/Resources/vendor/harness/node/bin/node"
if [ -f "$HARNESS_NODE" ]; then
  chmod +x "$HARNESS_NODE"
fi

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

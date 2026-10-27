#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) is required. Install it from https://cli.github.com/"
  exit 1
fi

REMOTE_URL="$(git remote get-url origin 2>/dev/null || true)"
if [ -z "$REMOTE_URL" ]; then
  echo "No git remote 'origin' found. Add one first, for example:"
  echo "  git remote add origin git@github.com:OWNER/REPO.git"
  exit 1
fi

VERSION="$("${DEEPSEEK_PYTHON:-/opt/anaconda3/envs/deepseek-chat/bin/python}" - "$ROOT_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from app import __version__
print(__version__)
PY
)"
TAG="${RELEASE_TAG:-v${VERSION}}"
DMG="$ROOT_DIR/release/DeepSeek-${VERSION}-macos-$(uname -m).dmg"
NOTES_FILE="${RELEASE_NOTES_FILE:-$ROOT_DIR/update.md}"

if [ ! -f "$DMG" ]; then
  echo "Missing ${DMG}. Run scripts/package_macos.sh first."
  exit 1
fi
if [ ! -f "$NOTES_FILE" ]; then
  echo "Missing release notes: ${NOTES_FILE}"
  exit 1
fi

if gh release view "$TAG" >/dev/null 2>&1; then
  echo ">> Publishing ${TAG} for ${REMOTE_URL}"
  gh release upload "$TAG" "$DMG" --clobber
  gh release edit "$TAG" \
    --title "DeepSeek ${VERSION}" \
    --notes-file "$NOTES_FILE" \
    --latest
else
  echo ">> Publishing ${TAG} for ${REMOTE_URL}"
  gh release create "$TAG" "$DMG" \
    --target "$(git rev-parse HEAD)" \
    --title "DeepSeek ${VERSION}" \
    --notes-file "$NOTES_FILE" \
    --latest
fi

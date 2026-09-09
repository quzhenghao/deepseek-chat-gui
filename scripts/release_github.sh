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

VERSION="$("${DEEPSEEK_PYTHON:-python3}" - "$ROOT_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from app import __version__
print(__version__)
PY
)"
TAG="v${VERSION}"
DMG="$ROOT_DIR/release/DeepSeek-Chat-${VERSION}-macos-$(uname -m).dmg"

if [ ! -f "$DMG" ]; then
  echo "Missing ${DMG}. Run scripts/package_macos.sh first."
  exit 1
fi

echo ">> Creating GitHub release ${TAG} for ${REMOTE_URL}"
gh release create "$TAG" "$DMG" \
  --title "DeepSeek Chat ${VERSION}" \
  --generate-notes

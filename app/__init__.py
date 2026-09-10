import sys
from pathlib import Path

__version__ = "1.0.0"

if getattr(sys, "frozen", False):
    _BUNDLE_DIR = Path(
        getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
    )
else:
    _BUNDLE_DIR = Path(__file__).resolve().parent.parent

ASSETS_DIR = _BUNDLE_DIR / "assets"
# Optional first-party runtime payload produced by scripts/vendor_harness.sh.
# Keeping this path beside the bundled assets lets a packaged .app use Harness
# without asking the end user to install Node.js or run npm manually.
HARNESS_BUNDLE_DIR = _BUNDLE_DIR / "vendor" / "harness"

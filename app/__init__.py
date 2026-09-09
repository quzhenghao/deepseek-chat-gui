import sys
from pathlib import Path

__version__ = "0.1.0"

if getattr(sys, "frozen", False):
    _BUNDLE_DIR = Path(
        getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
    )
else:
    _BUNDLE_DIR = Path(__file__).resolve().parent.parent

ASSETS_DIR = _BUNDLE_DIR / "assets"

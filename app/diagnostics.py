"""Persist crash and exception details for the desktop client.

The app is usually launched from an IDE or a macOS bundle, so Python tracebacks
that only reach stderr disappear with the window.  This module mirrors fatal
signals and unhandled exceptions into ``~/.deepseek_chat_gui/logs`` so an
unexpected exit can be diagnosed afterwards.
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from .config import APP_DIR

LOG_DIR = APP_DIR / "logs"
CRASH_LOG = LOG_DIR / "crash.log"
ERROR_LOG = LOG_DIR / "errors.log"
MAX_LOG_BYTES = 512 * 1024

_handle = None


def _trim(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.write_text("", encoding="utf-8")
    except OSError:
        pass


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _append(path: Path, text: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(text)
    except OSError:
        pass


def install() -> tuple[Path, Path]:
    """Route fatal signals and unhandled exceptions into log files."""

    global _handle
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _trim(CRASH_LOG)
    _trim(ERROR_LOG)
    try:
        if _handle is not None:
            _handle.close()
        _handle = CRASH_LOG.open("a", encoding="utf-8", buffering=1)
        _handle.write(f"\n=== session {_stamp()} ===\n")
        faulthandler.enable(file=_handle, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        _handle = None

    def report(exc_type, exc_value, exc_tb) -> None:
        _append(
            ERROR_LOG,
            f"\n=== {_stamp()} ===\n"
            + "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = report
    threading.excepthook = lambda args: report(
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
    )
    return CRASH_LOG, ERROR_LOG


__all__ = ["CRASH_LOG", "ERROR_LOG", "LOG_DIR", "install"]

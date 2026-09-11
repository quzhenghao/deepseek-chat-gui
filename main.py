#!/usr/bin/env python3
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import ASSETS_DIR
from app.config import load_config
from app.diagnostics import install as install_crash_logging
from app.storage import ConversationStore
from app.ui.main_window import MainWindow
from app.ui.theme import build_qss


def main() -> int:
    install_crash_logging()
    QApplication.setApplicationName("DeepSeek")
    QApplication.setOrganizationName("DeepSeek")
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("DeepSeek")
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "app-icon.png")))

    config = load_config()
    app.setStyleSheet(build_qss(config.get("theme", "light")))
    window = MainWindow(config, ConversationStore(), app)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

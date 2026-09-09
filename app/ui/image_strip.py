from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from .controls import RoundedMenu
from .icons import apply_icon
from .theme import colors


THUMB_SIZE = 62
MAX_IMAGES = 8


def rounded_thumbnail(path: str, size: int = THUMB_SIZE) -> QPixmap:
    image = QImage(path)
    if image.isNull():
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(QColor("#E4E7EC"))
    scaled = QPixmap.fromImage(image).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, size, size, 11, 11)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return result


class ThumbView(QLabel):
    removeRequested = Signal(object)

    def __init__(self, path: str, theme: str, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._theme = theme
        self.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self.setPixmap(rounded_thumbnail(path))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(Path(path).name)

        self.close_button = QToolButton(self)
        self.close_button.setFixedSize(20, 20)
        self.close_button.move(THUMB_SIZE - 22, 2)
        self.close_button.setToolTip("移除图片")
        self.close_button.clicked.connect(lambda: self.removeRequested.emit(self))
        self.apply_theme(theme)

    def path(self) -> str:
        return self._path

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        apply_icon(self.close_button, "close", "#FFFFFF", 13)
        self.close_button.setStyleSheet(
            "QToolButton { background:rgba(16,24,40,0.72); border-radius:10px; padding:2px; }"
            "QToolButton:hover { background:rgba(16,24,40,0.92); }"
        )
        self.setStyleSheet(
            f"border:1px solid {palette['border_strong']};border-radius:11px;"
        )

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = RoundedMenu(self._theme, self)
        open_action = menu.addAction("打开原图")
        remove_action = menu.addAction("移除图片")
        chosen = menu.exec(event.globalPos())
        if chosen is open_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))
        elif chosen is remove_action:
            self.removeRequested.emit(self)


class ImageStrip(QWidget):
    imagesChanged = Signal(list)
    limitReached = Signal(str)

    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._items: list[ThumbView] = []
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 6)
        self._layout.setSpacing(8)
        self._layout.addStretch()
        self.hide()

    def paths(self) -> list[str]:
        return [item.path() for item in self._items]

    def add_path(self, path: str) -> bool:
        if not path or path in self.paths():
            return False
        if len(self._items) >= MAX_IMAGES:
            self.limitReached.emit(f"每条消息最多添加 {MAX_IMAGES} 张图片")
            return False
        thumbnail = ThumbView(path, self._theme)
        thumbnail.removeRequested.connect(self._remove)
        self._layout.insertWidget(self._layout.count() - 1, thumbnail)
        self._items.append(thumbnail)
        self.show()
        self.imagesChanged.emit(self.paths())
        return True

    def add_paths(self, paths: list[str]) -> int:
        return sum(1 for path in paths if self.add_path(path))

    def clear(self) -> None:
        for thumbnail in self._items:
            thumbnail.deleteLater()
        self._items.clear()
        self.hide()
        self.imagesChanged.emit([])

    def _remove(self, thumbnail: ThumbView) -> None:
        if thumbnail in self._items:
            self._items.remove(thumbnail)
            thumbnail.deleteLater()
        self.setVisible(bool(self._items))
        self.imagesChanged.emit(self.paths())

    def set_style(self, theme: str) -> None:
        self._theme = theme
        self.setStyleSheet("background:transparent;")
        for thumbnail in self._items:
            thumbnail.apply_theme(theme)

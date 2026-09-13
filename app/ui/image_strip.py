from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from .controls import build_flat_menu
from .icons import apply_icon
from .theme import CHAT_BUBBLE_RADIUS, colors


THUMB_SIZE = 62
MAX_IMAGES = 8
THUMBNAIL_RADIUS = CHAT_BUBBLE_RADIUS
THUMBNAIL_BORDER_WIDTH = 1.0


def rounded_thumbnail(
    path: str,
    size: int = THUMB_SIZE,
    *,
    border_color: str | QColor | None = None,
    background_color: str | QColor | None = None,
) -> QPixmap:
    """Return one composited thumbnail surface.

    The image clip and its border deliberately live in the same painter.  A
    QLabel stylesheet paints its border separately from the pixmap, which can
    let an opaque square pixmap cover the antialiased corner pixels and make
    the border look broken.
    """

    radius = min(float(THUMBNAIL_RADIUS), size / 2)
    image = QImage(path)
    if image.isNull():
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(QColor(background_color or "#E5E5E5"))
    scaled = QPixmap.fromImage(image).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    left = max(0, (scaled.width() - size) // 2)
    top = max(0, (scaled.height() - size) // 2)
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, scaled.copy(left, top, size, size))

    if border_color is not None:
        # Center a one-pixel pen on the inside edge so the complete stroke is
        # retained by the thumbnail surface instead of being clipped by its
        # outer bounds.
        inset = THUMBNAIL_BORDER_WIDTH / 2
        border_rect = QRectF(
            inset,
            inset,
            max(0.0, size - THUMBNAIL_BORDER_WIDTH),
            max(0.0, size - THUMBNAIL_BORDER_WIDTH),
        )
        border_path = QPainterPath()
        border_path.addRoundedRect(
            border_rect,
            max(0.0, radius - inset),
            max(0.0, radius - inset),
        )
        pen = QPen(QColor(border_color), THUMBNAIL_BORDER_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setClipRect(QRectF(0, 0, size, size))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawPath(border_path)
    painter.end()
    return result


class ThumbView(QLabel):
    removeRequested = Signal(object)

    def __init__(self, path: str, theme: str, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._theme = theme
        self.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{Path(path).name}\n单击打开原图")

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
        self.setPixmap(
            rounded_thumbnail(
                self._path,
                THUMB_SIZE,
                border_color=palette["border_strong"],
                background_color=palette["canvas"],
            )
        )
        # The border is part of the pixmap.  Keeping the QLabel surface
        # transparent prevents a second style-layer border from competing
        # with the composited corner pixels.
        self.setStyleSheet("background:transparent;border:none;")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = build_flat_menu(self)
        open_action = menu.addAction("打开原图")
        remove_action = menu.addAction("移除图片")
        chosen = menu.exec(event.globalPos())
        menu.deleteLater()
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
            self.limitReached.emit(f"每条消息最多添加{MAX_IMAGES}张图片")
            return False
        thumbnail = ThumbView(path, self._theme)
        thumbnail.removeRequested.connect(self._remove)
        self._layout.insertWidget(self._layout.count() - 1, thumbnail)
        self._items.append(thumbnail)
        self.show()
        self._refresh_geometry()
        self.imagesChanged.emit(self.paths())
        return True

    def add_paths(self, paths: list[str]) -> int:
        return sum(1 for path in paths if self.add_path(path))

    def clear(self) -> None:
        for thumbnail in self._items:
            self._layout.removeWidget(thumbnail)
            thumbnail.deleteLater()
        self._items.clear()
        self.hide()
        self._refresh_geometry()
        self.imagesChanged.emit([])

    def _remove(self, thumbnail: ThumbView) -> None:
        if thumbnail in self._items:
            self._items.remove(thumbnail)
            self._layout.removeWidget(thumbnail)
            thumbnail.deleteLater()
        self.setVisible(bool(self._items))
        self._refresh_geometry()
        self.imagesChanged.emit(self.paths())

    def _refresh_geometry(self) -> None:
        """Invalidate the whole composer chain after the strip changes size."""

        self.updateGeometry()
        parent = self.parentWidget()
        while parent is not None:
            layout = parent.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            parent.updateGeometry()
            parent = parent.parentWidget()

    def set_style(self, theme: str) -> None:
        self._theme = theme
        self.setStyleSheet("background:transparent;")
        for thumbnail in self._items:
            thumbnail.apply_theme(theme)

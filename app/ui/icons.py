from __future__ import annotations

from math import sqrt

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _path(points: list[tuple[float, float]], closed: bool = False) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    if closed:
        path.closeSubpath()
    return path


def _cog_path(center: float = 12.0) -> QPainterPath:
    """Regular six-tooth vector cog generated from one repeated profile."""

    tooth = (
        (-3.2, -6.7),
        (-2.0, -9.1),
        (2.0, -9.1),
        (3.2, -6.7),
    )
    half_sqrt_three = sqrt(3.0) / 2.0
    rotations = (
        (1.0, 0.0),
        (0.5, half_sqrt_three),
        (-0.5, half_sqrt_three),
        (-1.0, 0.0),
        (-0.5, -half_sqrt_three),
        (0.5, -half_sqrt_three),
    )
    points = []
    for cosine, sine in rotations:
        for x, y in tooth:
            points.append(
                (
                    center + x * cosine - y * sine,
                    center + x * sine + y * cosine,
                )
            )
    return _path(points, True)


def _paint(painter: QPainter, name: str, color: QColor) -> None:
    pen = QPen(
        color,
        1.8,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "plus":
        painter.drawLine(QPointF(12, 5), QPointF(12, 19))
        painter.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "sidebar":
        painter.drawRoundedRect(QRectF(3.5, 4, 17, 16), 2.5, 2.5)
        painter.drawLine(QPointF(8.5, 4.5), QPointF(8.5, 19.5))
    elif name == "settings":
        painter.setPen(
            QPen(
                color,
                2.15,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(_cog_path())
        painter.drawEllipse(QPointF(12, 12), 2.5, 2.5)
    elif name == "trash":
        painter.drawRoundedRect(QRectF(6.5, 8, 11, 12), 1.5, 1.5)
        painter.drawLine(QPointF(5, 6), QPointF(19, 6))
        painter.drawLine(QPointF(9, 3.5), QPointF(15, 3.5))
        painter.drawLine(QPointF(10, 11), QPointF(10, 17))
        painter.drawLine(QPointF(14, 11), QPointF(14, 17))
    elif name == "select":
        painter.drawRoundedRect(QRectF(3.5, 3.5, 17, 17), 4, 4)
        painter.drawPath(_path([(7.5, 12.2), (10.5, 15.2), (16.8, 8.8)]))
    elif name == "send":
        painter.drawLine(QPointF(12, 18.5), QPointF(12, 5.5))
        painter.drawPath(_path([(6.8, 10.5), (12, 5.3), (17.2, 10.5)]))
    elif name == "arrow-down":
        painter.drawLine(QPointF(12, 5.5), QPointF(12, 18.5))
        painter.drawPath(_path([(6.8, 13.5), (12, 18.7), (17.2, 13.5)]))
    elif name == "expand":
        painter.drawPath(_path([(5, 10), (5, 5), (10, 5)]))
        painter.drawLine(QPointF(5, 5), QPointF(10, 10))
        painter.drawPath(_path([(14, 19), (19, 19), (19, 14)]))
        painter.drawLine(QPointF(14, 14), QPointF(19, 19))
    elif name == "collapse":
        painter.drawPath(_path([(5, 10), (10, 10), (10, 5)]))
        painter.drawLine(QPointF(5, 5), QPointF(10, 10))
        painter.drawPath(_path([(14, 19), (14, 14), (19, 14)]))
        painter.drawLine(QPointF(14, 14), QPointF(19, 19))
    elif name == "stop":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
    elif name == "add-square":
        painter.drawRoundedRect(QRectF(4.5, 4.5, 15, 15), 2, 2)
        painter.drawLine(QPointF(12, 8), QPointF(12, 16))
        painter.drawLine(QPointF(8, 12), QPointF(16, 12))
    elif name == "image":
        painter.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 2.5, 2.5)
        painter.drawEllipse(QPointF(9, 9.5), 1.6, 1.6)
        painter.drawPath(_path([(5.5, 17), (10.2, 12.5), (13.2, 15.2), (16.1, 12), (19, 15.2)]))
    elif name == "copy":
        painter.drawRoundedRect(QRectF(8, 8, 11.5, 11.5), 2, 2)
        painter.drawPath(_path([(6, 16), (5.5, 16), (5.5, 5.5), (16, 5.5), (16, 6)]))
    elif name == "eye":
        path = QPainterPath(QPointF(3.5, 12))
        path.cubicTo(7, 6.5, 17, 6.5, 20.5, 12)
        path.cubicTo(17, 17.5, 7, 17.5, 3.5, 12)
        painter.drawPath(path)
        painter.drawEllipse(QPointF(12, 12), 2.3, 2.3)
    elif name == "eye-off":
        _paint(painter, "eye", color)
        painter.drawLine(QPointF(4, 4), QPointF(20, 20))
    elif name == "chevron-right":
        painter.drawPath(_path([(9, 6.5), (14.5, 12), (9, 17.5)]))
    elif name == "chevron-down":
        painter.drawPath(_path([(6.5, 9), (12, 14.5), (17.5, 9)]))
    elif name == "arrow-left":
        painter.drawLine(QPointF(19, 12), QPointF(5, 12))
        painter.drawPath(_path([(10.5, 6.5), (5, 12), (10.5, 17.5)]))
    elif name == "sparkle":
        points = [
            (12, 3.5),
            (13.5, 9.2),
            (19.2, 10.7),
            (13.5, 12.2),
            (12, 18),
            (10.5, 12.2),
            (4.8, 10.7),
            (10.5, 9.2),
        ]
        painter.drawPath(_path(points, True))
        painter.drawLine(QPointF(18.5, 4), QPointF(18.5, 7))
        painter.drawLine(QPointF(17, 5.5), QPointF(20, 5.5))
    elif name == "globe":
        painter.drawEllipse(QPointF(12, 12), 7.4, 7.4)
        painter.drawEllipse(QPointF(12, 12), 3.1, 7.4)
        painter.drawLine(QPointF(4.6, 12), QPointF(19.4, 12))
        painter.drawLine(QPointF(5.8, 8.2), QPointF(18.2, 8.2))
        painter.drawLine(QPointF(5.8, 15.8), QPointF(18.2, 15.8))
    elif name == "check":
        painter.drawPath(_path([(5.5, 12.5), (9.7, 16.5), (18.5, 7.5)]))
    elif name == "edit":
        painter.drawPath(_path([(5, 16), (4.5, 19.5), (8, 19), (18.5, 8.5), (15.5, 5.5), (5, 16)]))
        painter.drawLine(QPointF(13.8, 7.2), QPointF(16.8, 10.2))
    elif name == "more":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for x in (6, 12, 18):
            painter.drawEllipse(QPointF(x, 12), 1.4, 1.4)
    elif name == "close":
        painter.drawLine(QPointF(7, 7), QPointF(17, 17))
        painter.drawLine(QPointF(17, 7), QPointF(7, 17))
    elif name == "refresh":
        painter.drawArc(QRectF(4.5, 4.5, 15, 15), 35 * 16, 285 * 16)
        painter.drawPath(_path([(17.5, 4.8), (19.7, 8.5), (15.5, 8.4)]))
    elif name == "question":
        question = QPainterPath(QPointF(7.8, 9.2))
        question.cubicTo(8.1, 6.4, 9.8, 5, 12.2, 5)
        question.cubicTo(14.7, 5, 16.3, 6.5, 16.3, 8.7)
        question.cubicTo(16.3, 10.7, 15.1, 11.7, 13.7, 12.6)
        question.cubicTo(12.5, 13.4, 12, 14.1, 12, 15.3)
        painter.drawPath(question)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(12, 19), 1.25, 1.25)


def icon(name: str, color: str = "#5E5E5E", size: int = 20) -> QIcon:
    density = 3
    pixmap = QPixmap(size * density, size * density)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(density)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    _paint(painter, name, QColor(color))
    painter.end()
    result = QIcon()
    result.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    return result


def apply_icon(button, name: str, color: str, size: int = 20) -> None:
    button.setIcon(icon(name, color, size))
    button.setIconSize(QSize(size, size))


def tint_pixmap(pixmap: QPixmap, color: str) -> QPixmap:
    """Apply a solid brand color while preserving the source alpha channel."""

    tinted = QPixmap(pixmap)
    if tinted.isNull():
        return tinted
    painter = QPainter(tinted)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    return tinted

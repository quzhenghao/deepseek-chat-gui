from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QTimer, Qt
from PySide6.QtGui import QHelpEvent, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QFrame,
    QLabel,
    QListView,
    QMenu,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import apply_icon
from .theme import colors


def rounded_surface_qss(
    theme: str, selector: str, padding: str = "6px"
) -> str:
    palette = colors(theme)
    return f"""
{selector} {{
    color: {palette['fg']};
    background: {palette['panel']};
    border: 1px solid {palette['border_strong']};
    border-radius: 12px;
    outline: none;
    padding: {padding};
}}
"""


def _apply_rounded_mask(widget: QWidget, radius: float = 12) -> None:
    if widget.width() <= 0 or widget.height() <= 0:
        return
    path = QPainterPath()
    path.addRoundedRect(QRectF(widget.rect()), radius, radius)
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


class RoundedComboBox(QComboBox):
    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        view = QListView()
        view.setObjectName("roundedComboView")
        view.setSpacing(3)
        view.setUniformItemSizes(False)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setView(view)
        self._prepare_popup()
        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        self.view().setStyleSheet(
            rounded_surface_qss(theme, "QListView#roundedComboView")
            + f"""
QListView#roundedComboView::item {{
    min-height: 22px;
    padding: 7px 10px;
    border-radius: 8px;
}}
QListView#roundedComboView::item:hover {{
    background: {palette['hover']};
}}
QListView#roundedComboView::item:selected {{
    color: {palette['accent']};
    background: {palette['accent_soft']};
}}
QListView#roundedComboView QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 8px 2px;
}}
QListView#roundedComboView QScrollBar::handle:vertical {{
    background: {palette['border_strong']};
    border-radius: 4px;
    min-height: 26px;
}}
QListView#roundedComboView QScrollBar::add-line:vertical,
QListView#roundedComboView QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""
        )
        self._style_popup()

    def _prepare_popup(self) -> None:
        popup = self.view().window()
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        popup.setContentsMargins(0, 0, 0, 0)
        popup.setStyleSheet(
            "QFrame { background: transparent; border: none; padding: 0; }"
        )

    def _style_popup(self) -> None:
        popup = self.view().window()
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        _apply_rounded_mask(popup)

    def showPopup(self) -> None:
        self._prepare_popup()
        super().showPopup()
        QTimer.singleShot(0, self._style_popup)

    def hidePopup(self) -> None:
        super().hidePopup()
        self._style_popup()

    def wheelEvent(self, event) -> None:
        event.ignore()


class RoundedMenu(QMenu):
    """Context menu with the same floating surface as rounded combo popups."""

    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("roundedMenu")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setContentsMargins(0, 0, 0, 0)
        self.setMinimumWidth(104)
        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        self.setStyleSheet(
            f"""
QMenu#roundedMenu {{
    color: {palette['fg']};
    background: {palette['panel']};
    border: 1px solid {palette['border_strong']};
    border-radius: 12px;
    padding: 6px;
    outline: none;
}}
QMenu#roundedMenu::item {{
    min-height: 22px;
    padding: 7px 10px;
    border-radius: 8px;
    font-weight: 400;
}}
QMenu#roundedMenu::item:selected {{
    color: {palette['accent']};
    background: {palette['accent_soft']};
}}
QMenu#roundedMenu::item:disabled {{ color: {palette['fg_muted']}; }}
QMenu#roundedMenu::separator {{
    height: 1px;
    background: {palette['border']};
    margin: 4px 7px;
}}
"""
        )
        self._style_popup()

    def _style_popup(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        _apply_rounded_mask(self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._style_popup()
        QTimer.singleShot(0, self._style_popup)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._style_popup()


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


class NoticeDialog(QDialog):
    def __init__(self, text: str, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("提示")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(340, 96)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame(self)
        self.card.setObjectName("noticeCard")
        root.addWidget(self.card)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(14, 10, 14, 14)

        self.close_button = QToolButton(self.card)
        self.close_button.setObjectName("noticeCloseBtn")
        self.close_button.setFixedSize(28, 28)
        self.close_button.setToolTip("关闭提示")
        self.close_button.clicked.connect(self.close)

        self.message = QLabel()
        self.message.setObjectName("noticeMessage")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        card_layout.addWidget(self.message, 1)
        self.set_text(text)
        self.apply_theme(theme)
        self._place_close_button()

    def set_text(self, text: str) -> None:
        self.message.setText(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_close_button()

    def _place_close_button(self) -> None:
        self.close_button.move(10, 10)
        self.close_button.raise_()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        self.card.setStyleSheet(
            rounded_surface_qss(theme, "QFrame#noticeCard", "0px")
            + f"""
QToolButton#noticeCloseBtn {{
    color: {palette['fg_sub']};
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 4px;
}}
QToolButton#noticeCloseBtn:hover {{
    color: {palette['fg']};
    background: {palette['hover']};
}}
QLabel#noticeMessage {{
    color: {palette['fg']};
    font-size: 18px;
    font-weight: 600;
}}
"""
        )
        apply_icon(self.close_button, "close", palette["fg_sub"], 16)


class HoverTipWidget(QFrame):
    def __init__(self, theme: str = "light") -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame(self)
        self.card.setObjectName("hoverTipCard")
        root.addWidget(self.card)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(0, 0, 0, 0)
        self.message = QLabel(self.card)
        self.message.setObjectName("hoverTipMessage")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.apply_theme(theme)

    def set_text(self, text: str) -> None:
        self.message.setText(text)

    def apply_theme(self, theme: str) -> None:
        palette = colors(theme)
        self.card.setStyleSheet(
            rounded_surface_qss(theme, "QFrame#hoverTipCard", "7px 11px")
            + f"""
QLabel#hoverTipMessage {{
    color: {palette['fg']};
    font-size: 12px;
}}
"""
        )


class HoverTipManager(QObject):
    def __init__(
        self,
        app: QApplication,
        theme: str = "light",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or app)
        self._app = app
        self._theme = theme
        self._owner: QWidget | None = None
        self._tip: HoverTipWidget | None = None
        self._last_pos = QPoint()
        self._roots: list[weakref.ReferenceType[QWidget]] = []
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(750)
        self._watch_timer.timeout.connect(self._refresh_watched_widgets)

    def watch(self, root: QWidget) -> None:
        """Watch tooltipped widgets without filtering Qt WebEngine internals."""

        if not any(reference() is root for reference in self._roots):
            self._roots.append(weakref.ref(root))
        self._watch_tree(root)
        if not self._watch_timer.isActive():
            self._watch_timer.start()

    def _refresh_watched_widgets(self) -> None:
        active_roots: list[weakref.ReferenceType[QWidget]] = []
        for reference in self._roots:
            root = reference()
            if root is None:
                continue
            active_roots.append(reference)
            self._watch_tree(root)
        self._roots = active_roots
        if not self._roots:
            self._watch_timer.stop()

    def _watch_tree(self, node: QObject) -> None:
        # A Python application-wide event filter can crash when Chromium creates
        # its native render delegate. Formula views mark their whole subtree so
        # it is never traversed or filtered by the custom tooltip implementation.
        if isinstance(node, QWidget):
            if bool(node.property("skipCustomTooltipScan")):
                return
            if node.toolTip().strip() and not bool(
                node.property("customTooltipFilterInstalled")
            ):
                node.installEventFilter(self)
                node.setProperty("customTooltipFilterInstalled", True)
        for child in node.children():
            self._watch_tree(child)

    def eventFilter(self, watched, event) -> bool:
        event_type = event.type()
        if event_type == QEvent.Type.ToolTip:
            if isinstance(event, QHelpEvent) and isinstance(watched, QWidget):
                text = watched.toolTip().strip()
                if text:
                    self.show(text, event.globalPos(), watched)
                    event.accept()
                    return True
        elif watched is self._owner and event_type in {
            QEvent.Type.Leave,
            QEvent.Type.Hide,
            QEvent.Type.Close,
            QEvent.Type.Destroy,
        }:
            self.hide()
        elif event_type in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Wheel,
        }:
            self.hide()
        return super().eventFilter(watched, event)

    def show(self, text: str, position: QPoint, owner: QWidget) -> None:
        if self._tip is None:
            self._tip = HoverTipWidget(self._theme)
        self._owner = owner
        self._last_pos = QPoint(position)
        self._tip.set_text(text)
        self._tip.apply_theme(self._theme)
        self._tip.adjustSize()
        screen = self._app.screenAt(position) or owner.screen()
        if screen is None:
            screen = self._app.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = position.x() + 14
            y = position.y() + 18
            x = max(available.left(), min(x, available.right() - self._tip.width() + 1))
            y = max(available.top(), min(y, available.bottom() - self._tip.height() + 1))
            self._tip.move(x, y)
        else:
            self._tip.move(position + QPoint(14, 18))
        self._tip.show()
        self._tip.raise_()

    def hide(self) -> None:
        if self._tip is not None:
            self._tip.hide()
        self._owner = None

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        if self._tip is not None:
            self._tip.apply_theme(theme)
            if self._tip.isVisible() and self._owner is not None:
                self.show(self._tip.message.text(), self._last_pos, self._owner)

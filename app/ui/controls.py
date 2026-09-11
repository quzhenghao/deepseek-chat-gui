from __future__ import annotations

import ctypes
import ctypes.util
import sys
import time
import weakref

from PySide6.QtCore import (
    QElapsedTimer,
    QEvent,
    QObject,
    QPoint,
    QRectF,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QHelpEvent,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import apply_icon, icon
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


def build_flat_menu(parent=None) -> QMenu:
    """Menu that Qt paints itself with the app's flat, opaque surface.

    macOS renders a plain QMenu as a native panel with a translucent vibrancy
    material.  Asking for a translucent background makes Qt draw the menu
    itself, so the style sheet's solid white (or dark) sheet is what the user
    actually sees.  The menu deliberately has no QWidget parent: callers such
    as QTextBrowser set a local ``background: transparent`` stylesheet, and
    Qt propagates that stylesheet to child menus before the application-level
    QMenu rule can paint the panel.

    ``parent`` remains accepted for source compatibility, but is intentionally
    not passed to QMenu.
    """

    menu = QMenu()
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    menu.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    return menu


def show_edit_menu(
    widget: QWidget,
    position,
    *,
    undo_available: bool,
    redo_available: bool,
    has_selection: bool,
    can_paste: bool,
    handlers: dict,
) -> None:
    """Show the standard edit actions on the app's flat menu surface."""

    menu = build_flat_menu(widget)
    entries = (
        ("undo", "撤销", undo_available),
        ("redo", "重做", redo_available),
        (None, None, None),
        ("cut", "剪切", has_selection),
        ("copy", "复制", has_selection),
        ("paste", "粘贴", can_paste),
        ("delete", "删除", has_selection),
        (None, None, None),
        ("select_all", "全选", True),
    )
    actions: dict[str, QAction] = {}
    for key, label, enabled in entries:
        if key is None:
            menu.addSeparator()
            continue
        action = menu.addAction(str(label))
        action.setEnabled(bool(enabled))
        actions[key] = action
    chosen = menu.exec(position)
    menu.deleteLater()
    if chosen is None:
        return
    for key, action in actions.items():
        if chosen is action:
            handler = handlers.get(key)
            if handler is not None:
                handler()
            return


class FlatLineEdit(QLineEdit):
    """Single-line field whose right-click menu stays a flat panel."""

    def contextMenuEvent(self, event) -> None:
        show_edit_menu(
            self,
            event.globalPos(),
            undo_available=self.isUndoAvailable(),
            redo_available=self.isRedoAvailable(),
            has_selection=self.hasSelectedText(),
            can_paste=bool(QApplication.clipboard().text()),
            handlers={
                "undo": self.undo,
                "redo": self.redo,
                "cut": self.cut,
                "copy": self.copy,
                "paste": self.paste,
                "delete": self.del_,
                "select_all": self.selectAll,
            },
        )


class FlatPlainTextEdit(QPlainTextEdit):
    """Multi-line field whose right-click menu stays a flat panel."""

    def contextMenuEvent(self, event) -> None:
        cursor = self.textCursor()
        handlers = {
            "undo": self.undo,
            "redo": self.redo,
            "cut": self.cut,
            "copy": self.copy,
            "paste": self.paste,
            "delete": lambda: self.textCursor().removeSelectedText(),
            "select_all": self.selectAll,
        }
        show_edit_menu(
            self,
            event.globalPos(),
            undo_available=self.document().isUndoAvailable(),
            redo_available=self.document().isRedoAvailable(),
            has_selection=cursor.hasSelection(),
            can_paste=self.canPaste(),
            handlers=handlers,
        )


class FrameAnimator(QObject):
    """Ramp a float on a precise 16 ms timer with a cubic ease-out curve.

    Layout transitions in this app animate geometry directly (splitter sizes,
    widget offsets), so a plain value ramp with a fixed 60 fps tick is both
    cheaper and more predictable than a property animation per frame.
    """

    valueChanged = Signal(float)
    finished = Signal()

    def __init__(self, duration_ms: int = 240, parent=None) -> None:
        super().__init__(parent)
        self._duration = max(1, int(duration_ms))
        self._start = 0.0
        self._end = 0.0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._advance)

    @property
    def timer(self) -> QTimer:
        return self._timer

    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self, start: float, end: float) -> None:
        self._start = float(start)
        self._end = float(end)
        self._clock.start()
        self._timer.start()
        self.valueChanged.emit(self._start)

    def stop(self) -> None:
        self._timer.stop()

    def _advance(self) -> None:
        progress = min(1.0, self._clock.elapsed() / self._duration)
        eased = 1.0 - (1.0 - progress) ** 3
        value = self._start + (self._end - self._start) * eased
        if progress >= 1.0:
            self._timer.stop()
            self.valueChanged.emit(self._end)
            self.finished.emit()
            return
        self.valueChanged.emit(value)


class SystemIdleClock:
    """Best-effort "seconds since the user last touched this machine".

    The desktop app schedules one expensive warm-up (building the WebEngine
    surface) and wants to run it while the user is not interacting.  Activity
    cannot be observed with a Python event filter on QApplication: PySide
    crashes when Chromium delivers events for its own unregistered types, and
    filters installed on individual widgets never see events sent straight to
    a child.  The platform idle clock answers the question directly instead.
    """

    def __init__(self) -> None:
        self._probe = None
        if sys.platform != "darwin":
            return
        try:
            library = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
            probe = library.CGEventSourceSecondsSinceLastEventType
            probe.restype = ctypes.c_double
            probe.argtypes = [ctypes.c_int32, ctypes.c_uint32]
        except (OSError, AttributeError, TypeError):
            return
        self._probe = probe

    def seconds_since_input(self) -> float | None:
        if self._probe is None:
            return None
        try:
            value = float(self._probe(0, 0xFFFFFFFF))
        except Exception:
            return None
        if value != value or value < 0:
            return None
        return value


class IdleDispatcher(QObject):
    """Run one heavy callback once the machine has been quiet for a moment.

    Creating the embedded WebEngine surface blocks the GUI thread for a few
    hundred milliseconds.  Waiting for an idle gap keeps that cost away from
    the user's keystrokes and clicks; ``deadline_ms`` guarantees the work still
    happens when the machine never goes quiet.
    """

    def __init__(
        self,
        *,
        idle_ms: int = 700,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._idle_ms = max(0, int(idle_ms))
        self._clock = SystemIdleClock()
        self._callback = None
        self._not_before = 0.0
        self._deadline = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._maybe_run)

    def schedule(
        self,
        callback,
        *,
        delay_ms: int = 0,
        deadline_ms: int = 6000,
    ) -> None:
        now = time.monotonic()
        self._callback = callback
        self._not_before = now + max(0, delay_ms) / 1000.0
        self._deadline = now + max(0, deadline_ms) / 1000.0 if deadline_ms else 0.0
        if not self._timer.isActive():
            self._timer.start()

    def cancel(self) -> None:
        self._callback = None
        self._timer.stop()

    def is_pending(self) -> bool:
        return self._callback is not None

    def seconds_since_input(self) -> float | None:
        return self._clock.seconds_since_input()

    def _maybe_run(self) -> None:
        callback = self._callback
        if callback is None:
            self._timer.stop()
            return
        now = time.monotonic()
        if now < self._not_before:
            return
        since_input = self.seconds_since_input()
        quiet = (
            since_input is None
            or since_input >= self._idle_ms / 1000.0
        )
        if not quiet and not (self._deadline and now >= self._deadline):
            return
        self._callback = None
        self._timer.stop()
        callback()


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
    """Rounded menu surface kept for callers that still import it.

    The application itself uses platform menus for text selection and
    right-click actions, so macOS renders its own native menu.
    """

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


class ConfirmationDialog(QDialog):
    """Small themed confirmation surface used for destructive actions."""

    def __init__(
        self,
        title: str,
        text: str,
        theme: str = "light",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("confirmationDialog")
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._surface_radius = 16.0
        self._surface_panel = "#FFFFFF"
        self._surface_border = "#D4D6D9"
        self.setStyleSheet(
            "QDialog#confirmationDialog { background: transparent; border: none; }"
        )
        self.setFixedWidth(460)
        self.setMinimumHeight(290)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame(self)
        self.card.setObjectName("confirmationCard")
        self.card.setMinimumWidth(412)
        root.addWidget(self.card)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(32, 28, 32, 26)
        card_layout.setSpacing(0)

        icon_row = QHBoxLayout()
        icon_row.addStretch()
        self.question_badge = QLabel(self.card)
        self.question_badge.setObjectName("confirmationQuestionBadge")
        self.question_badge.setFixedSize(56, 56)
        self.question_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.question_badge.setAccessibleName("确认操作")
        icon_row.addWidget(self.question_badge)
        icon_row.addStretch()
        card_layout.addLayout(icon_row)
        card_layout.addSpacing(16)

        self.title_label = QLabel(title, self.card)
        self.title_label.setObjectName("confirmationTitle")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.title_label)
        card_layout.addSpacing(8)

        self.message = QLabel(text, self.card)
        self.message.setObjectName("confirmationMessage")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setFixedWidth(344)
        card_layout.addWidget(
            self.message, 0, Qt.AlignmentFlag.AlignHCenter
        )
        card_layout.addSpacing(24)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        button_row.addStretch()
        self.no_button = QPushButton("No", self.card)
        self.no_button.setObjectName("confirmationNoBtn")
        self.no_button.setFixedSize(112, 40)
        self.no_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.no_button.setDefault(True)
        self.no_button.clicked.connect(self.reject)
        button_row.addWidget(self.no_button)

        self.yes_button = QPushButton("Yes", self.card)
        self.yes_button.setObjectName("confirmationYesBtn")
        self.yes_button.setFixedSize(112, 40)
        self.yes_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.yes_button.clicked.connect(self.accept)
        button_row.addWidget(self.yes_button)
        button_row.addStretch()
        card_layout.addLayout(button_row)

        self.apply_theme(theme)
        self.adjustSize()

    @classmethod
    def ask(
        cls,
        parent: QWidget,
        title: str,
        text: str,
        theme: str = "light",
    ) -> bool:
        dialog = cls(title, text, theme, parent)
        try:
            return dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.adjustSize()
        self._center_on_parent()
        self.no_button.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        center = parent.mapToGlobal(parent.rect().center())
        screen = parent.screen() or QApplication.primaryScreen()
        x = center.x() - self.width() // 2
        y = center.y() - self.height() // 2
        if screen is not None:
            available = screen.availableGeometry()
            x = max(
                available.left(),
                min(x, available.right() - self.width() + 1),
            )
            y = max(
                available.top(),
                min(y, available.bottom() - self.height() + 1),
            )
        self.move(x, y)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(self._surface_radius, rect.width() / 2, rect.height() / 2)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, QColor(self._surface_panel))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(self._surface_border), 1.0))
        painter.drawPath(path)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        self._surface_panel = palette["panel"]
        self._surface_border = palette["border_strong"]
        self.setStyleSheet(
            "QDialog#confirmationDialog { background: transparent; border: none; }"
        )
        self.card.setStyleSheet(
            f"""
QFrame#confirmationCard {{
    color: {palette['fg']};
    background: transparent;
    border: none;
    outline: none;
    padding: 0px;
}}
QLabel#confirmationQuestionBadge {{
    background: {palette['accent_soft']};
    border: none;
    border-radius: 28px;
}}
QLabel#confirmationTitle {{
    color: {palette['fg']};
    background: {palette['panel']};
    font-size: 18px;
    font-weight: 650;
}}
QLabel#confirmationMessage {{
    color: {palette['fg_sub']};
    background: {palette['panel']};
    font-size: 13px;
    line-height: 1.45;
}}
QPushButton#confirmationNoBtn,
QPushButton#confirmationYesBtn {{
    border-radius: 10px;
    padding: 0;
    font-weight: 600;
}}
QPushButton#confirmationNoBtn {{
    color: {palette['fg_sub']};
    background: {palette['panel']};
    border: 1px solid {palette['border_strong']};
}}
QPushButton#confirmationNoBtn:hover {{
    color: {palette['fg']};
    background: {palette['hover']};
    border-color: {palette['fg_muted']};
}}
QPushButton#confirmationNoBtn:pressed {{
    background: {palette['selected']};
    border-color: {palette['accent']};
}}
QPushButton#confirmationYesBtn {{
    color: {palette['danger']};
    background: {palette['danger_soft']};
    border: 1px solid {palette['danger']};
}}
QPushButton#confirmationYesBtn:hover {{
    color: #FFFFFF;
    background: {palette['danger']};
    border-color: {palette['danger']};
}}
QPushButton#confirmationYesBtn:pressed {{
    color: #FFFFFF;
    background: {palette['danger']};
    border-color: {palette['fg']};
}}
"""
        )
        self.question_badge.setPixmap(
            icon("question", palette["accent"], 28).pixmap(28, 28)
        )
        self.update()


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
        self._watch_timer.setInterval(2000)
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

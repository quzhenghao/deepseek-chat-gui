from __future__ import annotations

import html
import json
from math import ceil
from pathlib import Path

from PySide6.QtCore import (
    QElapsedTimer,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QDesktopServices,
    QFontMetricsF,
    QGuiApplication,
    QIcon,
    QImage,
    QLinearGradient,
    QPen,
    QPainter,
    QPixmap,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import ASSETS_DIR
from ..markdown import StreamingMarkdown, render_body, to_html
from .controls import build_flat_menu
from .image_strip import rounded_thumbnail
from .math_shell import MATH_WEB_SHELL
from .icons import apply_icon, tint_pixmap
from .theme import CHAT_BUBBLE_RADIUS, MESSAGE_CONTENT_MAX_WIDTH, colors


IMAGE_THUMB_SIZE = 160
IMAGE_GRID_COLUMNS = 3
LANE_MAX_WIDTH = MESSAGE_CONTENT_MAX_WIDTH + 63
KATEX_DIR = ASSETS_DIR / "vendor" / "katex"

WEB_SURFACE_TEXTURE_LIMIT = 8192
WEB_SURFACE_MAX_HEIGHT = 6000


_MATH_WEB_SHELL = MATH_WEB_SHELL


class _MathPage(QWebEnginePage):
    """Keep generated content local and hand user-clicked links to the OS."""

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame) -> bool:
        if navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            if url.scheme().lower() in {"http", "https", "mailto"}:
                QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class _MathBridge(QObject):
    layoutReported = Signal(int, int)
    verticalScrollRequested = Signal(float)
    copyRequested = Signal(str)
    selectionDragStarted = Signal(float, float)
    selectionDragMoved = Signal(float, float)
    selectionDragFinished = Signal()

    @Slot(float, float)
    def reportLayout(self, height: float, changed_top: float) -> None:
        self.layoutReported.emit(
            max(1, round(height)),
            max(0, round(changed_top)),
        )

    @Slot(float)
    def scrollVertically(self, delta: float) -> None:
        self.verticalScrollRequested.emit(delta)

    @Slot(str)
    def copyText(self, text: str) -> None:
        self.copyRequested.emit(text)

    @Slot(float, float)
    def startSelectionDrag(self, x: float, y: float) -> None:
        self.selectionDragStarted.emit(x, y)

    @Slot(float, float)
    def moveSelectionDrag(self, x: float, y: float) -> None:
        self.selectionDragMoved.emit(x, y)

    @Slot()
    def finishSelectionDrag(self) -> None:
        self.selectionDragFinished.emit()


class _MathWebView(QWebEngineView):
    contentHeightChanged = Signal(int)
    contentRendered = Signal()
    layoutReported = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("skipCustomTooltipScan", True)
        self._disposed = False
        self._ready = False
        self._pending_document: dict | None = None
        self._pending_calls: list[tuple[str, int]] = []
        self._generation = 0
        self._call_serial = 0
        self._rendered_generation = -1
        self._document_height = 0
        self._changed_top = 0
        self._offset = 0
        self._stream_started = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # The owning RichText positions tiles explicitly; it must stay free to
        # resize them, so no fixed height is set here.
        self.setMinimumHeight(1)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setStyleSheet("background:transparent;border:none;")

        page = _MathPage(self)
        self.setPage(page)
        page.setBackgroundColor(QColor(Qt.GlobalColor.transparent))
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            False,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
            False,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,
            False,
        )

        self._bridge = _MathBridge(self)
        self._bridge.layoutReported.connect(self._on_layout_reported)
        self._bridge.verticalScrollRequested.connect(self._forward_vertical_scroll)
        self._copy_to_clipboard = lambda text: QApplication.clipboard().setText(text)
        self._bridge.copyRequested.connect(self._copy_to_clipboard)
        self._bridge.selectionDragStarted.connect(self._start_selection_drag)
        self._bridge.selectionDragMoved.connect(self._move_selection_drag)
        self._bridge.selectionDragFinished.connect(self._finish_selection_drag)
        self._channel = QWebChannel(page)
        self._channel.registerObject("mathBridge", self._bridge)
        page.setWebChannel(self._channel)
        self.loadFinished.connect(self._on_load_finished)
        self._layout_refresh_timer = QTimer(self)
        self._layout_refresh_timer.setSingleShot(True)
        self._layout_refresh_timer.setInterval(50)
        self._layout_refresh_timer.timeout.connect(self._refresh_web_layout)

        base_url = QUrl.fromLocalFile(f"{KATEX_DIR.resolve()}/")
        self.setHtml(_MATH_WEB_SHELL, base_url)

    @property
    def document_height(self) -> int:
        """Natural height of the whole rendered answer, in logical pixels."""

        return max(0, self._document_height)

    @property
    def changed_top(self) -> int:
        """Document y where this tile's DOM last changed."""

        return max(0, self._changed_top)

    @property
    def offset(self) -> int:
        return self._offset

    def set_document(
        self,
        style: str,
        stable: str,
        tail: str,
        *,
        code_tail: str = "",
        offset: int | None = None,
    ) -> None:
        """Replace this tile's whole document."""

        if self._disposed:
            return
        self._generation += 1
        self._stream_started = False
        self._pending_document = {
            "style": style,
            "stable": stable,
            "tail": tail,
            "codeTail": code_tail,
        }
        self._pending_calls.clear()
        if offset is not None:
            self._offset = int(offset)
        if self._ready:
            self._render_pending_document()

    def push_stream(
        self,
        stable_delta: str,
        tail: str,
        *,
        code_delta: str = "",
        code_tail: str = "",
        composed_stable: str = "",
    ) -> None:
        """Append newly frozen HTML and swap the live tail of this tile."""

        if self._disposed:
            return
        if self._pending_document is not None or not self._stream_started:
            # The document has not been painted yet; fold the growth into it.
            pending = self._pending_document
            if pending is not None:
                pending["stable"] = composed_stable or (
                    pending.get("stable", "") + (stable_delta or "")
                )
                pending["tail"] = tail
                pending["codeTail"] = code_tail
            return
        data = {
            "stable": stable_delta or "",
            "code": code_delta or "",
            "codeTail": code_tail or "",
            "tail": tail or "",
            "hasTail": True,
        }
        payload = json.dumps(data)
        script = (
            f"window.setDeepSeekStream({json.dumps(payload)})"
        )
        self._run(script)

    def set_offset(self, offset: int) -> None:
        """Show rows ``[offset, offset + height)`` of the document."""

        if self._disposed:
            return
        offset = int(offset)
        if offset == self._offset:
            return
        self._offset = offset
        self._run(f"window.setDeepSeekOffset({offset})")

    def _on_load_finished(self, succeeded: bool) -> None:
        if self._disposed:
            return
        self._ready = succeeded
        if succeeded:
            self._render_pending_document()

    def _run(self, script: str) -> None:
        if self._disposed or not self._ready or self.page() is None:
            self._pending_calls.append((script, self._generation))
            return
        self._call_serial += 1
        serial = self._call_serial
        self.page().runJavaScript(
            script,
            lambda value, current=serial: self._call_finished(current, value),
        )

    def _render_pending_document(self) -> None:
        if self._disposed or not self._ready or self.page() is None:
            return
        pending = self._pending_document
        if pending is None:
            self._flush_pending_calls()
            return
        self._pending_document = None
        payload = json.dumps(
            {
                "style": pending["style"],
                "stable": pending["stable"],
                "tail": pending["tail"],
                "codeTail": pending.get("codeTail", ""),
            }
        )
        script = (
            f"window.setDeepSeekOffset({int(self._offset)});"
            f"window.setDeepSeekDocument({json.dumps(payload)})"
        )
        self._stream_started = True
        self._run(script)
        self._flush_pending_calls()

    def _flush_pending_calls(self) -> None:
        if not self._pending_calls:
            return
        pending, self._pending_calls = self._pending_calls, []
        for script, _generation in pending:
            self._run(script)

    def _call_finished(self, serial: int, value) -> None:
        if self._disposed or serial != self._call_serial:
            return
        if isinstance(value, str) and value.startswith("{"):
            try:
                data = json.loads(value)
            except ValueError:
                data = None
            if isinstance(data, dict):
                self._document_height = max(
                    1, int(data.get("documentHeight") or 0)
                )
                self._changed_top = max(0, int(data.get("changedTop") or 0))
                self.layoutReported.emit(
                    self._document_height,
                    self._changed_top,
                )
                self._rendered_generation = self._generation
        self.contentRendered.emit()

    @Slot(int, int)
    def _on_layout_reported(self, height: int, changed_top: int) -> None:
        if self._disposed:
            return
        if height <= 1 and self._document_height <= 1:
            # A page reports its still-unset body before the document call
            # lands; that empty state must never reach the lane.
            return
        self._document_height = max(1, int(height))
        self._changed_top = max(0, int(changed_top))
        self._rendered_generation = self._generation
        self.layoutReported.emit(
            self._document_height,
            self._changed_top,
        )

    def _surface_height_limit(self) -> int:
        """Largest safe web surface, in logical pixels, for this screen.

        Chromium reduces any surface taller than the GPU texture budget, which
        silently blanks the tail of the page, so one answer is painted by
        several tiles of at most this height instead.
        """

        screen = self.screen() or QGuiApplication.primaryScreen()
        ratio = float(screen.devicePixelRatio()) if screen is not None else 1.0
        return max(
            1200,
            min(
                WEB_SURFACE_MAX_HEIGHT,
                int(WEB_SURFACE_TEXTURE_LIMIT / max(1.0, ratio)),
            ),
        )

    @Slot(float)
    def _forward_vertical_scroll(self, delta: float) -> None:
        ancestor = self.parentWidget()
        while ancestor is not None and not isinstance(ancestor, QAbstractScrollArea):
            ancestor = ancestor.parentWidget()
        if ancestor is None:
            return
        scroll_bar = ancestor.verticalScrollBar()
        chat = _chat_view_for(self)
        if chat is not None:
            chat.pause_follow()
        scroll_bar.setValue(scroll_bar.value() + round(delta))

    def _start_selection_drag(self, x: float, y: float) -> None:
        chat = _chat_view_for(self)
        if chat is not None:
            chat._start_selection_drag(
                self, self.mapToGlobal(QPoint(round(x), round(y)))
            )

    def _move_selection_drag(self, x: float, y: float) -> None:
        chat = _chat_view_for(self)
        if chat is not None:
            chat._move_selection_drag(
                self, self.mapToGlobal(QPoint(round(x), round(y)))
            )

    def _finish_selection_drag(self) -> None:
        chat = _chat_view_for(self)
        if chat is not None:
            chat._stop_selection_drag(self)

    def _extend_selection_drag(self, delta: int, global_pos: QPoint) -> None:
        if self._disposed or self.page() is None:
            return
        point = self.mapFromGlobal(global_pos)
        self.page().runJavaScript(
            f"window.autoScrollSelection({delta}, {point.x()}, {point.y()})"
        )

    def focusOutEvent(self, event) -> None:
        if event.reason() == Qt.FocusReason.MouseFocusReason:
            self.clear_selection()
        super().focusOutEvent(event)

    def clear_selection(self) -> None:
        if self._disposed:
            return
        page = self.page()
        if page is not None:
            page.triggerAction(QWebEnginePage.WebAction.Unselect)

    def contextMenuEvent(self, event) -> None:
        """Flat menu with the standard actions Chromium offers in-page."""

        page = self.page()
        if self._disposed or page is None:
            return
        request = self.lastContextMenuRequest()
        selected = (request.selectedText() or "") if request is not None else ""
        link = ""
        if request is not None:
            url = request.linkUrl()
            link = url.toString() if url.isValid() and not url.isEmpty() else ""

        menu = build_flat_menu(self)
        copy_action = menu.addAction("复制")
        copy_action.setEnabled(bool(selected.strip()))
        link_action = menu.addAction("复制链接地址") if link else None
        menu.addSeparator()
        select_all_action = menu.addAction("全选")
        chosen = menu.exec(event.globalPos())
        menu.deleteLater()
        if chosen is None:
            return
        if chosen is copy_action:
            QApplication.clipboard().setText(selected)
        elif link_action is not None and chosen is link_action:
            QApplication.clipboard().setText(link)
        elif chosen is select_all_action and page is not None:
            page.triggerAction(QWebEnginePage.WebAction.SelectAll)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._ready and not self._disposed and not self._layout_refresh_timer.isActive():
            self._layout_refresh_timer.start()

    def _refresh_web_layout(self) -> None:
        if self._disposed or not self._ready:
            return
        page = self.page()
        if page is not None:
            page.runJavaScript("window.refreshDeepSeekLayout()")

    def dispose(self) -> None:
        """Stop callbacks and discard the renderer before deferred deletion."""

        if self._disposed:
            return
        self._finish_selection_drag()
        self._disposed = True
        self._ready = False
        self._generation += 1
        self._pending_document = None
        self._pending_calls.clear()
        self._layout_refresh_timer.stop()
        try:
            self.loadFinished.disconnect(self._on_load_finished)
        except (RuntimeError, TypeError):
            pass
        for signal, slot in (
            (self._bridge.layoutReported, self._on_layout_reported),
            (self._bridge.verticalScrollRequested, self._forward_vertical_scroll),
            (self._bridge.copyRequested, self._copy_to_clipboard),
            (self._bridge.selectionDragStarted, self._start_selection_drag),
            (self._bridge.selectionDragMoved, self._move_selection_drag),
            (self._bridge.selectionDragFinished, self._finish_selection_drag),
        ):
            try:
                signal.disconnect(slot)
            except (AttributeError, RuntimeError, TypeError):
                pass
        self.hide()
        page = self.page()
        if page is not None:
            try:
                page.setLifecycleState(QWebEnginePage.LifecycleState.Discarded)
            except (AttributeError, RuntimeError, TypeError):
                pass
        self.deleteLater()


def _chat_view_for(widget: QWidget) -> ChatView | None:
    ancestor = widget.parentWidget()
    while ancestor is not None and not isinstance(ancestor, ChatView):
        ancestor = ancestor.parentWidget()
    return ancestor


class MessageTextBrowser(QTextBrowser):
    """Read-only message text whose right-click menu stays a flat panel."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            chat = _chat_view_for(self)
            if chat is not None:
                chat._start_selection_drag(self, event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if event.buttons() & Qt.MouseButton.LeftButton:
            chat = _chat_view_for(self)
            if chat is not None:
                chat._move_selection_drag(self, event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            chat = _chat_view_for(self)
            if chat is not None:
                chat._stop_selection_drag(self)

    def _extend_selection_drag(self, global_pos: QPoint) -> None:
        cursor = self.textCursor()
        point = self.viewport().mapFromGlobal(global_pos)
        point.setX(max(0, min(self.viewport().width() - 1, point.x())))
        target = self.cursorForPosition(point)
        if target.position() != cursor.position():
            cursor.setPosition(target.position(), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)

    def focusOutEvent(self, event) -> None:
        if event.reason() == Qt.FocusReason.MouseFocusReason:
            self.clear_selection()
        super().focusOutEvent(event)

    def clear_selection(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.clearSelection()
            self.setTextCursor(cursor)

    def contextMenuEvent(self, event) -> None:
        menu = build_flat_menu(self)
        copy_action = menu.addAction("复制")
        copy_action.setEnabled(self.textCursor().hasSelection())
        link = self.anchorAt(event.pos())
        link_action = menu.addAction("复制链接地址") if link else None
        menu.addSeparator()
        select_all_action = menu.addAction("全选")
        chosen = menu.exec(event.globalPos())
        menu.deleteLater()
        if chosen is None:
            return
        if chosen is copy_action:
            self.copy()
        elif link_action is not None and chosen is link_action:
            QApplication.clipboard().setText(link)
        elif chosen is select_all_action:
            self.selectAll()


class _RevealCurtain(QWidget):
    """Soft edge that fades the newest message text from light to dark.

    The reveal frontier itself is animated by resizing the message viewport,
    which Qt composites without repainting the embedded Chromium surfaces.
    This strip only paints the gradient that makes the emerging text look like
    it is still developing instead of ending in a hard cut.
    """

    MIN_BAND = 42
    MAX_BAND = 260

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._color = QColor("#FFFFFF")
        self._band = 90
        self.hide()

    def set_color(self, color: QColor) -> None:
        if color == self._color:
            return
        self._color = QColor(color)
        self.update()

    def set_band(self, band: int) -> None:
        band = max(self.MIN_BAND, min(self.MAX_BAND, int(band)))
        if band == self._band:
            return
        self._band = band

    @property
    def band(self) -> int:
        return self._band

    def paintEvent(self, event) -> None:
        del event
        if self.height() <= 0:
            return
        painter = QPainter(self)
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
        transparent = QColor(self._color)
        transparent.setAlpha(0)
        soft = QColor(self._color)
        soft.setAlpha(210)
        opaque = QColor(self._color)
        gradient.setColorAt(0.0, transparent)
        gradient.setColorAt(0.55, soft)
        gradient.setColorAt(1.0, opaque)
        painter.fillRect(self.rect(), gradient)
        painter.end()


def _surface_height_limit(widget: QWidget) -> int:
    """Largest web surface, in logical pixels, this screen can composite.

    Chromium silently reduces anything taller than the GPU texture budget,
    which blanks the tail of the page, so a long answer is painted by several
    tiles of at most this height instead of one oversized surface.
    """

    screen = widget.screen() or QGuiApplication.primaryScreen()
    ratio = float(screen.devicePixelRatio()) if screen is not None else 1.0
    return max(
        1200,
        min(
            WEB_SURFACE_MAX_HEIGHT,
            int(WEB_SURFACE_TEXTURE_LIMIT / max(1.0, ratio)),
        ),
    )


def _needs_web_renderer(html: str) -> bool:
    """True when a body needs KaTeX or a code toolbar from Chromium."""

    return "data-tex=" in html or "data-code-block=" in html


def _split_rendered_html(rendered: str) -> tuple[str, str]:
    """Split a :func:`to_html` payload into its style block and inner body."""

    marker = '<div class="markdown-body">'
    index = rendered.find(marker)
    if index < 0:
        return "", rendered
    remainder = rendered[index + len(marker) :]
    end = remainder.rfind("</div>")
    if end >= 0:
        remainder = remainder[:end]
    return rendered[:index], remainder


class RichText(QWidget):
    """Fast QTextBrowser for ordinary text, KaTeX web layout only when needed."""

    heightChanged = Signal()
    revealFinished = Signal()

    # The reveal frontier walks the answer at display refresh rate.  It is
    # animated by the host - growing the message viewport and fading its edge
    # with a native curtain - so no Chromium surface has to change per frame
    # and the newest text still emerges as a large, soft, darkening area.
    REVEAL_CATCH_UP = 0.16
    REVEAL_MIN_STEP_PX = 2.0
    # Fast enough to feel immediate, slow enough that the lane can keep the
    # newest text pinned to the bottom of the viewport while following.
    REVEAL_MAX_STEP_PX = 130.0
    # The frontier may glide this far past the rendered text, which keeps it
    # moving smoothly even though the DOM itself is updated in batches.
    REVEAL_SETTLE_ALLOWANCE = 700.0
    REVEAL_BAND_PER_PIXEL = 2.5
    # The DOM is kept barely ahead of the frontier, so the reveal can advance
    # on every display frame instead of jumping when a batch lands.
    STREAM_RENDER_INTERVAL_MS = 16

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._theme = "light"
        self._disposed = False
        self._html = ""
        self._source = ""
        self._uses_math = False
        self._renderer = StreamingMarkdown()
        self._style_html = ""
        self._stable_html = ""
        self._tail_html = ""
        self._tiles: list[_MathWebView] = []
        self._document_height = 0
        self._changes_from = 0
        self._streaming = False
        self._finished = False
        self._stream_dirty = False
        self._reveal_active = False
        self._frontier = 0.0
        self._repaint_tiles = False

        self._text_view = MessageTextBrowser()
        self._text_view.setParent(self)
        self._text_view.setFrameShape(QFrame.Shape.NoFrame)
        self._text_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._text_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._text_view.setOpenExternalLinks(True)
        self._text_view.document().setDocumentMargin(0)
        self._text_view.setStyleSheet("background:transparent;border:none;")
        self._text_view.setGeometry(0, 0, 1, 1)

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit_text_height)
        self._text_view.document().contentsChanged.connect(self._schedule_fit)

        self._stream_timer = QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.setInterval(self.STREAM_RENDER_INTERVAL_MS)
        self._stream_timer.timeout.connect(self._flush_stream)

        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(16)
        self._reveal_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._reveal_timer.timeout.connect(self._advance_reveal)

        self._curtain = _RevealCurtain(self)
        self._curtain.set_color(QColor(colors("light")["canvas"]))

        self.setFixedHeight(22)

    def dispose(self) -> None:
        """Retire timers and Chromium surfaces before deletion."""

        if self._disposed:
            return
        self._disposed = True
        self._stop_timers()
        self._dispose_tiles()
        self._curtain.hide()

    def clear_selection(self) -> None:
        if self._uses_math:
            for tile in self._tiles:
                tile.clear_selection()
        else:
            self._text_view.clear_selection()

    def document(self) -> QTextDocument:
        """Retain the former QTextBrowser API for non-math callers and tests."""

        return self._text_view.document()

    def set_theme(self, dark: bool) -> None:
        """Track the palette; re-rendering happens on the next set_html."""

        theme = "dark" if dark else "light"
        if theme == self._theme:
            return
        self._theme = theme
        self._renderer.set_theme(dark)
        self._curtain.set_color(QColor(colors(theme)["canvas"]))

    @property
    def uses_web_renderer(self) -> bool:
        return self._uses_math

    @property
    def tile_count(self) -> int:
        """How many GPU-safe surfaces currently paint this message."""

        return len(self._tiles)

    @property
    def tile_height(self) -> int:
        """Maximum height of one painted surface, in logical pixels."""

        return self._tile_height()

    @property
    def document_height(self) -> int:
        """Natural height of the whole answer, reached or not."""

        return self._document_extent()

    @property
    def front_height(self) -> int:
        """Document y of the reveal frontier."""

        return max(0, self._front_height)

    @property
    def is_revealing(self) -> bool:
        return self._reveal_active

    @property
    def frontier(self) -> float:
        """Document y the reveal has uncovered so far."""

        return float(self._frontier)

    @property
    def revealed_fraction(self) -> float:
        """Fraction of the buffered answer that is already on screen."""

        if not self._reveal_active:
            return 1.0
        extent = max(1, self._document_extent())
        return max(0.0, min(1.0, self._frontier / extent))

    def set_html(
        self,
        body: str,
        reveal_characters: int | None = None,
        reveal_total_characters: int | None = None,
    ) -> None:
        """Show a finished body (history, reasoning) without streaming.

        ``reveal_characters`` / ``reveal_total_characters`` keep the legacy
        API: when they are given the body fades in from its first line.
        """

        if self._disposed:
            return
        self._stop_timers()
        self._streaming = False
        self._finished = True
        self._source = ""
        self._renderer.reset()
        self._renderer.set_theme(self._theme == "dark")
        self._html = str(body or "")
        style, inner = _split_rendered_html(self._html)
        self._style_html = style or self._renderer.style_html()
        self._stable_html = inner
        self._tail_html = ""
        self._uses_math = _needs_web_renderer(inner)
        animate = (
            reveal_characters is not None or reveal_total_characters is not None
        )
        self._reveal_active = bool(animate)
        self._frontier = 0.0 if animate else float("inf")
        self._document_height = 0
        self._changes_from = 0
        if self._uses_math:
            # A finished body is part of the conversation history, so it is
            # fully on screen the moment its surface has painted.
            self._reveal_active = False
            self._rebuild_web()
            return
        self._dispose_tiles()
        self._text_view.show()
        self._text_view.setHtml(self._html)
        self._curtain.hide()
        self._set_content_height(22)
        self._schedule_fit()

    def set_reveal_characters(self, characters: int | None) -> None:
        """Legacy hook: finish the reveal or hide the curtain."""

        if self._disposed:
            return
        if characters is None:
            self._finish_reveal()
            return
        self._reveal_active = True
        self._frontier = min(self._frontier, float(max(0, int(characters))))
        if not self._reveal_timer.isActive():
            self._reveal_timer.start()

    # ------------------------------------------------------------------
    # buffered streaming
    # ------------------------------------------------------------------
    def begin_stream(self) -> None:
        """Start an answer whose text arrives through :meth:`stream_text`."""

        if self._disposed:
            return
        self._stop_timers()
        self._renderer.set_theme(self._theme == "dark")
        self._renderer.reset()
        self._html = ""
        self._source = ""
        self._style_html = self._renderer.style_html()
        self._stable_html = ""
        self._tail_html = ""
        self._streaming = True
        self._finished = False
        self._stream_dirty = False
        self._reveal_active = True
        self._frontier = 0.0
        self._document_height = 0
        self._changes_from = 0
        self._dispose_tiles()
        self._uses_math = False
        self._text_view.show()
        self._text_view.document().setHtml("")
        self._curtain.setVisible(False)
        self._set_content_height(22)
        if not self._reveal_timer.isActive():
            self._reveal_timer.start()

    def stream_text(self, source: str) -> None:
        """Buffer model output; rendering and revealing follow on their own."""

        if self._disposed:
            return
        if not self._streaming:
            self.begin_stream()
        self._source = str(source or "")
        self._stream_dirty = True
        if not self._stream_timer.isActive():
            self._stream_timer.start()

    def complete_stream(self) -> None:
        """Mark the buffer final and let the reveal drain what is left."""

        if self._disposed:
            return
        self._finished = True
        if self._stream_dirty or self._stream_timer.isActive():
            self._stream_timer.stop()
            self._flush_stream()
        if not self._reveal_active:
            self._finish_reveal()
            return
        self._advance_reveal()

    # ------------------------------------------------------------------
    # reveal
    # ------------------------------------------------------------------
    def _reveal_limit(self) -> float:
        """Document y the frontier may reach, fade allowance included."""

        return self._document_extent() + self.REVEAL_SETTLE_ALLOWANCE

    def _advance_reveal(self) -> None:
        """Move the frontier one display frame forward and resize the body."""

        if self._disposed or not self._reveal_active:
            self._reveal_timer.stop()
            return
        limit = self._reveal_limit()
        backlog = limit - self._frontier
        if backlog > 0:
            step = min(
                self.REVEAL_MAX_STEP_PX,
                max(self.REVEAL_MIN_STEP_PX, backlog * self.REVEAL_CATCH_UP),
            )
            self._frontier = min(limit, self._frontier + step)
            self._curtain.set_band(step * self.REVEAL_BAND_PER_PIXEL)
        self._apply_reveal_geometry()
        if self._finished and self._frontier >= limit:
            self._finish_reveal()
            return
        self._reveal_timer.start()

    def _apply_reveal_geometry(self) -> None:
        """Expose the revealed slice and park the fade curtain on its edge."""

        extent = self._document_extent()
        visible = int(max(0.0, min(float(extent), self._frontier)))
        self._set_content_height(max(22, visible))
        if not self._reveal_active:
            self._curtain.hide()
            return
        band = self._curtain.band
        top = int(round(self._frontier)) - band
        self._curtain.setGeometry(0, top, max(1, self.width()), band)
        show = top < max(22, visible) - 4
        self._curtain.setVisible(show)
        if show:
            self._curtain.raise_()

    def _text_document_height(self) -> int:
        document = self._text_view.document()
        return max(0, int(document.size().height() + 3))

    def _document_extent(self) -> int:
        """Height of the whole answer, in document pixels."""

        if self._uses_math:
            return max(0, self._document_height)
        return self._text_document_height()

    def _finish_reveal(self) -> None:
        """Retire the curtain and expose the finished answer."""

        if self._disposed:
            return
        was_active = self._reveal_active
        self._reveal_active = False
        self._reveal_timer.stop()
        self._curtain.hide()
        if self._uses_math:
            if self._renderer.source:
                # Repaint every surface once from the finished source: the
                # last stream batch can still have been in flight, and a
                # transient split (an unterminated formula, a reference
                # defined after its use) can only be resolved by a full pass.
                self._style_html = self._renderer.style_html()
                self._stable_html = render_body(self._renderer.source)
                self._tail_html = ""
                self._rebuild_web()
        self._set_content_height(max(22, self._document_extent()))
        if was_active:
            self.revealFinished.emit()

    def _update_content_geometry(self) -> None:
        """Keep the painted surfaces and the curtain aligned with this body."""

        width = max(1, self.width())
        self._text_view.setGeometry(0, 0, width, max(1, self.height()))
        tile_height = self._tile_height()
        for index, tile in enumerate(self._tiles):
            tile.setGeometry(0, index * tile_height, width, tile.height())
        if self._reveal_active:
            self._apply_reveal_geometry()

    def _stop_timers(self) -> None:
        self._stream_timer.stop()
        self._reveal_timer.stop()
        self._fit_timer.stop()

    def _dispose_tiles(self) -> None:
        tiles, self._tiles = self._tiles, []
        for tile in tiles:
            tile.hide()
            tile.dispose()
            tile.deleteLater()

    def _tile_height(self) -> int:
        return _surface_height_limit(self)

    def _flush_stream(self) -> None:
        """Render buffered output, appending only what has not been shown."""

        self._stream_dirty = False
        if self._disposed or not self._streaming:
            return
        delta, code_delta, tail = self._renderer.update(self._source)
        self._style_html = self._renderer.style_html()
        # The live code line travels as ``codeTail`` so a surface can replace
        # it instead of printing it twice.
        self._stable_html = self._renderer.composed_stable_html(
            include_code_tail=False
        )
        self._tail_html = tail
        wants_web = _needs_web_renderer(self._stable_html) or _needs_web_renderer(
            self._tail_html
        )
        if wants_web and not self._uses_math:
            self._rebuild_web()
            return
        if wants_web:
            self._push_web(
                delta,
                self._tail_html,
                code_delta=code_delta,
                code_tail=self._renderer.code_tail_text,
            )
            return
        self._render_text_stream()

    def _render_text_stream(self) -> None:
        """Repaint the plain-text body from the incremental renderer."""

        self._dispose_tiles()
        self._uses_math = False
        self._text_view.show()
        self._text_view.setHtml(self._style_html + self._renderer.body_html())
        self._schedule_fit()
        if self._reveal_active:
            self._apply_reveal_geometry()

    def _rebuild_web(self) -> None:
        """Paint the answer with Chromium tiles using the current HTML."""

        self._uses_math = True
        self._text_view.hide()
        self._document_height = 0
        self._changes_from = 0
        self._repaint_tiles = True
        self._sync_tiles()
        if self._reveal_active:
            self._apply_reveal_geometry()

    def _sync_tiles(self) -> None:
        """Grow or shrink the windowed tile stack over the document."""

        tile_height = self._tile_height()
        document = max(0, self._document_height)
        needed = (
            max(1, int(ceil(document / tile_height)))
            if document > 0
            else (1 if (self._stable_html or self._tail_html) else 0)
        )
        while len(self._tiles) > needed:
            tile = self._tiles.pop()
            tile.hide()
            tile.dispose()
            tile.deleteLater()
        width = max(1, self.width())
        for index, tile in enumerate(self._tiles):
            top = index * tile_height
            height = max(1, min(tile_height, document - top))
            tile.setGeometry(0, top, width, height)
            tile.set_offset(top)
        while len(self._tiles) < needed:
            index = len(self._tiles)
            top = index * tile_height
            height = max(
                1,
                min(tile_height, document - top) if document else tile_height,
            )
            tile = _MathWebView(self)
            tile.layoutReported.connect(
                lambda height, changed, view=tile: self._on_tile_layout(
                    view, height, changed
                )
            )
            tile.setGeometry(0, top, width, height)
            self._paint_tile(tile, top)
            tile.show()
            tile.raise_()
            self._tiles.append(tile)
        if self._repaint_tiles:
            # A rebuild repaints the surfaces that are already alive instead
            # of replacing them, which keeps Chromium pages from churning.
            for index, tile in enumerate(self._tiles[:needed]):
                self._paint_tile(tile, index * tile_height)
        self._repaint_tiles = False
        if not self._tiles:
            self._set_content_height(22)
        elif not self._reveal_active:
            self._set_content_height(max(22, self._document_height))
        self._curtain.raise_()

    def _paint_tile(self, tile: _MathWebView, top: int) -> None:
        tile.set_document(
            self._style_html,
            self._stable_html,
            self._tail_html,
            code_tail=self._renderer.code_tail_text,
            offset=top,
        )

    def _push_web(
        self,
        delta: str,
        tail: str,
        *,
        code_delta: str = "",
        code_tail: str = "",
    ) -> None:
        """Send the newest HTML fragments to every tile that can show them."""

        if not self._tiles:
            self._sync_tiles()
            return
        tile_height = self._tile_height()
        dirty = max(0, self._changes_from)
        for index, tile in enumerate(self._tiles):
            if (index + 1) * tile_height <= dirty:
                continue
            tile.push_stream(
                delta,
                tail,
                code_delta=code_delta,
                code_tail=code_tail,
                composed_stable=self._stable_html,
            )

    def _on_tile_layout(
        self,
        tile: _MathWebView,
        document_height: int,
        changed_top: int,
    ) -> None:
        if self._disposed or tile is None or tile not in self._tiles:
            return
        if changed_top > self._changes_from:
            self._changes_from = changed_top
        if document_height > self._document_height:
            # Tiles that skipped an update report an older, shorter document;
            # the answer only ever grows, so the tallest report wins.
            self._document_height = document_height
            self._sync_tiles()
            if not self._reveal_active:
                self._set_content_height(max(22, self._document_height))

    def _schedule_fit(self) -> None:
        if not self._uses_math and not self._fit_timer.isActive():
            self._fit_timer.start()

    def _fit_text_height(self) -> None:
        if self._uses_math:
            return
        width = max(40, self._text_view.viewport().width())
        document = self._text_view.document()
        if abs(document.textWidth() - width) > 0.5:
            document.setTextWidth(width)
        if not self._reveal_active:
            self._set_content_height(max(22, self._text_document_height()))

    def _set_content_height(self, height: int) -> None:
        if abs(self.height() - height) > 1:
            self.setFixedHeight(height)
            self.heightChanged.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_content_geometry()
        self._schedule_fit()


class ThinkingIndicator(QWidget):
    """Rotating progress glyph shown while a reply is still thinking."""

    RADIUS = 6.4
    STROKE = 2.0
    ARC_SWEEP = -104.0

    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._angle = 0
        self._running = False
        self.setFixedSize(20, 20)
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        self._running = True
        self._elapsed.start()
        self._timer.start()
        self.update()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        self.update()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def _advance(self) -> None:
        if not self._elapsed.isValid():
            self._elapsed.start()
        self._angle = (self._elapsed.elapsed() * 360.0 / 1100.0) % 360.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(colors(self._theme)["accent"])
        if self._running:
            self._paint_arc(painter, accent)
        else:
            painter.setPen(accent)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(10, 3), QPointF(10, 17))
            painter.drawLine(QPointF(3, 10), QPointF(17, 10))
            painter.drawLine(QPointF(5.2, 5.2), QPointF(14.8, 14.8))
            painter.drawLine(QPointF(14.8, 5.2), QPointF(5.2, 14.8))
        painter.end()

    def _paint_arc(self, painter: QPainter, accent: QColor) -> None:
        """Draw a tapered ring: faint track plus a bright, trailing head."""

        painter.save()
        painter.translate(10.0, 10.0)
        painter.rotate(self._angle)
        track = QColor(accent)
        track.setAlpha(48)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(track, self.STROKE))
        painter.drawEllipse(QPointF(0.0, 0.0), self.RADIUS, self.RADIUS)

        head = QColor(accent)
        tail = QColor(accent)
        tail.setAlpha(0)
        gradient = QConicalGradient(QPointF(0.0, 0.0), 90.0)
        gradient.setColorAt(0.0, tail)
        gradient.setColorAt(1.0 - abs(self.ARC_SWEEP) / 360.0, head)
        gradient.setColorAt(1.0, tail)
        arc_pen = QPen(QBrush(gradient), self.STROKE)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        rect = QRectF(
            -self.RADIUS,
            -self.RADIUS,
            self.RADIUS * 2,
            self.RADIUS * 2,
        )
        painter.drawArc(rect, 90 * 16, int(self.ARC_SWEEP * 16))
        painter.restore()


_PREVIEW_SENTENCE_TERMINATORS = frozenset("。！？!?")
_PREVIEW_SENTENCE_CLOSERS = frozenset("”’\"'）)]】》」』〉»›")


def _extract_complete_sentences(text: str) -> list[str]:
    """Return complete thought sentences while leaving a streaming tail out."""

    source = str(text or "")
    return [
        source[start:end]
        for start, end in _sentence_spans(source)
    ]


def _sentence_spans(
    text: str,
    *,
    include_streaming_tail: bool = False,
) -> list[tuple[int, int]]:
    """Return source ranges whose starts are sentence starts.

    The preview can still show an unfinished streaming tail, but a new
    visual segment must never begin in the middle of a sentence.  Keeping
    source offsets here lets the width-aware segmenter use sentence
    boundaries without changing the text that is drawn.
    """

    source = str(text or "")
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    length = len(source)
    while index < length:
        character = source[index]
        is_terminator = character in _PREVIEW_SENTENCE_TERMINATORS
        if character == ".":
            next_index = index + 1
            while (
                next_index < length
                and source[next_index] in _PREVIEW_SENTENCE_CLOSERS
            ):
                next_index += 1
            next_character = source[next_index] if next_index < length else ""
            prefix = source[start:index].strip()
            # A period inside a decimal/version and a numbered list marker are
            # not useful sentence boundaries for the tiny streaming preview.
            is_terminator = (
                next_index >= length
                or next_character.isspace()
            ) and not prefix.isdigit()
        if not is_terminator:
            index += 1
            continue

        end = index + 1
        while end < length and source[end] in _PREVIEW_SENTENCE_TERMINATORS:
            end += 1
        while end < length and source[end] in _PREVIEW_SENTENCE_CLOSERS:
            end += 1
        content_start = start
        while content_start < end and source[content_start].isspace():
            content_start += 1
        content_end = end
        while content_end > content_start and source[content_end - 1].isspace():
            content_end -= 1
        if content_start < content_end:
            spans.append((content_start, content_end))
        start = end
        index = end

    if include_streaming_tail:
        tail_start = start
        while tail_start < length and source[tail_start].isspace():
            tail_start += 1
        tail_end = length
        while tail_end > tail_start and source[tail_end - 1].isspace():
            tail_end -= 1
        if tail_start < tail_end:
            spans.append((tail_start, tail_end))
    return spans


class ThinkingPreview(QWidget):
    """A width-aware, 60fps ticker for the collapsed reasoning header.

    The source is packed into visual-width windows, but each window begins at
    a sentence boundary.  A streaming tail is kept in the source so the
    header can remain informative before the next terminator arrives.  The
    right edge of each window is softened by the paint-time fade.
    """

    FRAME_INTERVAL_MS = 16
    TYPING_DURATION_MS = 500
    CYCLE_DURATION_MS = 1000
    FADE_WIDTH = 34

    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("reasoningPreview")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(20)

        self._theme = theme
        self._reasoning_text = ""
        self._sentences: list[str] = []
        self._segment_starts: list[int] = []
        self._current_index = 0
        self._current_sentence = ""
        self._visible_characters = 0
        self._running = False
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_INTERVAL_MS)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._advance)
        self._text_color = QColor()
        self._background_color = QColor()
        self.apply_theme(theme)

    @property
    def sentences(self) -> tuple[str, ...]:
        return tuple(self._sentences)

    @property
    def current_sentence(self) -> str:
        return self._current_sentence

    @property
    def visible_text(self) -> str:
        return self._current_sentence[: self._visible_characters]

    def set_reasoning(self, reasoning: str) -> None:
        # Keep the preview on one line while preserving the raw streaming
        # tail.  In particular, do not wait for a sentence-ending character.
        source = " ".join(str(reasoning or "").split())
        if source == self._reasoning_text:
            return
        self._reasoning_text = source
        self._rebuild_segments()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._sentences:
            self._current_index %= len(self._sentences)
            self._begin_cycle()
        else:
            self._visible_characters = 0
            self.update()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        self._elapsed.invalidate()
        self._current_index = 0
        self._current_sentence = ""
        self._visible_characters = 0
        self.update()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        self._text_color = QColor(palette["fg_muted"])
        self._background_color = QColor(palette["reason_bg"])
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rebuild_segments()

    def _rebuild_segments(self) -> None:
        """Pack visual windows without starting one inside a sentence."""

        source = self._reasoning_text
        old_start = (
            self._segment_starts[self._current_index]
            if self._segment_starts
            and self._current_index < len(self._segment_starts)
            else 0
        )
        old_visible = self._visible_characters
        if not source:
            self._sentences = []
            self._segment_starts = []
            self._current_index = 0
            self._current_sentence = ""
            self._visible_characters = 0
            self._timer.stop()
            self.update()
            return

        metrics = QFontMetricsF(self.font())
        # Include the fade region in the segment so the final characters are
        # present underneath the gradient instead of being hard-clipped at
        # the first pixel outside the header.
        max_width = max(1.0, float(self.width())) + self.FADE_WIDTH
        segments: list[str] = []
        starts: list[int] = []
        spans = _sentence_spans(source, include_streaming_tail=True)
        span_index = 0
        while span_index < len(spans):
            segment_start, segment_end = spans[span_index]
            next_index = span_index + 1
            while next_index < len(spans):
                candidate_end = spans[next_index][1]
                if (
                    metrics.horizontalAdvance(
                        source[segment_start:candidate_end]
                    )
                    > max_width
                ):
                    break
                segment_end = candidate_end
                next_index += 1

            starts.append(segment_start)
            segments.append(source[segment_start:segment_end])
            span_index = next_index

        self._sentences = segments
        self._segment_starts = starts
        if starts:
            # Keep the current window stable when a new stream chunk arrives;
            # after a resize, choose the window that contains its old start.
            index = 0
            for candidate, candidate_start in enumerate(starts):
                if candidate_start <= old_start:
                    index = candidate
                else:
                    break
            self._current_index = min(index, len(segments) - 1)
            self._current_sentence = segments[self._current_index]
            self._visible_characters = min(old_visible, len(self._current_sentence))
        else:
            self._current_index = 0
            self._current_sentence = ""
            self._visible_characters = 0

        if self._running and not self._timer.isActive() and self._sentences:
            self._begin_cycle()
        self.update()

    def _begin_cycle(self) -> None:
        if not self._running or not self._sentences:
            return
        self._current_sentence = self._sentences[self._current_index]
        self._visible_characters = 0
        if self._elapsed.isValid():
            self._elapsed.restart()
        else:
            self._elapsed.start()
        self._timer.start()
        self.update()

    def _advance(self) -> None:
        if not self._running or not self._sentences:
            self._timer.stop()
            return
        if not self._elapsed.isValid():
            self._elapsed.start()

        elapsed = self._elapsed.elapsed()
        if elapsed >= self.CYCLE_DURATION_MS:
            self._current_index = (self._current_index + 1) % len(self._sentences)
            self._begin_cycle()
            return

        if elapsed < self.TYPING_DURATION_MS:
            target_visible = min(
                len(self._current_sentence),
                int(
                    ceil(
                        len(self._current_sentence)
                        * elapsed
                        / self.TYPING_DURATION_MS
                    )
                ),
            )
            # A streaming update can extend the current width window while
            # its timer is already part-way through the typing phase.  Never
            # retract characters that were already painted in that case.
            visible = max(self._visible_characters, target_visible)
        else:
            visible = len(self._current_sentence)
        if visible != self._visible_characters:
            self._visible_characters = visible
            self.update()

    def paintEvent(self, event) -> None:
        del event
        if not self._current_sentence:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setClipRect(self.rect())
        metrics = QFontMetricsF(self.font())
        baseline = (self.height() - metrics.height()) / 2 + metrics.ascent()
        painter.setPen(self._text_color)
        painter.drawText(QPointF(0, baseline), self.visible_text)

        full_width = metrics.horizontalAdvance(self._current_sentence)
        visible_width = metrics.horizontalAdvance(self.visible_text)
        if full_width > self.width() and visible_width > self.width():
            fade_width = min(
                self.FADE_WIDTH,
                max(12, self.width() // 5),
            )
            fade_start = max(0, self.width() - fade_width)
            transparent = QColor(self._background_color)
            transparent.setAlpha(0)
            opaque = QColor(self._background_color)
            gradient = QLinearGradient(
                float(fade_start),
                0.0,
                float(self.width()),
                0.0,
            )
            gradient.setColorAt(0.0, transparent)
            gradient.setColorAt(1.0, opaque)
            painter.fillRect(
                QRectF(fade_start, 0, self.width() - fade_start, self.height()),
                gradient,
            )
        painter.end()

    def sizeHint(self) -> QSize:
        return QSize(120, 20)


class ReasoningPanel(QFrame):
    heightChanged = Signal()

    THINKING_PHASE = "thinking"
    SEARCHING_PHASE = "searching"
    _RUNNING_LABELS = {
        THINKING_PHASE: "正在深度思考",
        SEARCHING_PHASE: "正在联网搜索",
    }

    def __init__(
        self,
        reasoning: str = "",
        running: bool = False,
        theme: str = "light",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("reasoningPanel")
        self._theme = theme
        self._reasoning = reasoning
        self._rendered_reasoning: str | None = None
        self._running = False
        self._phase = self.THINKING_PHASE

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.indicator = ThinkingIndicator(theme)
        header.addWidget(self.indicator)
        self.toggle = QToolButton()
        self.toggle.setObjectName("reasonToggle")
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.toggled.connect(self._toggle_reasoning)
        header.addWidget(self.toggle)
        self.preview = ThinkingPreview(theme)
        header.addWidget(self.preview, 1)
        layout.addLayout(header)

        self.reasoning_view = RichText()
        self.reasoning_view.heightChanged.connect(self.heightChanged)
        self.reasoning_view.hide()
        layout.addWidget(self.reasoning_view)
        self.set_reasoning(reasoning)
        self.set_running(running)
        self.apply_theme(theme)

    def set_reasoning(self, reasoning: str) -> None:
        self._reasoning = reasoning
        self.preview.set_reasoning(reasoning)
        if reasoning == self._rendered_reasoning:
            return
        self.reasoning_view.set_html(
            to_html(reasoning, dark=self._theme == "dark")
        )
        self._rendered_reasoning = reasoning

    def set_running(self, running: bool) -> None:
        self._running = running
        if running:
            self.indicator.start()
            self.toggle.setText(self._RUNNING_LABELS[self._phase])
            self.preview.start()
            self.preview.show()
        else:
            self.indicator.stop()
            self.toggle.setText("已完成深度思考")
            self.preview.stop()
            # Keep the expanding preview slot in the header even when its
            # text is empty. Hiding that item makes QBoxLayout redistribute
            # the remaining controls around the center of the panel.
            self.preview.show()
        self._refresh_arrow()

    def set_running_label(self, text: str) -> None:
        """Keep the old string-based API while making the phase explicit."""

        phase = (
            self.SEARCHING_PHASE
            if str(text).strip().startswith("正在联网搜索")
            else self.THINKING_PHASE
        )
        self.set_phase(phase)

    def set_phase(self, phase: str) -> None:
        """Set the current running operation without changing completion state."""

        self._phase = (
            phase if phase in self._RUNNING_LABELS else self.THINKING_PHASE
        )
        if self._running:
            self.toggle.setText(self._RUNNING_LABELS[self._phase])

    def _toggle_reasoning(self, checked: bool) -> None:
        self.reasoning_view.setVisible(checked and bool(self._reasoning))
        self._refresh_arrow()
        self.heightChanged.emit()

    def _refresh_arrow(self) -> None:
        palette = colors(self._theme)
        name = "chevron-down" if self.toggle.isChecked() else "chevron-right"
        apply_icon(self.toggle, name, palette["fg_sub"], 16)

    def apply_theme(self, theme: str) -> None:
        theme_changed = theme != self._theme
        self._theme = theme
        palette = colors(theme)
        self.indicator.set_theme(theme)
        self.preview.apply_theme(theme)
        if theme_changed:
            self._rendered_reasoning = None
            self.set_reasoning(self._reasoning)
        self.reasoning_view.setStyleSheet(
            f"background:transparent;color:{palette['fg_sub']};border:none;"
        )
        self._refresh_arrow()


class OpenImageLabel(QLabel):
    """Clickable image surface whose rounded image and border are composited."""

    def __init__(
        self,
        path: str,
        parent=None,
        size: int = IMAGE_THUMB_SIZE,
    ) -> None:
        super().__init__(parent)
        self._path = path
        self._size = size
        self._has_image = not QImage(path).isNull()
        self._fallback_text = "" if self._has_image else Path(path).name
        self._text_color = QColor()
        self._thumbnail = QPixmap()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("单击打开原图")
        self.apply_theme("light")

    def apply_theme(self, theme: str) -> None:
        palette = colors(theme)
        self._text_color = QColor(palette["fg_sub"])
        self._thumbnail = rounded_thumbnail(
            self._path,
            self._size,
            border_color=palette["border_strong"],
            background_color=palette["canvas"],
        )
        super().setPixmap(self._thumbnail)
        # The border is already part of _thumbnail.  A stylesheet border here
        # would be a second stroke and can cover its antialiased corners.
        self.setStyleSheet("background:transparent;border:none;")
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._thumbnail.isNull():
            painter.drawPixmap(0, 0, self._thumbnail)
        if self._fallback_text:
            painter.setPen(self._text_color)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._fallback_text,
            )
        painter.end()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _image_label(
    path: str,
    parent=None,
    size: int = IMAGE_THUMB_SIZE,
) -> OpenImageLabel:
    return OpenImageLabel(path, parent, size)


class MessageBubble(QWidget):
    role = "base"

    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._plain = ""
        self._disposed = False

    def plain_text(self) -> str:
        return self._plain

    def dispose(self) -> None:
        """Release expensive child surfaces before the bubble is deleted."""

        self._disposed = True

    def clear_selection(self) -> None:
        pass

    def apply_theme(self, theme: str) -> None:
        self._theme = theme


class UserBubble(MessageBubble):
    role = "user"

    def __init__(
        self,
        text: str,
        images: list[str] | None = None,
        theme: str = "light",
        parent=None,
    ) -> None:
        super().__init__(theme, parent)
        self._plain = text
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.addStretch()

        self.card = QFrame()
        self.card.setObjectName("userBubble")
        self.card.setMaximumWidth(MESSAGE_CONTENT_MAX_WIDTH + 28)
        self._preferred_card_width: int | None = None
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(8)

        image_paths = images or []
        self._image_labels: list[OpenImageLabel] = []
        if image_paths:
            image_grid = QGridLayout()
            image_grid.setContentsMargins(0, 0, 0, 0)
            image_grid.setHorizontalSpacing(7)
            image_grid.setVerticalSpacing(7)
            for index, image_path in enumerate(image_paths):
                image_label = _image_label(image_path)
                self._image_labels.append(image_label)
                image_grid.addWidget(
                    image_label,
                    index // IMAGE_GRID_COLUMNS,
                    index % IMAGE_GRID_COLUMNS,
                )
            card_layout.addLayout(image_grid)

        if text.strip():
            self.text_view = RichText()
            safe = html.escape(text).replace("\n", "<br>")
            self.text_view.set_html(f"<body><p>{safe}</p></body>")
            card_layout.addWidget(self.text_view)
            if not image_paths:
                metrics = QFontMetricsF(self.text_view._text_view.font())
                natural_width = max(
                    (metrics.horizontalAdvance(line) for line in text.split("\n")),
                    default=0.0,
                )
                content_width = max(
                    44,
                    min(MESSAGE_CONTENT_MAX_WIDTH, ceil(natural_width + 12)),
                )
                self._preferred_card_width = content_width + 28
                self.text_view.setFixedWidth(content_width)
                self.card.setFixedWidth(self._preferred_card_width)
        outer.addWidget(self.card)
        self.apply_theme(theme)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._preferred_card_width is not None:
            card_width = min(self._preferred_card_width, max(72, self.width()))
            self.card.setFixedWidth(card_width)
            self.text_view.setFixedWidth(card_width - 28)

    def apply_theme(self, theme: str) -> None:
        super().apply_theme(theme)
        palette = colors(theme)
        self.card.setStyleSheet(
            f"QFrame#userBubble{{background:{palette['user_bubble']};"
            f"border:none;border-radius:{CHAT_BUBBLE_RADIUS}px;"
            f"color:{palette['fg']};}}"
        )
        for image_label in self._image_labels:
            image_label.apply_theme(theme)
        if hasattr(self, "text_view"):
            self.text_view.setStyleSheet(
                f"background:transparent;color:{palette['fg']};border:none;"
            )

    def clear_selection(self) -> None:
        if hasattr(self, "text_view"):
            self.text_view.clear_selection()


class AssistantBubble(MessageBubble):
    role = "assistant"
    layoutHeightChanged = Signal()

    def __init__(
        self,
        content: str = "",
        reasoning: str = "",
        meta: str = "",
        thinking: bool = True,
        streaming: bool = False,
        theme: str = "light",
        parent=None,
    ) -> None:
        super().__init__(theme, parent)
        self._plain = content
        self._reasoning = reasoning
        self._streaming = streaming
        self._content_dirty = bool(content)
        self._operation_phase = ReasoningPanel.THINKING_PHASE

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 10, 24, 10)
        outer.setSpacing(11)
        self.avatar = QLabel()
        self.avatar.setFixedSize(28, 28)
        self.avatar.setPixmap(
            tint_pixmap(
                QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(28, 28),
                colors(theme)["fg"],
            )
        )
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(7)
        outer.addLayout(column, 1)

        if meta:
            self.meta_label = QLabel(meta)
            self.meta_label.setObjectName("metaLabel")
            self.meta_label.setStyleSheet("font-size:11px;")
            column.addWidget(self.meta_label)

        self.reasoning_panel: ReasoningPanel | None = None
        if thinking or reasoning:
            self.reasoning_panel = ReasoningPanel(
                reasoning,
                running=streaming,
                theme=theme,
            )
            self.reasoning_panel.heightChanged.connect(self.layoutHeightChanged)
            column.addWidget(self.reasoning_panel)

        self.status_row = QWidget()
        status_layout = QHBoxLayout(self.status_row)
        status_layout.setContentsMargins(2, 2, 0, 2)
        status_layout.setSpacing(7)
        self.status_indicator = ThinkingIndicator(theme)
        self.status_label = QLabel("正在生成")
        self.status_label.setObjectName("hintLabel")
        status_layout.addWidget(self.status_indicator)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        column.addWidget(self.status_row)

        self.content_view = RichText()
        self.content_view.set_theme(theme == "dark")
        self.content_view.heightChanged.connect(self.layoutHeightChanged)
        self.content_view.revealFinished.connect(self._on_reveal_finished)
        self.content_view.setVisible(bool(content))
        column.addWidget(self.content_view)

        self.actions = QWidget()
        action_layout = QHBoxLayout(self.actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)
        self.copy_button = QToolButton()
        self.copy_button.setToolTip("复制回答")
        self.copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self._plain)
        )
        action_layout.addWidget(self.copy_button)
        self.completion_label = QLabel()
        self.completion_label.setObjectName("tinyLabel")
        action_layout.addWidget(self.completion_label)
        action_layout.addStretch()
        self.actions.setVisible(bool(content) and not streaming)
        column.addWidget(self.actions)

        self._reasoning_timer = QTimer(self)
        self._reasoning_timer.setSingleShot(True)
        self._reasoning_timer.setInterval(80)
        self._reasoning_timer.timeout.connect(self._render_reasoning)

        if content:
            if streaming:
                self.content_view.begin_stream()
                self.content_view.stream_text(content)
            else:
                self._render_content()
        if streaming and not thinking:
            self.status_indicator.start()
            self.status_row.show()
        else:
            self.status_row.hide()
        self.apply_theme(theme)

    def dispose(self) -> None:
        """Stop timers and retire any embedded WebEngine renderers."""

        if self._disposed:
            return
        self._disposed = True
        self._reasoning_timer.stop()
        self.status_indicator.stop()
        if self.reasoning_panel is not None:
            self.reasoning_panel.indicator.stop()
            self.reasoning_panel.preview.stop()
            self.reasoning_panel.reasoning_view.dispose()
        self.content_view.dispose()

    def clear_selection(self) -> None:
        self.content_view.clear_selection()
        if self.reasoning_panel is not None:
            self.reasoning_panel.reasoning_view.clear_selection()

    def set_status(self, text: str) -> None:
        if self._disposed or not self._streaming:
            return
        self._operation_phase = (
            ReasoningPanel.SEARCHING_PHASE
            if str(text).strip().startswith("正在联网搜索")
            else ReasoningPanel.THINKING_PHASE
        )
        if self.reasoning_panel is not None:
            # A tool-call preamble may already have caused begin_answer() to
            # stop the panel. Every status event is a fresh operation phase,
            # so explicitly restart the running state here.
            self.reasoning_panel.set_phase(self._operation_phase)
            self.reasoning_panel.set_running(True)
            if self.status_row.isVisible():
                self.status_row.hide()
                self.layoutHeightChanged.emit()
            return

        # Standard mode has no reasoning content, but a web-search request
        # still needs to expose what the worker is doing.
        label = (
            "正在联网搜索"
            if self._operation_phase == ReasoningPanel.SEARCHING_PHASE
            else "正在生成"
        )
        self.status_label.setText(label)
        self.status_indicator.start()
        was_visible = self.status_row.isVisible()
        self.status_row.show()
        if not was_visible:
            self.layoutHeightChanged.emit()

    def set_reasoning(self, reasoning: str) -> None:
        if self._disposed:
            return
        self._reasoning = reasoning
        if self.reasoning_panel is None:
            self.reasoning_panel = ReasoningPanel(
                reasoning,
                running=self._streaming,
                theme=self._theme,
            )
            self.reasoning_panel.set_phase(self._operation_phase)
            self.reasoning_panel.heightChanged.connect(self.layoutHeightChanged)
            layout = self.layout().itemAt(1).layout()
            insert_at = layout.indexOf(self.status_row)
            layout.insertWidget(insert_at, self.reasoning_panel)
            if self.status_row.isVisible():
                self.status_row.hide()
                self.layoutHeightChanged.emit()
        if not self._reasoning_timer.isActive():
            self._reasoning_timer.start()

    def _render_reasoning(self) -> None:
        if not self._disposed and self.reasoning_panel:
            self.reasoning_panel.set_reasoning(self._reasoning)

    def begin_answer(self) -> None:
        if self._disposed:
            return
        if self.reasoning_panel:
            self.reasoning_panel.set_running(False)
        self.status_indicator.stop()
        was_visible = self.status_row.isVisible()
        self.status_row.hide()
        self.content_view.show()
        if was_visible:
            self.layoutHeightChanged.emit()

    def set_content(self, content: str) -> None:
        """Buffer model output; the reveal reads it back out on its own."""

        if self._disposed:
            return
        self._plain = content
        self._content_dirty = True
        self.begin_answer()
        if not self._streaming:
            self._render_content()
            return
        self.content_view.stream_text(content)

    def _render_content(self) -> None:
        """Paint a finished (or history) body in one pass."""

        if self._disposed or not self._content_dirty:
            return
        self._content_dirty = False
        self.content_view.set_html(
            to_html(self._plain, dark=self._theme == "dark"),
        )
        self.content_view.setVisible(bool(self._plain))
        self.actions.setVisible(bool(self._plain))

    @Slot()
    def _on_reveal_finished(self) -> None:
        """The newest text has fully emerged; expose the message actions."""

        if self._disposed:
            return
        self.content_view.setVisible(bool(self._plain))
        self.actions.setVisible(bool(self._plain))
        self.layoutHeightChanged.emit()

    def finish(self, stopped: bool = False) -> None:
        if self._disposed:
            return
        self._streaming = False
        self._reasoning_timer.stop()
        self._render_reasoning()
        self.content_view.complete_stream()
        if self.reasoning_panel:
            self.reasoning_panel.set_running(False)
        self.status_indicator.stop()
        self.status_row.hide()
        self.content_view.setVisible(bool(self._plain))
        self.completion_label.setText("已停止" if stopped else "")
        if not self.content_view.is_revealing:
            self.actions.setVisible(bool(self._plain))

    def fail(self, message: str) -> None:
        if self._disposed:
            return
        self.finish()
        self.completion_label.setText(message)
        self.completion_label.setStyleSheet(
            f"color:{colors(self._theme)['danger']};font-size:11px;"
        )
        self.actions.show()

    def apply_theme(self, theme: str) -> None:
        if self._disposed:
            return
        theme_changed = theme != self._theme
        super().apply_theme(theme)
        palette = colors(theme)
        self.avatar.setPixmap(
            tint_pixmap(
                QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(28, 28),
                palette["fg"],
            )
        )
        self.status_indicator.set_theme(theme)
        self.content_view.set_theme(theme == "dark")
        self.content_view.setStyleSheet(
            f"background:transparent;color:{palette['fg']};border:none;"
        )
        if self._plain and theme_changed:
            self._content_dirty = True
            if self._streaming:
                revealed = int(
                    self.content_view.revealed_fraction * len(self._plain)
                )
                self.content_view.set_html(
                    to_html(self._plain, dark=theme == "dark"),
                    reveal_characters=revealed,
                    reveal_total_characters=len(self._plain),
                )
            else:
                self._render_content()
        if self.reasoning_panel:
            self.reasoning_panel.apply_theme(theme)
        apply_icon(self.copy_button, "copy", palette["fg_sub"], 17)


class ErrorBubble(MessageBubble):
    role = "error"

    def __init__(self, text: str, theme: str = "light", parent=None) -> None:
        super().__init__(theme, parent)
        self._plain = text
        outer = QHBoxLayout(self)
        outer.setContentsMargins(39, 8, 24, 8)
        self.card = QFrame()
        self.card.setObjectName("errorCard")
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(12, 9, 12, 9)
        title = QLabel("请求没有完成")
        title.setStyleSheet("font-weight:600;")
        self.message = QLabel(text)
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(title)
        layout.addWidget(self.message)
        outer.addWidget(self.card, 1)
        self.apply_theme(theme)

    def apply_theme(self, theme: str) -> None:
        super().apply_theme(theme)
        palette = colors(theme)
        self.message.setStyleSheet(f"color:{palette['danger']};")


class ChatView(QScrollArea):
    followChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._theme = "light"
        self._bubbles: list[MessageBubble] = []
        self._last_bubble_width: int | None = None
        self._follow_output = True
        self._programmatic_scroll = False
        self._layout_transition_active = False
        self._catch_up_active = False
        self._catch_up_start = 0
        self._catch_up_duration = 0
        self._follow_maximum = 0
        self._catch_up_clock = QElapsedTimer()
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(16)
        self._scroll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._scroll_timer.timeout.connect(self._advance_follow_scroll)
        self._selection_drag_source: MessageTextBrowser | _MathWebView | None = None
        self._selection_drag_pos = QPoint()
        self._selection_drag_moved = False
        self._selection_scroll_timer = QTimer(self)
        self._selection_scroll_timer.setInterval(30)
        self._selection_scroll_timer.timeout.connect(self._scroll_during_selection)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)
        self.viewport().installEventFilter(self)
        self.verticalScrollBar().installEventFilter(self)

        self.container = QWidget()
        self.container.setObjectName("messageContainer")
        self.messages = QVBoxLayout(self.container)
        self.messages.setContentsMargins(24, 18, 24, 18)
        self.messages.setSpacing(4)
        self.messages.addStretch()
        self.setWidget(self.container)
        self.viewport().setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.container.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.container.installEventFilter(self)
        self.apply_theme("light")

    def clear(self) -> None:
        self._stop_selection_drag()
        self._scroll_timer.stop()
        self._catch_up_active = False
        self._follow_maximum = 0
        for bubble in self._bubbles:
            self.messages.removeWidget(bubble)
            bubble.dispose()
            bubble.deleteLater()
        self._bubbles.clear()
        self._last_bubble_width = None
        self._set_follow_output(True)

    def dispose(self) -> None:
        """Retire message renderers before the top-level window is destroyed."""

        self.clear()

    def _add(self, bubble: MessageBubble) -> MessageBubble:
        self._bubbles.append(bubble)
        bubble.apply_theme(self._theme)
        self._apply_size(bubble)
        self.messages.insertWidget(
            self.messages.count() - 1,
            bubble,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        if isinstance(bubble, AssistantBubble):
            bubble.layoutHeightChanged.connect(
                lambda current=bubble: (
                    self.message_updated(current)
                    if current in self._bubbles
                    else None
                )
            )
        self.scroll_to_bottom(force=True)
        return bubble

    def add_user(self, text: str, images: list[str] | None = None) -> UserBubble:
        return self._add(UserBubble(text, images, self._theme))

    def add_assistant(
        self,
        content: str,
        reasoning: str = "",
        meta: str = "",
        thinking: bool = True,
        stopped: bool = False,
    ) -> AssistantBubble:
        bubble = AssistantBubble(
            content,
            reasoning,
            meta,
            thinking=thinking,
            streaming=False,
            theme=self._theme,
        )
        self._add(bubble)
        bubble.finish(stopped)
        return bubble

    def add_streaming(self, meta: str, thinking: bool) -> AssistantBubble:
        return self._add(
            AssistantBubble(
                meta=meta,
                thinking=thinking,
                streaming=True,
                theme=self._theme,
            )
        )

    def add_error(self, text: str) -> ErrorBubble:
        return self._add(ErrorBubble(text, self._theme))

    def remove_bubble(self, bubble: MessageBubble) -> None:
        if bubble in self._bubbles:
            source = self._selection_drag_source
            if source is not None and (source is bubble or bubble.isAncestorOf(source)):
                self._stop_selection_drag()
            self._bubbles.remove(bubble)
            self.messages.removeWidget(bubble)
            bubble.dispose()
            bubble.deleteLater()

    def message_updated(self, bubble: MessageBubble) -> None:
        self._apply_size(bubble)
        self.scroll_to_bottom()

    def _apply_size(self, bubble: MessageBubble) -> None:
        width = min(LANE_MAX_WIDTH, max(420, self.viewport().width() - 56))
        if width != self._last_bubble_width:
            for current in self._bubbles:
                current.setFixedWidth(width)
            self._last_bubble_width = width
        elif bubble.width() != width:
            bubble.setFixedWidth(width)

    def set_bottom_inset(self, inset: int) -> None:
        """Leave trailing space below the final message."""

        left, top, right, _bottom = self.messages.getContentsMargins()
        bottom = max(18, int(inset))
        if bottom == _bottom:
            return
        self.messages.setContentsMargins(left, top, right, bottom)
        self.scroll_to_bottom()

    def set_composer_clearance(self, clearance: int) -> None:
        """Reserve a viewport lane for the bottom composer."""

        bottom = max(0, int(clearance))
        margins = self.viewportMargins()
        if margins.bottom() == bottom:
            return
        self.setViewportMargins(
            margins.left(),
            margins.top(),
            margins.right(),
            bottom,
        )
        self.scroll_to_bottom()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._layout_transition_active:
            for bubble in self._bubbles:
                self._apply_size(bubble)
        self.scroll_to_bottom()

    def set_layout_transition_active(self, active: bool) -> None:
        """Reflow rich messages once after a sidebar width transition."""

        active = bool(active)
        if active == self._layout_transition_active:
            return
        self._layout_transition_active = active
        if not active:
            self._last_bubble_width = None
            for bubble in self._bubbles:
                self._apply_size(bubble)
            self.scroll_to_bottom()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        self.setStyleSheet(
            f"QScrollArea{{background:{palette['canvas']};border:none;}}"
            f"QWidget#messageContainer{{background:{palette['canvas']};}}"
        )
        for bubble in self._bubbles:
            bubble.apply_theme(theme)

    @property
    def follows_output(self) -> bool:
        return self._follow_output

    def _set_follow_output(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._follow_output:
            return
        self._follow_output = enabled
        if not enabled:
            self._scroll_timer.stop()
            self._catch_up_active = False
        self.followChanged.emit(enabled)

    def pause_follow(self) -> None:
        """Pause streaming auto-scroll after a user navigates upward."""

        if self._bubbles:
            self._set_follow_output(False)

    def resume_follow(self) -> None:
        """Resume auto-scroll and reveal the newest generated content."""

        self._set_follow_output(True)
        bar = self.verticalScrollBar()
        distance = bar.maximum() - bar.value()
        if distance <= 0:
            return
        self._catch_up_active = True
        self._catch_up_start = bar.value()
        self._follow_maximum = bar.maximum()
        self._catch_up_duration = min(650, max(260, round(260 + distance ** 0.5 * 4)))
        self._catch_up_clock.start()
        self._scroll_timer.start()

    def _on_scroll_value_changed(self, value: int) -> None:
        if self._programmatic_scroll:
            return
        bar = self.verticalScrollBar()
        maximum = bar.maximum()
        if maximum <= 0:
            return
        if maximum - value > 10:
            self._set_follow_output(False)

    def eventFilter(self, watched, event) -> bool:
        container = getattr(self, "container", None)
        if (
            (watched is self.viewport() or watched is container)
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._clear_active_selection()
        if watched is self.viewport() and event.type() == QEvent.Type.Wheel:
            self.pause_follow()
        elif watched is self.verticalScrollBar():
            if event.type() == QEvent.Type.MouseButtonPress:
                self.pause_follow()
            elif event.type() == QEvent.Type.MouseMove and event.buttons():
                self.pause_follow()
        return super().eventFilter(watched, event)

    def _clear_active_selection(self) -> None:
        focused = QApplication.focusWidget()
        if isinstance(focused, (MessageTextBrowser, _MathWebView)):
            focused.clear_selection()

    def _start_selection_drag(
        self, source: MessageTextBrowser | _MathWebView, global_pos: QPoint
    ) -> None:
        self._selection_drag_source = source
        self._selection_drag_pos = global_pos
        self._selection_drag_moved = False
        self._selection_scroll_timer.start()

    def _move_selection_drag(
        self, source: MessageTextBrowser | _MathWebView, global_pos: QPoint
    ) -> None:
        if source is not self._selection_drag_source:
            return
        if global_pos != self._selection_drag_pos:
            self._selection_drag_moved = True
            self._selection_drag_pos = global_pos

    def _stop_selection_drag(
        self, source: MessageTextBrowser | _MathWebView | None = None
    ) -> None:
        if source is not None and source is not self._selection_drag_source:
            return
        self._selection_scroll_timer.stop()
        self._selection_drag_source = None
        self._selection_drag_moved = False

    def _scroll_during_selection(self) -> None:
        source = self._selection_drag_source
        if source is None or not (
            QApplication.mouseButtons() & Qt.MouseButton.LeftButton
        ):
            self._stop_selection_drag()
            return
        if not self._selection_drag_moved:
            return

        point = self.viewport().mapFromGlobal(self._selection_drag_pos)
        edge = 36
        if point.y() < edge:
            direction = -1
            distance = edge - point.y()
        elif point.y() > self.viewport().height() - edge:
            direction = 1
            distance = point.y() - (self.viewport().height() - edge)
        else:
            return

        step = direction * min(80, max(5, round(distance * 1.2)))
        bar = self.verticalScrollBar()
        before = bar.value()
        self.pause_follow()
        bar.setValue(before + step)
        if isinstance(source, MessageTextBrowser):
            source._extend_selection_drag(self._selection_drag_pos)
        elif isinstance(source, _MathWebView):
            top = source.mapTo(self.viewport(), QPoint()).y()
            visible = top < self.viewport().height() and top + source.height() > 0
            inside = step if visible and bar.value() == before else 0
            source._extend_selection_drag(inside, self._selection_drag_pos)

    def wheelEvent(self, event) -> None:
        self.pause_follow()
        super().wheelEvent(event)

    def scroll_to_bottom(self, force: bool = False) -> None:
        if force:
            self._set_follow_output(True)
            self._follow_maximum = self.verticalScrollBar().maximum()
        if not self._follow_output:
            return
        if not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def _advance_follow_scroll(self) -> None:
        if not self._follow_output:
            self._scroll_timer.stop()
            return
        bar = self.verticalScrollBar()
        maximum = bar.maximum()
        current = bar.value()
        growth = max(0, maximum - self._follow_maximum)
        self._follow_maximum = maximum
        if self._catch_up_active:
            progress = min(1.0, self._catch_up_clock.elapsed() / self._catch_up_duration)
            eased = progress * progress * (3.0 - 2.0 * progress)
            target = round(self._catch_up_start + (maximum - self._catch_up_start) * eased)
            if progress >= 1.0:
                self._catch_up_active = False
        else:
            distance = maximum - current
            # While the answer keeps growing the lane has to move at least as
            # fast as the content does, so the newest text stays pinned to the
            # bottom of the viewport instead of sliding out of sight.
            step = max(growth, min(140, max(1, ceil(distance * 0.42))))
            target = current + step
        self._programmatic_scroll = True
        try:
            bar.setValue(min(maximum, target))
        finally:
            self._programmatic_scroll = False
        if (
            not self._catch_up_active
            and growth <= 0
            and bar.value() >= bar.maximum()
        ):
            self._scroll_timer.stop()

from __future__ import annotations

import html
import json
from math import ceil, cos, pi, sin
from pathlib import Path

from PySide6.QtCore import (
    QElapsedTimer,
    QEvent,
    QObject,
    QPointF,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
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
    QStackedLayout,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import ASSETS_DIR
from ..markdown import to_html
from .controls import RoundedMenu
from .icons import apply_icon, tint_pixmap
from .theme import colors


IMAGE_MAX_HEIGHT = 180
IMAGE_MAX_WIDTH = 250
LANE_MAX_WIDTH = 840
KATEX_DIR = ASSETS_DIR / "vendor" / "katex"


_MATH_WEB_SHELL = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="katex.min.css">
  <style>
    html, body {
      box-sizing: border-box;
      width: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: transparent;
    }
    #content-root {
      display: flow-root;
      box-sizing: border-box;
      width: 100%;
      min-height: 1px;
      margin: 0;
      padding: 0;
      background: transparent;
    }
  </style>
</head>
<body>
  <main id="content-root"></main>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script src="katex.min.js"></script>
  <script>
    (() => {
      const root = document.getElementById("content-root");
      let bridge = null;

      const measuredHeight = () => Math.max(
        1,
        Math.ceil(root.getBoundingClientRect().height)
      );

      const refreshOverflow = () => {
        root.querySelectorAll(".math-display-shell").forEach((shell) => {
          const overflowing = shell.scrollWidth > shell.clientWidth + 2;
          shell.classList.toggle("is-overflowing", overflowing);
          shell.setAttribute("data-overflowing", overflowing ? "true" : "false");
          shell.setAttribute("tabindex", overflowing ? "0" : "-1");
          shell.setAttribute(
            "aria-label",
            overflowing ? "数学公式，可横向滚动查看完整内容" : "数学公式"
          );
        });
        root.querySelectorAll(".math-inline").forEach((inline) => {
          const overflowing = inline.scrollWidth > inline.clientWidth + 4;
          inline.classList.toggle("is-overflowing", overflowing);
          inline.setAttribute("tabindex", overflowing ? "0" : "-1");
        });
      };

      const reportLayout = () => {
        refreshOverflow();
        const height = measuredHeight();
        if (bridge) bridge.reportHeight(height);
        return height;
      };

      const renderFormulas = () => {
        root.querySelectorAll("[data-tex]").forEach((node) => {
          const expression = node.getAttribute("data-tex") || "";
          try {
            if (typeof katex === "undefined") {
              throw new Error("KaTeX is unavailable");
            }
            katex.render(expression, node, {
              displayMode: node.getAttribute("data-display") === "true",
              output: "htmlAndMathml",
              throwOnError: false,
              strict: "ignore",
              trust: false,
              maxSize: 12,
              maxExpand: 1000
            });
          } catch (error) {
            node.classList.add("katex-error");
            node.textContent = expression;
          }
        });
      };

      window.setDeepSeekContent = (markup) => {
        root.innerHTML = markup;
        renderFormulas();
        reportLayout();
        requestAnimationFrame(reportLayout);
        if (document.fonts && document.fonts.ready) {
          document.fonts.ready.then(reportLayout);
        }
        return measuredHeight();
      };
      window.refreshDeepSeekLayout = reportLayout;

      document.addEventListener("click", (event) => {
        const button = event.target instanceof Element
          ? event.target.closest(".code-copy")
          : null;
        if (!button) return;
        const block = button.closest(".code-block");
        const code = block ? block.querySelector("pre code") : null;
        if (!code || !bridge) return;
        bridge.copyText(code.textContent || "");
        button.textContent = "已复制";
        button.classList.add("is-copied");
        window.setTimeout(() => {
          button.textContent = "复制";
          button.classList.remove("is-copied");
        }, 1400);
      });

      if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {
        new QWebChannel(qt.webChannelTransport, (channel) => {
          bridge = channel.objects.mathBridge;
          reportLayout();
        });
      }

      new ResizeObserver(() => requestAnimationFrame(reportLayout)).observe(root);
      document.addEventListener("wheel", (event) => {
        const horizontalRegion = event.target instanceof Element
          ? event.target.closest(
              ".math-display-shell, .math-inline.is-overflowing"
            )
          : null;
        if (horizontalRegion && event.shiftKey && event.deltaY !== 0) {
          horizontalRegion.scrollLeft += event.deltaY;
          event.preventDefault();
          return;
        }
        if (!bridge || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
        bridge.scrollVertically(event.deltaY);
        event.preventDefault();
      }, { passive: false });
    })();
  </script>
</body>
</html>
"""


class _MathPage(QWebEnginePage):
    """Keep generated content local and hand user-clicked links to the OS."""

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame) -> bool:
        if navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            if url.scheme().lower() in {"http", "https", "mailto"}:
                QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class _MathBridge(QObject):
    heightReported = Signal(int)
    verticalScrollRequested = Signal(float)
    copyRequested = Signal(str)

    @Slot(float)
    def reportHeight(self, height: float) -> None:
        self.heightReported.emit(max(1, round(height)))

    @Slot(float)
    def scrollVertically(self, delta: float) -> None:
        self.verticalScrollRequested.emit(delta)

    @Slot(str)
    def copyText(self, text: str) -> None:
        self.copyRequested.emit(text)


class _MathWebView(QWebEngineView):
    contentHeightChanged = Signal(int)
    contentRendered = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("skipCustomTooltipScan", True)
        self._ready = False
        self._pending_html = ""
        self._generation = 0
        self._rendered_generation = -1
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(22)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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
        self._bridge.heightReported.connect(self._apply_content_height)
        self._bridge.verticalScrollRequested.connect(self._forward_vertical_scroll)
        self._bridge.copyRequested.connect(
            lambda text: QApplication.clipboard().setText(text)
        )
        self._channel = QWebChannel(page)
        self._channel.registerObject("mathBridge", self._bridge)
        page.setWebChannel(self._channel)
        self.loadFinished.connect(self._on_load_finished)

        base_url = QUrl.fromLocalFile(f"{KATEX_DIR.resolve()}/")
        self.setHtml(_MATH_WEB_SHELL, base_url)

    def set_content(self, body: str) -> None:
        self._pending_html = body
        self._generation += 1
        if self._ready:
            self._render_pending_content()

    def _on_load_finished(self, succeeded: bool) -> None:
        self._ready = succeeded
        if succeeded:
            self._render_pending_content()

    def _render_pending_content(self) -> None:
        generation = self._generation
        payload = json.dumps(self._pending_html)
        script = f"window.setDeepSeekContent({payload})"
        self.page().runJavaScript(
            script,
            lambda height, current=generation: self._content_applied(current, height),
        )

    def _content_applied(self, generation: int, height) -> None:
        if generation != self._generation:
            return
        if isinstance(height, (int, float)):
            self._apply_content_height(round(height))
        if self._rendered_generation != generation:
            self._rendered_generation = generation
            self.contentRendered.emit()

    @Slot(int)
    def _apply_content_height(self, height: int) -> None:
        height = max(22, min(int(height) + 1, 100_000))
        if abs(self.height() - height) > 1:
            self.setFixedHeight(height)
            self.contentHeightChanged.emit(height)

    @Slot(float)
    def _forward_vertical_scroll(self, delta: float) -> None:
        ancestor = self.parentWidget()
        while ancestor is not None and not isinstance(ancestor, QAbstractScrollArea):
            ancestor = ancestor.parentWidget()
        if ancestor is None:
            return
        scroll_bar = ancestor.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.value() + round(delta))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._ready:
            self.page().runJavaScript("window.refreshDeepSeekLayout()")


class RichText(QWidget):
    """Fast QTextBrowser for ordinary text, KaTeX web layout only when needed."""

    heightChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._html = ""
        self._uses_math = False
        self._web_view: _MathWebView | None = None

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._text_view = QTextBrowser()
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
        self._stack.addWidget(self._text_view)

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit_text_height)
        self._text_view.document().contentsChanged.connect(self._schedule_fit)

    def document(self) -> QTextDocument:
        """Retain the former QTextBrowser API for non-math callers and tests."""

        return self._text_view.document()

    def set_html(self, body: str) -> None:
        self._html = body
        # Math and code blocks both benefit from the local WebEngine renderer:
        # KaTeX needs DOM layout, while code blocks use a real copy button and
        # the same WebChannel clipboard bridge.
        self._uses_math = "data-tex=" in body or "data-code-block=" in body
        self._text_view.setHtml(body)
        if self._uses_math:
            self._ensure_web_view().set_content(body)
        else:
            self._stack.setCurrentWidget(self._text_view)
            self._schedule_fit()

    def _ensure_web_view(self) -> _MathWebView:
        if self._web_view is None:
            self._web_view = _MathWebView()
            self._web_view.contentRendered.connect(self._show_rendered_math)
            self._web_view.contentHeightChanged.connect(self._fit_web_height)
            self._stack.addWidget(self._web_view)
        return self._web_view

    def _show_rendered_math(self) -> None:
        if not self._uses_math or self._web_view is None:
            return
        self._stack.setCurrentWidget(self._web_view)
        self._fit_web_height(self._web_view.height())

    @Slot(int)
    def _fit_web_height(self, height: int) -> None:
        if not self._uses_math or self._web_view is None:
            return
        self._set_content_height(height)

    def _schedule_fit(self) -> None:
        if not self._uses_math:
            self._fit_timer.start()

    def _fit_text_height(self) -> None:
        if self._uses_math:
            return
        width = max(40, self._text_view.viewport().width())
        self._text_view.document().setTextWidth(width)
        height = max(22, int(self._text_view.document().size().height() + 3))
        self._set_content_height(height)

    def _set_content_height(self, height: int) -> None:
        if abs(self.height() - height) > 1:
            self.setFixedHeight(height)
            self.heightChanged.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_fit()


class ThinkingIndicator(QWidget):
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
            center = QPointF(10, 10)
            for index in range(3):
                angle = (self._angle - index * 95) * pi / 180
                point = QPointF(
                    center.x() + cos(angle) * 5.4,
                    center.y() + sin(angle) * 5.4,
                )
                dot = QColor(accent)
                dot.setAlpha(255 - index * 65)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(dot)
                painter.drawEllipse(point, 2.1 - index * 0.25, 2.1 - index * 0.25)
        else:
            painter.setPen(accent)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(10, 3), QPointF(10, 17))
            painter.drawLine(QPointF(3, 10), QPointF(17, 10))
            painter.drawLine(QPointF(5.2, 5.2), QPointF(14.8, 14.8))
            painter.drawLine(QPointF(14.8, 5.2), QPointF(5.2, 14.8))
        painter.end()


class ReasoningPanel(QFrame):
    heightChanged = Signal()

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
        header.addStretch()
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
        self.reasoning_view.set_html(
            to_html(reasoning, dark=self._theme == "dark")
        )

    def set_running(self, running: bool) -> None:
        if running:
            self.indicator.start()
            self.toggle.setText("正在深度思考")
        else:
            self.indicator.stop()
            self.toggle.setText("已完成深度思考")
        self._refresh_arrow()

    def _toggle_reasoning(self, checked: bool) -> None:
        self.reasoning_view.setVisible(checked and bool(self._reasoning))
        self._refresh_arrow()
        self.heightChanged.emit()

    def _refresh_arrow(self) -> None:
        palette = colors(self._theme)
        name = "chevron-down" if self.toggle.isChecked() else "chevron-right"
        apply_icon(self.toggle, name, palette["fg_sub"], 16)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        self.indicator.set_theme(theme)
        self.reasoning_view.set_html(
            to_html(self._reasoning, dark=theme == "dark")
        )
        self.reasoning_view.setStyleSheet(
            f"background:transparent;color:{palette['fg_sub']};border:none;"
        )
        self._refresh_arrow()


class OpenImageLabel(QLabel):
    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self._path = path

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))
        super().mouseDoubleClickEvent(event)


def _image_label(path: str, parent=None) -> QLabel:
    label = OpenImageLabel(path, parent)
    image = QImage(path)
    if image.isNull():
        label.setText(Path(path).name)
        return label
    image = image.scaled(
        IMAGE_MAX_WIDTH,
        IMAGE_MAX_HEIGHT,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    label.setPixmap(QPixmap.fromImage(image))
    label.setFixedSize(image.size())
    label.setCursor(Qt.CursorShape.PointingHandCursor)
    label.setToolTip("双击打开原图")
    return label


class MessageBubble(QWidget):
    role = "base"

    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._plain = ""

    def plain_text(self) -> str:
        return self._plain

    def apply_theme(self, theme: str) -> None:
        self._theme = theme

    def contextMenuEvent(self, event) -> None:
        menu = RoundedMenu(self._theme, self)
        copy_action = menu.addAction("复制内容")
        copy_action.setEnabled(bool(self._plain.strip()))
        if menu.exec(event.globalPos()) is copy_action:
            QApplication.clipboard().setText(self._plain)


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
        outer.setContentsMargins(42, 8, 0, 8)
        outer.addStretch()

        self.card = QFrame()
        self.card.setObjectName("userBubble")
        self.card.setMaximumWidth(680)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(8)

        image_paths = images or []
        if image_paths:
            image_grid = QGridLayout()
            image_grid.setHorizontalSpacing(7)
            image_grid.setVerticalSpacing(7)
            for index, image_path in enumerate(image_paths[:4]):
                image_grid.addWidget(_image_label(image_path), index // 2, index % 2)
            if len(image_paths) > 4:
                image_grid.addWidget(QLabel(f"另有 {len(image_paths) - 4} 张"), 2, 0)
            card_layout.addLayout(image_grid)

        if text.strip():
            self.text_view = RichText()
            safe = html.escape(text).replace("\n", "<br>")
            self.text_view.set_html(f"<body><p>{safe}</p></body>")
            card_layout.addWidget(self.text_view)
            if not image_paths:
                natural_document = QTextDocument()
                natural_document.setDefaultFont(self.text_view.font())
                natural_document.setDocumentMargin(0)
                natural_document.setPlainText(text)
                natural_document.setTextWidth(-1)
                content_width = max(
                    44,
                    min(652, ceil(natural_document.idealWidth() + 3)),
                )
                self.text_view.setFixedWidth(content_width)
                self.card.setFixedWidth(content_width + 28)
        outer.addWidget(self.card)
        self.apply_theme(theme)

    def apply_theme(self, theme: str) -> None:
        super().apply_theme(theme)
        palette = colors(theme)
        self.card.setStyleSheet(
            f"QFrame#userBubble{{background:{palette['user_bubble']};"
            f"border:none;border-radius:14px;color:{palette['fg']};}}"
        )
        if hasattr(self, "text_view"):
            self.text_view.setStyleSheet(
                f"background:transparent;color:{palette['fg']};border:none;"
            )


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
        self.content_view.heightChanged.connect(self.layoutHeightChanged)
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

        # 合并高频 token 更新，减少富文本重排和闪烁。
        self._content_timer = QTimer(self)
        self._content_timer.setSingleShot(True)
        self._content_timer.setInterval(35)
        self._content_timer.timeout.connect(self._render_content)
        self._reasoning_timer = QTimer(self)
        self._reasoning_timer.setSingleShot(True)
        self._reasoning_timer.setInterval(80)
        self._reasoning_timer.timeout.connect(self._render_reasoning)

        if content:
            self._render_content()
        if streaming and not thinking:
            self.status_indicator.start()
            self.status_row.show()
        else:
            self.status_row.hide()
        self.apply_theme(theme)

    def set_reasoning(self, reasoning: str) -> None:
        self._reasoning = reasoning
        if self.reasoning_panel is None:
            self.reasoning_panel = ReasoningPanel(
                reasoning,
                running=self._streaming,
                theme=self._theme,
            )
            self.reasoning_panel.heightChanged.connect(self.layoutHeightChanged)
            layout = self.layout().itemAt(1).layout()
            insert_at = layout.indexOf(self.status_row)
            layout.insertWidget(insert_at, self.reasoning_panel)
        if not self._reasoning_timer.isActive():
            self._reasoning_timer.start()

    def _render_reasoning(self) -> None:
        if self.reasoning_panel:
            self.reasoning_panel.set_reasoning(self._reasoning)

    def begin_answer(self) -> None:
        if self.reasoning_panel:
            self.reasoning_panel.set_running(False)
        self.status_indicator.stop()
        self.status_row.hide()
        self.content_view.show()

    def set_content(self, content: str) -> None:
        self._plain = content
        self.begin_answer()
        if not self._content_timer.isActive():
            self._content_timer.start()

    def _render_content(self) -> None:
        self.content_view.set_html(
            to_html(self._plain, dark=self._theme == "dark")
        )

    def finish(self, stopped: bool = False) -> None:
        self._streaming = False
        self._content_timer.stop()
        self._reasoning_timer.stop()
        self._render_reasoning()
        self._render_content()
        if self.reasoning_panel:
            self.reasoning_panel.set_running(False)
        self.status_indicator.stop()
        self.status_row.hide()
        self.content_view.setVisible(bool(self._plain))
        self.completion_label.setText("已停止" if stopped else "")
        self.actions.setVisible(bool(self._plain))

    def fail(self, message: str) -> None:
        self.finish()
        self.completion_label.setText(message)
        self.completion_label.setStyleSheet(
            f"color:{colors(self._theme)['danger']};font-size:11px;"
        )
        self.actions.show()

    def apply_theme(self, theme: str) -> None:
        super().apply_theme(theme)
        palette = colors(theme)
        self.avatar.setPixmap(
            tint_pixmap(
                QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(28, 28),
                palette["fg"],
            )
        )
        self.status_indicator.set_theme(theme)
        self.content_view.setStyleSheet(
            f"background:transparent;color:{palette['fg']};border:none;"
        )
        if self._plain:
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
        self._follow_output = True
        self._programmatic_scroll = False
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
        self.apply_theme("light")

    def clear(self) -> None:
        for bubble in self._bubbles:
            bubble.deleteLater()
        self._bubbles.clear()
        self._set_follow_output(True)

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
            self._bubbles.remove(bubble)
            bubble.deleteLater()

    def message_updated(self, bubble: MessageBubble) -> None:
        self._apply_size(bubble)
        self.scroll_to_bottom()

    def _apply_size(self, bubble: MessageBubble) -> None:
        width = min(LANE_MAX_WIDTH, max(420, self.viewport().width() - 56))
        bubble.setFixedWidth(width)

    def set_bottom_inset(self, inset: int) -> None:
        """Leave room for the overlaid composer without changing message widths."""

        left, top, right, _bottom = self.messages.getContentsMargins()
        self.messages.setContentsMargins(left, top, right, max(18, int(inset)))
        self.scroll_to_bottom()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
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
        self.followChanged.emit(enabled)

    def pause_follow(self) -> None:
        """Pause streaming auto-scroll after a user navigates upward."""

        if self.verticalScrollBar().maximum() > 0:
            self._set_follow_output(False)

    def resume_follow(self) -> None:
        """Resume auto-scroll and reveal the newest generated content."""

        self._set_follow_output(True)
        self.scroll_to_bottom(force=True)

    def _on_scroll_value_changed(self, value: int) -> None:
        if self._programmatic_scroll:
            return
        bar = self.verticalScrollBar()
        maximum = bar.maximum()
        if maximum <= 0:
            return
        # Once the user takes over the scroll position, only the explicit
        # "回到最新消息" control (or a new outgoing message) resumes follow.
        # This prevents an intermediate layout pass at the bottom from
        # accidentally re-enabling follow while a response is still streaming.
        if maximum - value > 10:
            self._set_follow_output(False)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta < 0:
                self.pause_follow()
            elif delta > 0:
                self._on_scroll_value_changed(self.verticalScrollBar().value())
        elif watched is self.verticalScrollBar():
            if event.type() == QEvent.Type.MouseButtonPress:
                self.pause_follow()
            elif event.type() == QEvent.Type.MouseMove and event.buttons():
                self.pause_follow()
        return super().eventFilter(watched, event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta < 0:
            self.pause_follow()
        super().wheelEvent(event)

    def scroll_to_bottom(self, force: bool = False) -> None:
        if force:
            self._set_follow_output(True)
        if not self._follow_output:
            return
        QTimer.singleShot(0, self._scroll_to_bottom_if_following)

    def _scroll_to_bottom_if_following(self) -> None:
        if not self._follow_output:
            return
        bar = self.verticalScrollBar()
        self._programmatic_scroll = True
        bar.setValue(bar.maximum())
        self._programmatic_scroll = False

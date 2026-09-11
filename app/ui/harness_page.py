from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import ASSETS_DIR
from ..harness import (
    HARNESS_DISPLAY_VERSION,
    HARNESS_DOCS_URL,
    HARNESS_REPOSITORY_URL,
    HarnessRuntime,
    harness_home,
)
from .icons import tint_pixmap
from .controls import IdleDispatcher
from .sidebar import ProductModeSelector
from .theme import colors


class _HarnessWebPage(QWebEnginePage):
    """Keep the embedded surface on loopback and open external links safely."""

    def __init__(self, profile: QWebEngineProfile, allowed_origin: str, parent=None) -> None:
        super().__init__(profile, parent)
        self._allowed_origin = allowed_origin.rstrip("/")

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame) -> bool:
        origin = f"{url.scheme()}://{url.authority()}".rstrip("/")
        if origin == self._allowed_origin or url.scheme() in {"about", "data"}:
            return super().acceptNavigationRequest(url, navigation_type, is_main_frame)
        if navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            if url.scheme().lower() in {"http", "https", "mailto"}:
                QDesktopServices.openUrl(url)
            return False
        return False


class HarnessSurface(QWidget):
    """Official Harness canvas rendered below MainWindow's app-level bar."""

    modeRequested = Signal(str)
    retryRequested = Signal()

    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("harnessSurface")
        self._theme = theme
        self._web_view: QWebEngineView | None = None
        self._profile: QWebEngineProfile | None = None
        self._disposing = False
        self._loaded_url = ""
        self._awaiting_first_paint = False
        self._build_status_panel()
        self.mode_selector = ProductModeSelector(theme, parent=self)
        self.mode_selector.set_mode("harness")
        self.mode_selector.hide()
        self.mode_selector.modeChanged.connect(self.modeRequested.emit)
        self._build_content_host()
        self._resize_children()

    def _build_content_host(self) -> None:
        """Reserve a separate canvas so the official sidebar starts cleanly."""

        self.content_host = QWidget(self)
        self.content_host.setObjectName("harnessContentHost")
        self.status_panel.setParent(self.content_host)
        self.apply_theme(self._theme)

    def _build_status_panel(self) -> None:
        self.status_panel = QFrame(self)
        self.status_panel.setObjectName("harnessStatusPanel")
        layout = QVBoxLayout(self.status_panel)
        layout.setContentsMargins(36, 28, 36, 30)
        layout.setSpacing(8)
        layout.addStretch(1)

        self.status_icon = QLabel(self.status_panel)
        self.status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_icon.setPixmap(
            tint_pixmap(
                QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(58, 58),
                colors(self._theme)["fg"],
            )
        )
        layout.addWidget(self.status_icon)

        self.status_title = QLabel("DeepSeek Harness", self.status_panel)
        self.status_title.setObjectName("harnessStatusTitle")
        self.status_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_title)

        self.status_label = QLabel("选择 Harness 后将启动官方开发者预览版", self.status_panel)
        self.status_label.setObjectName("harnessStatusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.status_detail = QLabel(
            f"官方 dsh {HARNESS_DISPLAY_VERSION} · 项目、工具、审批和轨迹由 Harness 管理",
            self.status_panel,
        )
        self.status_detail.setObjectName("harnessStatusDetail")
        self.status_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_detail.setWordWrap(True)
        layout.addWidget(self.status_detail)
        layout.addSpacing(9)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()
        self.retry_button = QPushButton("重新启动", self.status_panel)
        self.retry_button.setObjectName("primaryBtn")
        self.retry_button.clicked.connect(self.retryRequested.emit)
        buttons.addWidget(self.retry_button)
        self.docs_button = QPushButton("查看官方文档", self.status_panel)
        self.docs_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(HARNESS_DOCS_URL))
        )
        buttons.addWidget(self.docs_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addStretch(2)

    def show_status(self, text: str, *, failed: bool = False) -> None:
        self.status_label.setText(text)
        self.retry_button.setVisible(failed)
        self.status_panel.show()
        self.status_panel.raise_()

    def set_detail(self, text: str) -> None:
        self.status_detail.setText(text)

    def show_web(self, url: str) -> QWebEngineView | None:
        if self._disposing:
            return None
        view = self._ensure_web_view(url)
        if self._loaded_url != url:
            self._loaded_url = url
            self._awaiting_first_paint = True
            self._load_url(view, url)
        if self._awaiting_first_paint:
            self.status_panel.raise_()
        else:
            self._reveal_web()
        self._resize_children()
        return view

    def _load_url(self, view: QWebEngineView, url: str) -> None:
        view.load(QUrl(url))

    def _ensure_web_view(self, url: str) -> QWebEngineView:
        if self._web_view is not None:
            return self._web_view
        self._profile = QWebEngineProfile("deepseek-harness-desktop", self)
        browser_dir = harness_home() / "browser"
        browser_dir.mkdir(parents=True, exist_ok=True)
        self._profile.setPersistentStoragePath(str(browser_dir))
        self._profile.setCachePath(str(browser_dir / "cache"))
        self._profile.setHttpAcceptLanguage("zh-CN,zh;q=0.9,en;q=0.7")

        view = QWebEngineView(self.content_host)
        view.setObjectName("harnessWebView")
        view.setProperty("skipCustomTooltipScan", True)
        view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        parsed = QUrl(url)
        allowed_origin = f"{parsed.scheme()}://{parsed.authority()}"
        page = _HarnessWebPage(self._profile, allowed_origin, view)
        page.setBackgroundColor(QColor(colors(self._theme)["canvas"]))
        view.setPage(page)
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            False,
        )
        view.loadFinished.connect(self._web_load_finished)
        self._web_view = view
        return view

    def _reveal_web(self) -> None:
        if self._web_view is None:
            return
        self.status_panel.hide()
        self._web_view.show()
        self._web_view.raise_()

    def _web_load_finished(self, ok: bool) -> None:
        if self._disposing:
            return
        if not ok:
            self._loaded_url = ""
            self._awaiting_first_paint = False
            self.show_status(
                "官方 Harness 页面加载失败，请检查本机服务状态后重试。",
                failed=True,
            )
            return
        self._awaiting_first_paint = False
        self._reveal_web()

    def dispose(self) -> None:
        """Retire WebEngine objects through Qt's event loop.

        Calling ``shiboken.delete`` on a live QWebEngineView tears down the
        Qt Quick scene graph synchronously while Chromium may still be
        delivering a frame.  On macOS that can crash in
        ``QQuickWindow::~QQuickWindow``.  Hide and discard the page first,
        then let Qt destroy the view and profile in their normal ownership
        order.
        """

        if self._disposing:
            return
        self._disposing = True

        view = self._web_view
        profile = self._profile
        self._web_view = None
        self._profile = None
        self._loaded_url = ""
        self._awaiting_first_paint = False
        if view is not None:
            try:
                view.loadFinished.disconnect(self._web_load_finished)
            except (AttributeError, RuntimeError, TypeError):
                pass
            view.hide()
            page = view.page()
            if page is not None:
                try:
                    page.setLifecycleState(QWebEnginePage.LifecycleState.Discarded)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            if profile is not None:
                view.destroyed.connect(profile.deleteLater)
            view.deleteLater()
        elif profile is not None:
            profile.deleteLater()

    def _resize_children(self) -> None:
        width = self.width()
        content_height = max(0, self.height())
        self.content_host.setGeometry(0, 0, width, content_height)
        self.status_panel.setGeometry(0, 0, width, content_height)
        if self._web_view is not None:
            self._web_view.setGeometry(0, 0, width, content_height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_children()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        if self._web_view is not None:
            page = self._web_view.page()
            if page is not None:
                page.setBackgroundColor(QColor(palette["canvas"]))
        self.setStyleSheet(f"QWidget#harnessSurface{{background:{palette['canvas']};}}")
        self.content_host.setStyleSheet(
            f"QWidget#harnessContentHost{{background:{palette['canvas']};}}"
        )
        self.status_panel.setStyleSheet(
            f"QFrame#harnessStatusPanel{{background:{palette['canvas']};border:none;}}"
        )
        self.status_title.setStyleSheet(
            f"color:{palette['fg']};background:transparent;font-size:25px;font-weight:650;"
        )
        self.status_label.setStyleSheet(
            f"color:{palette['fg_sub']};background:transparent;font-size:14px;"
        )
        self.status_detail.setStyleSheet(
            f"color:{palette['fg_muted']};background:transparent;font-size:11px;"
        )
        self.status_icon.setPixmap(
            tint_pixmap(
                QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(58, 58),
                palette["fg"],
            )
        )


class HarnessPage(QWidget):
    """Own the official Harness subprocess and its embedded Web UI."""

    modeRequested = Signal(str)

    def __init__(self, cfg: dict, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("harnessPage")
        self._cfg = dict(cfg)
        self._theme = theme
        self._started_once = False
        self._defer_surface = False
        self._idle = IdleDispatcher(idle_ms=600, parent=self)
        self.surface = HarnessSurface(theme, self)
        self.surface.modeRequested.connect(self.modeRequested.emit)
        self.surface.retryRequested.connect(self.start)
        self.runtime = HarnessRuntime(cfg, self)
        self.runtime.stateChanged.connect(self._on_state)
        self.runtime.ready.connect(self._on_ready)
        self.runtime.failed.connect(self._on_failed)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.surface)
        self.surface.set_detail(
            f"官方 dsh {HARNESS_DISPLAY_VERSION} · MIT · "
            f"{HARNESS_REPOSITORY_URL}"
        )

    def update_config(self, cfg: dict) -> None:
        previous = self._cfg
        self._cfg = dict(cfg)
        self.runtime.update_config(cfg)
        runtime_inputs = ("api_key", "base_url", "harness_projects")
        if self.runtime.is_running and any(
            previous.get(key) != self._cfg.get(key) for key in runtime_inputs
        ):
            self._idle.cancel()
            self._defer_surface = False
            self.runtime.stop()
            self.surface.show_status("Harness 配置已更新，下次进入时会重新启动。")

    def start(self, silent: bool = False) -> None:
        """Start the runtime for a user-visible visit and reveal the surface."""

        self._started_once = True
        self._defer_surface = False
        self._idle.cancel()
        if self.runtime.is_ready:
            self.surface.show_web(self.runtime.url)
            return
        if not silent:
            self.surface.show_status("正在准备官方 Harness（首次启动会下载运行包）…")
            self.surface.set_detail(
                "Harness 是开发者预览版，会执行模型生成的工具和命令；请只授予必要的项目目录权限。"
            )
        working_directory = self._working_directory()
        self.runtime.start(working_directory)

    def warm(self) -> None:
        """Start the runtime in the background and defer the heavy GUI work.

        The subprocess is the long pole, so it starts right away; building the
        WebEngine surface blocks the GUI thread, so that part waits for an idle
        moment instead of stuttering whatever the user is doing.
        """

        self._started_once = True
        self._defer_surface = True
        self.runtime.start(self._working_directory())

    def _working_directory(self) -> Path:
        for value in self._cfg.get("harness_projects") or []:
            path = Path(str(value)).expanduser()
            if path.is_dir():
                return path
        current = Path.cwd()
        if current.is_dir() and str(current) not in {"/", "/Applications"}:
            return current
        return Path.home()

    def _on_state(self, text: str) -> None:
        if self._defer_surface and not self.isVisible():
            return
        self.surface.show_status(text)

    def _on_ready(self, url: str) -> None:
        if not self.isVisible():
            self._idle.schedule(
                lambda: self.surface.show_web(url),
                delay_ms=150,
            )
            return
        self.surface.show_web(url)

    def _on_failed(self, message: str) -> None:
        self.surface.show_status(message, failed=True)
        self.surface.set_detail(
            "可查看官方文档，确认 Node.js 22.19+ / 24+、网络和 API 密钥后再次启动。"
        )

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self.surface.apply_theme(theme)

    def stop(self) -> None:
        self._defer_surface = False
        self._idle.cancel()
        self.runtime.stop()
        self.surface.dispose()


__all__ = ["HarnessPage", "HarnessSurface"]

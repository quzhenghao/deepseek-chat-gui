from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QDir,
    QEvent,
    QPoint,
    QTemporaryDir,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QIcon, QImage
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from .. import ASSETS_DIR
from ..api import (
    MAX_INLINE_IMAGE_BYTES,
    is_image_path,
    payload_messages,
    title_messages,
)
from ..config import (
    EFFORT_LEVELS,
    effort_label,
    is_vision_model,
    model_label,
    sanitize_config,
    save_config,
    supports_thinking,
)
from ..worker import ChatWorker, TitleWorker
from .icons import apply_icon, tint_pixmap
from .image_strip import ImageStrip
from .message_bubbles import AssistantBubble, ChatView
from .controls import (
    ConfirmationDialog,
    FrameAnimator,
    HoverTipManager,
    NoticeDialog,
    RoundedComboBox,
    show_edit_menu,
)
from .settings_dialog import SettingsPage
from .sidebar import ProductModeSelector, Sidebar
from .harness_page import HarnessPage
from .theme import (
    RAIL_SIDEBAR_WIDTH,
    MESSAGE_CONTENT_MAX_WIDTH,
    RIGHT_HEADER_HEIGHT,
    RIGHT_HEADER_MARGINS,
    RIGHT_HEADER_SPACING,
    SIDEBAR_DEFAULT_WIDTH,
    SIDEBAR_MIN_WIDTH,
    build_qss,
    colors,
)


class ChatTextEdit(QTextEdit):
    submitRequested = Signal()
    imagePasted = Signal(object)
    expandedChanged = Signal(bool)
    heightChanged = Signal()

    COLLAPSED_HEIGHT = 84
    EXPANDED_HEIGHT = COLLAPSED_HEIGHT * 3

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chatInput")
        self.setAcceptDrops(False)
        self.setAcceptRichText(False)
        self.setFixedHeight(self.COLLAPSED_HEIGHT)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._ime_active = False
        self._expanded = False
        self._height_animator = FrameAnimator(280, self)
        self._height_animator.valueChanged.connect(self._apply_animated_height)
        self._height_animator.finished.connect(
            lambda: QTimer.singleShot(0, self.heightChanged.emit)
        )

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._height_animator.stop()
        self._height_animator.start(
            self.height(),
            self.EXPANDED_HEIGHT if expanded else self.COLLAPSED_HEIGHT,
        )
        self.expandedChanged.emit(expanded)

    def _apply_animated_height(self, height: float) -> None:
        target = round(height)
        if target != self.height():
            self.setFixedHeight(target)
            self.heightChanged.emit()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.InputMethod:
            self._ime_active = bool(event.preeditString())
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if event.isAutoRepeat():
                return
            if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if self._ime_active:
                    self._ime_active = False
                    super().keyPressEvent(event)
                    return
                self.submitRequested.emit()
                return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                self.imagePasted.emit(image)
            return
        super().insertFromMimeData(source)

    def contextMenuEvent(self, event) -> None:
        """Standard edit actions on the app's flat, opaque menu surface."""

        show_edit_menu(
            self,
            event.globalPos(),
            undo_available=self.document().isUndoAvailable(),
            redo_available=self.document().isRedoAvailable(),
            has_selection=self.textCursor().hasSelection(),
            can_paste=self.canPaste(),
            handlers={
                "undo": self.undo,
                "redo": self.redo,
                "cut": self.cut,
                "copy": self.copy,
                "paste": self.paste,
                "delete": lambda: self.textCursor().removeSelectedText(),
                "select_all": self.selectAll,
            },
        )

    def set_placeholder(self, vision: bool) -> None:
        text = "给DeepSeek发送消息"
        if vision:
            text += "，或拖入图片"
        self.setPlaceholderText(text)

class InputPanel(QWidget):
    filesDropped = Signal(list)
    attachRequested = Signal()
    submitRequested = Signal()
    stopRequested = Signal()
    thinkingChanged = Signal(bool)
    webSearchChanged = Signal(bool)
    effortChanged = Signal(str)
    notice = Signal(str)

    def __init__(
        self,
        editor: ChatTextEdit,
        thinking: bool,
        web_search: bool,
        effort: str,
        theme: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("composerArea")
        self.setAcceptDrops(True)
        self._theme = theme
        self._vision = False
        self._generating = False
        self._thinking_available = True
        self._action_icon_state: tuple[bool, bool, str] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 6, 24, 14)
        root.setSpacing(7)
        row = QHBoxLayout()
        row.addStretch()

        self.card = QFrame()
        self.card.setObjectName("composerCard")
        self.card.setMaximumWidth(MESSAGE_CONTENT_MAX_WIDTH + 60)
        self.card.setMinimumWidth(480)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(14, 10, 10, 9)
        card_layout.setSpacing(4)

        self.image_strip = ImageStrip(theme)
        self.image_strip.imagesChanged.connect(self._update_action)
        self.image_strip.limitReached.connect(self.notice.emit)
        card_layout.addWidget(self.image_strip)

        self.editor = editor
        self.editor.textChanged.connect(self._update_action)
        editor_row = QHBoxLayout()
        editor_row.setSpacing(2)
        editor_row.addWidget(self.editor, 1)
        self.expand_button = QToolButton()
        self.expand_button.setObjectName("expandInputBtn")
        self.expand_button.setFixedSize(28, 28)
        self.expand_button.setCheckable(True)
        self.expand_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_button.toggled.connect(self.editor.set_expanded)
        self.expand_button.toggled.connect(self._refresh_expand_button)
        editor_row.addWidget(
            self.expand_button, 0, Qt.AlignmentFlag.AlignTop
        )
        card_layout.addLayout(editor_row)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(5)
        self.attach_button = QToolButton()
        self.attach_button.setObjectName("attachBtn")
        self.attach_button.setFixedSize(34, 34)
        self.attach_button.setToolTip("添加图片")
        self.attach_button.clicked.connect(self.attachRequested.emit)
        toolbar.addWidget(self.attach_button)

        self.thinking_button = QPushButton("深度思考")
        self.thinking_button.setObjectName("thinkingBtn")
        self.thinking_button.setCheckable(True)
        self.thinking_button.setChecked(thinking)
        self.thinking_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thinking_button.toggled.connect(self._thinking_toggled)
        toolbar.addWidget(self.thinking_button)

        self.search_button = QPushButton("联网搜索")
        self.search_button.setObjectName("searchBtn")
        self.search_button.setCheckable(True)
        self.search_button.setChecked(web_search)
        self.search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_button.setToolTip("使用DeepSeek_Responses_API联网搜索")
        self.search_button.toggled.connect(self._web_search_toggled)
        toolbar.addWidget(self.search_button)

        self.effort_combo = RoundedComboBox(theme)
        self.effort_combo.setObjectName("effortCombo")
        for value in EFFORT_LEVELS:
            self.effort_combo.addItem(effort_label(value), value)
        self.effort_combo.setCurrentIndex(max(0, self.effort_combo.findData(effort)))
        self.effort_combo.currentIndexChanged.connect(
            lambda: self.effortChanged.emit(self.current_effort())
        )
        self.effort_combo.setEnabled(thinking)
        self.effort_combo.setToolTip("思考强度")
        toolbar.addWidget(self.effort_combo)
        toolbar.addStretch()

        self.action_button = QToolButton()
        self.action_button.setObjectName("actionBtn")
        self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_button.clicked.connect(self._trigger_action)
        toolbar.addWidget(self.action_button)
        card_layout.addLayout(toolbar)

        row.addWidget(self.card, 1)
        row.addStretch()
        root.addLayout(row)
        self.hint_label = QLabel(
            "Enter 发送 · Shift + Enter 换行 · 内容由 AI 生成，请仔细甄别"
        )
        self.hint_label.setObjectName("composerHint")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 0, 0, 0)
        hint_row.addStretch()
        hint_row.addWidget(self.hint_label)
        hint_row.addStretch()
        root.addLayout(hint_row)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 5)
        self.card.setGraphicsEffect(shadow)
        self._shadow = shadow
        self.apply_theme(theme)
        self._update_action()

    def _refresh_expand_button(self) -> None:
        palette = colors(self._theme)
        expanded = self.expand_button.isChecked()
        apply_icon(
            self.expand_button,
            "collapse" if expanded else "expand",
            palette["fg_sub"],
            17,
        )
        self.expand_button.setToolTip("收起输入框" if expanded else "展开输入框")

    def current_effort(self) -> str:
        return str(self.effort_combo.currentData() or "high")

    def is_thinking(self) -> bool:
        return self.thinking_button.isChecked()

    def is_web_search(self) -> bool:
        return self.search_button.isChecked()

    def set_thinking(self, enabled: bool) -> None:
        self.thinking_button.setChecked(enabled and self._thinking_available)

    def set_web_search(self, enabled: bool) -> None:
        self.search_button.setChecked(enabled)

    def set_thinking_available(self, enabled: bool) -> None:
        self._thinking_available = enabled
        if not enabled:
            self.thinking_button.setChecked(False)
        self.thinking_button.setEnabled(enabled)
        self.effort_combo.setEnabled(
            enabled and self.is_thinking()
        )
        self.thinking_button.setToolTip(
            "深度思考" if enabled else "当前模型不支持深度思考"
        )

    def set_effort(self, effort: str) -> None:
        index = self.effort_combo.findData(effort)
        if index >= 0:
            self.effort_combo.setCurrentIndex(index)

    def set_vision(self, enabled: bool) -> None:
        self._vision = enabled
        self.attach_button.setEnabled(True)
        self.attach_button.setToolTip(
            "添加图片" if enabled else "当前模型不支持图片"
        )

    def set_generating(self, generating: bool) -> None:
        self._generating = generating
        self.action_button.setObjectName("stopBtn" if generating else "actionBtn")
        self.action_button.style().unpolish(self.action_button)
        self.action_button.style().polish(self.action_button)
        self._update_action()

    def _thinking_toggled(self, enabled: bool) -> None:
        self.effort_combo.setEnabled(
            enabled and self._thinking_available
        )
        self.thinkingChanged.emit(enabled)
        self.apply_theme(self._theme)

    def _web_search_toggled(self, enabled: bool) -> None:
        self.webSearchChanged.emit(enabled)
        self.apply_theme(self._theme)

    def _trigger_action(self) -> None:
        if self._generating:
            self.stopRequested.emit()
        else:
            self.submitRequested.emit()

    def _update_action(self) -> None:
        has_content = bool(self.editor.toPlainText().strip() or self.image_strip.paths())
        enabled = self._generating or has_content
        if self.action_button.isEnabled() != enabled:
            self.action_button.setEnabled(enabled)
        self._refresh_action_icon()

    def _refresh_action_icon(self) -> None:
        state = (
            self._generating,
            self.action_button.isEnabled(),
            self._theme,
        )
        if state == self._action_icon_state:
            return
        self._action_icon_state = state
        palette = colors(self._theme)
        if self._generating:
            apply_icon(self.action_button, "stop", "#FFFFFF", 18)
            self.action_button.setToolTip("停止生成")
        else:
            color = "#FFFFFF" if self.action_button.isEnabled() else palette["fg_muted"]
            apply_icon(self.action_button, "send", color, 19)
            self.action_button.setToolTip("发送")

    def _image_urls(self, event) -> list[str]:
        if not event.mimeData().hasUrls():
            return []
        return [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile() and is_image_path(url.toLocalFile())
        ]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._vision and self._image_urls(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._vision and self._image_urls(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._image_urls(event)
        if self._vision and paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths)
        else:
            event.ignore()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        # An even icon canvas centers exactly inside the 34px circular button;
        # the previous 19px canvas could land on a half-pixel offset.
        apply_icon(self.attach_button, "plus", palette["fg_sub"], 20)
        self._refresh_expand_button()
        self.effort_combo.set_theme(theme)
        apply_icon(
            self.thinking_button,
            "sparkle",
            palette["accent"] if self.is_thinking() else palette["fg_sub"],
            17,
        )
        apply_icon(
            self.search_button,
            "globe",
            palette["accent"] if self.is_web_search() else palette["fg_sub"],
            17,
        )
        self._refresh_action_icon()
        self.image_strip.set_style(theme)
        self._shadow.setColor(QColor(palette["shadow"]))


class ChatWorkspace(QWidget):
    """Stack the conversation surface and keep the composer in the right place.

    The empty state uses the same composer as a normal conversation, but lets
    it float into the visual center of the canvas.  Once a conversation has
    messages the composer floats at the bottom of the canvas while the message
    viewport ends directly above it.  The full-size stack keeps the surrounding
    canvas continuous, so the card retains its floating silhouette.
    """

    FOLLOW_BUTTON_GAP = 16

    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chatWorkspace")
        self._theme = theme
        self._stack: QStackedWidget | None = None
        self._panel: InputPanel | None = None
        self._welcome: QWidget | None = None
        self._chat_view: ChatView | None = None
        self.follow_button = QToolButton(self)
        self.follow_button.setObjectName("followLatestBtn")
        self.follow_button.setFixedSize(36, 36)
        self.follow_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.follow_button.setToolTip("回到最新消息并继续跟随")
        self.follow_button.hide()

    def attach(
        self,
        stack: QStackedWidget,
        panel: InputPanel,
        welcome: QWidget,
        chat_view: ChatView,
    ) -> None:
        self._stack = stack
        self._panel = panel
        self._welcome = welcome
        self._chat_view = chat_view
        stack.setParent(self)
        panel.setParent(self)
        stack.currentChanged.connect(lambda _index: self._sync_layout())
        panel.editor.heightChanged.connect(self._sync_layout)
        panel.image_strip.imagesChanged.connect(self._sync_layout)
        chat_view.followChanged.connect(lambda _enabled: self._sync_follow_button())
        self.follow_button.clicked.connect(chat_view.resume_follow)
        chat_view.follow_button = self.follow_button
        self._sync_layout()

    def set_page(self, widget: QWidget) -> None:
        if self._stack is not None:
            self._stack.setCurrentWidget(widget)
        self._sync_layout()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        self.setStyleSheet(
            f"QWidget#chatWorkspace{{background:{palette['canvas']};}}"
        )
        apply_icon(self.follow_button, "arrow-down", palette["fg"], 19)
        self._sync_layout()

    def _sync_follow_button(self) -> None:
        if self._chat_view is None or self._stack is None:
            return
        visible = (
            self._stack.currentWidget() is self._chat_view
            and bool(self._chat_view._bubbles)
            and not self._chat_view.follows_output
        )
        self.follow_button.setVisible(visible)
        if visible:
            self.follow_button.raise_()

    def _sync_layout(self) -> None:
        if self._stack is None or self._panel is None:
            return
        width = max(0, self.width())
        height = max(0, self.height())
        self._stack.setGeometry(0, 0, width, height)
        panel_layout = self._panel.layout()
        if panel_layout is not None:
            panel_layout.activate()
        panel_height = min(height, max(132, self._panel.sizeHint().height()))
        self._panel.setGeometry(0, 0, width, panel_height)

        is_welcome = self._stack.currentWidget() is self._welcome
        if is_welcome:
            panel_y = max(0, min(int(height * 0.59), height - panel_height))
            welcome_layout = self._welcome.layout()
            if welcome_layout is not None:
                left, top, right, bottom = welcome_layout.getContentsMargins()
                clearance = max(10, height - panel_y + 4)
                if bottom != clearance:
                    welcome_layout.setContentsMargins(
                        left, top, right, clearance
                    )
            if self._chat_view is not None:
                self._chat_view.set_composer_clearance(0)
                self._chat_view.set_bottom_inset(18)
        else:
            panel_y = max(0, height - panel_height)
            if self._chat_view is not None:
                self._chat_view.set_composer_clearance(panel_height)
                self._chat_view.set_bottom_inset(18)
        self._panel.move(0, panel_y)
        self._panel.raise_()

        if self._chat_view is not None and not is_welcome:
            self._place_follow_button()
        self._sync_follow_button()

    def _place_follow_button(self) -> None:
        """Park the control beside the submit button, on its exact baseline."""

        if self._panel is None:
            return
        panel_layout = self._panel.layout()
        if panel_layout is not None:
            panel_layout.activate()
        card_layout = self._panel.card.layout()
        if card_layout is not None:
            card_layout.activate()
        anchor = self._panel.action_button
        origin = anchor.mapTo(self, QPoint(0, 0))
        size = self.follow_button.width()
        left = origin.x() + anchor.width() + self.FOLLOW_BUTTON_GAP
        top = origin.y() + (anchor.height() - size) // 2
        self.follow_button.move(
            min(left, max(12, self.width() - size - 12)),
            max(12, top),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_layout()


@dataclass
class StreamContext:
    conversation_id: str
    bubble: AssistantBubble | None
    model: str
    effort: str
    thinking: bool
    web_search: bool = False
    content: str = ""
    reasoning: str = ""
    status: str = ""
    stopped: bool = False
    worker: ChatWorker | None = None


@dataclass
class DraftState:
    text: str
    images: list[str]
    cursor_position: int


class MainWindow(QMainWindow):
    def __init__(self, cfg: dict, store, app: QApplication) -> None:
        super().__init__()
        self.cfg = cfg
        self.store = store
        self._app = app
        self._theme = cfg.get("theme", "light")
        self._current_conversation_id: str | None = None
        self._streams: dict[str, StreamContext] = {}
        self._workers: set[ChatWorker] = set()
        self._drafts: dict[str | None, DraftState] = {}
        self._title_workers: set[TitleWorker] = set()
        self._title_worker_by_conversation: dict[str, TitleWorker] = {}
        self._notice_dialog: NoticeDialog | None = None
        self._mode = "chat"
        self._closing = False
        self._warm_start_armed = bool(cfg.get("harness_warm_start", True))
        self._warm_start_pending = False
        self._sidebar_collapsed = False
        self._sidebar_animator = FrameAnimator(300, self)
        self._sidebar_animator.valueChanged.connect(self._apply_sidebar_width)
        self._sidebar_animator.finished.connect(self._finish_sidebar_transition)
        self._hover_tips = HoverTipManager(app, self._theme, self)
        draft_template = str(Path(QDir.tempPath()) / "deepseek-chat-draft-XXXXXX")
        self._draft_dir = QTemporaryDir(draft_template)
        self.setWindowTitle("DeepSeek")
        self.resize(1280, 820)
        self.setMinimumSize(920, 640)
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "app-icon.png")))
        self._build_ui()
        self._hover_tips.watch(self)
        self._rebuild_models()
        self.apply_theme(self._theme)
        self.refresh_sidebar()
        self.show_welcome()
        if not cfg.get("api_key"):
            QTimer.singleShot(350, self.open_settings)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._warm_start_armed:
            self._warm_start_armed = False
            self._schedule_harness_warm()

    def _schedule_harness_warm(self) -> None:
        if (
            self._closing
            or self._app.platformName() == "offscreen"
            or self._mode != "chat"
            or not self.cfg.get("harness_warm_start", True)
            or self._warm_start_pending
        ):
            return
        self._warm_start_pending = True
        QTimer.singleShot(0, self._run_scheduled_harness_warm)

    def _run_scheduled_harness_warm(self) -> None:
        self._warm_start_pending = False
        self._warm_harness()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_mode_bar(root)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("mainPageStack")
        root.addWidget(self.page_stack)

        self.chat_page = QWidget()
        self.chat_page.setObjectName("chatPage")
        chat_page_layout = QHBoxLayout(self.chat_page)
        chat_page_layout.setContentsMargins(0, 0, 0, 0)
        chat_page_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        chat_page_layout.addWidget(self.splitter)

        self.sidebar = Sidebar(self._theme)
        self.sidebar.newChatRequested.connect(self.on_new_chat)
        self.sidebar.conversationSelected.connect(self.on_select_conversation)
        self.sidebar.renameConversation.connect(self.on_rename_conversation)
        self.sidebar.deleteConversation.connect(self.on_delete_conversation)
        self.sidebar.deleteConversations.connect(self.on_delete_conversations)
        self.sidebar.modeChanged.connect(self._switch_mode)
        self.sidebar.settingsRequested.connect(self.open_settings)
        self.sidebar.collapseRequested.connect(self._toggle_sidebar)
        self.sidebar.expandRequested.connect(self._toggle_sidebar)
        self.splitter.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self._build_header(right_layout)

        self.chat_workspace = ChatWorkspace(self._theme)
        self.stack = QStackedWidget(self.chat_workspace)
        self.welcome = self._build_welcome()
        self.chat_view = ChatView()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.chat_view)

        self.chat_input = ChatTextEdit()
        self.chat_input.expandedChanged.connect(self._set_welcome_compact)
        self.input_panel = InputPanel(
            self.chat_input,
            bool(self.cfg.get("deep_thinking", True)),
            bool(self.cfg.get("web_search", True)),
            self.cfg.get("last_effort", "high"),
            self._theme,
            parent=self.chat_workspace,
        )
        self.chat_input.submitRequested.connect(self.on_send)
        self.chat_input.imagePasted.connect(self._on_image_pasted)
        self.input_panel.filesDropped.connect(self._add_images)
        self.input_panel.attachRequested.connect(self._choose_images)
        self.input_panel.submitRequested.connect(self.on_send)
        self.input_panel.stopRequested.connect(self.on_stop)
        self.input_panel.thinkingChanged.connect(self._thinking_changed)
        self.input_panel.webSearchChanged.connect(self._web_search_changed)
        self.input_panel.effortChanged.connect(self._effort_changed)
        self.input_panel.notice.connect(self._show_notice)
        self.chat_workspace.attach(
            self.stack,
            self.input_panel,
            self.welcome,
            self.chat_view,
        )
        right_layout.addWidget(self.chat_workspace, 1)

        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([SIDEBAR_DEFAULT_WIDTH, 1280 - SIDEBAR_DEFAULT_WIDTH])

        self._settings_page: SettingsPage | None = None
        self.harness_page = HarnessPage(self.cfg, self._theme)
        self.harness_page.modeRequested.connect(self._switch_mode)
        self.page_stack.addWidget(self.chat_page)
        self.page_stack.addWidget(self.harness_page)
        self.page_stack.setCurrentWidget(self.chat_page)

    @property
    def settings_page(self) -> SettingsPage:
        page = self._settings_page
        if page is None:
            page = SettingsPage(self.cfg)
            page.saveRequested.connect(self._save_settings)
            page.cancelRequested.connect(self._close_settings)
            page.apply_theme(self._theme)
            self._settings_page = page
            self.page_stack.addWidget(page)
        return page

    def _build_mode_bar(self, parent_layout: QVBoxLayout) -> None:
        """Create the one product switcher shared by Chat and Harness."""

        self.mode_bar = QFrame()
        self.mode_bar.setObjectName("modeBar")
        self.mode_bar.setFixedHeight(58)
        layout = QHBoxLayout(self.mode_bar)
        layout.setContentsMargins(20, 0, 24, 0)
        layout.setSpacing(0)
        self.mode_selector = ProductModeSelector(self._theme, parent=self.mode_bar)
        self.mode_selector.modeChanged.connect(self._switch_mode)
        layout.addWidget(self.mode_selector, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        parent_layout.addWidget(self.mode_bar)

    def _build_header(self, parent_layout: QVBoxLayout) -> None:
        header = QWidget()
        header.setObjectName("chatHeader")
        header.setFixedHeight(RIGHT_HEADER_HEIGHT)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(*RIGHT_HEADER_MARGINS)
        layout.setSpacing(RIGHT_HEADER_SPACING)

        self.model_combo = RoundedComboBox(self._theme)
        self.model_combo.setObjectName("modelCombo")
        self.model_combo.setMinimumWidth(250)
        self.model_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        layout.addWidget(self.model_combo)

        self.vision_chip = QLabel("视觉模型")
        self.vision_chip.setObjectName("visionChip")
        layout.addWidget(self.vision_chip)
        layout.addStretch()

        self.api_status = QLabel()
        self.api_status.setObjectName("statusChip")
        layout.addWidget(self.api_status)
        parent_layout.addWidget(header)

    def _build_welcome(self) -> QWidget:
        page = QWidget()
        page.setObjectName("welcomePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 20, 36, 10)
        layout.addStretch(2)

        logo = QLabel()
        self.welcome_logo = logo
        logo.setPixmap(
            tint_pixmap(
                QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(64, 64),
                colors(self._theme)["fg"],
            )
        )
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        layout.addSpacing(12)
        title = QLabel("有什么可以帮到你？")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(7)
        subtitle = QLabel("调用你自己的DeepSeek_API，对话记录仅保存在本机")
        subtitle.setObjectName("subText")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        self.welcome_suggestion_gap = QSpacerItem(
            0, 26, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        layout.addItem(self.welcome_suggestion_gap)

        suggestions = QWidget()
        self.welcome_suggestions = suggestions
        suggestions.setMaximumWidth(620)
        grid = QGridLayout(suggestions)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        prompts = [
            ("解释一个复杂概念", "请用通俗的语言解释："),
            ("帮我完善一段代码", "请帮我检查并改进这段代码：\n"),
            ("润色这段文字", "请帮我润色下面这段文字：\n"),
            ("制定一个行动计划", "请为下面的目标制定清晰的行动计划：\n"),
        ]
        for index, (label, prompt) in enumerate(prompts):
            button = QPushButton(label)
            button.setObjectName("suggestionBtn")
            button.clicked.connect(
                lambda checked=False, value=prompt: self._use_suggestion(value)
            )
            grid.addWidget(button, index // 2, index % 2)
        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(suggestions)
        center.addStretch()
        layout.addLayout(center)
        layout.addStretch(5)
        return page

    def _set_welcome_compact(self, expanded: bool) -> None:
        self.welcome_suggestions.setVisible(not expanded)
        self.welcome_suggestion_gap.changeSize(
            0,
            0 if expanded else 26,
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Fixed,
        )
        self.welcome.layout().invalidate()

    def show_welcome(self) -> None:
        self.chat_workspace.set_page(self.welcome)
        self.sidebar.set_current(None)
        self.chat_input.setFocus()

    def _switch_mode(self, mode: str) -> None:
        """Switch the product surface while keeping one synchronized selector."""

        normalized = mode if mode in {"chat", "harness"} else "chat"
        self.mode_selector.set_mode(normalized)
        self.sidebar.set_mode(normalized)
        self.harness_page.surface.mode_selector.set_mode(normalized)
        if normalized == self._mode:
            if normalized == "harness":
                self.page_stack.setCurrentWidget(self.harness_page)
                self.harness_page.start()
            return
        self._mode = normalized
        if normalized == "harness":
            self.page_stack.setCurrentWidget(self.harness_page)
            self.harness_page.start()
            return
        self.page_stack.setCurrentWidget(self.chat_page)
        self.chat_input.setFocus()

    def _warm_harness(self) -> None:
        if (
            not self._closing
            and self._app.platformName() != "offscreen"
            and self._mode == "chat"
            and self.cfg.get("harness_warm_start", True)
        ):
            self.harness_page.warm()

    def _use_suggestion(self, prompt: str) -> None:
        self.chat_input.setPlainText(prompt)
        self.chat_input.moveCursor(self.chat_input.textCursor().MoveOperation.End)
        self.chat_input.setFocus()

    def _rebuild_models(self, selected: str | None = None) -> None:
        target = selected or self.cfg.get("last_model") or self.cfg.get("default_model")
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in self.cfg.get("models", []):
            self.model_combo.addItem(model_label(model), model)
        index = self.model_combo.findData(target)
        self.model_combo.setCurrentIndex(max(0, index))
        self.model_combo.blockSignals(False)
        self._apply_model_state()

    def current_model(self) -> str:
        return str(self.model_combo.currentData() or "")

    def _model_changed(self) -> None:
        model = self.current_model()
        if model:
            self.cfg["last_model"] = model
            save_config(self.cfg)
        self._apply_model_state()

    def _apply_model_state(self) -> None:
        self.input_panel.set_thinking_available(
            supports_thinking(self.current_model())
        )
        vision = is_vision_model(self.current_model())
        self.vision_chip.setVisible(vision)
        self.input_panel.set_vision(vision)
        self.chat_input.set_placeholder(vision)

    def _thinking_changed(self, enabled: bool) -> None:
        self.cfg["deep_thinking"] = enabled
        save_config(self.cfg)

    def _web_search_changed(self, enabled: bool) -> None:
        self.cfg["web_search"] = enabled
        save_config(self.cfg)

    def _effort_changed(self, effort: str) -> None:
        if effort in EFFORT_LEVELS:
            self.cfg["last_effort"] = effort
            save_config(self.cfg)

    def _toggle_sidebar(self) -> None:
        self.set_sidebar_collapsed(not self._sidebar_collapsed)

    def set_sidebar_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        """Animate the chat sidebar between its full page and the icon rail."""

        collapsed = bool(collapsed)
        self._sidebar_collapsed = collapsed
        target = RAIL_SIDEBAR_WIDTH if collapsed else SIDEBAR_DEFAULT_WIDTH
        if collapsed:
            self.sidebar.setMinimumWidth(RAIL_SIDEBAR_WIDTH)
        else:
            # Reveal the full page while it is still clipped by the narrow
            # sidebar, instead of swapping pages halfway through the motion.
            self.sidebar.set_collapsed(False)
        self._sidebar_animator.stop()
        start = self.sidebar.width() or SIDEBAR_DEFAULT_WIDTH
        if not animate or start == target:
            self._apply_sidebar_width(target)
            self._finish_sidebar_transition()
            return
        self.chat_view.set_layout_transition_active(True)
        self._sidebar_animator.start(start, target)

    def _apply_sidebar_width(self, width: float) -> None:
        sizes = self.splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        value = int(round(width))
        value = max(RAIL_SIDEBAR_WIDTH, min(SIDEBAR_DEFAULT_WIDTH, value))
        self.splitter.setSizes([value, max(0, total - value)])

    def _finish_sidebar_transition(self) -> None:
        if self._sidebar_collapsed:
            self._apply_sidebar_width(RAIL_SIDEBAR_WIDTH)
            self.sidebar.set_collapsed(True)
            self.chat_view.set_layout_transition_active(False)
            return
        self._apply_sidebar_width(SIDEBAR_DEFAULT_WIDTH)
        self.sidebar.setMinimumWidth(SIDEBAR_MIN_WIDTH)
        self.chat_view.set_layout_transition_active(False)

    def refresh_sidebar(self, selected: str | None = None) -> None:
        current = selected if selected is not None else self._current_conversation_id
        self.sidebar.refresh(
            self.store.conversations(), current, set(self._streams)
        )

    def _save_draft(self) -> None:
        key = self._current_conversation_id
        draft = DraftState(
            self.chat_input.toPlainText(),
            self.input_panel.image_strip.paths(),
            self.chat_input.textCursor().position(),
        )
        if draft.text or draft.images:
            self._drafts[key] = draft
        else:
            self._drafts.pop(key, None)

    def _restore_draft(self, conversation_id: str | None) -> None:
        draft = self._drafts.get(conversation_id)
        self.chat_input.setPlainText(draft.text if draft else "")
        cursor = self.chat_input.textCursor()
        cursor.setPosition(min(draft.cursor_position, len(draft.text)) if draft else 0)
        self.chat_input.setTextCursor(cursor)
        self.input_panel.image_strip.clear()
        if draft:
            self.input_panel.image_strip.add_paths(
                [path for path in draft.images if Path(path).is_file()]
            )

    def _detach_visible_stream(self) -> None:
        context = self._streams.get(self._current_conversation_id or "")
        if context is not None:
            context.bubble = None

    def on_new_chat(self) -> None:
        self._save_draft()
        self._detach_visible_stream()
        self._current_conversation_id = None
        self.chat_view.clear()
        self._drafts.pop(None, None)
        self._restore_draft(None)
        self._sync_generating()
        self.show_welcome()

    def on_select_conversation(self, conversation_id: str) -> None:
        conversation = self.store.get(conversation_id)
        if conversation is None:
            return
        if self._current_conversation_id == conversation_id:
            self.sidebar.set_current(conversation_id)
            self.chat_input.setFocus()
            return
        self._save_draft()
        self._detach_visible_stream()
        self._current_conversation_id = conversation_id
        self.chat_workspace.set_page(self.chat_view)
        self.chat_view.clear()
        for message in conversation.get("messages", []):
            role = message.get("role")
            if role == "user":
                self.chat_view.add_user(
                    message.get("content", ""), message.get("images") or []
                )
            elif role == "assistant":
                thinking = bool(
                    message.get("thinking", message.get("reasoning_content"))
                )
                self.chat_view.add_assistant(
                    message.get("content", ""),
                    message.get("reasoning_content") or "",
                    self._message_meta(
                        message.get("model", ""),
                        message.get("effort", ""),
                        thinking,
                        bool(message.get("web_search", False)),
                    ),
                    thinking=thinking,
                    stopped=bool(message.get("stopped", False)),
                )
            elif role == "error" or (
                role == "system" and not message.get("hidden", False)
            ):
                self.chat_view.add_error(message.get("content", "请求失败"))
        context = self._streams.get(conversation_id)
        if context is not None:
            bubble = self.chat_view.add_streaming(
                self._message_meta(
                    context.model,
                    context.effort,
                    context.thinking,
                    context.web_search,
                ),
                context.thinking,
            )
            context.bubble = bubble
            if context.reasoning:
                bubble.set_reasoning(context.reasoning)
            if context.content:
                bubble.set_content(context.content)
            if context.status:
                bubble.set_status(context.status)
        self._restore_draft(conversation_id)
        self._sync_generating()
        self.sidebar.set_current(conversation_id)
        self.chat_view.scroll_to_bottom(force=True)
        self.chat_input.setFocus()

    def on_rename_conversation(self, conversation_id: str) -> None:
        conversation = self.store.get(conversation_id)
        if conversation is None:
            return
        title, accepted = QInputDialog.getText(
            self,
            "重命名对话",
            "对话名称",
            text=conversation.get("title", ""),
        )
        if accepted and title.strip():
            self.store.rename(conversation_id, title)
            self.refresh_sidebar(conversation_id)

    def on_delete_conversation(self, conversation_id: str) -> None:
        conversation = self.store.get(conversation_id)
        if conversation is None:
            return
        confirmed = ConfirmationDialog.ask(
            self,
            "删除对话",
            (
                f"确定删除“{conversation.get('title', '该对话')}”吗？\n"
                "对话消息和本地图片会一起删除"
            ),
            self._theme,
        )
        if not confirmed:
            return
        self._cancel_stream(conversation_id)
        self._cancel_title_summary(conversation_id)
        self.store.delete(conversation_id)
        self._drafts.pop(conversation_id, None)
        if self._current_conversation_id == conversation_id:
            self._current_conversation_id = None
            self.chat_view.clear()
            self._restore_draft(None)
            self._sync_generating()
            self.show_welcome()
        self.refresh_sidebar()

    def on_delete_conversations(self, conversation_ids: list[str]) -> None:
        if not conversation_ids:
            return
        confirmed = ConfirmationDialog.ask(
            self,
            "删除多个对话",
            (
                f"确定删除选中的 {len(conversation_ids)} 个对话吗？\n"
                "相关消息和本地图片会一起删除。"
            ),
            self._theme,
        )
        if not confirmed:
            return
        for conversation_id in conversation_ids:
            self._cancel_stream(conversation_id)
            self._cancel_title_summary(conversation_id)
            self._drafts.pop(conversation_id, None)
        self.store.delete_many(conversation_ids)
        if self._current_conversation_id in conversation_ids:
            self._current_conversation_id = None
            self.chat_view.clear()
            self._restore_draft(None)
            self._sync_generating()
            self.show_welcome()
        self.refresh_sidebar()

    def _choose_images(self) -> None:
        if not is_vision_model(self.current_model()):
            self._show_notice("请先切换到视觉模型")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.gif *.webp)",
        )
        self._add_images(paths)

    def _add_images(self, paths: list[str]) -> None:
        if not is_vision_model(self.current_model()):
            self._show_notice("当前模型不支持图片")
            return
        accepted: list[str] = []
        for path in paths:
            file_path = Path(path)
            if not is_image_path(path):
                continue
            if file_path.stat().st_size > MAX_INLINE_IMAGE_BYTES:
                self._show_notice(f"{file_path.name} 超过 32 MiB")
                continue
            accepted.append(path)
        self.input_panel.image_strip.add_paths(accepted)

    def _on_image_pasted(self, image: QImage) -> None:
        if not is_vision_model(self.current_model()):
            self._show_notice("当前模型不支持图片")
            return
        if not self._draft_dir.isValid():
            self._show_notice("无法创建临时图片目录")
            return
        path = Path(self._draft_dir.path()) / f"{uuid.uuid4().hex}.png"
        if image.save(str(path)):
            self.input_panel.image_strip.add_path(str(path))
        else:
            self._show_notice("粘贴的图片无法保存")

    def _show_notice(self, text: str) -> None:
        if self._notice_dialog is not None and isValid(self._notice_dialog):
            if self._notice_dialog.isVisible():
                self._notice_dialog.set_text(text)
                self._center_notice(self._notice_dialog)
                self._notice_dialog.raise_()
                return
        dialog = NoticeDialog(text, self._theme, self)
        self._notice_dialog = dialog
        dialog.finished.connect(lambda: self._clear_notice(dialog))
        self._center_notice(dialog)
        dialog.show()
        dialog.raise_()

    def _center_notice(self, dialog: NoticeDialog) -> None:
        dialog.adjustSize()
        center = self.mapToGlobal(self.rect().center())
        screen = dialog.screen() or self.screen()
        if screen is None:
            dialog.move(center - QPoint(dialog.width() // 2, dialog.height() // 2))
            return
        available = screen.availableGeometry()
        x = center.x() - dialog.width() // 2
        y = center.y() - dialog.height() // 2
        x = max(available.left(), min(x, available.right() - dialog.width() + 1))
        y = max(available.top(), min(y, available.bottom() - dialog.height() + 1))
        dialog.move(x, y)

    def _clear_notice(self, dialog: NoticeDialog) -> None:
        if self._notice_dialog is dialog:
            self._notice_dialog = None

    def _ensure_conversation(self, title: str) -> dict:
        if self._current_conversation_id:
            conversation = self.store.get(self._current_conversation_id)
            if conversation:
                return conversation
        conversation = self.store.create(title)
        self._current_conversation_id = conversation["id"]
        self.refresh_sidebar(conversation["id"])
        return conversation

    def on_send(self) -> None:
        if self._current_conversation_id in self._streams:
            return
        text = self.chat_input.toPlainText().strip()
        staged_images = self.input_panel.image_strip.paths()
        if not text and not staged_images:
            return
        if not (self.cfg.get("api_key") or "").strip():
            self._show_notice("请先在设置中填写API密钥")
            self.open_settings()
            return
        if staged_images and not is_vision_model(self.current_model()):
            self._show_notice("当前模型不支持已添加的图片")
            return

        previous_id = self._current_conversation_id
        conversation = self._ensure_conversation("新对话")
        conversation_id = conversation["id"]
        stored_images: list[str] = []
        for image_path in staged_images:
            try:
                stored_images.append(
                    self.store.import_image(conversation_id, image_path)
                )
            except OSError as exc:
                self._show_notice(f"图片导入失败：{exc}")
        if not text and not stored_images:
            return
        is_first_turn = not conversation.get("messages")

        model = self.current_model()
        effort = self.input_panel.current_effort()
        thinking = self.input_panel.is_thinking()
        web_search = self.input_panel.is_web_search()
        system_prompt = str(self.cfg.get("system_prompt") or "").strip()
        if is_first_turn and system_prompt:
            self.store.append_message(
                conversation_id,
                {
                    "role": "system",
                    "content": system_prompt,
                    "hidden": True,
                },
            )
        user_message = {
            "role": "user",
            "content": text,
            "images": stored_images,
            "model": model,
            "effort": effort,
            "thinking": thinking,
            "web_search": web_search,
        }
        self.store.append_message(conversation_id, user_message)
        self.chat_workspace.set_page(self.chat_view)
        self.chat_view.add_user(text, stored_images)
        self.input_panel.image_strip.clear()
        self.chat_input.clear()
        self._drafts.pop(previous_id, None)
        self._drafts.pop(conversation_id, None)
        self.refresh_sidebar(conversation_id)
        self._start_request(conversation_id, model, effort, thinking, web_search)

    @staticmethod
    def _message_meta(
        model: str,
        effort: str,
        thinking: bool,
        web_search: bool = False,
    ) -> str:
        parts: list[str] = [model_label(model)]
        if thinking:
            parts.append(f"深度思考 {effort_label(effort)}")
        else:
            parts.append("标准模式")
        if web_search:
            parts.append("联网搜索")
        return " · ".join(parts)

    def _start_request(
        self,
        conversation_id: str,
        model: str,
        effort: str,
        thinking: bool,
        web_search: bool,
    ) -> None:
        conversation = self.store.get(conversation_id)
        if conversation is None:
            return
        try:
            messages = payload_messages(conversation.get("messages", []))
        except Exception as exc:
            message = f"无法读取图片：{exc}"
            self.store.append_message(
                conversation_id, {"role": "error", "content": message}
            )
            self.chat_view.add_error(message)
            return
        bubble = self.chat_view.add_streaming(
            self._message_meta(model, effort, thinking, web_search), thinking
        )
        context = StreamContext(
            conversation_id,
            bubble,
            model,
            effort,
            thinking,
            web_search,
        )
        worker = ChatWorker(
            self.cfg,
            model,
            effort,
            thinking,
            messages,
            float(self.cfg.get("temperature", 1.0)),
            int(self.cfg.get("max_tokens", 0)),
            web_search,
        )
        context.worker = worker
        self._streams[conversation_id] = context
        self._workers.add(worker)
        worker.chunk.connect(
            lambda text, active=context: self._on_chunk(active, text)
        )
        worker.reasoning.connect(
            lambda text, active=context: self._on_reasoning(active, text)
        )
        worker.status.connect(
            lambda text, active=context: self._on_status(active, text)
        )
        worker.done.connect(lambda active=context: self._on_done(active))
        worker.failed.connect(
            lambda message, active=context: self._on_failed(active, message)
        )
        worker.finished.connect(lambda: self._clear_worker(worker))
        self._sync_generating()
        self.refresh_sidebar()
        worker.start()

    def _sync_generating(self) -> None:
        self.input_panel.set_generating(
            self._current_conversation_id in self._streams
        )

    def _visible_bubble(self, context: StreamContext) -> AssistantBubble | None:
        if (
            self._streams.get(context.conversation_id) is not context
            or self._current_conversation_id != context.conversation_id
            or context.bubble is None
            or not isValid(context.bubble)
        ):
            return None
        return context.bubble

    def _on_chunk(self, context: StreamContext, text: str) -> None:
        if self._streams.get(context.conversation_id) is not context:
            return
        context.content += text
        bubble = self._visible_bubble(context)
        if bubble is not None:
            bubble.set_content(context.content)
            self.chat_view.message_updated(bubble)

    def _on_reasoning(self, context: StreamContext, text: str) -> None:
        if self._streams.get(context.conversation_id) is not context:
            return
        context.reasoning += text
        bubble = self._visible_bubble(context)
        if bubble is not None:
            bubble.set_reasoning(context.reasoning)
            self.chat_view.message_updated(bubble)

    def _on_status(self, context: StreamContext, text: str) -> None:
        if self._streams.get(context.conversation_id) is not context:
            return
        context.status = text
        bubble = self._visible_bubble(context)
        if bubble is not None:
            bubble.set_status(text)

    def _assistant_record(self, context: StreamContext) -> dict:
        return {
            "role": "assistant",
            "content": context.content,
            "reasoning_content": context.reasoning or None,
            "images": [],
            "model": context.model,
            "effort": context.effort,
            "thinking": context.thinking,
            "web_search": context.web_search,
            "stopped": context.stopped,
        }

    def _on_done(self, context: StreamContext) -> None:
        if self._streams.get(context.conversation_id) is not context:
            return
        self._streams.pop(context.conversation_id, None)
        self.store.append_message(
            context.conversation_id, self._assistant_record(context)
        )
        if (
            self._current_conversation_id == context.conversation_id
            and context.bubble is not None
            and isValid(context.bubble)
        ):
            context.bubble.finish(context.stopped)
            self.chat_view.message_updated(context.bubble)
            if self.page_stack.currentWidget() is self.chat_page:
                self.chat_input.setFocus()
        self._sync_generating()
        self.refresh_sidebar()
        self._start_title_summary(context.conversation_id, context.model)

    def _on_failed(self, context: StreamContext, message: str) -> None:
        if self._streams.get(context.conversation_id) is not context:
            return
        self._streams.pop(context.conversation_id, None)
        visible = (
            self._current_conversation_id == context.conversation_id
            and context.bubble is not None
            and isValid(context.bubble)
        )
        if context.content or context.reasoning:
            context.stopped = True
            self.store.append_message(
                context.conversation_id, self._assistant_record(context)
            )
            if visible:
                context.bubble.fail(f"生成中断：{message}")
                self.chat_view.message_updated(context.bubble)
            self._start_title_summary(context.conversation_id, context.model)
        else:
            self.store.append_message(
                context.conversation_id,
                {"role": "error", "content": message},
            )
            if visible:
                self.chat_view.remove_bubble(context.bubble)
                self.chat_view.add_error(message)
        self._sync_generating()
        self.refresh_sidebar()

    def on_stop(self) -> None:
        context = self._streams.get(self._current_conversation_id or "")
        if context is None:
            return
        context.stopped = True
        if context.worker is not None:
            context.worker.cancel()

    def _cancel_stream(self, conversation_id: str) -> None:
        context = self._streams.pop(conversation_id, None)
        if context is not None and context.worker is not None:
            context.worker.cancel()
        self._sync_generating()

    def _clear_worker(self, worker: ChatWorker) -> None:
        self._workers.discard(worker)
        worker.deleteLater()

    def _start_title_summary(self, conversation_id: str, model: str) -> None:
        conversation = self.store.get(conversation_id)
        if conversation is None:
            return
        messages = title_messages(conversation.get("messages", []))
        previous = self._title_worker_by_conversation.get(conversation_id)
        if previous is not None:
            previous.cancel()
        worker = TitleWorker(self.cfg, model, messages, self)
        self._title_workers.add(worker)
        self._title_worker_by_conversation[conversation_id] = worker
        worker.titleReady.connect(
            lambda title, cid=conversation_id, active=worker: (
                self._apply_summary_title(cid, active, title)
            )
        )
        worker.finished.connect(
            lambda cid=conversation_id, active=worker: (
                self._clear_title_worker(cid, active)
            )
        )
        worker.start()

    def _apply_summary_title(
        self,
        conversation_id: str,
        worker: TitleWorker,
        title: str,
    ) -> None:
        if self._title_worker_by_conversation.get(conversation_id) is not worker:
            return
        if self.store.get(conversation_id) is None:
            return
        self.store.update_title(conversation_id, title)
        self.refresh_sidebar()

    def _cancel_title_summary(self, conversation_id: str) -> None:
        worker = self._title_worker_by_conversation.get(conversation_id)
        if worker is not None:
            worker.cancel()

    def _clear_title_worker(
        self,
        conversation_id: str,
        worker: TitleWorker,
    ) -> None:
        self._title_workers.discard(worker)
        if self._title_worker_by_conversation.get(conversation_id) is worker:
            self._title_worker_by_conversation.pop(conversation_id, None)
        worker.deleteLater()

    def open_settings(self) -> None:
        if self._closing:
            return
        self.settings_page.load_config(self.cfg)
        self.page_stack.setCurrentWidget(self.settings_page)

    def _close_settings(self) -> None:
        self.page_stack.setCurrentWidget(self.chat_page)
        self.chat_input.setFocus()

    def _save_settings(self, values: dict) -> None:
        previous_model = self.current_model()
        self.cfg.update(values)
        save_config(self.cfg)
        self.cfg = sanitize_config(self.cfg)
        self.harness_page.update_config(self.cfg)
        available_models = self.cfg.get("models", [])
        selected = (
            previous_model
            if previous_model in available_models
            else self.cfg.get("default_model")
        )
        self._rebuild_models(selected)
        self.input_panel.set_thinking(values["deep_thinking"])
        self.input_panel.set_web_search(values["web_search"])
        self.input_panel.set_effort(values["default_effort"])
        self.apply_theme(values["theme"])
        if self.cfg.get("harness_warm_start", True):
            self._schedule_harness_warm()
        self._close_settings()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self._app.setStyleSheet(build_qss(theme))
        palette = colors(theme)
        self._hover_tips.set_theme(theme)
        self.mode_selector.apply_theme(theme)
        self.mode_bar.setStyleSheet(
            f"QFrame#modeBar{{background:{palette['canvas']};"
            f"border-bottom:1px solid {palette['border']};}}"
        )
        self.sidebar.apply_theme(theme)
        self.chat_workspace.apply_theme(theme)
        self.welcome_logo.setPixmap(
            tint_pixmap(
                QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(64, 64),
                palette["fg"],
            )
        )
        self.chat_view.apply_theme(theme)
        self.input_panel.apply_theme(theme)
        if self._settings_page is not None:
            self._settings_page.apply_theme(theme)
        self.harness_page.apply_theme(theme)
        self.model_combo.set_theme(theme)
        if self._notice_dialog is not None and isValid(self._notice_dialog):
            self._notice_dialog.apply_theme(theme)
            if self._notice_dialog.isVisible():
                self._center_notice(self._notice_dialog)
        configured = bool((self.cfg.get("api_key") or "").strip())
        self.api_status.setText("API 已配置" if configured else "需要 API 密钥")
        if configured:
            self.api_status.setStyleSheet("")
        else:
            self.api_status.setStyleSheet(
                f"color:{palette['danger']};background:{palette['danger_soft']};"
                "border-radius:10px;padding:4px 9px;font-size:11px;font-weight:600;"
            )

    def closeEvent(self, event) -> None:
        self._closing = True
        self._warm_start_armed = False
        self._warm_start_pending = False
        if self._settings_page is not None:
            self._settings_page.cancel_pending_request()
        if self._notice_dialog is not None and isValid(self._notice_dialog):
            self._notice_dialog.close()
        self._hover_tips.hide()
        workers = list(self._workers)
        for worker in workers:
            worker.cancel()
        for worker in workers:
            if not worker.wait(12000):
                worker.terminate()
                worker.wait(1000)
        self._streams.clear()
        self._workers.clear()
        title_workers = list(self._title_workers)
        for worker in title_workers:
            worker.cancel()
        for worker in title_workers:
            if not worker.wait(5000):
                worker.terminate()
                worker.wait(1000)
        self.chat_view.dispose()
        self.harness_page.stop()
        for _ in range(2):
            QCoreApplication.sendPostedEvents(
                None, QEvent.Type.DeferredDelete
            )
        self._draft_dir.remove()
        super().closeEvent(event)

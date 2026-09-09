from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QDir, QEvent, QTemporaryDir, Qt, QTimer, Signal
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
    QMessageBox,
    QPushButton,
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
    save_config,
    supports_thinking,
)
from ..worker import ChatWorker, TitleWorker
from .icons import apply_icon
from .image_strip import ImageStrip
from .message_bubbles import AssistantBubble, ChatView
from .controls import HoverTipManager, NoticeDialog, RoundedComboBox
from .settings_dialog import SettingsPage
from .sidebar import Sidebar
from .theme import SIDEBAR_DEFAULT_WIDTH, build_qss, colors


class ChatTextEdit(QTextEdit):
    submitRequested = Signal()
    imagePasted = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chatInput")
        self.setAcceptDrops(False)
        self.setAcceptRichText(False)
        self.setMinimumHeight(42)
        self.setMaximumHeight(138)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._ime_active = False
        self.document().contentsChanged.connect(self._fit_height)
        self._fit_height()

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

    def set_placeholder(self, vision: bool) -> None:
        text = "给 DeepSeek 发送消息"
        if vision:
            text += "，或拖入图片"
        self.setPlaceholderText(text)

    def _fit_height(self) -> None:
        document_height = int(self.document().size().height())
        self.setFixedHeight(min(138, max(42, document_height + 10)))


class InputPanel(QWidget):
    filesDropped = Signal(list)
    attachRequested = Signal()
    submitRequested = Signal()
    stopRequested = Signal()
    thinkingChanged = Signal(bool)
    effortChanged = Signal(str)
    notice = Signal(str)

    def __init__(
        self,
        editor: ChatTextEdit,
        thinking: bool,
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

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 6, 24, 14)
        root.setSpacing(7)
        row = QHBoxLayout()
        row.addStretch()

        self.card = QFrame()
        self.card.setObjectName("composerCard")
        self.card.setMaximumWidth(880)
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
        card_layout.addWidget(self.editor)

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
        hint = QLabel(
            "Enter 发送 · Shift + Enter 换行 · 内容由 AI 生成，请仔细甄别"
        )
        hint.setObjectName("tinyLabel")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(hint)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 5)
        self.card.setGraphicsEffect(shadow)
        self._shadow = shadow
        self.apply_theme(theme)
        self._update_action()

    def current_effort(self) -> str:
        return str(self.effort_combo.currentData() or "high")

    def is_thinking(self) -> bool:
        return self.thinking_button.isChecked()

    def set_thinking(self, enabled: bool) -> None:
        self.thinking_button.setChecked(enabled and self._thinking_available)

    def set_thinking_available(self, enabled: bool) -> None:
        self._thinking_available = enabled
        if not enabled:
            self.thinking_button.setChecked(False)
        self.thinking_button.setEnabled(enabled and not self._generating)
        self.effort_combo.setEnabled(
            enabled and not self._generating and self.is_thinking()
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
        self.attach_button.setEnabled(not self._generating)
        self.attach_button.setToolTip(
            "添加图片" if enabled else "当前模型不支持图片"
        )

    def set_generating(self, generating: bool) -> None:
        self._generating = generating
        self.editor.setReadOnly(generating)
        self.attach_button.setEnabled(not generating)
        self.thinking_button.setEnabled(self._thinking_available and not generating)
        self.effort_combo.setEnabled(
            self._thinking_available and not generating and self.is_thinking()
        )
        self.action_button.setObjectName("stopBtn" if generating else "actionBtn")
        self.action_button.style().unpolish(self.action_button)
        self.action_button.style().polish(self.action_button)
        self._update_action()

    def _thinking_toggled(self, enabled: bool) -> None:
        self.effort_combo.setEnabled(
            enabled and self._thinking_available and not self._generating
        )
        self.thinkingChanged.emit(enabled)
        self.apply_theme(self._theme)

    def _trigger_action(self) -> None:
        if self._generating:
            self.stopRequested.emit()
        else:
            self.submitRequested.emit()

    def _update_action(self) -> None:
        has_content = bool(self.editor.toPlainText().strip() or self.image_strip.paths())
        self.action_button.setEnabled(self._generating or has_content)
        self.apply_theme(self._theme)

    def _image_urls(self, event) -> list[str]:
        if not event.mimeData().hasUrls():
            return []
        return [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile() and is_image_path(url.toLocalFile())
        ]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._vision and self._image_urls(event) and not self._generating:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._vision and self._image_urls(event) and not self._generating:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._image_urls(event)
        if self._vision and paths and not self._generating:
            event.acceptProposedAction()
            self.filesDropped.emit(paths)
        else:
            event.ignore()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        apply_icon(self.attach_button, "add-square", "#9BCBFF", 20)
        self.effort_combo.set_theme(theme)
        apply_icon(
            self.thinking_button,
            "sparkle",
            palette["accent"] if self.is_thinking() else palette["fg_sub"],
            17,
        )
        if self._generating:
            apply_icon(self.action_button, "stop", "#FFFFFF", 18)
            self.action_button.setToolTip("停止生成")
        else:
            color = "#FFFFFF" if self.action_button.isEnabled() else palette["fg_muted"]
            apply_icon(self.action_button, "send", color, 19)
            self.action_button.setToolTip("发送")
        self.image_strip.set_style(theme)
        self._shadow.setColor(QColor(palette["shadow"]))


@dataclass
class StreamContext:
    conversation_id: str
    bubble: AssistantBubble
    model: str
    effort: str
    thinking: bool
    content: str = ""
    reasoning: str = ""
    stopped: bool = False


class MainWindow(QMainWindow):
    def __init__(self, cfg: dict, store, app: QApplication) -> None:
        super().__init__()
        self.cfg = cfg
        self.store = store
        self._app = app
        self._theme = cfg.get("theme", "light")
        self._current_conversation_id: str | None = None
        self._context: StreamContext | None = None
        self._worker: ChatWorker | None = None
        self._title_workers: set[TitleWorker] = set()
        self._title_worker_by_conversation: dict[str, TitleWorker] = {}
        self._notice_dialog: NoticeDialog | None = None
        self._hover_tips = HoverTipManager(app, self._theme, self)
        draft_template = str(Path(QDir.tempPath()) / "deepseek-chat-draft-XXXXXX")
        self._draft_dir = QTemporaryDir(draft_template)
        self.setWindowTitle("DeepSeek Chat")
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

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

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
        self.sidebar.settingsRequested.connect(self.open_settings)
        self.sidebar.collapseRequested.connect(self._toggle_sidebar)
        self.splitter.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self._build_header(right_layout)

        self.stack = QStackedWidget()
        self.welcome = self._build_welcome()
        self.chat_view = ChatView()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.chat_view)
        right_layout.addWidget(self.stack, 1)

        self.chat_input = ChatTextEdit()
        self.input_panel = InputPanel(
            self.chat_input,
            bool(self.cfg.get("deep_thinking", True)),
            self.cfg.get("last_effort", "high"),
            self._theme,
        )
        self.chat_input.submitRequested.connect(self.on_send)
        self.chat_input.imagePasted.connect(self._on_image_pasted)
        self.input_panel.filesDropped.connect(self._add_images)
        self.input_panel.attachRequested.connect(self._choose_images)
        self.input_panel.submitRequested.connect(self.on_send)
        self.input_panel.stopRequested.connect(self.on_stop)
        self.input_panel.thinkingChanged.connect(self._thinking_changed)
        self.input_panel.effortChanged.connect(self._effort_changed)
        self.input_panel.notice.connect(self._show_notice)
        right_layout.addWidget(self.input_panel)

        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([SIDEBAR_DEFAULT_WIDTH, 1280 - SIDEBAR_DEFAULT_WIDTH])

        self.settings_page = SettingsPage(self.cfg)
        self.settings_page.saveRequested.connect(self._save_settings)
        self.settings_page.cancelRequested.connect(self._close_settings)
        self.page_stack.addWidget(self.chat_page)
        self.page_stack.addWidget(self.settings_page)
        self.page_stack.setCurrentWidget(self.chat_page)

    def _build_header(self, parent_layout: QVBoxLayout) -> None:
        header = QWidget()
        header.setObjectName("chatHeader")
        header.setFixedHeight(58)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 8, 16, 8)
        layout.setSpacing(8)

        self.sidebar_button = QToolButton()
        self.sidebar_button.setFixedSize(34, 34)
        self.sidebar_button.setToolTip("展开或收起侧边栏")
        self.sidebar_button.clicked.connect(self._toggle_sidebar)
        layout.addWidget(self.sidebar_button)

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
        self.header_settings = QToolButton()
        self.header_settings.setFixedSize(34, 34)
        self.header_settings.setToolTip("设置")
        self.header_settings.clicked.connect(self.open_settings)
        layout.addWidget(self.header_settings)
        parent_layout.addWidget(header)

    def _build_welcome(self) -> QWidget:
        page = QWidget()
        page.setObjectName("welcomePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 20, 36, 10)
        layout.addStretch(2)

        logo = QLabel()
        logo.setPixmap(
            QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(64, 64)
        )
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        layout.addSpacing(12)
        title = QLabel("有什么可以帮到你？")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(7)
        subtitle = QLabel("调用你自己的 DeepSeek API，对话记录仅保存在本机")
        subtitle.setObjectName("subText")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(26)

        suggestions = QWidget()
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
        layout.addStretch(3)
        return page

    def show_welcome(self) -> None:
        self.stack.setCurrentWidget(self.welcome)
        self.sidebar.set_current(None)
        self.chat_input.setFocus()

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

    def _effort_changed(self, effort: str) -> None:
        if effort in EFFORT_LEVELS:
            self.cfg["last_effort"] = effort
            save_config(self.cfg)

    def _toggle_sidebar(self) -> None:
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def refresh_sidebar(self, selected: str | None = None) -> None:
        current = selected if selected is not None else self._current_conversation_id
        self.sidebar.refresh(self.store.conversations(), current)

    def on_new_chat(self) -> None:
        self._stop_current()
        self._current_conversation_id = None
        self.chat_view.clear()
        self.chat_input.clear()
        self.input_panel.image_strip.clear()
        self.show_welcome()

    def on_select_conversation(self, conversation_id: str) -> None:
        if self._context and self._context.conversation_id != conversation_id:
            self.on_stop()
        conversation = self.store.get(conversation_id)
        if conversation is None:
            return
        self._current_conversation_id = conversation_id
        # Give formula-capable message views their final visible width before
        # restoring history so KaTeX can compute overflow and height once.
        self.stack.setCurrentWidget(self.chat_view)
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
                    ),
                    thinking=thinking,
                    stopped=bool(message.get("stopped", False)),
                )
            elif role == "system" and not message.get("hidden", False):
                self.chat_view.add_error(message.get("content", "请求失败"))
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
        result = QMessageBox.question(
            self,
            "删除对话",
            (
                f"确定删除“{conversation.get('title', '该对话')}”吗？\n"
                "对话消息和本地图片会一起删除。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        if self._context and self._context.conversation_id == conversation_id:
            self.on_stop()
        self._cancel_title_summary(conversation_id)
        self.store.delete(conversation_id)
        if self._current_conversation_id == conversation_id:
            self._current_conversation_id = None
            self.chat_view.clear()
            self.show_welcome()
        self.refresh_sidebar()

    def on_delete_conversations(self, conversation_ids: list[str]) -> None:
        if not conversation_ids:
            return
        result = QMessageBox.question(
            self,
            "删除多个对话",
            (
                f"确定删除选中的 {len(conversation_ids)} 个对话吗？\n"
                "相关消息和本地图片会一起删除。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        if self._context and self._context.conversation_id in conversation_ids:
            self.on_stop()
        for conversation_id in conversation_ids:
            self._cancel_title_summary(conversation_id)
        self.store.delete_many(conversation_ids)
        if self._current_conversation_id in conversation_ids:
            self._current_conversation_id = None
            self.chat_view.clear()
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
        if self._context is not None:
            return
        text = self.chat_input.toPlainText().strip()
        staged_images = self.input_panel.image_strip.paths()
        if not text and not staged_images:
            return
        if not (self.cfg.get("api_key") or "").strip():
            self._show_notice("请先在设置中填写 API 密钥")
            self.open_settings()
            return
        if staged_images and not is_vision_model(self.current_model()):
            self._show_notice("当前模型不支持已添加的图片")
            return

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
        }
        self.store.append_message(conversation_id, user_message)
        self.stack.setCurrentWidget(self.chat_view)
        self.chat_view.add_user(text, stored_images)
        self.input_panel.image_strip.clear()
        self.chat_input.clear()
        self.refresh_sidebar(conversation_id)
        self._start_request(conversation_id, model, effort, thinking)

    @staticmethod
    def _message_meta(model: str, effort: str, thinking: bool) -> str:
        if thinking:
            return f"{model_label(model)} · 深度思考 {effort_label(effort)}"
        return f"{model_label(model)} · 标准模式"

    def _start_request(
        self,
        conversation_id: str,
        model: str,
        effort: str,
        thinking: bool,
    ) -> None:
        conversation = self.store.get(conversation_id)
        if conversation is None:
            return
        try:
            messages = payload_messages(conversation.get("messages", []))
        except Exception as exc:
            self.chat_view.add_error(f"无法读取图片：{exc}")
            return
        bubble = self.chat_view.add_streaming(
            self._message_meta(model, effort, thinking), thinking
        )
        self._context = StreamContext(
            conversation_id,
            bubble,
            model,
            effort,
            thinking,
        )
        worker = ChatWorker(
            self.cfg,
            model,
            effort,
            thinking,
            messages,
            float(self.cfg.get("temperature", 1.0)),
            int(self.cfg.get("max_tokens", 0)),
        )
        self._worker = worker
        worker.chunk.connect(self._on_chunk)
        worker.reasoning.connect(self._on_reasoning)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(lambda: self._clear_worker(worker))
        self._set_generating(True)
        worker.start()

    def _set_generating(self, generating: bool) -> None:
        self.model_combo.setEnabled(not generating)
        self.input_panel.set_generating(generating)

    def _on_chunk(self, text: str) -> None:
        context = self._context
        if context is None:
            return
        # 正文首段到达时，气泡会结束思考动画并显示答案。
        context.content += text
        if isValid(context.bubble):
            context.bubble.set_content(context.content)
            self.chat_view.message_updated(context.bubble)

    def _on_reasoning(self, text: str) -> None:
        context = self._context
        if context is None:
            return
        context.reasoning += text
        if isValid(context.bubble):
            context.bubble.set_reasoning(context.reasoning)
            self.chat_view.message_updated(context.bubble)

    def _assistant_record(self, context: StreamContext) -> dict:
        return {
            "role": "assistant",
            "content": context.content,
            "reasoning_content": context.reasoning or None,
            "images": [],
            "model": context.model,
            "effort": context.effort,
            "thinking": context.thinking,
            "stopped": context.stopped,
        }

    def _on_done(self) -> None:
        context = self._context
        if context is None:
            return
        self._context = None
        self._set_generating(False)
        self.store.append_message(
            context.conversation_id, self._assistant_record(context)
        )
        if isValid(context.bubble):
            context.bubble.finish(context.stopped)
            self.chat_view.message_updated(context.bubble)
        self.refresh_sidebar()
        self._start_title_summary(context.conversation_id, context.model)
        self.chat_input.setFocus()

    def _on_failed(self, message: str) -> None:
        context = self._context
        if context is None:
            return
        self._context = None
        self._set_generating(False)
        if context.content or context.reasoning:
            context.stopped = True
            self.store.append_message(
                context.conversation_id, self._assistant_record(context)
            )
            if isValid(context.bubble):
                context.bubble.fail(f"生成中断：{message}")
                self.chat_view.message_updated(context.bubble)
            self._start_title_summary(context.conversation_id, context.model)
        else:
            if isValid(context.bubble):
                self.chat_view.remove_bubble(context.bubble)
                self.chat_view.add_error(message)
        self.refresh_sidebar()

    def on_stop(self) -> None:
        if self._context is None:
            return
        self._context.stopped = True
        if self._worker:
            self._worker.cancel()

    def _stop_current(self) -> None:
        self.on_stop()

    def _clear_worker(self, worker: ChatWorker) -> None:
        if self._worker is worker:
            self._worker = None
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
        self.settings_page.load_config(self.cfg)
        self.page_stack.setCurrentWidget(self.settings_page)

    def _close_settings(self) -> None:
        self.page_stack.setCurrentWidget(self.chat_page)
        self.chat_input.setFocus()

    def _save_settings(self, values: dict) -> None:
        previous_model = self.current_model()
        self.cfg.update(values)
        save_config(self.cfg)
        selected = (
            previous_model
            if previous_model in values["models"]
            else values["default_model"]
        )
        self._rebuild_models(selected)
        self.input_panel.set_thinking(values["deep_thinking"])
        self.input_panel.set_effort(values["default_effort"])
        self.apply_theme(values["theme"])
        self._close_settings()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self._app.setStyleSheet(build_qss(theme))
        palette = colors(theme)
        self._hover_tips.set_theme(theme)
        self.sidebar.apply_theme(theme)
        self.chat_view.apply_theme(theme)
        self.input_panel.apply_theme(theme)
        self.settings_page.apply_theme(theme)
        self.model_combo.set_theme(theme)
        if self._notice_dialog is not None and isValid(self._notice_dialog):
            self._notice_dialog.apply_theme(theme)
            if self._notice_dialog.isVisible():
                self._center_notice(self._notice_dialog)
        apply_icon(self.sidebar_button, "sidebar", palette["fg_sub"], 20)
        apply_icon(self.header_settings, "settings", palette["fg_sub"], 19)
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
        self.settings_page.cancel_pending_request()
        if self._notice_dialog is not None and isValid(self._notice_dialog):
            self._notice_dialog.close()
        self._hover_tips.hide()
        if self._worker:
            self._worker.cancel()
            if not self._worker.wait(12000):
                self._worker.terminate()
                self._worker.wait(1000)
        title_workers = list(self._title_workers)
        for worker in title_workers:
            worker.cancel()
        for worker in title_workers:
            if not worker.wait(5000):
                worker.terminate()
                worker.wait(1000)
        self._draft_dir.remove()
        super().closeEvent(event)

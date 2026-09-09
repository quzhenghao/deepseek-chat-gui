from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import ASSETS_DIR
from .controls import RoundedMenu
from .icons import apply_icon
from .theme import SIDEBAR_DEFAULT_WIDTH, SIDEBAR_MIN_WIDTH, colors


def _format_time(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return ""
    now = datetime.now()
    if timestamp.date() == now.date():
        return timestamp.strftime("%H:%M")
    if timestamp.year == now.year:
        return timestamp.strftime("%m月%d日")
    return timestamp.strftime("%Y年%m月%d日")


class ConversationItem(QWidget):
    selected = Signal(str)
    renameRequested = Signal(str)
    deleteRequested = Signal(str)
    checkChanged = Signal()

    def __init__(
        self,
        conversation: dict,
        batch_mode: bool,
        checked: bool,
        theme: str,
    ) -> None:
        super().__init__()
        self.conversation_id = conversation["id"]
        self._theme = theme
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 5, 5, 5)
        layout.setSpacing(7)
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        self.checkbox.setVisible(batch_mode)
        self.checkbox.toggled.connect(lambda _: self.checkChanged.emit())
        layout.addWidget(self.checkbox)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        self.title = QLabel(conversation.get("title") or "新对话")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setToolTip(conversation.get("title") or "新对话")
        self.title.setSizePolicy(
            self.title.sizePolicy().horizontalPolicy().Ignored,
            self.title.sizePolicy().verticalPolicy(),
        )
        self.time = QLabel(_format_time(conversation.get("updated_at", "")))
        self.time.setObjectName("timeLabel")
        self.time.setStyleSheet("font-size:11px;")
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.time)
        layout.addLayout(text_layout, 1)

        self.more_button = QToolButton()
        self.more_button.setFixedSize(28, 28)
        self.more_button.setToolTip("更多操作")
        self.more_button.clicked.connect(self._show_menu)
        self.more_button.hide()
        layout.addWidget(self.more_button)
        self.apply_theme(theme)

    def set_checked(self, checked: bool) -> None:
        self.checkbox.setChecked(checked)

    def _show_menu(self) -> None:
        menu = RoundedMenu(self._theme, self)
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        chosen = menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))
        if chosen is rename_action:
            self.renameRequested.emit(self.conversation_id)
        elif chosen is delete_action:
            self.deleteRequested.emit(self.conversation_id)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.conversation_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self._show_menu()

    def enterEvent(self, event) -> None:
        self.more_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.more_button.hide()
        super().leaveEvent(event)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        self.setStyleSheet("background:transparent;")
        self.title.setStyleSheet(f"color:{palette['fg']};background:transparent;")
        self.time.setStyleSheet(
            f"color:{palette['fg_muted']};background:transparent;font-size:11px;"
        )
        apply_icon(self.more_button, "more", palette["fg_sub"], 18)


class Sidebar(QWidget):
    newChatRequested = Signal()
    conversationSelected = Signal(str)
    renameConversation = Signal(str)
    deleteConversation = Signal(str)
    deleteConversations = Signal(list)
    settingsRequested = Signal()
    collapseRequested = Signal()

    def __init__(self, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setMinimumWidth(SIDEBAR_MIN_WIDTH)
        self.setMaximumWidth(SIDEBAR_DEFAULT_WIDTH)
        self._theme = theme
        self._batch_mode = False
        self._checked: dict[str, bool] = {}
        self._items: dict[str, ConversationItem] = {}
        self._list_items: dict[str, QListWidgetItem] = {}
        self._current_id: str | None = None
        self._build_ui()
        self.apply_theme(theme)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 17, 16, 16)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 0)
        header.setSpacing(9)
        mark = QLabel()
        mark.setPixmap(
            QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(30, 30)
        )
        mark.setFixedSize(30, 30)
        header.addWidget(mark)
        brand = QLabel("deepseek")
        brand.setObjectName("settingsBrand")
        header.addWidget(brand)
        header.addStretch()
        self.collapse_button = QToolButton()
        self.collapse_button.setFixedSize(30, 30)
        self.collapse_button.setToolTip("收起侧边栏")
        self.collapse_button.clicked.connect(self.collapseRequested.emit)
        header.addWidget(self.collapse_button)
        root.addLayout(header)
        root.addSpacing(18)

        self.new_button = QPushButton("新建对话")
        self.new_button.setObjectName("settingsNavBtn")
        self.new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_button.clicked.connect(self.newChatRequested.emit)
        self.new_button.setIconSize(QSize(18, 18))
        root.addWidget(self.new_button)

        section = QHBoxLayout()
        section.setContentsMargins(8, 0, 0, 2)
        recent = QLabel("最近对话")
        recent.setObjectName("sectionLabel")
        section.addWidget(recent)
        section.addStretch()
        self.batch_button = QToolButton()
        self.batch_button.setCheckable(True)
        self.batch_button.setFixedSize(28, 28)
        self.batch_button.setToolTip("批量选择")
        self.batch_button.toggled.connect(self._set_batch_mode)
        section.addWidget(self.batch_button)
        root.addLayout(section)

        self.batch_bar = QWidget()
        batch_layout = QHBoxLayout(self.batch_bar)
        batch_layout.setContentsMargins(2, 0, 2, 0)
        batch_layout.setSpacing(6)
        self.select_all = QCheckBox("全选")
        self.select_all.toggled.connect(self._select_all)
        batch_layout.addWidget(self.select_all)
        batch_layout.addStretch()
        self.delete_selected = QPushButton("删除 0 项")
        self.delete_selected.setObjectName("dangerBtn")
        self.delete_selected.clicked.connect(self._delete_checked)
        batch_layout.addWidget(self.delete_selected)
        self.batch_bar.hide()
        root.addWidget(self.batch_bar)

        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("convList")
        self.conversation_list.setSpacing(1)
        self.conversation_list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self.conversation_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.conversation_list.currentItemChanged.connect(self._selection_changed)
        root.addWidget(self.conversation_list, 1)

        self.empty_label = QLabel("还没有对话\n发一条消息开始吧")
        self.empty_label.setObjectName("hintLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("line-height:1.5;")
        root.addWidget(self.empty_label, 1)

        local_hint = QLabel("对话与图片仅保存在本机")
        local_hint.setObjectName("tinyLabel")
        local_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(local_hint)

        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("sidebarFooterBtn")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        self.settings_button.setIconSize(QSize(18, 18))
        root.addWidget(self.settings_button)

    def refresh(self, conversations: list[dict], current_id: str | None) -> None:
        self._current_id = current_id
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        self._items.clear()
        self._list_items.clear()
        valid_ids = {conversation["id"] for conversation in conversations}
        self._checked = {
            key: value for key, value in self._checked.items() if key in valid_ids
        }
        for conversation in conversations:
            conversation_id = conversation["id"]
            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, conversation_id)
            list_item.setSizeHint(QSize(0, 52))
            widget = ConversationItem(
                conversation,
                self._batch_mode,
                self._checked.get(conversation_id, False),
                self._theme,
            )
            widget.selected.connect(self._select_id)
            widget.renameRequested.connect(self.renameConversation.emit)
            widget.deleteRequested.connect(self.deleteConversation.emit)
            widget.checkChanged.connect(self._update_count)
            self.conversation_list.addItem(list_item)
            self.conversation_list.setItemWidget(list_item, widget)
            self._items[conversation_id] = widget
            self._list_items[conversation_id] = list_item
            if conversation_id == current_id:
                list_item.setSelected(True)
        self.conversation_list.blockSignals(False)
        has_items = bool(conversations)
        self.conversation_list.setVisible(has_items)
        self.empty_label.setVisible(not has_items)
        self._update_count()

    def set_current(self, conversation_id: str | None) -> None:
        self._current_id = conversation_id
        self.conversation_list.blockSignals(True)
        for identifier, item in self._list_items.items():
            item.setSelected(identifier == conversation_id)
        if conversation_id in self._list_items:
            self.conversation_list.scrollToItem(self._list_items[conversation_id])
        self.conversation_list.blockSignals(False)

    def _select_id(self, conversation_id: str) -> None:
        if self._batch_mode:
            widget = self._items.get(conversation_id)
            if widget:
                widget.set_checked(not widget.checkbox.isChecked())
            return
        self.set_current(conversation_id)
        self.conversationSelected.emit(conversation_id)

    def _selection_changed(self, current, previous) -> None:
        if current is None or self._batch_mode:
            return
        conversation_id = current.data(Qt.ItemDataRole.UserRole)
        if conversation_id and conversation_id != self._current_id:
            self._current_id = conversation_id
            self.conversationSelected.emit(conversation_id)

    def _set_batch_mode(self, active: bool) -> None:
        self._batch_mode = active
        self.batch_bar.setVisible(active)
        for widget in self._items.values():
            widget.checkbox.setVisible(active)
        if not active:
            self._checked.clear()
            self.select_all.blockSignals(True)
            self.select_all.setChecked(False)
            self.select_all.blockSignals(False)
        self._update_count()

    def _select_all(self, checked: bool) -> None:
        for conversation_id, widget in self._items.items():
            widget.checkbox.blockSignals(True)
            widget.set_checked(checked)
            widget.checkbox.blockSignals(False)
            self._checked[conversation_id] = checked
        self._update_count()

    def _collect_checked(self) -> list[str]:
        self._checked = {
            conversation_id: widget.checkbox.isChecked()
            for conversation_id, widget in self._items.items()
        }
        return [key for key, checked in self._checked.items() if checked]

    def _update_count(self) -> None:
        checked = self._collect_checked()
        self.delete_selected.setText(f"删除 {len(checked)} 项")
        self.delete_selected.setEnabled(bool(checked))

    def _delete_checked(self) -> None:
        checked = self._collect_checked()
        if checked:
            self.deleteConversations.emit(checked)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        palette = colors(theme)
        apply_icon(self.collapse_button, "sidebar", palette["fg_sub"], 19)
        apply_icon(self.new_button, "plus", palette["accent"], 18)
        apply_icon(self.batch_button, "select", palette["fg_sub"], 17)
        apply_icon(self.settings_button, "settings", palette["fg_sub"], 18)
        for item in self._items.values():
            item.apply_theme(theme)

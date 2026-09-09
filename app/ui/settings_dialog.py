from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import ASSETS_DIR
from ..config import (
    DEFAULT_BASE_URL,
    EFFORT_LEVELS,
    effort_label,
    include_unlisted_builtin_models,
    model_label,
    uses_official_api,
)
from .controls import NoWheelSpinBox, RoundedComboBox
from .icons import apply_icon
from .theme import SIDEBAR_DEFAULT_WIDTH, build_qss, colors


class SettingsPage(QWidget):
    """Full-window settings surface embedded in the main application."""

    saveRequested = Signal(dict)
    cancelRequested = Signal()

    def __init__(self, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self._cfg = dict(cfg)
        self._theme = cfg.get("theme", "light")
        self._loading = False
        self._connection_state: bool | None = None
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._probe_timed_out = False
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.timeout.connect(self._connection_timeout)
        self._build_ui()
        self.load_config(cfg)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(SIDEBAR_DEFAULT_WIDTH)
        self.sidebar = sidebar
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 17, 16, 16)
        sidebar_layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(4, 0, 4, 0)
        brand_row.setSpacing(9)
        mark = QLabel()
        mark.setPixmap(QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(30, 30))
        mark.setFixedSize(30, 30)
        brand_row.addWidget(mark)
        brand = QLabel("设置")
        brand.setObjectName("settingsBrand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        sidebar_layout.addLayout(brand_row)
        sidebar_layout.addSpacing(18)

        section_label = QLabel("设置")
        section_label.setObjectName("sectionLabel")
        section_label.setContentsMargins(8, 0, 0, 2)
        sidebar_layout.addWidget(section_label)

        self.basic_button = self._nav_button("基础配置")
        self.personalization_button = self._nav_button("个性化")
        sidebar_layout.addWidget(self.basic_button)
        sidebar_layout.addWidget(self.personalization_button)
        sidebar_layout.addStretch()

        local_hint = QLabel("设置仅保存在当前电脑")
        local_hint.setObjectName("tinyLabel")
        local_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(local_hint)

        self.back_button = QPushButton("返回聊天")
        self.back_button.setObjectName("settingsBackBtn")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self._cancel)
        sidebar_layout.addWidget(self.back_button)
        root.addWidget(sidebar)

        right = QWidget()
        right.setObjectName("settingsRight")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("settingsHeader")
        header.setFixedHeight(72)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(30, 10, 30, 10)
        header_layout.setSpacing(10)
        heading = QVBoxLayout()
        heading.setSpacing(1)
        self.page_title = QLabel()
        self.page_title.setObjectName("settingsPageTitle")
        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("hintLabel")
        heading.addWidget(self.page_title)
        heading.addWidget(self.page_subtitle)
        header_layout.addLayout(heading)
        header_layout.addStretch()
        self.validation_status = QLabel()
        self.validation_status.setObjectName("settingsValidation")
        self.validation_status.hide()
        header_layout.addWidget(self.validation_status)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self._cancel)
        header_layout.addWidget(self.cancel_button)
        self.save_button = QPushButton("保存设置")
        self.save_button.setObjectName("primaryBtn")
        self.save_button.clicked.connect(self._save)
        header_layout.addWidget(self.save_button)
        right_layout.addWidget(header)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("settingsContentStack")
        self.content_stack.addWidget(self._build_basic_page())
        self.content_stack.addWidget(self._build_personalization_page())
        right_layout.addWidget(self.content_stack, 1)
        root.addWidget(right, 1)

        self.navigation = QButtonGroup(self)
        self.navigation.setExclusive(True)
        self.navigation.addButton(self.basic_button, 0)
        self.navigation.addButton(self.personalization_button, 1)
        self.navigation.idClicked.connect(self.select_section)
        self.select_section(0)

    @staticmethod
    def _nav_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("settingsNavBtn")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _content_host(self) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        host = QWidget()
        host.setObjectName("settingsHost")
        outer = QHBoxLayout(host)
        outer.setContentsMargins(30, 26, 30, 36)
        outer.setSpacing(0)
        outer.addStretch()
        content = QWidget()
        content.setObjectName("settingsContent")
        content.setMaximumWidth(820)
        sections = QVBoxLayout(content)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setSpacing(14)
        outer.addWidget(content, 1)
        outer.addStretch()
        scroll.setWidget(host)
        return scroll, sections

    def _build_basic_page(self) -> QWidget:
        scroll, sections = self._content_host()

        connection, connection_form = self._section(
            "API 连接", "密钥只保存在当前电脑，不会写入项目源码。"
        )
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-…")
        self.show_key = QToolButton()
        self.show_key.setCheckable(True)
        self.show_key.setFixedSize(32, 32)
        self.show_key.setToolTip("显示密钥")
        self.show_key.toggled.connect(self._toggle_key)
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self._test_connection)
        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(self.show_key)
        key_row.addWidget(self.test_button)
        connection_form.addRow("API 密钥", key_row)

        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText(DEFAULT_BASE_URL)
        connection_form.addRow("API 地址", self.base_url)
        self.connection_status = QLabel("可先测试连接并同步账号可用模型")
        self.connection_status.setObjectName("hintLabel")
        self.connection_status.setWordWrap(True)
        connection_form.addRow("", self.connection_status)
        sections.addWidget(connection)

        generation, generation_form = self._section(
            "生成设置", "选择新对话默认使用的模型与生成方式。"
        )
        self.default_model = RoundedComboBox(self._theme)
        generation_form.addRow("默认模型", self.default_model)

        self.deep_thinking = QCheckBox("默认开启深度思考")
        generation_form.addRow("思考模式", self.deep_thinking)

        self.default_effort = RoundedComboBox(self._theme)
        for effort in EFFORT_LEVELS:
            self.default_effort.addItem(effort_label(effort), effort)
        generation_form.addRow("默认强度", self.default_effort)

        self.max_tokens = NoWheelSpinBox()
        self.max_tokens.setRange(0, 384000)
        self.max_tokens.setSingleStep(1024)
        self.max_tokens.setSpecialValueText("使用模型默认值")
        generation_form.addRow("最大输出", self.max_tokens)
        sections.addWidget(generation)

        appearance, appearance_form = self._section(
            "外观", "主题会在当前设置页立即预览，保存后应用到主界面。"
        )
        self.theme_combo = RoundedComboBox(self._theme)
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.currentIndexChanged.connect(self._preview_theme)
        appearance_form.addRow("界面主题", self.theme_combo)
        sections.addWidget(appearance)

        models, models_form = self._section(
            "模型列表", "每行一个 API 模型 ID；测试连接成功时会自动同步。"
        )
        self.models_edit = QPlainTextEdit()
        self.models_edit.setPlaceholderText("deepseek-v4-flash")
        self.models_edit.setFixedHeight(104)
        self.models_edit.textChanged.connect(self._models_changed)
        models_form.addRow("模型 ID", self.models_edit)
        sections.addWidget(models)
        sections.addStretch()
        return scroll

    def _build_personalization_page(self) -> QWidget:
        scroll, sections = self._content_host()
        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(8)

        heading = QLabel("系统提示词注入")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        hint = QLabel(
            "保存后，每个新对话都会在首条用户消息之前自动加入这段系统提示词。"
            "它不会显示为聊天气泡，也不会改写已经存在的对话。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(8)

        self.system_prompt_edit = QPlainTextEdit()
        self.system_prompt_edit.setObjectName("systemPromptEdit")
        self.system_prompt_edit.setPlaceholderText(
            "例如：你是一位严谨、耐心的助手。请始终使用简体中文回答，并在不确定时明确说明。"
        )
        self.system_prompt_edit.setMinimumHeight(280)
        self.system_prompt_edit.textChanged.connect(self._update_prompt_count)
        layout.addWidget(self.system_prompt_edit)

        prompt_footer = QHBoxLayout()
        prompt_footer.setContentsMargins(2, 2, 2, 0)
        prompt_note = QLabel("留空则不注入系统提示词")
        prompt_note.setObjectName("tinyLabel")
        prompt_footer.addWidget(prompt_note)
        prompt_footer.addStretch()
        self.prompt_count = QLabel("0 字")
        self.prompt_count.setObjectName("tinyLabel")
        prompt_footer.addWidget(self.prompt_count)
        layout.addLayout(prompt_footer)
        sections.addWidget(card)
        sections.addStretch()
        return scroll

    @staticmethod
    def _section(title: str, subtitle: str) -> tuple[QFrame, QFormLayout]:
        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        hint = QLabel(subtitle)
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:11px;")
        layout.addWidget(hint)
        layout.addSpacing(8)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addLayout(form)
        return card, form

    def select_section(self, index: int) -> None:
        if index not in {0, 1}:
            return
        self.content_stack.setCurrentIndex(index)
        button = self.navigation.button(index) if hasattr(self, "navigation") else None
        if button is not None:
            button.setChecked(True)
        titles = (
            ("基础配置", "管理 API、默认模型与界面外观"),
            ("个性化", "为每个新对话设置专属的系统提示词"),
        )
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])
        self._clear_validation()

    def load_config(self, cfg: dict) -> None:
        self._cfg = dict(cfg)
        self._loading = True
        self.api_key.setText(str(cfg.get("api_key", "")))
        self.show_key.setChecked(False)
        self.base_url.setText(str(cfg.get("base_url", DEFAULT_BASE_URL)))
        self._fill_models(cfg.get("models", []), cfg.get("default_model", ""))
        self.deep_thinking.setChecked(bool(cfg.get("deep_thinking", True)))
        effort_index = self.default_effort.findData(cfg.get("default_effort", "high"))
        self.default_effort.setCurrentIndex(max(0, effort_index))
        self.max_tokens.setValue(int(cfg.get("max_tokens", 0)))
        theme_index = self.theme_combo.findData(cfg.get("theme", "light"))
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        self.models_edit.blockSignals(True)
        self.models_edit.setPlainText("\n".join(cfg.get("models", [])))
        self.models_edit.blockSignals(False)
        self.system_prompt_edit.setPlainText(str(cfg.get("system_prompt", "")))
        self._connection_state = None
        self.connection_status.setText("可先测试连接并同步账号可用模型")
        self._loading = False
        self.select_section(0)
        self._update_prompt_count()
        self.apply_theme(str(cfg.get("theme", "light")))

    def _fill_models(self, models: list[str], selected: str) -> None:
        self.default_model.blockSignals(True)
        self.default_model.clear()
        for model in models:
            self.default_model.addItem(model_label(model), model)
        index = self.default_model.findData(selected)
        self.default_model.setCurrentIndex(max(0, index))
        self.default_model.blockSignals(False)

    def _model_lines(self) -> list[str]:
        models: list[str] = []
        for line in self.models_edit.toPlainText().splitlines():
            value = line.strip()
            if value and value not in models:
                models.append(value)
        return models

    def _models_changed(self) -> None:
        current = self.default_model.currentData()
        self._fill_models(self._model_lines(), current)

    def _toggle_key(self, visible: bool) -> None:
        self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.show_key.setToolTip("隐藏密钥" if visible else "显示密钥")
        self._apply_icons()

    def _test_connection(self) -> None:
        if self._reply and self._reply.isRunning():
            return
        api_key = self.api_key.text().strip()
        base_url = self.base_url.text().strip().rstrip("/")
        if not api_key or not base_url:
            self._set_status("请先填写 API 密钥和地址", False)
            return
        request = QNetworkRequest(QUrl(f"{base_url}/models"))
        request.setRawHeader(b"Authorization", f"Bearer {api_key}".encode())
        self._reply = self._network.get(request)
        self._reply.finished.connect(self._connection_finished)
        self._probe_timed_out = False
        self._probe_timer.start(15000)
        self.test_button.setEnabled(False)
        self.test_button.setText("连接中…")
        self._set_status("正在验证密钥并读取模型列表…", None)

    def _connection_finished(self) -> None:
        reply = self._reply
        self._reply = None
        self._probe_timer.stop()
        self.test_button.setEnabled(True)
        self.test_button.setText("测试连接")
        if reply is None:
            return
        try:
            if self._probe_timed_out:
                self._set_status("连接超时，请检查网络或 API 地址", False)
                return
            payload = bytes(reply.readAll()).decode("utf-8", errors="replace")
            if reply.error() != QNetworkReply.NetworkError.NoError:
                detail = reply.errorString()
                try:
                    body = json.loads(payload)
                    detail = body.get("error", {}).get("message", detail)
                except (ValueError, AttributeError):
                    pass
                self._set_status(f"连接失败：{detail}", False)
                return
            data = json.loads(payload)
            listed_models = [
                item["id"]
                for item in data.get("data", [])
                if isinstance(item, dict) and item.get("id")
            ]
            if not listed_models:
                self._set_status("连接成功，但接口没有返回模型", False)
                return
            models = list(listed_models)
            if uses_official_api(self.base_url.text()):
                models = include_unlisted_builtin_models(models)
            self.models_edit.setPlainText("\n".join(models))
            extra_count = len(models) - len(listed_models)
            if extra_count:
                self._set_status(
                    f"连接成功，已同步 {len(listed_models)} 个接口模型，"
                    f"并保留 {extra_count} 个限时模型",
                    True,
                )
            else:
                self._set_status(f"连接成功，已同步 {len(models)} 个模型", True)
        except (ValueError, TypeError):
            self._set_status("连接成功，但响应格式无法识别", False)
        finally:
            self._probe_timed_out = False
            reply.deleteLater()

    def _connection_timeout(self) -> None:
        if self._reply and self._reply.isRunning():
            self._probe_timed_out = True
            self._reply.abort()

    def _set_status(self, text: str, success: bool | None) -> None:
        self._connection_state = success
        palette = colors(self._theme)
        color = palette["fg_sub"]
        if success is True:
            color = palette["success"]
        elif success is False:
            color = palette["danger"]
        self.connection_status.setText(text)
        self.connection_status.setStyleSheet(f"color:{color};font-size:11px;")

    def _preview_theme(self) -> None:
        if not self._loading:
            self.apply_theme(str(self.theme_combo.currentData()))

    def _update_prompt_count(self) -> None:
        self.prompt_count.setText(f"{len(self.system_prompt_edit.toPlainText())} 字")

    def _show_validation(self, text: str) -> None:
        self.validation_status.setText(text)
        self.validation_status.setStyleSheet(
            f"color:{colors(self._theme)['danger']};font-size:12px;"
        )
        self.validation_status.show()

    def _clear_validation(self) -> None:
        self.validation_status.clear()
        self.validation_status.hide()

    def _save(self) -> None:
        base_url = self.base_url.text().strip()
        models = self._model_lines()
        if not base_url.startswith(("https://", "http://")):
            self.select_section(0)
            self._show_validation("API 地址需要以 http:// 或 https:// 开头")
            self.base_url.setFocus()
            return
        if not models:
            self.select_section(0)
            self._show_validation("请至少保留一个模型 ID")
            self.models_edit.setFocus()
            return
        values = self.values()
        self._cfg.update(values)
        self._clear_validation()
        self.saveRequested.emit(values)

    def _cancel(self) -> None:
        self.cancel_pending_request()
        self.load_config(self._cfg)
        self.cancelRequested.emit()

    def values(self) -> dict:
        return {
            "api_key": self.api_key.text().strip(),
            "base_url": self.base_url.text().strip().rstrip("/"),
            "models": self._model_lines(),
            "default_model": self.default_model.currentData(),
            "default_effort": self.default_effort.currentData(),
            "deep_thinking": self.deep_thinking.isChecked(),
            "max_tokens": self.max_tokens.value(),
            "theme": self.theme_combo.currentData(),
            "system_prompt": self.system_prompt_edit.toPlainText().strip(),
        }

    def _apply_icons(self) -> None:
        palette = colors(self._theme)
        name = "eye-off" if self.show_key.isChecked() else "eye"
        apply_icon(self.show_key, name, palette["fg_sub"], 18)
        apply_icon(self.basic_button, "settings", palette["fg_sub"], 18)
        apply_icon(self.personalization_button, "sparkle", palette["fg_sub"], 18)
        apply_icon(self.back_button, "arrow-left", palette["fg_sub"], 18)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self.setStyleSheet(build_qss(theme))
        self.default_model.set_theme(theme)
        self.default_effort.set_theme(theme)
        self.theme_combo.set_theme(theme)
        self._apply_icons()
        self._set_status(self.connection_status.text(), self._connection_state)
        if self.validation_status.isVisible() and self.validation_status.text():
            self._show_validation(self.validation_status.text())

    def cancel_pending_request(self) -> None:
        if self._reply and self._reply.isRunning():
            self._reply.abort()


# Keep the former import name working for callers while the surface itself is no
# longer a dialog.
SettingsDialog = SettingsPage

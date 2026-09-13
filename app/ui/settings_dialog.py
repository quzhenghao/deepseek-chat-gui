from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    MAX_OUTPUT_TOKENS,
    APP_DIR,
    effort_label,
    normalize_official_models,
    model_label,
    uses_official_api,
)
from ..harness import (
    HARNESS_DISPLAY_VERSION,
    HARNESS_DOCS_URL,
    HARNESS_REPOSITORY_URL,
    bundled_harness_available,
    find_node,
    find_npx,
    harness_home,
)
from .controls import (
    FlatLineEdit,
    FlatPlainTextEdit,
    NoWheelSpinBox,
    RoundedComboBox,
)
from .icons import apply_icon, tint_pixmap
from .theme import (
    BRAND_BADGE_SIZE,
    BRAND_MARK_SIZE,
    BRAND_WORDMARK_SIZE,
    RIGHT_HEADER_HEIGHT,
    RIGHT_HEADER_MARGINS,
    RIGHT_HEADER_SPACING,
    SIDEBAR_DEFAULT_WIDTH,
    build_qss,
    colors,
)

NODE_DOWNLOAD_URL = "https://nodejs.org/en/download"


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
        brand_row.setSpacing(8)
        self.brand_mark = QLabel()
        self.brand_mark.setFixedSize(BRAND_MARK_SIZE, BRAND_MARK_SIZE)
        brand_row.addWidget(self.brand_mark)
        self.brand_wordmark = QLabel("deepseek")
        self.brand_wordmark.setObjectName("settingsBrandWordmark")
        brand_row.addWidget(self.brand_wordmark, 0, Qt.AlignmentFlag.AlignVCenter)
        self.brand_badge = QLabel("CHAT")
        self.brand_badge.setObjectName("brandBadge")
        brand_row.addWidget(self.brand_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.brand = QLabel("DeepSeek")
        self.brand.setObjectName("settingsBrand")
        self.brand.setAccessibleName("DeepSeek")
        self.brand.hide()
        brand_row.addStretch()
        sidebar_layout.addLayout(brand_row)
        sidebar_layout.addSpacing(18)

        section_label = QLabel("设置")
        section_label.setObjectName("sectionLabel")
        section_label.setContentsMargins(8, 0, 0, 2)
        sidebar_layout.addWidget(section_label)

        self.basic_button = self._nav_button("基础配置")
        self.personalization_button = self._nav_button("个性化")
        self.environment_button = self._nav_button("运行环境")
        sidebar_layout.addWidget(self.basic_button)
        sidebar_layout.addWidget(self.personalization_button)
        sidebar_layout.addWidget(self.environment_button)
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
        header.setFixedHeight(RIGHT_HEADER_HEIGHT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(*RIGHT_HEADER_MARGINS)
        header_layout.setSpacing(RIGHT_HEADER_SPACING)
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
        self.content_stack.addWidget(self._build_environment_page())
        right_layout.addWidget(self.content_stack, 1)
        root.addWidget(right, 1)

        self.navigation = QButtonGroup(self)
        self.navigation.setExclusive(True)
        self.navigation.addButton(self.basic_button, 0)
        self.navigation.addButton(self.personalization_button, 1)
        self.navigation.addButton(self.environment_button, 2)
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
            "API连接", "密钥只保存在当前电脑，不会写入项目源码。"
        )
        self.api_key = FlatLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-…")
        self.show_key = QToolButton()
        self.show_key.setCheckable(True)
        self.show_key.setFixedSize(32, 32)
        self.show_key.setToolTip("显示密钥")
        self.show_key.toggled.connect(self._toggle_key)
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self._test_connection)
        self.first_run_hint = QLabel(
            "首次使用：填入API密钥 → 测试连接 → 保存设置，即可开始对话"
        )
        self.first_run_hint.setObjectName("onboardingHint")
        self.first_run_hint.setWordWrap(True)
        connection_form.addRow("", self.first_run_hint)
        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(self.show_key)
        key_row.addWidget(self.test_button)
        connection_form.addRow("API密钥", key_row)

        self.base_url = FlatLineEdit()
        self.base_url.setPlaceholderText(DEFAULT_BASE_URL)
        connection_form.addRow("API地址", self.base_url)
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

        self.web_search = QCheckBox("默认开启联网搜索")
        generation_form.addRow("联网搜索", self.web_search)

        self.search_provider = RoundedComboBox(self._theme)
        self.search_provider.addItem("DuckDuckGo(免费，无需密钥)", "duckduckgo")
        self.search_provider.addItem("Tavily(更稳定，需API-Key)", "tavily")
        generation_form.addRow("搜索服务商", self.search_provider)

        self.search_api_key = FlatLineEdit()
        self.search_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.search_api_key.setPlaceholderText("tvly-…")
        generation_form.addRow("搜索API-Key", self.search_api_key)

        self.default_effort = RoundedComboBox(self._theme)
        for effort in EFFORT_LEVELS:
            self.default_effort.addItem(effort_label(effort), effort)
        generation_form.addRow("默认强度", self.default_effort)

        self.max_tokens = NoWheelSpinBox()
        self.max_tokens.setRange(0, MAX_OUTPUT_TOKENS)
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
            "模型列表", "每行一个API模型ID；测试连接成功时会自动同步"
        )
        self.models_edit = FlatPlainTextEdit()
        self.models_edit.setPlaceholderText("deepseek-flash")
        self.models_edit.setFixedHeight(104)
        self.models_edit.textChanged.connect(self._models_changed)
        models_form.addRow("模型ID", self.models_edit)
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

        self.system_prompt_edit = FlatPlainTextEdit()
        self.system_prompt_edit.setObjectName("systemPromptEdit")
        self.system_prompt_edit.setPlaceholderText(
            "例如：你是一位严谨、耐心的助手。请始终使用简体中文回答，并在不确定时明确说明"
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

    def _build_environment_page(self) -> QWidget:
        scroll, sections = self._content_host()

        runtime, runtime_form = self._section(
            "运行环境",
            "查看客户端、Node.js与官方Harness运行包状态。完整安装包会优先使用内置运行环境",
        )
        self.environment_status = QLabel()
        self.environment_status.setObjectName("environmentStatus")
        self.environment_status.setWordWrap(True)
        self.environment_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        runtime_form.addRow("当前状态", self.environment_status)

        runtime_actions = QHBoxLayout()
        runtime_actions.setSpacing(8)
        self.refresh_environment_button = QPushButton("重新检测")
        self.refresh_environment_button.clicked.connect(self._refresh_environment)
        runtime_actions.addWidget(self.refresh_environment_button)
        self.open_config_button = QPushButton("打开配置目录")
        self.open_config_button.clicked.connect(self._open_config_directory)
        runtime_actions.addWidget(self.open_config_button)
        self.node_download_button = QPushButton("Node.js更新入口")
        self.node_download_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(NODE_DOWNLOAD_URL))
        )
        runtime_actions.addWidget(self.node_download_button)
        runtime_actions.addStretch()
        runtime_form.addRow("操作", runtime_actions)
        sections.addWidget(runtime)

        harness, harness_form = self._section(
            "Harness预热与项目",
            "Harness是官方开发者预览版。启动Chat后会在后台提前准备，让首次切换更顺畅。",
        )
        self.harness_warm_start = QCheckBox("启动时预热Harness(推荐)")
        harness_form.addRow("启动行为", self.harness_warm_start)

        self.harness_projects_edit = FlatPlainTextEdit()
        self.harness_projects_edit.setPlaceholderText(
            "可选：每行一个项目目录；留空则使用当前工作目录"
        )
        self.harness_projects_edit.setFixedHeight(86)
        project_row = QHBoxLayout()
        project_row.setSpacing(8)
        project_row.addWidget(self.harness_projects_edit, 1)
        self.choose_project_button = QPushButton("选择目录")
        self.choose_project_button.clicked.connect(self._choose_harness_project)
        project_row.addWidget(self.choose_project_button, 0, Qt.AlignmentFlag.AlignTop)
        harness_form.addRow("项目目录", project_row)

        links = QHBoxLayout()
        links.setSpacing(8)
        self.harness_docs_button = QPushButton("官方文档")
        self.harness_docs_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(HARNESS_DOCS_URL))
        )
        links.addWidget(self.harness_docs_button)
        self.harness_repository_button = QPushButton("官方仓库")
        self.harness_repository_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(HARNESS_REPOSITORY_URL))
        )
        links.addWidget(self.harness_repository_button)
        links.addStretch()
        harness_form.addRow("帮助", links)
        sections.addWidget(harness)

        note, note_form = self._section(
            "安全提示",
            "Harness可能执行模型生成的命令或修改项目文件。请只授予必要的项目目录，并认真处理页面中的审批提示",
        )
        note_label = QLabel(
            f"数据目录：{harness_home()}\n"
            "API密钥通过进程环境传递给Harness，不会写入Harness配置文件。"
        )
        note_label.setObjectName("hintLabel")
        note_label.setWordWrap(True)
        note_form.addRow("本地数据", note_label)
        sections.addWidget(note)
        sections.addStretch()
        self._refresh_environment()
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
        if index not in {0, 1, 2}:
            return
        self.content_stack.setCurrentIndex(index)
        button = self.navigation.button(index) if hasattr(self, "navigation") else None
        if button is not None:
            button.setChecked(True)
        titles = (
            ("基础配置", "管理API、默认模型与界面外观"),
            ("个性化", "为每个新对话设置专属的系统提示词"),
            ("运行环境", "检查 Harness 依赖、项目目录与启动行为"),
        )
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])
        self._clear_validation()

    def load_config(self, cfg: dict) -> None:
        self._cfg = dict(cfg)
        self._loading = True
        self.api_key.setText(str(cfg.get("api_key", "")))
        self.first_run_hint.setVisible(not bool(str(cfg.get("api_key", "")).strip()))
        self.show_key.setChecked(False)
        self.base_url.setText(str(cfg.get("base_url", DEFAULT_BASE_URL)))
        self._fill_models(cfg.get("models", []), cfg.get("default_model", ""))
        self.deep_thinking.setChecked(bool(cfg.get("deep_thinking", True)))
        self.web_search.setChecked(bool(cfg.get("web_search", True)))
        provider_index = self.search_provider.findData(
            cfg.get("search_provider", "duckduckgo")
        )
        self.search_provider.setCurrentIndex(max(0, provider_index))
        self.search_api_key.setText(str(cfg.get("search_api_key", "")))
        effort_index = self.default_effort.findData(cfg.get("default_effort", "high"))
        self.default_effort.setCurrentIndex(max(0, effort_index))
        self.max_tokens.setValue(int(cfg.get("max_tokens", 0)))
        theme_index = self.theme_combo.findData(cfg.get("theme", "light"))
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        self.models_edit.blockSignals(True)
        self.models_edit.setPlainText("\n".join(cfg.get("models", [])))
        self.models_edit.blockSignals(False)
        self.system_prompt_edit.setPlainText(str(cfg.get("system_prompt", "")))
        self.harness_warm_start.setChecked(bool(cfg.get("harness_warm_start", True)))
        self.harness_projects_edit.blockSignals(True)
        self.harness_projects_edit.setPlainText(
            "\n".join(cfg.get("harness_projects", []))
        )
        self.harness_projects_edit.blockSignals(False)
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

    def _project_lines(self) -> list[str]:
        projects: list[str] = []
        for line in self.harness_projects_edit.toPlainText().splitlines():
            value = str(Path(line.strip()).expanduser()) if line.strip() else ""
            if value and value not in projects:
                projects.append(value)
        return projects

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
            self._set_status("请先填写API密钥和地址", False)
            return
        request = QNetworkRequest(QUrl(f"{base_url}/models"))
        request.setRawHeader(b"Authorization", f"Bearer {api_key}".encode())
        self._reply = self._network.get(request)
        self._reply.finished.connect(self._connection_finished)
        self._probe_timed_out = False
        self._probe_timer.start(15000)
        self.test_button.setEnabled(False)
        self.test_button.setText("连接中...")
        self._set_status("正在验证密钥并读取模型列表...", None)

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
                self._set_status("连接超时，请检查网络或API地址", False)
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
                models = normalize_official_models(models)
                if not models:
                    self._set_status(
                        "连接成功，但账号没有返回当前客户端支持的模型",
                        False,
                    )
                    return
            self.models_edit.setPlainText("\n".join(models))
            if uses_official_api(self.base_url.text()):
                self._set_status(
                    f"连接成功，已同步{len(models)}个当前可用模型",
                    True,
                )
            else:
                self._set_status(f"连接成功，已同步{len(models)}个模型", True)
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

    def _choose_harness_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择Harness项目目录",
            str(Path.home()),
        )
        if not directory:
            return
        projects = self._project_lines()
        if directory not in projects:
            projects.append(directory)
        self.harness_projects_edit.setPlainText("\n".join(projects))

    def _open_config_directory(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_DIR)))

    def _refresh_environment(self) -> None:
        node = find_node()
        npx = find_npx()
        node_version = "未找到"
        if node:
            try:
                result = subprocess.run(
                    [node, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                node_version = result.stdout.strip() or "可执行"
            except (OSError, subprocess.SubprocessError):
                node_version = "可执行"
        harness_state = (
            f"已内置（{HARNESS_DISPLAY_VERSION}）"
            if bundled_harness_available()
            else f"按需准备({HARNESS_DISPLAY_VERSION})"
        )
        self.environment_status.setText(
            f"Node.js：{node_version}\n"
            f"npx：{npx or '未找到'}\n"
            f"Harness：{harness_state}\n"
            f"应用数据：{APP_DIR}"
        )

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
            self._show_validation("API地址需要以http://或https://开头")
            self.base_url.setFocus()
            return
        if not models:
            self.select_section(0)
            self._show_validation("请至少保留一个模型ID")
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
            "web_search": self.web_search.isChecked(),
            "search_provider": self.search_provider.currentData(),
            "search_api_key": self.search_api_key.text().strip(),
            "max_tokens": self.max_tokens.value(),
            "theme": self.theme_combo.currentData(),
            "system_prompt": self.system_prompt_edit.toPlainText().strip(),
            "harness_projects": self._project_lines(),
            "harness_warm_start": self.harness_warm_start.isChecked(),
        }

    def _apply_icons(self) -> None:
        palette = colors(self._theme)
        name = "eye-off" if self.show_key.isChecked() else "eye"
        apply_icon(self.show_key, name, palette["fg_sub"], 18)
        apply_icon(self.basic_button, "settings", palette["fg_sub"], 18)
        apply_icon(self.personalization_button, "sparkle", palette["fg_sub"], 18)
        apply_icon(self.environment_button, "refresh", palette["fg_sub"], 18)
        apply_icon(self.back_button, "arrow-left", palette["entry_fg"], 18)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self.setStyleSheet(build_qss(theme))
        palette = colors(theme)
        self.brand_mark.setPixmap(
            tint_pixmap(
                QIcon(str(ASSETS_DIR / "deepseek-mark.svg")).pixmap(
                    BRAND_MARK_SIZE, BRAND_MARK_SIZE
                ),
                palette["fg"],
            )
        )
        self.brand_wordmark.setStyleSheet(
            f"color:{palette['fg']};background:transparent;"
            f"font-size:{BRAND_WORDMARK_SIZE}px;font-weight:650;"
        )
        self.brand_badge.setStyleSheet(
            "color:#FFFFFF;background:#171717;border-radius:4px;"
            f"padding:3px 6px 2px 6px;font-size:{BRAND_BADGE_SIZE}px;font-weight:750;"
        )
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


SettingsDialog = SettingsPage

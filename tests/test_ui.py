from __future__ import annotations

import json
import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import ASSETS_DIR
from app.config import (
    DEFAULTS,
    EFFORT_LABELS,
    EFFORT_LEVELS,
    MODEL_CAPABILITIES,
    V41_FLASH_MODEL,
    effort_label,
    is_vision_model,
    model_label,
    supports_thinking,
)
from app.api import payload_messages
from app.ui.controls import (
    ConfirmationDialog,
    HoverTipWidget,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    NoticeDialog,
    RoundedComboBox,
    RoundedMenu,
)
from app.ui.main_window import MainWindow
from app.ui.message_bubbles import ChatView, ThinkingIndicator
from app.ui.sidebar import ProductModeSelector
from app.ui.theme import SIDEBAR_DEFAULT_WIDTH, SIDEBAR_MIN_WIDTH, colors


class MemoryStore:
    def __init__(self) -> None:
        self._items: list[dict] = []

    def conversations(self) -> list[dict]:
        return list(reversed(self._items))

    def get(self, conversation_id: str):
        return next(
            (item for item in self._items if item["id"] == conversation_id),
            None,
        )

    def create(self, title: str = "新对话") -> dict:
        conversation = {
            "id": f"conversation-{len(self._items) + 1}",
            "title": title,
            "created_at": "",
            "updated_at": "",
            "messages": [],
        }
        self._items.append(conversation)
        return conversation

    def rename(self, conversation_id: str, title: str) -> None:
        conversation = self.get(conversation_id)
        if conversation is not None:
            conversation["title"] = title

    def update_title(self, conversation_id: str, title: str) -> None:
        conversation = self.get(conversation_id)
        if conversation is not None:
            conversation["title"] = title

    def append_message(self, conversation_id: str, message: dict) -> None:
        conversation = self.get(conversation_id)
        if conversation is not None:
            conversation["messages"].append(message)

    def delete(self, conversation_id: str) -> None:
        self._items = [
            item for item in self._items if item["id"] != conversation_id
        ]

    def delete_many(self, conversation_ids: list[str]) -> None:
        identifiers = set(conversation_ids)
        self._items = [
            item for item in self._items if item["id"] not in identifiers
        ]


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        # The suite repeatedly closes its last top-level widget. Keep the shared
        # application alive so a later Qt WebEngine view is not initialized
        # after QApplication has already entered its quit path.
        cls.app.setQuitOnLastWindowClosed(False)

    def wait_for(self, predicate, timeout_ms: int = 5000) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            QTest.qWait(10)
        self.app.processEvents()
        return bool(predicate())

    def javascript_value(self, page, script: str, timeout_ms: int = 3000):
        result: list[object] = []
        page.runJavaScript(script, result.append)
        self.assertTrue(self.wait_for(lambda: bool(result), timeout_ms))
        return result[0]

    def test_streaming_reasoning_is_animated_and_collapsed(self) -> None:
        view = ChatView()
        view.resize(900, 600)
        view.show()
        bubble = view.add_streaming("DeepSeek V4.1 Flash · 深度思考 High", True)
        bubble.set_reasoning("内部思考内容")
        self.app.processEvents()
        self.assertTrue(bubble.reasoning_panel.indicator._timer.isActive())
        self.assertFalse(bubble.reasoning_panel.reasoning_view.isVisible())
        bubble.set_content("最终答案")
        bubble.finish()
        self.app.processEvents()
        self.assertFalse(bubble.reasoning_panel.indicator._timer.isActive())
        self.assertTrue(bubble.content_view.isVisible())
        view.close()

    def test_streaming_switches_to_math_only_after_delimiter_closes(self) -> None:
        view = ChatView()
        view.resize(900, 600)
        view.show()
        bubble = view.add_streaming("DeepSeek V4.1 Flash · 标准模式", False)
        bubble.set_content(r"正在生成：\[\frac{a}")
        QTest.qWait(80)
        self.app.processEvents()
        self.assertIsNone(bubble.content_view._web_view)

        bubble.set_content(r"正在生成：\[\frac{a}{b}\] 已完成。")
        bubble.finish()
        web_view = bubble.content_view._web_view
        self.assertIsNotNone(web_view)
        self.assertTrue(
            self.wait_for(
                lambda: bubble.content_view._stack.currentWidget() is web_view
            )
        )
        count = self.javascript_value(
            web_view.page(), "document.querySelectorAll('.katex').length"
        )
        self.assertEqual(count, 1)
        view.close()

    def test_short_user_message_bubble_uses_its_natural_width(self) -> None:
        view = ChatView()
        view.resize(900, 600)
        view.show()
        short = view.add_user("什么是证据理论的正交和")
        self.app.processEvents()
        self.assertLess(short.card.width(), 360)
        self.assertEqual(short.card.width(), short.text_view.width() + 28)

        long = view.add_user("很长的提问内容" * 100)
        self.app.processEvents()
        self.assertEqual(long.card.width(), 680)
        view.close()

    def test_plain_assistant_content_does_not_create_a_web_renderer(self) -> None:
        view = ChatView()
        view.resize(900, 600)
        view.show()
        bubble = view.add_assistant("普通 Markdown 回答，不包含数学公式。", thinking=False)
        self.app.processEvents()
        self.assertIsNone(bubble.content_view._web_view)
        self.assertGreater(bubble.content_view.height(), 20)
        view.close()

    def test_code_block_uses_copyable_web_renderer(self) -> None:
        view = ChatView()
        view.resize(720, 900)
        view.show()
        bubble = view.add_assistant(
            "下面这段代码可直接复制：\n\n"
            "~~~python\n"
            "print('hello from DeepSeek')\n"
            "~~~",
            thinking=False,
        )
        web_view = bubble.content_view._web_view
        self.assertIsNotNone(web_view)
        self.assertTrue(
            self.wait_for(
                lambda: bubble.content_view._stack.currentWidget() is web_view,
                timeout_ms=5000,
            )
        )
        self.assertEqual(
            self.javascript_value(
                web_view.page(),
                "document.querySelectorAll('.code-copy').length",
            ),
            1,
        )
        self.assertEqual(
            self.javascript_value(
                web_view.page(),
                "document.querySelector('.code-language').textContent",
            ),
            "Python",
        )
        web_view.page().runJavaScript(
            "document.querySelector('.code-copy').click()"
        )
        self.assertTrue(
            self.wait_for(
                lambda: QApplication.clipboard().text()
                == "print('hello from DeepSeek')\n",
                timeout_ms=3000,
            )
        )
        view.close()

    def test_math_uses_katex_dom_layout_and_responsive_overflow(self) -> None:
        view = ChatView()
        view.resize(560, 900)
        view.show()
        long_formula = (
            r"\mathcal{L}(\theta)=\sum_{i=1}^{n}\left["
            r"y_i\log\sigma(\theta^Tx_i)+(1-y_i)"
            r"\log(1-\sigma(\theta^Tx_i))\right]"
            r"+\lambda\sum_{j=1}^{m}|\theta_j|"
            r"+\frac{\alpha}{2}\sum_{j=1}^{m}\theta_j^2"
        )
        content = (
            r"行内 $P(A\mid B)=\frac{P(B\mid A)P(A)}{P(B)}$ 对齐。"
            "\n\n"
            r"\[A=\begin{pmatrix}a&b\\c&d\end{pmatrix},\quad "
            r"f(x)=\begin{cases}x^2,&x\ge0\\-x,&x<0\end{cases}\]"
            "\n\n"
            rf"\[{long_formula}\]"
        )
        bubble = view.add_assistant(content, thinking=False)
        web_view = bubble.content_view._web_view
        self.assertIsNotNone(web_view)
        self.assertTrue(
            self.wait_for(
                lambda: bubble.content_view._stack.currentWidget() is web_view
                and web_view.height() > 22
            )
        )
        # Font metrics settle asynchronously in Chromium; the production
        # ResizeObserver/document.fonts hooks refresh overflow after this point.
        QTest.qWait(350)
        self.app.processEvents()

        metrics_script = """
          JSON.stringify({
            katex: document.querySelectorAll('.katex').length,
            mathml: document.querySelectorAll('math').length,
            mtables: document.querySelectorAll('mtable').length,
            images: document.images.length,
            canvases: document.querySelectorAll('canvas').length,
            rootHeight: document.getElementById('content-root')
              .getBoundingClientRect().height,
            dpr: window.devicePixelRatio,
            overflow: [...document.querySelectorAll('.math-display-shell')]
              .map((element) => ({
                overflowing: element.dataset.overflowing,
                clientWidth: element.clientWidth,
                scrollWidth: element.scrollWidth
              }))
          })
        """
        narrow = json.loads(self.javascript_value(web_view.page(), metrics_script))
        self.assertEqual(narrow["katex"], 3)
        self.assertEqual(narrow["mathml"], 3)
        self.assertGreaterEqual(narrow["mtables"], 2)
        self.assertEqual(narrow["images"], 0)
        self.assertEqual(narrow["canvases"], 0)
        self.assertLessEqual(narrow["rootHeight"], web_view.height())
        self.assertTrue(
            any(
                item["overflowing"] == "true"
                and item["scrollWidth"] > item["clientWidth"]
                for item in narrow["overflow"]
            )
        )
        scroll_state = json.loads(
            self.javascript_value(
                web_view.page(),
                """
                (() => {
                  const element = document.querySelector(
                    '.math-display-shell[data-overflowing="true"]'
                  );
                  element.scrollLeft = element.scrollWidth;
                  return JSON.stringify({
                    left: element.scrollLeft,
                    maximum: element.scrollWidth - element.clientWidth
                  });
                })()
                """,
            )
        )
        self.assertGreater(scroll_state["left"], 0)
        self.assertAlmostEqual(
            scroll_state["left"], scroll_state["maximum"], delta=2
        )

        view.resize(920, 900)
        self.assertTrue(self.wait_for(lambda: web_view.width() >= 760))
        QTest.qWait(150)
        self.app.processEvents()
        wide = json.loads(self.javascript_value(web_view.page(), metrics_script))
        self.assertTrue(
            all(item["overflowing"] == "false" for item in wide["overflow"])
        )
        self.assertLessEqual(wide["rootHeight"], web_view.height())

        # Vertical wheel input inside Chromium must continue scrolling the outer
        # chat instead of getting trapped in a fixed-height embedded page.
        view.resize(920, 180)
        self.assertTrue(self.wait_for(lambda: view.verticalScrollBar().maximum() > 0))
        view.verticalScrollBar().setValue(0)
        self.javascript_value(
            web_view.page(),
            "document.dispatchEvent(new WheelEvent('wheel', {deltaY: 120}))",
        )
        self.assertTrue(
            self.wait_for(lambda: view.verticalScrollBar().value() > 0)
        )
        view.close()

    def test_window_uses_official_model_id(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        self.assertEqual(window.current_model(), "deepseek-flash")
        self.assertTrue(window.input_panel.is_thinking())
        window.close()

    def test_controls_keep_values_when_wheeled(self) -> None:
        class FakeWheel:
            def __init__(self) -> None:
                self.ignored = False

            def ignore(self) -> None:
                self.ignored = True

        combo = RoundedComboBox()
        combo.addItems(["one", "two"])
        combo.setCurrentIndex(1)
        combo_event = FakeWheel()
        combo.wheelEvent(combo_event)
        self.assertTrue(combo_event.ignored)
        self.assertEqual(combo.currentIndex(), 1)

        integer = NoWheelSpinBox()
        integer.setValue(12)
        integer_event = FakeWheel()
        integer.wheelEvent(integer_event)
        self.assertTrue(integer_event.ignored)
        self.assertEqual(integer.value(), 12)
        self.assertFalse(integer.lineEdit().isReadOnly())
        integer.stepUp()
        self.assertEqual(integer.value(), 13)

        decimal = NoWheelDoubleSpinBox()
        decimal.setSingleStep(0.1)
        decimal.setValue(0.7)
        decimal_event = FakeWheel()
        decimal.wheelEvent(decimal_event)
        self.assertTrue(decimal_event.ignored)
        self.assertEqual(decimal.value(), 0.7)
        self.assertFalse(decimal.lineEdit().isReadOnly())
        decimal.stepDown()
        self.assertEqual(decimal.value(), 0.6)

    def test_context_menu_uses_the_same_rounded_surface_as_combo_popup(self) -> None:
        menu = RoundedMenu("light")
        menu.addAction("重命名")
        menu.addAction("删除")
        self.assertEqual(menu.minimumWidth(), 104)
        self.assertIn("border-radius: 12px", menu.styleSheet())
        self.assertIn("background: #EEEEEE", menu.styleSheet())
        self.assertIn("padding: 7px 10px", menu.styleSheet())

        menu.set_theme("dark")
        self.assertIn("background: #353535", menu.styleSheet())
        menu.resize(150, 100)
        menu.show()
        self.app.processEvents()
        self.assertFalse(menu.mask().isEmpty())
        menu.close()
        menu.deleteLater()

    def test_confirmation_dialog_has_symmetric_rounded_actions(self) -> None:
        dialog = ConfirmationDialog(
            "删除对话",
            "确定删除“测试对话”吗？\n对话消息和本地图片会一起删除。",
            "light",
        )
        dialog.show()
        self.app.processEvents()

        self.assertEqual(dialog.windowType(), Qt.WindowType.Tool)
        self.assertEqual(dialog.no_button.text(), "No")
        self.assertEqual(dialog.yes_button.text(), "Yes")
        self.assertEqual(dialog.no_button.size(), dialog.yes_button.size())
        action_midpoint = (
            dialog.no_button.geometry().center().x()
            + dialog.yes_button.geometry().center().x()
        ) / 2
        self.assertAlmostEqual(
            action_midpoint, dialog.card.rect().center().x(), delta=1
        )
        self.assertTrue(dialog.no_button.isDefault())
        self.assertFalse(dialog.question_badge.pixmap().isNull())
        self.assertIn("border-radius: 16px", dialog.card.styleSheet())
        self.assertIn("border-radius: 10px", dialog.card.styleSheet())
        self.assertIn("background: #FFF1F0", dialog.card.styleSheet())

        dialog.apply_theme("dark")
        self.assertIn("background: #3A2426", dialog.card.styleSheet())
        dialog.close()
        dialog.deleteLater()

    def test_conversation_delete_uses_the_themed_confirmation(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        store = MemoryStore()
        conversation = store.create("待删除对话")
        window = MainWindow(cfg, store, self.app)

        with patch.object(ConfirmationDialog, "ask", return_value=False) as ask:
            window.on_delete_conversation(conversation["id"])
        self.assertIsNotNone(store.get(conversation["id"]))
        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[1], "删除对话")
        self.assertEqual(ask.call_args.args[3], "light")

        with patch.object(ConfirmationDialog, "ask", return_value=True):
            window.on_delete_conversation(conversation["id"])
        self.assertIsNone(store.get(conversation["id"]))
        window.close()

    def test_effort_labels_and_thinking_timer_are_explicit(self) -> None:
        self.assertEqual(EFFORT_LABELS, {"low": "Low", "high": "High", "max": "Max"})
        self.assertEqual(effort_label("高"), "High")
        self.assertEqual(set(MODEL_CAPABILITIES), set(DEFAULTS["models"]))
        for model, capabilities in MODEL_CAPABILITIES.items():
            self.assertTrue(supports_thinking(model))
            self.assertEqual(is_vision_model(model), capabilities["vision"])
            self.assertEqual(capabilities["efforts"], tuple(EFFORT_LEVELS))
        indicator = ThinkingIndicator()
        self.assertEqual(indicator._timer.interval(), 16)
        self.assertEqual(indicator._timer.timerType(), Qt.TimerType.PreciseTimer)
        indicator.deleteLater()

    def test_formula_history_restores_safely_inside_main_window(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        store = MemoryStore()
        conversation = store.create("公式历史")
        store.append_message(
            conversation["id"],
            {
                "role": "assistant",
                "content": (
                    r"\[A=\begin{pmatrix}1&2\\3&4\end{pmatrix}\]"
                ),
                "reasoning_content": None,
                "model": "deepseek-flash",
                "effort": "high",
                "thinking": False,
            },
        )
        window = MainWindow(cfg, store, self.app)
        window.resize(920, 700)
        window.show()
        window.on_select_conversation(conversation["id"])
        bubble = window.chat_view._bubbles[-1]
        web_view = bubble.content_view._web_view
        self.assertIsNotNone(web_view)
        self.assertTrue(
            self.wait_for(
                lambda: bubble.content_view._stack.currentWidget() is web_view
                and web_view.height() > 22
            )
        )
        count = self.javascript_value(
            web_view.page(), "document.querySelectorAll('.katex').length"
        )
        self.assertEqual(count, 1)
        window.close()

    def test_formula_pages_survive_repeated_clear_and_rebuild(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.resize(920, 700)
        window.show()
        window.stack.setCurrentWidget(window.chat_view)

        formula = (
            r"\[A=\begin{pmatrix}1&2\\3&4\end{pmatrix},\quad "
            r"f(x)=\begin{cases}x^2,&x\ge0\\-x,&x<0\end{cases}\]"
        )
        for cycle in range(3):
            bubbles = [
                window.chat_view.add_assistant(
                    f"第 {cycle + 1} 轮，第 {index + 1} 条。\n\n{formula}",
                    thinking=False,
                )
                for index in range(4)
            ]
            web_views = [bubble.content_view._web_view for bubble in bubbles]
            self.assertTrue(all(web_view is not None for web_view in web_views))
            self.assertTrue(
                self.wait_for(
                    lambda: all(
                        web_view is not None
                        and web_view._rendered_generation >= 0
                        and web_view.height() > 22
                        for web_view in web_views
                    ),
                    timeout_ms=8000,
                )
            )
            window._hover_tips._refresh_watched_widgets()
            window.chat_view.clear()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
            self.assertEqual(window.chat_view._bubbles, [])

        window.close()

    def test_current_v41_flash_model_is_labeled_and_multimodal(self) -> None:
        self.assertIn(V41_FLASH_MODEL, DEFAULTS["models"])
        self.assertEqual(
            model_label(V41_FLASH_MODEL),
            "DeepSeek V4.1 Flash",
        )
        self.assertTrue(is_vision_model(V41_FLASH_MODEL))
        self.assertTrue(supports_thinking(V41_FLASH_MODEL))

    def test_main_controls_use_rounded_model_and_add_icon(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        self.assertIsInstance(window.model_combo, RoundedComboBox)
        self.assertEqual(
            [window.model_combo.itemData(index) for index in range(window.model_combo.count())],
            DEFAULTS["models"],
        )
        self.assertEqual(
            [window.input_panel.effort_combo.itemData(index) for index in range(window.input_panel.effort_combo.count())],
            EFFORT_LEVELS,
        )
        self.assertEqual(
            window._message_meta("deepseek-flash", "high", True),
            "DeepSeek V4.1 Flash · 深度思考 High",
        )
        self.assertEqual(window.input_panel.attach_button.objectName(), "attachBtn")
        self.assertFalse(window.input_panel.attach_button.icon().isNull())
        window.close()

    def test_settings_uses_embedded_two_column_page(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        window.open_settings()
        self.app.processEvents()

        page = window.settings_page
        self.assertIs(window.page_stack.currentWidget(), page)
        self.assertIs(page.window(), window)
        self.assertEqual(page.basic_button.text(), "基础配置")
        self.assertEqual(page.personalization_button.text(), "个性化")
        self.assertTrue(page.basic_button.isChecked())
        self.assertFalse(hasattr(page, "temperature"))

        page.personalization_button.click()
        self.app.processEvents()
        self.assertEqual(page.content_stack.currentIndex(), 1)
        self.assertEqual(page.page_title.text(), "个性化")
        self.assertEqual(page.system_prompt_edit.objectName(), "systemPromptEdit")

        page.back_button.click()
        self.app.processEvents()
        self.assertIs(window.page_stack.currentWidget(), window.chat_page)
        window.close()

    def test_chat_harness_selector_switches_surfaces_and_keeps_runtime_warm(self) -> None:
        selector = ProductModeSelector()
        self.assertEqual(selector.mode(), "chat")
        self.assertEqual(
            [selector.mode_combo.itemData(i) for i in range(selector.mode_combo.count())],
            ["chat", "harness"],
        )
        self.assertEqual(selector.work_type_label.text(), "Work Type:")
        self.assertEqual(selector.chat_button.text(), "Chat")
        self.assertEqual(selector.harness_button.text(), "Harness")
        selector.harness_button.click()
        self.assertEqual(selector.mode(), "harness")
        selector.close()

        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        with (
            patch.object(window.harness_page, "start") as start,
            patch.object(window.harness_page, "stop") as stop,
        ):
            window.mode_selector.harness_button.click()
            self.app.processEvents()
            self.assertEqual(window._mode, "harness")
            self.assertIs(window.page_stack.currentWidget(), window.harness_page)
            start.assert_called_once()

            window.mode_selector.chat_button.click()
            self.app.processEvents()
            self.assertEqual(window._mode, "chat")
            self.assertIs(window.page_stack.currentWidget(), window.chat_page)
            # Switching products does not tear down the official runtime; the
            # close event remains responsible for releasing it.
            stop.assert_not_called()
            window.close()
            stop.assert_called_once()

    def test_harness_switcher_has_one_main_window_chrome_row(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        self.assertIs(window.mode_selector.parentWidget(), window.mode_bar)
        self.assertEqual(window.mode_bar.height(), 58)
        self.assertNotIn("mode_bar", window.harness_page.surface.__dict__)
        self.assertEqual(window.mode_selector.work_type_label.text(), "Work Type:")
        self.assertIn(
            f"background:{colors('light')['mode_active']}",
            window.mode_selector.styleSheet(),
        )
        with patch.object(window.harness_page, "start"):
            window.mode_selector.harness_button.click()
            self.app.processEvents()
        self.assertEqual(window.harness_page.surface.content_host.geometry().top(), 0)
        self.assertEqual(window.harness_page.surface.status_panel.geometry().top(), 0)
        self.assertEqual(
            window.harness_page.surface.status_panel.parentWidget(),
            window.harness_page.surface.content_host,
        )
        window.close()

    def test_native_brands_use_monochrome_logo_and_neutral_sidebars(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        palette = colors("light")
        self.assertEqual(window.sidebar.brand_label.text(), "DeepSeek")
        self.assertEqual(window.settings_page.brand.text(), "DeepSeek")
        self.assertEqual(window.windowTitle(), "DeepSeek")
        self.assertFalse(window.windowIcon().isNull())
        icon_source = (ASSETS_DIR / "app-icon.svg").read_text(encoding="utf-8")
        self.assertIn('fill="#171717"', icon_source)
        self.assertNotIn("#4D6BFE", icon_source)
        self.assertEqual(palette["side_bg"], "#F3F3F3")
        self.assertNotIn("#4D6BFE", window.mode_selector.styleSheet())
        window.close()

    def test_sidebar_widths_match_and_chat_defaults_to_maximum(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        self.assertEqual(window.sidebar.minimumWidth(), SIDEBAR_MIN_WIDTH)
        self.assertEqual(window.sidebar.maximumWidth(), SIDEBAR_DEFAULT_WIDTH)
        self.assertEqual(window.splitter.sizes()[0], SIDEBAR_DEFAULT_WIDTH)
        self.assertEqual(window.sidebar.width(), SIDEBAR_DEFAULT_WIDTH)

        # Dragging toward the right must stay at the maximum; dragging toward
        # the left must stop at the usable minimum.
        window.splitter.setSizes([900, 379])
        self.app.processEvents()
        self.assertEqual(window.sidebar.width(), SIDEBAR_DEFAULT_WIDTH)
        window.splitter.setSizes([100, 1179])
        self.app.processEvents()
        self.assertEqual(window.sidebar.width(), SIDEBAR_MIN_WIDTH)

        window.open_settings()
        self.app.processEvents()
        self.assertEqual(window.settings_page.sidebar.width(), SIDEBAR_DEFAULT_WIDTH)
        window.close()

    def test_personalization_setting_is_saved_from_embedded_page(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.open_settings()
        window.settings_page.personalization_button.click()
        window.settings_page.system_prompt_edit.setPlainText("  始终使用简体中文。  ")

        with patch("app.ui.main_window.save_config") as mocked_save:
            window.settings_page.save_button.click()

        self.assertEqual(window.cfg["system_prompt"], "始终使用简体中文。")
        mocked_save.assert_called_once()
        self.assertIs(window.page_stack.currentWidget(), window.chat_page)
        window.close()

    def test_system_prompt_is_hidden_and_precedes_first_user_message(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        cfg["system_prompt"] = "回答时先核验事实。"
        store = MemoryStore()
        window = MainWindow(cfg, store, self.app)

        with patch.object(window, "_start_request"):
            window.chat_input.setPlainText("第一条问题")
            window.on_send()
            window.chat_input.setPlainText("第二条问题")
            window.on_send()

        conversation = store.get("conversation-1")
        self.assertIsNotNone(conversation)
        self.assertEqual(conversation["title"], "新对话")
        messages = conversation["messages"]
        self.assertEqual([message["role"] for message in messages], ["system", "user", "user"])
        self.assertEqual(messages[0]["content"], "回答时先核验事实。")
        self.assertTrue(messages[0]["hidden"])
        self.assertEqual(
            payload_messages(messages)[:2],
            [
                {"role": "system", "content": "回答时先核验事实。"},
                {"role": "user", "content": "第一条问题"},
            ],
        )

        with patch.object(window.chat_view, "add_error") as add_error:
            window.on_select_conversation("conversation-1")
        add_error.assert_not_called()
        window.close()

    def test_completed_round_starts_full_context_title_summary(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        store = MemoryStore()
        conversation = store.create("新对话")
        store.append_message(
            conversation["id"],
            {"role": "user", "content": "解释证据理论"},
        )
        window = MainWindow(cfg, store, self.app)
        bubble = window.chat_view.add_streaming("模型", False)
        from app.ui.main_window import StreamContext

        window._context = StreamContext(
            conversation["id"],
            bubble,
            "deepseek-flash",
            "high",
            False,
            content="它用于表达和组合不确定证据。",
        )
        with patch.object(window, "_start_title_summary") as summarize:
            window._on_done()

        summarize.assert_called_once_with(conversation["id"], "deepseek-flash")
        self.assertEqual(
            [message["role"] for message in conversation["messages"]],
            ["user", "assistant"],
        )
        window.close()

    def test_notice_is_centered_manual_dialog(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.resize(1280, 820)
        window.show()
        self.app.processEvents()
        window._show_notice("请先切换到视觉模型")
        self.app.processEvents()
        dialog = window._notice_dialog
        self.assertIsInstance(dialog, NoticeDialog)
        self.assertEqual(dialog.message.text(), "请先切换到视觉模型")
        self.assertEqual(dialog.close_button.objectName(), "noticeCloseBtn")
        self.assertIn("border-radius: 12px", dialog.card.styleSheet())
        expected = window.mapToGlobal(window.rect().center())
        available = dialog.screen().availableGeometry()
        expected_x = max(
            available.left(),
            min(
                expected.x() - dialog.width() // 2,
                available.right() - dialog.width() + 1,
            ),
        ) + dialog.width() // 2
        expected_y = max(
            available.top(),
            min(
                expected.y() - dialog.height() // 2,
                available.bottom() - dialog.height() + 1,
            ),
        ) + dialog.height() // 2
        actual = dialog.geometry().center()
        self.assertLessEqual(abs(actual.x() - expected_x), 2)
        self.assertLessEqual(abs(actual.y() - expected_y), 2)
        dialog.close_button.click()
        self.app.processEvents()
        self.assertIsNone(window._notice_dialog)
        window.close()

    def test_hover_tips_use_custom_rounded_surface(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()
        button = window.input_panel.attach_button
        global_pos = button.mapToGlobal(QPoint(3, 3))
        event = QHelpEvent(QEvent.Type.ToolTip, QPoint(3, 3), global_pos)
        self.assertTrue(self.app.sendEvent(button, event))
        self.app.processEvents()
        tip = window._hover_tips._tip
        self.assertIsInstance(tip, HoverTipWidget)
        self.assertTrue(tip.isVisible())
        self.assertIn("border-radius: 12px", tip.card.styleSheet())
        native_tips = [
            widget
            for widget in self.app.topLevelWidgets()
            if "QTipLabel" in widget.metaObject().className() and widget.isVisible()
        ]
        self.assertFalse(native_tips)
        self.app.sendEvent(button, QEvent(QEvent.Type.Leave))
        self.app.processEvents()
        self.assertFalse(tip.isVisible())
        window.close()


if __name__ == "__main__":
    unittest.main()

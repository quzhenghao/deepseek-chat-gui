from __future__ import annotations

import json
import io
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from math import sqrt
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, QUrl, Qt
from PySide6.QtGui import QHelpEvent, QImage, QPalette, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMenu,
    QPushButton,
    QTextBrowser,
    QToolButton,
    QWidget,
)

from app import ASSETS_DIR, diagnostics
from app.config import (
    DEFAULTS,
    EFFORT_LABELS,
    EFFORT_LEVELS,
    MODEL_CAPABILITIES,
    V4_PRO_MODEL,
    V41_FLASH_MODEL,
    effort_label,
    is_vision_model,
    model_label,
    supports_thinking,
)
from app.api import payload_messages
from app.markdown import _CODE_FONT_STACK, to_html
from app.ui.controls import (
    build_flat_menu,
    ConfirmationDialog,
    FrameAnimator,
    HoverTipWidget,
    IdleDispatcher,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    NoticeDialog,
    RoundedComboBox,
    RoundedMenu,
)
from app.ui.icons import _cog_path, icon
from app.ui.harness_page import HarnessSurface
from app.ui.image_strip import ImageStrip, THUMBNAIL_RADIUS
from app.ui.main_window import ChatTextEdit, MainWindow
from app.ui.message_bubbles import (
    IMAGE_GRID_COLUMNS,
    IMAGE_THUMB_SIZE,
    WEB_SURFACE_MAX_HEIGHT,
    WEB_SURFACE_TEXTURE_LIMIT,
    ChatView,
    MessageTextBrowser,
    OpenImageLabel,
    ThinkingPreview,
    ThinkingIndicator,
    _MathWebView,
    _MATH_WEB_SHELL,
    _extract_complete_sentences,
)
from app.ui.sidebar import ProductModeSelector
from app.ui.theme import (
    CHAT_BUBBLE_RADIUS,
    RAIL_SIDEBAR_WIDTH,
    SIDEBAR_DEFAULT_WIDTH,
    SIDEBAR_MIN_WIDTH,
    build_qss,
    colors,
)


class FakeMenuEvent:
    """Minimal stand-in for the context-menu events the widgets receive."""

    def __init__(self, pos: QPoint | None = None) -> None:
        self._pos = QPoint(4, 4) if pos is None else pos

    def pos(self) -> QPoint:
        return self._pos

    def globalPos(self) -> QPoint:
        return QPoint(0, 0)


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
        running_indicator_left = bubble.reasoning_panel.indicator.geometry().left()
        running_toggle_left = bubble.reasoning_panel.toggle.geometry().left()
        bubble.set_content("最终答案")
        bubble.finish()
        self.app.processEvents()
        self.assertFalse(bubble.reasoning_panel.indicator._timer.isActive())
        self.assertTrue(bubble.content_view.isVisible())
        self.assertTrue(bubble.reasoning_panel.preview.isVisible())
        self.assertEqual(
            bubble.reasoning_panel.indicator.geometry().left(),
            running_indicator_left,
        )
        self.assertEqual(
            bubble.reasoning_panel.toggle.geometry().left(),
            running_toggle_left,
        )
        view.close()

    def test_streaming_answer_body_reveals_from_top_to_bottom(self) -> None:
        view = ChatView()
        view.resize(900, 600)
        view.show()
        bubble = view.add_streaming("模型 · 标准模式", False)
        content = "第一行正文内容。\n\n" + "第二行正文内容。" * 12
        bubble.set_content(content)

        self.assertTrue(
            self.wait_for(
                lambda: bubble._typing_timer.isActive(),
                timeout_ms=3000,
            )
        )
        self.assertGreater(bubble._typing_visible_characters, 0)
        self.assertLess(
            bubble._typing_visible_characters,
            len(content),
        )

        bubble.finish()
        self.assertTrue(
            self.wait_for(
                lambda: not bubble._typing_timer.isActive(),
                timeout_ms=5000,
            )
        )
        self.assertFalse(bubble._typing_enabled)
        self.assertEqual(bubble._typing_visible_characters, len(content))
        self.assertTrue(bubble.actions.isVisible())
        view.close()

    def test_reasoning_preview_fills_width_and_keeps_streaming_tail_at_60fps(self) -> None:
        self.assertEqual(
            _extract_complete_sentences("第一句。第二句！还没有结束"),
            ["第一句。", "第二句！"],
        )

        preview = ThinkingPreview()
        preview.resize(180, 20)
        preview.set_reasoning("第一句。第二句！还没有结束")
        self.assertEqual(
            "".join(preview.sentences),
            "第一句。第二句！还没有结束",
        )
        preview.start()
        self.assertEqual(preview._timer.interval(), 16)
        self.assertEqual(
            preview._timer.timerType(),
            Qt.TimerType.PreciseTimer,
        )
        self.assertIn("第一句。", preview.current_sentence)
        self.assertEqual(preview.visible_text, "")

        self.assertTrue(
            self.wait_for(
                lambda: preview.visible_text == preview.current_sentence,
                timeout_ms=700,
            )
        )
        self.assertGreater(len(preview.visible_text), len("第一句。"))
        self.assertTrue(any(len(segment) > len("第一句。") for segment in preview.sentences))
        preview.stop()
        self.assertFalse(preview._timer.isActive())
        preview.deleteLater()

    def test_reasoning_preview_windows_begin_at_sentence_boundaries(self) -> None:
        preview = ThinkingPreview()
        preview.resize(120, 20)
        source = (
            "第一句是一段足够长的思考内容，需要在右侧渐隐处理。"
            "第二句同样从句首开始显示，避免从中间截断。"
        )
        preview.set_reasoning(source)

        second_sentence_start = source.index("第二句")
        self.assertEqual(
            preview._segment_starts,
            [0, second_sentence_start],
        )
        self.assertTrue(
            all(
                segment.startswith(expected)
                for segment, expected in zip(
                    preview.sentences,
                    ("第一句", "第二句"),
                )
            )
        )

        preview.start()
        preview._current_index = 1
        preview._begin_cycle()
        self.assertTrue(preview.current_sentence.startswith("第二句"))
        preview.stop()
        preview.deleteLater()

    def test_web_search_status_replaces_thinking_label_in_reasoning_bar(self) -> None:
        view = ChatView()
        view.resize(900, 600)
        view.show()
        bubble = view.add_streaming(
            "DeepSeek V4.1 Flash · 深度思考 High · 联网搜索", True
        )
        bubble.set_reasoning("先确定查询词")
        self.app.processEvents()
        self.assertEqual(bubble.reasoning_panel.toggle.text(), "正在深度思考")
        self.assertFalse(bubble.status_row.isVisible())

        bubble.set_status("正在联网搜索…")
        self.app.processEvents()
        self.assertEqual(bubble.reasoning_panel.toggle.text(), "正在联网搜索")
        self.assertFalse(bubble.status_row.isVisible())

        bubble.set_status("已获取 1 条结果，正在生成回答…")
        self.app.processEvents()
        self.assertEqual(bubble.reasoning_panel.toggle.text(), "正在深度思考")
        self.assertFalse(bubble.status_row.isVisible())

        # A model may emit a short tool-call preamble before the worker knows
        # that it needs to search. The status transition must restart the
        # reasoning indicator instead of leaving the panel in its completed
        # state.
        bubble.set_content("我先搜索一下")
        bubble.set_status("正在联网搜索…")
        self.app.processEvents()
        self.assertEqual(bubble.reasoning_panel.toggle.text(), "正在联网搜索")
        self.assertTrue(bubble.reasoning_panel.indicator._timer.isActive())

        bubble.finish()
        self.app.processEvents()
        self.assertEqual(bubble.reasoning_panel.toggle.text(), "已完成深度思考")
        view.close()

    def test_standard_mode_exposes_web_search_status(self) -> None:
        view = ChatView()
        view.resize(900, 600)
        view.show()
        bubble = view.add_streaming("DeepSeek V4.1 Flash · 标准模式 · 联网搜索", False)
        self.app.processEvents()
        self.assertTrue(bubble.status_row.isVisible())
        self.assertEqual(bubble.status_label.text(), "正在生成")

        bubble.set_status("正在联网搜索…")
        self.app.processEvents()
        self.assertEqual(bubble.status_label.text(), "正在联网搜索")
        self.assertTrue(bubble.status_indicator._timer.isActive())

        bubble.set_status("已获取 2 条结果，正在生成回答…")
        self.app.processEvents()
        self.assertEqual(bubble.status_label.text(), "正在生成")

        bubble.set_content("答案")
        bubble.finish()
        self.app.processEvents()
        self.assertFalse(bubble.status_row.isVisible())
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

    def test_image_thumbnails_are_square_three_column_and_single_click(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deepseek-image-ui-") as directory:
            paths: list[str] = []
            for index, (width, height) in enumerate(
                ((320, 120), (120, 320), (220, 220), (480, 160), (160, 480))
            ):
                image = QImage(width, height, QImage.Format.Format_RGB32)
                image.fill(index + 1)
                path = Path(directory) / f"image-{index}.png"
                self.assertTrue(image.save(str(path)))
                paths.append(str(path))

            strip = ImageStrip()
            strip.show()
            self.app.processEvents()
            self.assertEqual(strip.add_paths(paths[:2]), 2)
            with patch("app.ui.image_strip.QDesktopServices.openUrl") as open_before:
                QTest.mouseClick(
                    strip._items[0],
                    Qt.MouseButton.LeftButton,
                    pos=strip._items[0].rect().center(),
                )
            open_before.assert_called_once_with(QUrl.fromLocalFile(paths[0]))

            view = ChatView()
            view.resize(900, 600)
            view.show()
            bubble = view.add_user("图片说明", paths)
            self.app.processEvents()

            labels = bubble.card.findChildren(OpenImageLabel)
            self.assertEqual(len(labels), len(paths))
            self.assertTrue(
                all(label.size() == QSize(IMAGE_THUMB_SIZE, IMAGE_THUMB_SIZE) for label in labels)
            )
            self.assertEqual(THUMBNAIL_RADIUS, CHAT_BUBBLE_RADIUS)
            self.assertTrue(all("border:none" in label.styleSheet() for label in labels))
            thumbnail_image = labels[0].pixmap().toImage()
            self.assertEqual(thumbnail_image.pixelColor(0, 0).alpha(), 0)
            image_grid = bubble.card.layout().itemAt(0).layout()
            self.assertIsNotNone(image_grid)
            self.assertEqual(
                [image_grid.getItemPosition(index)[:2] for index in range(image_grid.count())],
                [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)],
            )
            self.assertEqual(image_grid.columnCount(), IMAGE_GRID_COLUMNS)
            self.assertIs(bubble.card.layout().itemAt(1).widget(), bubble.text_view)

            with patch("app.ui.message_bubbles.QDesktopServices.openUrl") as open_after:
                QTest.mouseClick(
                    labels[0],
                    Qt.MouseButton.LeftButton,
                    pos=labels[0].rect().center(),
                )
            open_after.assert_called_once_with(QUrl.fromLocalFile(paths[0]))

            image_only = view.add_user("", paths[:1])
            self.app.processEvents()
            self.assertEqual(image_only.card.layout().count(), 1)
            self.assertIsNone(image_only.card.layout().itemAt(0).widget())
            self.assertEqual(image_only.card.layout().itemAt(0).layout().count(), 1)
            view.close()
            strip.close()

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
        self.assertTrue(window.input_panel.is_web_search())
        window.close()

    def test_web_search_control_defaults_on_and_sits_right_of_thinking(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        thinking = window.input_panel.thinking_button
        search = window.input_panel.search_button
        self.assertEqual(search.objectName(), "searchBtn")
        self.assertTrue(search.isChecked())
        self.assertEqual(search.height(), thinking.height())
        self.assertGreater(search.geometry().left(), thinking.geometry().left())
        self.assertFalse(search.icon().isNull())

        with patch("app.ui.main_window.save_config") as save:
            search.click()
            self.app.processEvents()
        self.assertFalse(window.cfg["web_search"])
        save.assert_called_once()
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

    def test_confirmation_dialog_uses_one_flat_surface(self) -> None:
        dialog = ConfirmationDialog(
            "删除对话",
            "确定删除“测试对话”吗？\n对话消息和本地图片会一起删除。",
            "light",
        )
        dialog.show()
        self.app.processEvents()

        self.assertEqual(dialog.windowType(), Qt.WindowType.Tool)
        self.assertTrue(dialog.windowFlags() & Qt.WindowType.NoDropShadowWindowHint)
        self.assertEqual(dialog.no_button.text(), "No")
        self.assertEqual(dialog.yes_button.text(), "Yes")
        self.assertEqual(dialog.no_button.size(), dialog.yes_button.size())
        self.assertEqual(dialog.no_button.y(), dialog.yes_button.y())
        self.assertLess(dialog.no_button.x(), dialog.yes_button.x())
        self.assertLess(dialog.message.y(), dialog.no_button.y())
        self.assertTrue(dialog.no_button.isDefault())
        self.assertEqual(dialog.title_label.text(), "删除对话")
        self.assertEqual(
            dialog.message.text(),
            "确定删除“测试对话”吗？\n对话消息和本地图片会一起删除。",
        )
        self.assertIs(dialog.title_label.parentWidget(), dialog)
        self.assertIs(dialog.message.parentWidget(), dialog)
        self.assertFalse(hasattr(dialog, "card"))
        self.assertFalse(dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        dialog_surface = (
            dialog.styleSheet()
            .split("QDialog#confirmationDialog {", 1)[1]
            .split("}", 1)[0]
        )
        self.assertIn("background: #FFFFFF;", dialog_surface)
        self.assertIn("border: 1px solid #D4D6D9;", dialog_surface)
        self.assertNotIn("border-radius", dialog_surface)
        self.assertEqual(dialog.grab().toImage().pixelColor(0, 0).alpha(), 255)

        dialog.apply_theme("dark")
        self.app.processEvents()
        self.assertIn("background: #222222;", dialog.styleSheet())
        self.assertIn("border: 1px solid #454545;", dialog.styleSheet())
        self.assertEqual(dialog.grab().toImage().pixelColor(0, 0).alpha(), 255)
        dialog.no_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        dialog.deleteLater()

        confirmed = ConfirmationDialog("删除对话", "确定删除吗？", "light")
        confirmed.show()
        self.app.processEvents()
        confirmed.yes_button.click()
        self.assertEqual(confirmed.result(), QDialog.DialogCode.Accepted)
        confirmed.deleteLater()

    def test_chat_composer_input_paints_the_card_surface(self) -> None:
        for theme in ("light", "dark"):
            sheet = build_qss(theme)
            rule = (
                sheet
                .split("QTextEdit#chatInput {", 1)[1]
                .split("}", 1)[0]
            )
            self.assertIn(f"background: {colors(theme)['panel']};", rule)
            area_rule = (
                sheet.split("QWidget#composerArea {", 1)[1].split("}", 1)[0]
            )
            self.assertIn("background: transparent;", area_rule)
            card_rule = (
                sheet.split("QFrame#composerCard {", 1)[1].split("}", 1)[0]
            )
            self.assertIn(f"background: {colors(theme)['panel']};", card_rule)
            hint_rule = (
                sheet.split("QLabel#composerHint {", 1)[1].split("}", 1)[0]
            )
            self.assertIn("background: transparent;", hint_rule)

        host = QWidget()
        host.setStyleSheet(build_qss("light"))
        editor = ChatTextEdit(host)
        editor.resize(260, 64)
        host.show()
        self.app.processEvents()
        image = editor.viewport().grab().toImage()
        sample = image.pixelColor(image.width() // 2, image.height() - 4)
        self.assertEqual(sample.alpha(), 255)
        self.assertEqual(sample.name(), colors("light")["panel"].lower())
        host.close()
        host.deleteLater()

    def test_chat_composer_floats_below_the_message_viewport(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.resize(920, 700)
        window.show()
        window.chat_workspace.set_page(window.chat_view)
        self.app.processEvents()

        message_rect = window.stack.geometry()
        composer_rect = window.input_panel.geometry()
        self.assertEqual(message_rect, window.chat_workspace.rect())
        self.assertTrue(message_rect.intersects(composer_rect))
        self.assertEqual(composer_rect.bottom() + 1, window.chat_workspace.height())
        self.assertEqual(
            window.chat_view.viewportMargins().bottom(), composer_rect.height()
        )
        viewport_bottom = window.chat_view.viewport().mapTo(
            window.chat_workspace,
            QPoint(0, window.chat_view.viewport().height()),
        )
        self.assertLessEqual(viewport_bottom.y(), composer_rect.top())
        self.assertEqual(window.chat_view.messages.contentsMargins().bottom(), 18)

        window.chat_input.setPlainText("第一行\n" * 12)
        self.app.processEvents()
        grown_composer_rect = window.input_panel.geometry()
        grown_viewport_bottom = window.chat_view.viewport().mapTo(
            window.chat_workspace,
            QPoint(0, window.chat_view.viewport().height()),
        )
        self.assertEqual(window.stack.geometry(), window.chat_workspace.rect())
        self.assertEqual(
            window.chat_view.viewportMargins().bottom(), grown_composer_rect.height()
        )
        self.assertLessEqual(grown_viewport_bottom.y(), grown_composer_rect.top())

        window.chat_input.clear()
        window.show_welcome()
        self.app.processEvents()
        self.assertEqual(window.stack.geometry(), window.chat_workspace.rect())
        self.assertEqual(window.chat_view.viewportMargins().bottom(), 0)
        welcome_top = window.welcome_logo.mapTo(
            window.chat_workspace, QPoint(0, 0)
        ).y()
        welcome_bottom = window.input_panel.hint_label.mapTo(
            window.chat_workspace,
            QPoint(0, window.input_panel.hint_label.height()),
        ).y()
        visual_center = (welcome_top + welcome_bottom) / 2
        self.assertAlmostEqual(
            visual_center,
            window.chat_workspace.height() / 2,
            delta=18,
        )
        window.close()

    def test_clearing_uploaded_images_restores_the_composer_height(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.resize(920, 700)
        window.show()
        window.chat_workspace.set_page(window.chat_view)
        self.app.processEvents()

        original_height = window.input_panel.height()
        self.assertFalse(window.input_panel.image_strip.isVisible())
        window.input_panel.image_strip.add_path("/tmp/deepseek-composer-test.png")
        self.assertTrue(
            self.wait_for(lambda: window.input_panel.height() > original_height)
        )

        window.input_panel.image_strip.clear()
        self.assertTrue(
            self.wait_for(lambda: window.input_panel.height() == original_height)
        )
        window.chat_input.setPlainText("下一轮输入")
        self.app.processEvents()
        self.assertEqual(window.input_panel.height(), original_height)
        window.close()

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
        composer_rect = window.input_panel.geometry()
        viewport_bottom = window.chat_view.viewport().mapTo(
            window.chat_workspace,
            QPoint(0, window.chat_view.viewport().height()),
        )
        self.assertLessEqual(viewport_bottom.y(), composer_rect.top())
        visible_formula_region = web_view.visibleRegion().boundingRect()
        self.assertFalse(visible_formula_region.isEmpty())
        visible_formula_bottom = web_view.mapTo(
            window.chat_workspace,
            QPoint(0, visible_formula_region.bottom() + 1),
        )
        self.assertLessEqual(visible_formula_bottom.y(), composer_rect.top())
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

    def test_current_v4_pro_model_is_labeled_and_text_only(self) -> None:
        self.assertIn(V4_PRO_MODEL, DEFAULTS["models"])
        self.assertEqual(model_label(V4_PRO_MODEL), "DeepSeek V4 Pro")
        self.assertFalse(is_vision_model(V4_PRO_MODEL))
        self.assertTrue(supports_thinking(V4_PRO_MODEL))

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
        self.assertEqual(window.input_panel.attach_button.iconSize(), QSize(20, 20))
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

    def test_settings_expose_default_web_search_switch(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.open_settings()
        self.app.processEvents()

        page = window.settings_page
        self.assertEqual(page.web_search.text(), "默认开启联网搜索")
        self.assertTrue(page.web_search.isChecked())
        self.assertEqual(
            [page.search_provider.itemData(i) for i in range(page.search_provider.count())],
            ["duckduckgo", "tavily"],
        )
        self.assertEqual(page.search_provider.currentData(), "duckduckgo")
        window.close()

    def test_message_meta_marks_web_search(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        self.assertEqual(
            window._message_meta("deepseek-flash", "high", False, True),
            "DeepSeek V4.1 Flash · 标准模式 · 联网搜索",
        )
        self.assertEqual(
            window._message_meta("deepseek-flash", "max", True, True),
            "DeepSeek V4.1 Flash · 深度思考 Max · 联网搜索",
        )
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

    def test_harness_warm_start_defers_the_webengine_surface_until_quiet(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        page = window.harness_page
        url = "http://127.0.0.1:8123/ui?token=abc"
        shown: list[str] = []
        with (
            patch.object(page.runtime, "start") as runtime_start,
            patch.object(page.surface, "show_web", lambda value: shown.append(value)),
            patch.object(page, "_window_inactive", return_value=True),
        ):
            page.warm()
            runtime_start.assert_called_once()
            self.assertEqual(shown, [])

            page.runtime._ready = True
            page.runtime._url = url
            page._on_ready(url)
            self.assertEqual(shown, [])
            self.assertTrue(page._idle.is_pending())

            page.start()
            self.assertEqual(shown, [url])
            self.assertFalse(page._idle.is_pending())
            runtime_start.assert_called_once()

            page.start()
            self.assertEqual(shown, [url, url])
        window.close()

    def test_harness_warm_start_keeps_chat_stable_until_harness_is_opened(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        page = window.harness_page
        url = "http://127.0.0.1:8123/ui?token=abc"
        shown: list[str] = []
        with (
            patch.object(page.runtime, "start"),
            patch.object(page.surface, "show_web", lambda value: shown.append(value)),
            patch.object(page, "_window_inactive", return_value=False),
        ):
            page.warm()
            page.runtime._ready = True
            page.runtime._url = url
            page._on_ready(url)
            self.assertEqual(shown, [])
            self.assertFalse(page._idle.is_pending())
            self.assertEqual(page._pending_url, url)

            page.start()
            self.assertEqual(shown, [url])
            self.assertIsNone(page._pending_url)
        window.close()

    def test_harness_surface_build_resumes_when_the_app_leaves_the_foreground(
        self,
    ) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        page = window.harness_page
        url = "http://127.0.0.1:8123/ui?token=abc"
        page._pending_url = url
        with (
            patch.object(page, "_window_inactive", return_value=True),
            patch.object(page.surface, "show_web", lambda value: None),
        ):
            page._on_application_state_changed(
                Qt.ApplicationState.ApplicationInactive
            )
            self.assertTrue(page._idle.is_pending())
        window.close()

    def test_harness_deferred_surface_skips_build_when_the_user_returns(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        page = window.harness_page
        url = "http://127.0.0.1:8123/ui?token=abc"
        page._pending_url = url
        with (
            patch.object(page, "_window_inactive", return_value=False),
            patch.object(page.surface, "show_web") as show_web,
        ):
            page._build_deferred_surface()
            show_web.assert_not_called()
            self.assertEqual(page._pending_url, url)

        with (
            patch.object(page, "_window_inactive", return_value=True),
            patch.object(page.surface, "show_web") as show_web,
        ):
            page._build_deferred_surface()
            show_web.assert_called_once_with(url)
            self.assertIsNone(page._pending_url)
        window.close()

    def test_harness_warm_start_is_armed_by_the_first_visible_event(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        with (
            patch.object(window._app, "platformName", return_value="cocoa"),
            patch.object(window.harness_page, "warm") as warm,
        ):
            window.show()
            self.app.processEvents()
            warm.assert_called_once_with()
            self.assertFalse(window._warm_start_armed)
            self.assertFalse(window._warm_start_pending)
        window.close()

    def test_macos_code_font_stack_does_not_request_consolas(self) -> None:
        if sys.platform != "darwin":
            self.skipTest("macOS font resolution is not active on this platform")
        self.assertNotIn("Consolas", _CODE_FONT_STACK)
        self.assertIn("Menlo", to_html("```text\nprint(1)\n```"))

    def test_harness_surface_loads_the_official_ui_once(self) -> None:
        url = "http://127.0.0.1:8123/ui?token=abc"
        loads: list[str] = []
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp,
            patch("app.ui.harness_page.harness_home", lambda: Path(tmp)),
            patch.object(
                HarnessSurface,
                "_load_url",
                lambda self, view, value: loads.append(value),
            ),
        ):
            surface = HarnessSurface("light")
            surface.show_web(url)
            self.assertIsNotNone(surface._profile)
            self.assertEqual(
                surface._profile.persistentCookiesPolicy(),
                QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies,
            )
            surface.show_web(url)
            self.assertEqual(loads, [url])

            surface._web_load_finished(True)
            surface.show_web(url)
            self.assertEqual(loads, [url])

            the_next_runtime = "http://127.0.0.1:9999/ui?token=def"
            surface.show_web(the_next_runtime)
            self.assertEqual(loads, [url, the_next_runtime])

            surface._web_load_finished(False)
            surface.show_web(the_next_runtime)
            self.assertEqual(loads, [url, the_next_runtime, the_next_runtime])
            surface.dispose()

    def test_crash_logging_records_fatal_and_python_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crash_log = root / "crash.log"
            error_log = root / "errors.log"
            original_hook = sys.excepthook
            with (
                patch.object(diagnostics, "LOG_DIR", root),
                patch.object(diagnostics, "CRASH_LOG", crash_log),
                patch.object(diagnostics, "ERROR_LOG", error_log),
            ):
                try:
                    self.assertEqual(
                        diagnostics.install(),
                        (crash_log, error_log),
                    )
                    self.assertTrue(crash_log.exists())
                    self.assertIn("session", crash_log.read_text(encoding="utf-8"))
                    try:
                        raise RuntimeError("diagnostics probe")
                    except RuntimeError:
                        with redirect_stderr(io.StringIO()):
                            sys.excepthook(*sys.exc_info())
                    recorded = error_log.read_text(encoding="utf-8")
                    self.assertIn("diagnostics probe", recorded)
                    self.assertIn("RuntimeError", recorded)
                finally:
                    sys.excepthook = original_hook

    def test_inline_web_surface_never_exceeds_the_gpu_texture_limit(self) -> None:
        view = _MathWebView()
        view.resize(840, 22)
        view._apply_content_height(60_000)
        self.assertLessEqual(view.height(), WEB_SURFACE_MAX_HEIGHT)
        self.assertLessEqual(view.height(), WEB_SURFACE_TEXTURE_LIMIT)
        self.assertGreaterEqual(view.height(), 22)

        view._apply_content_height(320)
        self.assertEqual(view.height(), 321)

        self.assertIn("internalScroll", _MATH_WEB_SHELL)
        self.assertIn("if (!atEdge) return;", _MATH_WEB_SHELL)
        self.assertIn("overflow: hidden", _MATH_WEB_SHELL)
        self.assertIn("bridge.scrollVertically", _MATH_WEB_SHELL)
        view.dispose()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_long_inline_web_surface_keeps_the_answer_tail_scrollable(self) -> None:
        view = ChatView()
        view.resize(720, 600)
        view.show()
        content = (
            "```python\n"
            + ("print('long answer line')\n" * 360)
            + "```\n\n"
            + "回答尾部：这段内容必须可以完整显示。"
        )

        bubble = view.add_assistant(content, thinking=False)
        web_view = bubble.content_view._web_view
        self.assertIsNotNone(web_view)
        self.assertTrue(
            self.wait_for(
                lambda: web_view.height() == web_view._surface_height_limit()
                and web_view.height() > 22,
                timeout_ms=5000,
            )
        )

        metrics = json.loads(
            self.javascript_value(
                web_view.page(),
                """
                JSON.stringify({
                  overflow: getComputedStyle(document.documentElement)
                    .overflowY,
                  innerHeight: window.innerHeight,
                  scrollHeight: Math.max(
                    document.documentElement.scrollHeight,
                    document.body.scrollHeight
                  ),
                  maxScroll: Math.max(
                    0,
                    Math.max(
                      document.documentElement.scrollHeight,
                      document.body.scrollHeight
                    ) - window.innerHeight
                  )
                })
                """,
            )
        )
        self.assertEqual(metrics["overflow"], "auto")
        self.assertGreater(metrics["scrollHeight"], metrics["innerHeight"])
        self.assertGreater(metrics["maxScroll"], 0)

        tail_scroll = json.loads(
            self.javascript_value(
                web_view.page(),
                """
                (() => {
                  window.scrollTo(0, document.documentElement.scrollHeight);
                  return JSON.stringify({
                    scrollY: window.scrollY,
                    maxScroll: Math.max(
                      0,
                      Math.max(
                        document.documentElement.scrollHeight,
                        document.body.scrollHeight
                      ) - window.innerHeight
                    ),
                    tail: document.body.innerText.slice(-20)
                  });
                })()
                """,
            )
        )
        self.assertGreater(tail_scroll["scrollY"], 0)
        self.assertAlmostEqual(
            tail_scroll["scrollY"],
            tail_scroll["maxScroll"],
            delta=2,
        )
        self.assertIn("回答尾部", tail_scroll["tail"])

        view.close()

    def test_text_selection_uses_the_platform_palette(self) -> None:
        for theme in ("light", "dark"):
            sheet = build_qss(theme)
            for selector in (
                "QTextBrowser",
                "QTextEdit#chatInput",
                "QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit",
            ):
                rule = sheet.split(f"{selector} {{", 1)[1].split("}", 1)[0]
                self.assertNotIn(
                    "selection",
                    rule,
                    f"{selector} must keep the platform selection colors",
                )

        host = QWidget()
        host.setStyleSheet(build_qss("light"))
        host.resize(300, 120)
        browser = QTextBrowser(host)
        browser.setGeometry(0, 0, 300, 120)
        browser.setPlainText("这是可以被选中的正文内容" * 4)
        host.show()
        self.app.processEvents()
        cursor = browser.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        browser.setTextCursor(cursor)
        self.app.processEvents()

        image = browser.grab().toImage()
        background = image.pixelColor(image.width() - 4, image.height() - 4)
        counts: dict[str, int] = {}
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color != background:
                    counts[color.name()] = counts.get(color.name(), 0) + 1
        self.assertTrue(counts)
        painted = max(counts, key=lambda name: counts[name])
        self.assertEqual(painted, QApplication.palette().highlight().color().name())
        self.assertNotEqual(painted, colors("light")["accent"])
        host.close()

    def test_clicking_outside_message_clears_its_selection(self) -> None:
        host = QWidget()
        host.resize(420, 160)
        browser = MessageTextBrowser(host)
        browser.setGeometry(0, 0, 300, 100)
        browser.setPlainText("这段回答可以被选中")
        blank = QPushButton("空白区域", host)
        blank.setGeometry(310, 100, 100, 40)
        host.show()
        self.app.processEvents()

        cursor = browser.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        browser.setTextCursor(cursor)
        browser.setFocus()
        self.app.processEvents()
        self.assertTrue(browser.textCursor().hasSelection())

        QTest.mouseClick(blank, Qt.MouseButton.LeftButton)
        self.app.processEvents()

        self.assertFalse(browser.textCursor().hasSelection())
        host.close()

    def test_right_click_keeps_message_selection_and_copy_menu_enabled(self) -> None:
        view = ChatView()
        view.resize(520, 260)
        bubble = view.add_assistant("这段回答可以被复制", thinking=False)
        view.show()
        self.app.processEvents()

        browser = bubble.content_view._text_view
        self.assertEqual(browser.cursor().shape(), Qt.CursorShape.IBeamCursor)
        self.assertEqual(
            browser.viewport().cursor().shape(), Qt.CursorShape.IBeamCursor
        )
        cursor = browser.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        browser.setTextCursor(cursor)
        browser.setFocus()
        self.app.processEvents()
        self.assertTrue(browser.textCursor().hasSelection())

        QTest.mouseClick(
            browser.viewport(),
            Qt.MouseButton.RightButton,
            pos=browser.viewport().rect().center(),
        )
        self.app.processEvents()
        self.assertTrue(browser.textCursor().hasSelection())

        class CopyMenu(QMenu):
            def exec(self, *args, **kwargs):
                return next(
                    action
                    for action in self.actions()
                    if action.text() == "复制"
                )

        clipboard = QApplication.clipboard()
        previous = clipboard.text()
        try:
            with patch("app.ui.controls.QMenu", CopyMenu):
                browser.contextMenuEvent(FakeMenuEvent())
            self.assertEqual(clipboard.text().strip(), "这段回答可以被复制")
            self.assertTrue(browser.textCursor().hasSelection())
        finally:
            clipboard.setText(previous)
        view.close()

    def test_math_surface_uses_text_cursor(self) -> None:
        surface = _MathWebView()
        self.assertEqual(surface.cursor().shape(), Qt.CursorShape.IBeamCursor)
        surface.dispose()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_clicking_empty_message_lane_clears_its_selection(self) -> None:
        view = ChatView()
        view.resize(520, 260)
        bubble = view.add_assistant("这段回答可以被选中", thinking=False)
        view.show()
        self.app.processEvents()

        browser = bubble.content_view._text_view
        cursor = browser.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        browser.setTextCursor(cursor)
        browser.setFocus()
        self.app.processEvents()
        self.assertTrue(browser.textCursor().hasSelection())

        QTest.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(12, 12),
        )
        self.app.processEvents()

        self.assertFalse(browser.textCursor().hasSelection())
        view.close()

    def test_context_menu_surface_is_flat_and_opaque(self) -> None:
        for theme in ("light", "dark"):
            sheet = build_qss(theme)
            rule = sheet.split("QMenu {", 1)[1].split("}", 1)[0]
            self.assertIn(f"background: {colors(theme)['panel']};", rule)
            self.assertNotIn("transparent", rule)
        self.assertEqual(colors("light")["panel"], "#FFFFFF")

        host = QWidget()
        host.setStyleSheet("background:transparent;border:none;")
        menu = build_flat_menu(host)
        self.assertIsNone(menu.parent())
        self.assertEqual(
            menu.palette().color(QPalette.ColorRole.Window).alpha(),
            255,
        )

        self.assertTrue(
            menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        )
        menu.addAction("拷贝")
        menu.addAction("全选")
        menu.resize(160, 70)
        menu.show()
        self.app.processEvents()
        image = menu.grab().toImage()
        for point in ((8, 8), (image.width() - 8, image.height() - 8), (140, 62)):
            color = image.pixelColor(*point)
            self.assertEqual(color.alpha(), 255)
            self.assertEqual(color.name().upper(), colors("light")["panel"])
        menu.close()
        menu.deleteLater()

    def test_every_chat_surface_shows_the_flat_menu(self) -> None:
        shown: list[QMenu] = []

        class SpyMenu(QMenu):
            def exec(self, *args, **kwargs):
                shown.append(self)
                return None

        with patch("app.ui.controls.QMenu", SpyMenu):
            editor = ChatTextEdit()
            editor.setPlainText("草稿")
            editor.contextMenuEvent(FakeMenuEvent())

            view = ChatView()
            bubble = view.add_assistant("正文内容", meta="DeepSeek")
            bubble.content_view._text_view.contextMenuEvent(FakeMenuEvent())
            bubble.content_view._ensure_web_view().contextMenuEvent(FakeMenuEvent())

            cfg = dict(DEFAULTS)
            cfg["models"] = list(DEFAULTS["models"])
            store = MemoryStore()
            conversation = store.create("会话")
            window = MainWindow(cfg, store, self.app)
            window.refresh_sidebar()
            window.sidebar._items[conversation["id"]]._show_menu()
            window.close()

        self.assertEqual(len(shown), 4)
        for menu in shown:
            self.assertTrue(
                menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
                "menus must be drawn by Qt so they cannot fall back to the "
                "translucent native panel",
            )
        labels = [
            [action.text() for action in menu.actions()]
            for menu in shown
        ]
        self.assertIn(
            ["撤销", "重做", "", "剪切", "复制", "粘贴", "删除", "", "全选"],
            labels,
        )
        self.assertEqual(labels[1], ["复制", "", "全选"])
        self.assertEqual(labels[2], ["复制", "", "全选"])
        self.assertEqual(labels[3], ["重命名", "删除"])

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

        window.splitter.setSizes([900, 379])
        self.app.processEvents()
        self.assertEqual(window.sidebar.width(), SIDEBAR_DEFAULT_WIDTH)
        window.splitter.setSizes([100, 1179])
        self.app.processEvents()
        self.assertEqual(window.sidebar.width(), SIDEBAR_MIN_WIDTH)

        window.open_settings()
        self.app.processEvents()
        self.assertEqual(window.settings_page.sidebar.width(), SIDEBAR_DEFAULT_WIDTH)
        chat_header = window.chat_page.findChild(QWidget, "chatHeader")
        settings_header = window.settings_page.findChild(QWidget, "settingsHeader")
        self.assertIsNotNone(chat_header)
        self.assertIsNotNone(settings_header)
        self.assertEqual(settings_header.height(), chat_header.height())
        self.assertEqual(
            settings_header.layout().contentsMargins(),
            chat_header.layout().contentsMargins(),
        )
        window.close()

    def test_sidebar_collapses_into_an_icon_rail_with_animation(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        frames: list[float] = []
        window._sidebar_animator.valueChanged.connect(frames.append)
        window.set_sidebar_collapsed(True)
        self.assertTrue(self.wait_for(lambda: not window._sidebar_animator.is_running()))

        widths = [round(value) for value in frames]
        self.assertGreaterEqual(len(widths), 10)
        self.assertEqual(widths[0], SIDEBAR_DEFAULT_WIDTH)
        self.assertEqual(widths[-1], RAIL_SIDEBAR_WIDTH)
        self.assertEqual(
            widths,
            sorted(widths, reverse=True),
            "the rail must shrink monotonically",
        )
        self.assertTrue(window.sidebar.is_collapsed())
        self.assertEqual(window.sidebar.width(), RAIL_SIDEBAR_WIDTH)
        self.assertIs(window.sidebar.pages.currentWidget(), window.sidebar.rail_page)

        for button in (
            window.sidebar.rail_expand_button,
            window.sidebar.rail_new_button,
            window.sidebar.rail_settings_button,
        ):
            self.assertTrue(button.isVisible())
            self.assertFalse(button.icon().isNull())
        self.assertFalse(window.sidebar.full_page.isVisible())
        self.assertFalse(window.sidebar.settings_button.isVisible())

        window.set_sidebar_collapsed(False)
        self.assertTrue(self.wait_for(lambda: not window._sidebar_animator.is_running()))
        self.assertFalse(window.sidebar.is_collapsed())
        self.assertEqual(window.sidebar.width(), SIDEBAR_DEFAULT_WIDTH)
        self.assertIs(window.sidebar.pages.currentWidget(), window.sidebar.full_page)
        self.assertEqual(window.sidebar.minimumWidth(), SIDEBAR_MIN_WIDTH)
        window.close()

    def test_sidebar_transition_ticks_above_sixty_frames_per_second(self) -> None:
        animator = FrameAnimator(230)
        self.assertEqual(animator.timer.interval(), 16)
        self.assertEqual(animator.timer.timerType(), Qt.TimerType.PreciseTimer)

        stamps: list[float] = []
        animator.valueChanged.connect(lambda _value: stamps.append(time.perf_counter()))
        animator.start(SIDEBAR_DEFAULT_WIDTH, RAIL_SIDEBAR_WIDTH)
        self.assertTrue(self.wait_for(lambda: not animator.is_running()))

        intervals = [
            later - earlier for earlier, later in zip(stamps, stamps[1:])
        ]
        self.assertGreaterEqual(len(intervals), 10)
        self.assertLessEqual(max(intervals), 0.045)
        self.assertLessEqual(sum(intervals) / len(intervals), 0.02)

    def test_sidebar_rail_entries_are_wired_to_their_actions(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        window.set_sidebar_collapsed(True, animate=False)
        self.app.processEvents()

        window.sidebar.rail_settings_button.click()
        self.assertIs(window.page_stack.currentWidget(), window.settings_page)
        window.settings_page.back_button.click()
        self.assertIs(window.page_stack.currentWidget(), window.chat_page)

        window.sidebar.rail_expand_button.click()
        self.assertTrue(self.wait_for(lambda: not window._sidebar_animator.is_running()))
        self.assertFalse(window.sidebar.is_collapsed())
        self.assertEqual(window.sidebar.width(), SIDEBAR_DEFAULT_WIDTH)

        window.chat_input.setPlainText("待发送的草稿")
        window.sidebar.rail_new_button.click()
        self.app.processEvents()
        self.assertEqual(window.chat_input.toPlainText(), "")
        self.assertIs(window.stack.currentWidget(), window.welcome)
        window.close()

    def test_header_keeps_only_the_api_chip_at_the_trailing_edge(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        header = window.chat_page.findChild(QWidget, "chatHeader")
        self.assertIsNotNone(header)
        self.assertFalse(hasattr(window, "header_settings"))
        self.assertFalse(hasattr(window, "sidebar_button"))
        settings_buttons = [
            button
            for button in header.findChildren(QToolButton)
            if button.toolTip() == "设置"
        ]
        self.assertEqual(settings_buttons, [])
        toggles = [
            button
            for button in header.findChildren(QToolButton)
            if "侧边栏" in button.toolTip()
        ]
        self.assertEqual(toggles, [])
        entry_glyph = window.sidebar.collapse_button.icon().pixmap(20, 20)
        rail_glyph = window.sidebar.rail_expand_button.icon().pixmap(20, 20)
        self.assertFalse(entry_glyph.isNull())
        self.assertFalse(rail_glyph.isNull())
        self.assertEqual(entry_glyph.toImage(), rail_glyph.toImage())
        layout = header.layout()
        self.assertIs(layout.itemAt(layout.count() - 1).widget(), window.api_status)
        self.assertEqual(window.api_status.text(), "API 已配置")
        self.assertLessEqual(
            header.width() - window.api_status.geometry().right() - 1,
            24,
        )
        window.close()

    def test_sidebar_brand_lockup_fits_without_clipping(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()

        header = window.sidebar.brand_header
        row = header.layout()
        margins = row.contentsMargins()
        required = margins.left() + margins.right()
        required += sum(
            widget.sizeHint().width()
            for widget in (
                row.itemAt(index).widget() for index in range(row.count())
            )
            if widget is not None
        )
        required += row.spacing() * max(0, row.count() - 1)
        self.assertLessEqual(
            required,
            header.width(),
            f"brand row needs {required}px but only has {header.width()}px",
        )

        for label, wordmark in (
            ("chat", window.sidebar.brand_wordmark),
            ("settings", window.settings_page.brand_wordmark),
        ):
            self.assertGreaterEqual(
                wordmark.width(),
                wordmark.sizeHint().width(),
                f"{label} wordmark is clipped",
            )
        window.close()

    def test_idle_dispatcher_waits_for_quiet_and_never_filters_the_app(self) -> None:
        dispatcher = IdleDispatcher(idle_ms=250)
        calls: list[str] = []

        with patch.object(dispatcher, "seconds_since_input", lambda: 0.05):
            dispatcher.schedule(
                lambda: calls.append("busy"),
                delay_ms=0,
                deadline_ms=600,
            )
            self.assertFalse(self.wait_for(lambda: bool(calls), timeout_ms=350))
            self.assertEqual(calls, [])

        with patch.object(dispatcher, "seconds_since_input", lambda: 5.0):
            self.assertTrue(self.wait_for(lambda: bool(calls), timeout_ms=500))
        self.assertEqual(calls, ["busy"])
        self.assertFalse(dispatcher.is_pending())

        calls.clear()
        with patch.object(dispatcher, "seconds_since_input", lambda: 0.05):
            dispatcher.schedule(
                lambda: calls.append("deadline"),
                delay_ms=0,
                deadline_ms=120,
            )
            self.assertTrue(self.wait_for(lambda: bool(calls), timeout_ms=1200))
        self.assertEqual(calls, ["deadline"])
        dispatcher.cancel()

        filtered: list[object] = []
        original = QObject.installEventFilter

        def spy(owner, watched):
            if watched is self.app:
                filtered.append(owner)
            return original(owner, watched)

        with patch.object(QObject, "installEventFilter", spy):
            cfg = dict(DEFAULTS)
            cfg["models"] = list(DEFAULTS["models"])
            cfg["api_key"] = "test"
            window = MainWindow(cfg, MemoryStore(), self.app)
            window.show()
            self.app.processEvents()
        self.assertEqual(filtered, [])
        window.close()

    def test_follow_button_mirrors_the_composer_submit_button(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.resize(1280, 820)
        window.show()
        window.chat_workspace.set_page(window.chat_view)
        window.chat_view.add_user("帮我看一下并发问题")
        window.chat_view.add_assistant("结论：需要给共享状态加锁。", meta="DeepSeek")
        for index in range(6):
            window.chat_view.add_user(f"继续追问 {index + 2}")
            window.chat_view.add_assistant(
                "先给出结论，再补充细节。" * 12,
                meta="DeepSeek V4.1 Flash · High · 深度思考",
            )
        self.app.processEvents()
        self.wait_for(
            lambda: window.chat_view.verticalScrollBar().maximum() > 0
        )

        window.chat_view.pause_follow()
        window.chat_view.verticalScrollBar().setValue(0)
        self.app.processEvents()
        self.assertTrue(self.wait_for(lambda: window.chat_workspace.follow_button.isVisible()))

        submit = window.input_panel.action_button
        follow = window.chat_workspace.follow_button
        submit_origin = submit.mapTo(window.chat_workspace, QPoint(0, 0))
        self.assertEqual(follow.size(), submit.size())
        self.assertEqual(follow.y(), submit_origin.y())
        self.assertGreater(follow.x(), submit_origin.x() + submit.width())
        self.assertLessEqual(follow.x() + follow.width(), window.chat_workspace.width())
        window.close()

    def test_settings_entries_share_one_flat_harness_surface(self) -> None:
        cfg = dict(DEFAULTS)
        cfg["models"] = list(DEFAULTS["models"])
        cfg["api_key"] = "test"
        window = MainWindow(cfg, MemoryStore(), self.app)
        window.show()
        self.app.processEvents()
        window.open_settings()
        self.app.processEvents()

        entry = window.sidebar.settings_button
        back = window.settings_page.back_button
        self.assertEqual(entry.size(), back.size())
        self.assertEqual(entry.iconSize(), back.iconSize())

        for theme in ("light", "dark"):
            window.apply_theme(theme)
            self.app.processEvents()
            palette = colors(theme)
            rule = (
                build_qss(theme)
                .split("QPushButton#sidebarFooterBtn, QPushButton#settingsBackBtn {", 1)[1]
                .split("}", 1)[0]
            )
            self.assertIn(f"color: {palette['entry_fg']};", rule)
            self.assertIn("background: transparent;", rule)
            hover_rule = (
                build_qss(theme)
                .split(
                    "QPushButton#sidebarFooterBtn:hover, QPushButton#settingsBackBtn:hover {",
                    1,
                )[1]
                .split("}", 1)[0]
            )
            self.assertIn(f"background: {palette['hover']};", hover_rule)
            for button in (entry, back):
                image = button.grab().toImage()
                for point in ((image.width() - 6, 4), (image.width() // 2, 2)):
                    self.assertEqual(image.pixelColor(*point).alpha(), 0)
                ink = min(
                    image.pixelColor(x, y).lightness()
                    for x in range(0, image.width(), 2)
                    for y in range(image.height())
                    if image.pixelColor(x, y).alpha() > 200
                )
                if theme == "light":
                    self.assertLessEqual(ink, 32)
                else:
                    self.assertGreaterEqual(ink, 200)
        window.close()

    def test_settings_icon_uses_six_tooth_vector_outline(self) -> None:
        outline = _cog_path()
        self.assertEqual(outline.elementCount(), 25)
        self.assertFalse(
            any(
                outline.elementAt(index).isCurveTo()
                for index in range(outline.elementCount())
            )
        )
        points = {
            (
                round(outline.elementAt(index).x, 6),
                round(outline.elementAt(index).y, 6),
            )
            for index in range(24)
        }
        turn_cosine = 0.5
        turn_sine = sqrt(3.0) / 2.0
        for x, y in points:
            rotated = (
                round(12.0 + (x - 12.0) * turn_cosine - (y - 12.0) * turn_sine, 6),
                round(12.0 + (x - 12.0) * turn_sine + (y - 12.0) * turn_cosine, 6),
            )
            self.assertIn(rotated, points)

    def test_stop_icon_uses_a_larger_center_square(self) -> None:
        image = icon("stop", "#000000", 24).pixmap(QSize(24, 24)).toImage()
        points = [
            (x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        ]
        self.assertEqual(
            (
                min(x for x, _ in points),
                min(y for _, y in points),
                max(x for x, _ in points),
                max(y for _, y in points),
            ),
            (6, 6, 17, 17),
        )

    def test_light_settings_entries_use_pure_black_ink(self) -> None:
        self.assertEqual(colors("light")["entry_fg"], "#000000")

        glyph = icon("settings", colors("light")["entry_fg"], 48)
        image = glyph.pixmap(48, 48).toImage()
        center = image.width() // 2
        self.assertEqual(image.pixelColor(center, center).alpha(), 0)
        self.assertGreater(image.pixelColor(center + 5, center).alpha(), 120)
        for dx, dy in (
            (16, 9),
            (0, 18),
            (-16, 9),
            (16, -9),
            (0, -18),
            (-16, -9),
        ):
            self.assertGreater(
                image.pixelColor(center + dx, center + dy).alpha(),
                120,
            )
        self.assertEqual(image.pixelColor(center + 20, center).alpha(), 0)

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

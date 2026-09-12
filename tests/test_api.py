from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import api
from app.config import DEFAULT_MODELS, EFFORT_LEVELS
from app.worker import TitleWorker


class ResponseContext:
    def __init__(self, lines: list[str], content_type: str = "text/event-stream") -> None:
        self.status_code = 200
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self._lines = lines
        self.text = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self, decode_unicode: bool = False):
        return iter(self._lines)


class APITests(unittest.TestCase):
    def test_title_request_contains_every_visible_turn_without_images(self) -> None:
        messages = api.title_messages(
            [
                {"role": "system", "content": "个性化指令", "hidden": True},
                {"role": "user", "content": "先解释证据理论"},
                {"role": "assistant", "content": "证据理论用于融合信息。"},
                {
                    "role": "user",
                    "content": "再解释正交和",
                    "images": ["one.png", "two.png"],
                },
                {"role": "assistant", "content": "正交和用于组合证据。"},
            ]
        )
        self.assertEqual(
            [message["role"] for message in messages],
            ["system", "user", "assistant", "user", "assistant", "user"],
        )
        transcript = "\n".join(str(message["content"]) for message in messages)
        self.assertNotIn("个性化指令", transcript)
        self.assertIn("先解释证据理论", transcript)
        self.assertIn("正交和用于组合证据", transcript)
        self.assertIn("[本轮包含2张图片]", transcript)
        self.assertNotIn("data:image", transcript)

    def test_generated_title_is_clean_and_bounded_for_sidebar(self) -> None:
        self.assertEqual(
            api.clean_conversation_title("**标题：证据理论的正交和**。"),
            "证据理论的正交和",
        )
        self.assertEqual(
            api.clean_conversation_title("```text\n多源证据融合方法\n```"),
            "多源证据融合方法",
        )
        bounded = api.clean_conversation_title(
            "这是一个非常非常长且无法显示完整的自动标题"
        )
        self.assertTrue(bounded.endswith("…"))
        self.assertLessEqual(
            api._display_units(bounded), api.TITLE_MAX_DISPLAY_UNITS
        )

    def test_title_worker_uses_a_short_non_thinking_request(self) -> None:
        request: dict = {}

        def fake_stream(
            cfg,
            model,
            effort,
            deep_thinking,
            messages,
            temperature,
            max_tokens,
            stop,
            timeout=(10, 600),
            response_callback=None,
        ):
            request.update(
                model=model,
                effort=effort,
                deep_thinking=deep_thinking,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            yield "content", "证据理论"
            yield "content", "正交和"

        worker = TitleWorker(
            {"api_key": "test"},
            "deepseek-flash",
            [{"role": "user", "content": "完整上下文"}],
        )
        titles: list[str] = []
        worker.titleReady.connect(titles.append)
        with patch("app.worker.api.stream_chat", side_effect=fake_stream):
            worker.run()

        self.assertEqual(titles, ["证据理论正交和"])
        self.assertEqual(request["model"], "deepseek-flash")
        self.assertEqual(request["effort"], "low")
        self.assertFalse(request["deep_thinking"])
        self.assertEqual(request["temperature"], 0.2)
        self.assertEqual(request["max_tokens"], 64)

    def test_official_models_forward_selected_effort(self) -> None:
        for model in DEFAULT_MODELS:
            for effort in EFFORT_LEVELS:
                body = api.build_chat_body(
                    model,
                    effort,
                    True,
                    [{"role": "user", "content": "hi"}],
                    1.0,
                    0,
                )
                self.assertEqual(body["model"], model)
                self.assertEqual(body["reasoning_effort"], effort)

    def test_official_model_listing_uses_current_catalog(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": [
                {"id": "deepseek-v4-pro"},
                {"id": "deepseek-v4-flash"},
                {"id": "deepseek-flash"},
            ]
        }
        with patch("app.api.requests.get", return_value=response):
            models = api.list_models(
                {"api_key": "test", "base_url": "https://api.deepseek.com"}
            )
        self.assertEqual(models, ["deepseek-flash"])

    def test_thinking_body_uses_effort_without_temperature(self) -> None:
        body = api.build_chat_body(
            "deepseek-flash", "max", True, [{"role": "user", "content": "hi"}], 0.4, 0
        )
        self.assertEqual(body["reasoning_effort"], "max")
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertNotIn("temperature", body)

    def test_standard_body_uses_temperature_without_effort(self) -> None:
        body = api.build_chat_body(
            "deepseek-flash", "high", False, [], 0.7, 2048
        )
        self.assertEqual(body["temperature"], 0.7)
        self.assertEqual(body["max_tokens"], 2048)
        self.assertNotIn("reasoning_effort", body)

    def test_payload_encodes_user_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "tiny.png"
            image.write_bytes(b"png")
            payload = api.payload_messages(
                [{"role": "user", "content": "看图", "images": [str(image)]}]
            )
        parts = payload[0]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "看图"})
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_stream_separates_reasoning_and_content(self) -> None:
        lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"先想"}}]}',
            'data: {"choices":[{"delta":{"content":"答案"}}]}',
            "data: [DONE]",
        ]
        response = ResponseContext(lines)
        with patch("app.api.requests.post", return_value=response):
            result = list(
                api.stream_chat(
                    {"api_key": "test", "base_url": "https://example.com"},
                    "deepseek-flash",
                    "low",
                    True,
                    [{"role": "user", "content": "test"}],
                    1.0,
                    0,
                    threading.Event(),
                )
            )
        self.assertEqual(result, [("reasoning", "先想"), ("content", "答案")])

    def test_json_response_uses_message_object(self) -> None:
        response = ResponseContext([], "application/json")
        response.json = Mock(
            return_value={
                "choices": [
                    {"message": {"reasoning_content": "过程", "content": "结论"}}
                ]
            }
        )
        with patch("app.api.requests.post", return_value=response):
            result = list(
                api.stream_chat(
                    {"api_key": "test", "base_url": "https://example.com"},
                    "deepseek-flash",
                    "high",
                    True,
                    [],
                    1.0,
                    0,
                    threading.Event(),
                )
            )
        self.assertEqual(result, [("reasoning", "过程"), ("content", "结论")])

    def test_search_body_declares_web_search_tool(self) -> None:
        body = api.build_search_body(
            "deepseek-flash",
            "max",
            True,
            [{"role": "user", "content": "最新新闻"}],
            0.5,
            2048,
        )
        self.assertEqual(body["tools"], [{"type": "web_search"}])
        self.assertEqual(body["reasoning"], {"effort": "max"})
        self.assertEqual(body["max_output_tokens"], 2048)
        self.assertNotIn("temperature", body)

    def test_search_body_disables_reasoning_in_standard_mode(self) -> None:
        body = api.build_search_body(
            "deepseek-flash",
            "high",
            False,
            [{"role": "user", "content": "最新新闻"}],
            0.7,
            0,
        )
        self.assertEqual(body["tools"], [{"type": "web_search"}])
        self.assertEqual(body["reasoning"], {"effort": "none"})
        self.assertEqual(body["temperature"], 0.7)
        self.assertNotIn("max_output_tokens", body)

    def test_responses_input_converts_user_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "tiny.png"
            image.write_bytes(b"png")
            items = api.responses_input(
                [
                    {"role": "system", "content": "系统提示"},
                    {"role": "user", "content": "看图", "images": [str(image)]},
                    {"role": "assistant", "content": "收到"},
                ]
            )
        self.assertEqual(
            items[0],
            {"role": "system", "content": "系统提示"},
        )
        parts = items[1]["content"]
        self.assertEqual(parts[0], {"type": "input_text", "text": "看图"})
        self.assertEqual(parts[1]["type"], "input_image")
        self.assertTrue(parts[1]["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(items[2], {"role": "assistant", "content": "收到"})

    def test_responses_input_accepts_payload_message_parts(self) -> None:
        items = api.responses_input(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "看图"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,cG5n"},
                        },
                    ],
                }
            ]
        )
        self.assertEqual(
            items[0],
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "看图"},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,cG5n",
                    },
                ],
            },
        )

    def test_search_stream_parses_responses_events(self) -> None:
        lines = [
            'data: {"type":"response.created","sequence_number":0}',
            'data: {"type":"response.reasoning_text.delta","delta":"思考"}',
            'data: {"type":"response.output_text.delta","delta":"答案"}',
            'data: {"type":"response.completed"}',
        ]
        response = ResponseContext(lines)
        with patch("app.api.requests.post", return_value=response) as post:
            result = list(
                api.stream_chat(
                    {"api_key": "test", "base_url": "https://api.deepseek.com"},
                    "deepseek-flash",
                    "high",
                    True,
                    [{"role": "user", "content": "test"}],
                    1.0,
                    0,
                    threading.Event(),
                    web_search=True,
                )
            )
        self.assertEqual(result, [("reasoning", "思考"), ("content", "答案")])
        self.assertTrue(post.call_args.args[0].endswith("/responses"))
        self.assertEqual(
            post.call_args.kwargs["json"]["tools"],
            [{"type": "web_search"}],
        )


if __name__ == "__main__":
    unittest.main()

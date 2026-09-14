from __future__ import annotations

import json
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
        self.assertEqual(models, ["deepseek-v4-pro", "deepseek-flash"])

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

    def test_search_body_uses_function_tool_and_forces_it_in_standard_mode(
        self,
    ) -> None:
        body = api.build_chat_body(
            "deepseek-flash",
            "high",
            False,
            [{"role": "user", "content": "最新新闻"}],
            0.7,
            2048,
            web_search=True,
        )
        self.assertEqual(body["tools"], api.SEARCH_TOOLS)
        self.assertEqual(
            body["tool_choice"],
            {"type": "function", "function": {"name": "web_search"}},
        )
        self.assertEqual(body["temperature"], 0.7)
        self.assertEqual(body["max_tokens"], 2048)
        self.assertNotIn("reasoning_effort", body)

    def test_search_body_uses_auto_tool_choice_in_thinking_mode(self) -> None:
        body = api.build_chat_body(
            "deepseek-flash",
            "max",
            True,
            [{"role": "user", "content": "最新新闻"}],
            0.5,
            0,
            web_search=True,
        )
        self.assertEqual(body["tools"], api.SEARCH_TOOLS)
        self.assertEqual(body["tool_choice"], "auto")
        self.assertEqual(body["reasoning_effort"], "max")
        self.assertNotIn("temperature", body)

    def test_duckduckgo_lite_results_are_parsed_and_decoded(self) -> None:
        page = (
            '<a rel="nofollow" href="//duckduckgo.com/l/'
            '?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=x" '
            "class='result-link'>Example <b>A</b></a>"
            "<td class='result-snippet'>Snippet <b>one</b> &amp; more</td>"
            '<a rel="nofollow" href="//duckduckgo.com/l/'
            '?uddg=https%3A%2F%2Fexample.com%2Fb&amp;rut=y" '
            "class='result-link'>Example B</a>"
            "<td class='result-snippet'>Snippet two</td>"
        )
        results = api._parse_duckduckgo_lite(page, 5)
        self.assertEqual(results[0]["url"], "https://example.com/a")
        self.assertEqual(results[0]["title"], "Example A")
        self.assertEqual(results[0]["snippet"], "Snippet one & more")
        self.assertEqual(results[1]["title"], "Example B")

    def test_search_tool_content_numbers_sources_for_citations(self) -> None:
        content = api.search_tool_content(
            [{"title": "标题", "url": "https://example.com", "snippet": "摘要"}]
        )
        self.assertIn("[1] 标题", content)
        self.assertIn("URL: https://example.com", content)
        self.assertIn("参考来源", content)

    def test_search_stream_runs_function_tool_and_appends_results(self) -> None:
        def sse(payload: dict) -> str:
            return "data: " + json.dumps(payload, ensure_ascii=False)

        phase_one = ResponseContext(
            [
                sse(
                    {"choices": [{"delta": {"reasoning_content": "先查一下"}}]}
                ),
                sse(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call_1",
                                            "type": "function",
                                            "function": {
                                                "name": "web_search",
                                                "arguments": '{"query":',
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ),
                sse(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "function": {
                                                "arguments": '"DeepSeek 发布"}'
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ),
                sse({"choices": [{"finish_reason": "tool_calls"}]}),
            ]
        )
        phase_two = ResponseContext(
            [
                sse({"choices": [{"delta": {"content": "已发布，见 [1]。"}}]}),
                "data: [DONE]",
            ]
        )
        with (
            patch("app.api.requests.post", side_effect=[phase_one, phase_two]) as post,
            patch(
                "app.api.run_web_search",
                return_value=[
                    {"title": "官网", "url": "https://example.com/a", "snippet": "发布说明"}
                ],
            ) as search,
        ):
            result = list(
                api.stream_chat(
                    {"api_key": "test", "base_url": "https://example.com"},
                    "deepseek-flash",
                    "high",
                    False,
                    [{"role": "user", "content": "DeepSeek 最新发布是什么"}],
                    1.0,
                    0,
                    threading.Event(),
                    web_search=True,
                )
            )
        self.assertEqual(
            result,
            [
                ("reasoning", "先查一下"),
                ("search", "正在联网搜索…"),
                ("search", "已获取 1 条结果，正在生成回答…"),
                ("content", "已发布，见 [1]。"),
            ],
        )
        self.assertTrue(post.call_args_list[0].args[0].endswith("/chat/completions"))
        self.assertEqual(
            post.call_args_list[0].kwargs["json"]["tool_choice"],
            {"type": "function", "function": {"name": "web_search"}},
        )
        second_body = post.call_args_list[1].kwargs["json"]
        self.assertEqual(second_body["tools"], api.SEARCH_TOOLS)
        self.assertEqual(second_body["tool_choice"], "auto")
        self.assertEqual(
            [message["role"] for message in second_body["messages"]],
            ["user", "assistant", "tool"],
        )
        self.assertEqual(
            second_body["messages"][-2]["tool_calls"][0]["id"], "call_1"
        )
        self.assertEqual(
            second_body["messages"][-1]["tool_call_id"], "call_1"
        )
        self.assertIn("[1] 官网", second_body["messages"][-1]["content"])
        self.assertEqual(search.call_args.args[1], "DeepSeek 发布")

    def test_search_stream_does_not_emit_tool_call_preamble_as_answer(self) -> None:
        def sse(payload: dict) -> str:
            return "data: " + json.dumps(payload, ensure_ascii=False)

        response = ResponseContext(
            [
                sse({"choices": [{"delta": {"content": "我先搜索一下。"}}]}),
                sse(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call_1",
                                            "function": {
                                                "name": "web_search",
                                                "arguments": '{"query":"测试"}',
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ),
                sse({"choices": [{"finish_reason": "tool_calls"}]}),
            ]
        )
        final = ResponseContext(
            [sse({"choices": [{"delta": {"content": "最终答案"}}]}), "data: [DONE]"]
        )
        with (
            patch("app.api.requests.post", side_effect=[response, final]),
            patch(
                "app.api.run_web_search",
                return_value=[
                    {"title": "结果", "url": "https://example.com", "snippet": "摘要"}
                ],
            ),
        ):
            result = list(
                api.stream_chat(
                    {"api_key": "test", "base_url": "https://example.com"},
                    "deepseek-flash",
                    "high",
                    True,
                    [{"role": "user", "content": "测试"}],
                    1.0,
                    0,
                    threading.Event(),
                    web_search=True,
                )
            )

        self.assertNotIn(("content", "我先搜索一下。"), result)
        self.assertEqual(result[-1], ("content", "最终答案"))

    def test_zenith_tool_blocks_are_stripped_from_prose(self) -> None:
        raw = (
            "我来打开索尼官方规格页面获取详细信息。 response\n\n"
            '<zenith_calls>\n'
            '<zenith_invoke name="open_page">\n'
            '<zenith_parameter name="url" string="true">'
            "https://helpguide.sony.net/spec.html"
            "</zenith_parameter>\n"
            "</zenith_invoke>\n"
            "</zenith_calls>\n"
        )
        self.assertEqual(
            api._strip_zenith(raw),
            "我来打开索尼官方规格页面获取详细信息。",
        )
        self.assertEqual(
            api._strip_zenith(
                "先说明一下。response\n<zenith calls>\n"
                '<zenith invoke name="web_fetch"></zenith invoke>\n'
                "</zenith calls>"
            ),
            "先说明一下。",
        )
        self.assertEqual(api._strip_zenith("普通回答 response time"), "普通回答 response time")

    def test_fetch_page_text_extracts_title_and_plain_text(self) -> None:
        response = Mock(status_code=200)
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.encoding = "utf-8"
        response.iter_content.return_value = [
            (
                "<html><head><title>规格页</title>"
                "<style>.x{}</style><script>bad()</script></head>"
                "<body><h1>规格</h1><p>APS-C 2600万像素</p>"
                "<table><tr><td>E卡口</td></tr></table></body></html>"
            ).encode("utf-8")
        ]
        with patch("app.api.requests.get", return_value=response):
            page = api.fetch_page_text("https://example.com/spec.html")
        self.assertEqual(page["title"], "规格页")
        self.assertIn("APS-C 2600万像素", page["snippet"])
        self.assertIn("E卡口", page["snippet"])
        self.assertNotIn("bad()", page["snippet"])
        self.assertNotIn(".x{}", page["snippet"])

    def test_fetch_page_text_rejects_loopback_urls(self) -> None:
        with self.assertRaises(api.APIError):
            api.fetch_page_text("http://127.0.0.1:8080/secret")

    def test_search_loop_runs_multiple_tool_rounds_with_global_citations(self) -> None:
        def sse(payload: dict) -> str:
            return "data: " + json.dumps(payload, ensure_ascii=False)

        tool_call = {
            "delta": {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query":"第一轮"}',
                        },
                    }
                ]
            }
        }
        second_call = {
            "delta": {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query":"第二轮"}',
                        },
                    }
                ]
            }
        }
        responses = [
            ResponseContext(
                [sse({"choices": [tool_call]}), sse({"choices": [{"finish_reason": "tool_calls"}]})]
            ),
            ResponseContext(
                [sse({"choices": [second_call]}), sse({"choices": [{"finish_reason": "tool_calls"}]})]
            ),
            ResponseContext(
                [sse({"choices": [{"delta": {"content": "答案 [1][2]。"}}]}), "data: [DONE]"]
            ),
        ]
        results_by_query = {
            "第一轮": [{"title": "甲", "url": "https://example.com/a", "snippet": "A"}],
            "第二轮": [{"title": "乙", "url": "https://example.com/b", "snippet": "B"}],
        }
        with (
            patch("app.api.requests.post", side_effect=responses) as post,
            patch(
                "app.api.run_web_search",
                side_effect=lambda cfg, query, **kwargs: results_by_query.get(query, []),
            ),
        ):
            result = list(
                api.stream_chat(
                    {"api_key": "test", "base_url": "https://example.com"},
                    "deepseek-flash",
                    "high",
                    False,
                    [{"role": "user", "content": "两轮搜索"}],
                    1.0,
                    0,
                    threading.Event(),
                    web_search=True,
                )
            )
        self.assertEqual(
            [item[0] for item in result],
            ["search", "search", "search", "search", "content"],
        )
        self.assertEqual(post.call_count, 3)
        third_body = post.call_args_list[2].kwargs["json"]
        tool_messages = [
            message for message in third_body["messages"] if message["role"] == "tool"
        ]
        self.assertEqual(len(tool_messages), 2)
        self.assertIn("[1] 甲", tool_messages[0]["content"])
        self.assertIn("[2] 乙", tool_messages[1]["content"])


if __name__ == "__main__":
    unittest.main()

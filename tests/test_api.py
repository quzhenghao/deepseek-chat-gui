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
    def __init__(
        self, lines: list[str], content_type: str = "text/event-stream", *, payload=None
    ) -> None:
        self.status_code = 200
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self._lines = lines
        self._payload = payload
        self.text = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self, decode_unicode: bool = False):
        return iter(self._lines)

    def json(self):
        return self._payload

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
                {"id": "unavailable-model"},
                {"id": "deepseek-flash"},
            ]
        }
        with patch("app.api.requests.get", return_value=response):
            models = api.list_models(
                {"api_key": "test", "base_url": "https://api.deepseek.com"}
            )
        self.assertEqual(models, ["deepseek-v4-pro", "deepseek-flash"])

    def test_model_listing_rejects_invalid_response_shapes(self) -> None:
        for payload in ([], {}, {"data": None}, {"data": "invalid"}):
            response = Mock(status_code=200)
            response.json.return_value = payload
            with (
                patch("app.api.requests.get", return_value=response),
                self.assertRaises(api.APIError),
            ):
                api.list_models({"api_key": "test"})

    def test_max_output_stays_within_the_official_limit(self) -> None:
        for model in DEFAULT_MODELS:
            body = api.build_chat_body(model, "high", True, [], 1.0, 393216)
            self.assertEqual(body["max_tokens"], 393216)
            body = api.build_chat_body(model, "max", True, [], 1.0, 999999)
            self.assertEqual(body["max_tokens"], 393216)

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

    def test_tool_requests_preserve_reasoning_from_every_assistant_turn(self) -> None:
        history = [
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "答案", "reasoning_content": "  思考\n"},
            {"role": "user", "content": "第二问"},
            {"role": "assistant", "content": "直接回答"},
            {"role": "user", "content": "请搜索"},
        ]
        messages = api.payload_messages(history)
        body = api.build_chat_body(
            "deepseek-flash", "high", True, messages, 1.0, 0, web_search=True
        )
        self.assertEqual(body["messages"][1]["reasoning_content"], "  思考\n")
        self.assertEqual(body["messages"][3]["reasoning_content"], "")
        messages.append({"role": "user", "content": "后续消息"})
        self.assertEqual(len(body["messages"]), 5)

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
        response = ResponseContext(
            [],
            "application/json",
            payload={
                "choices": [
                    {"message": {"reasoning_content": "过程", "content": "结论"}}
                ]
            },
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

    def test_deepseek_search_uses_bearer_auth_and_model_summaries(self) -> None:
        response = ResponseContext(
            [],
            payload={"results": [
                {"title": "甲", "url": "https://example.com/a", "summary": "长摘要", "snippet": "短摘要"},
                {"title": "乙", "url": "https://example.com/b", "summary": "", "snippet": "短摘要"},
            ]},
        )
        with patch("app.api.requests.post", return_value=response) as post:
            results = api.run_web_search(
                {"api_key": "test", "base_url": "https://api.deepseek.com/v1/", "search_max_results": 2},
                "  搜" + "词" * 128,
            )
        self.assertEqual(post.call_args.args, ("https://api.deepseek.com/v1/tools/search",))
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test")
        self.assertEqual(post.call_args.kwargs["json"], {
            "query": "搜" + "词" * 127, "count": 2, "need_content": False,
        })
        self.assertEqual(results, [
            {"title": "甲", "url": "https://example.com/a", "snippet": "长摘要"},
            {"title": "乙", "url": "https://example.com/b", "snippet": "短摘要"},
        ])

    def test_search_tool_content_numbers_sources_for_citations(self) -> None:
        content = api._sources_tool_content(
            {1: {"title": "标题", "url": "https://example.com", "snippet": "摘要"}}
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
                    {"choices": [{"delta": {"reasoning_content": "  先查一下\n"}}]}
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
        search_response = ResponseContext([], payload={"results": [
            {"title": "官网", "url": "https://example.com/a", "summary": "发布说明"}
        ]})
        with patch.object(
            api.requests.Session, "post", autospec=True,
            side_effect=[phase_one, search_response, phase_two],
        ) as post:
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
                ("reasoning", "  先查一下\n"),
                ("search", "正在联网搜索…"),
                ("search", "已获取 1 条结果，正在生成回答…"),
                ("content", "已发布，见 [1]。"),
            ],
        )
        self.assertEqual(
            [call.args[1] for call in post.call_args_list],
            [
                "https://example.com/chat/completions",
                "https://example.com/v1/tools/search",
                "https://example.com/chat/completions",
            ],
        )
        self.assertEqual(len({call.args[0] for call in post.call_args_list}), 1)
        self.assertEqual(
            post.call_args_list[0].kwargs["json"]["tool_choice"],
            {"type": "function", "function": {"name": "web_search"}},
        )
        second_body = post.call_args_list[2].kwargs["json"]
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
            second_body["messages"][-2]["reasoning_content"], "  先查一下\n"
        )
        self.assertEqual(
            second_body["messages"][-1]["tool_call_id"], "call_1"
        )
        self.assertIn("[1] 官网", second_body["messages"][-1]["content"])
        self.assertEqual(post.call_args_list[1].kwargs["json"]["query"], "DeepSeek 发布")

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
            patch.object(api.requests.Session, "post", side_effect=[response, final]),
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

    def test_search_stream_surfaces_api_errors(self) -> None:
        response = ResponseContext(
            ['data: {"error":{"message":"request rejected"}}', "data: [DONE]"]
        )
        with (
            patch.object(api.requests.Session, "post", return_value=response),
            self.assertRaisesRegex(api.APIError, "request rejected"),
        ):
            list(
                api.stream_chat(
                    {"api_key": "test"}, "deepseek-flash", "high", True,
                    [{"role": "user", "content": "搜索"}], 1.0, 0,
                    threading.Event(), web_search=True,
                )
            )

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

    def test_fetch_page_text_returns_deepseek_markdown(self) -> None:
        target = "https://example.com/spec.html"
        markdown = "# 规格\n\n- APS-C 2600万像素\n- E卡口"
        response = ResponseContext([], payload={"title": "规格页", "content": markdown})
        with patch("app.api.requests.post", return_value=response) as post:
            page = api.fetch_page_text({"api_key": "test"}, target)
        self.assertEqual(page, {"title": "规格页", "url": target, "snippet": markdown})
        self.assertEqual(post.call_args.args, ("https://api.deepseek.com/v1/tools/fetch",))
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test")
        self.assertEqual(post.call_args.kwargs["json"], {"url": target})

    def test_fetch_page_text_rejects_loopback_urls(self) -> None:
        with self.assertRaises(api.APIError):
            api.fetch_page_text({}, "http://127.0.0.1:8080/secret")

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
                    },
                    {
                        "index": 1,
                        "id": "call_3",
                        "type": "function",
                        "function": {
                            "name": "open_page",
                            "arguments": '{"url":"https://example.com/a"}',
                        },
                    },
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
            ResponseContext([], payload={"title": "甲", "content": "甲的网页正文"}),
            ResponseContext(
                [sse({"choices": [{"delta": {"content": "答案 [1][2]。"}}]}), "data: [DONE]"]
            ),
        ]
        results_by_query = {
            "第一轮": [{"title": "甲", "url": "https://example.com/a", "snippet": "A"}],
            "第二轮": [{"title": "乙", "url": "https://example.com/b", "snippet": "B"}],
        }
        with (
            patch.object(api.requests.Session, "post", side_effect=responses) as post,
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
        self.assertEqual(post.call_count, 4)
        third_body = post.call_args_list[3].kwargs["json"]
        tool_messages = [
            message for message in third_body["messages"] if message["role"] == "tool"
        ]
        self.assertEqual(len(tool_messages), 3)
        self.assertIn("[1] 甲", tool_messages[0]["content"])
        self.assertIn("[2] 乙", tool_messages[1]["content"])
        self.assertIn("[1] 甲", tool_messages[2]["content"])
        self.assertIn("甲的网页正文", tool_messages[2]["content"])

if __name__ == "__main__":
    unittest.main()

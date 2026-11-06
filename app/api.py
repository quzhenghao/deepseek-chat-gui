from __future__ import annotations

import base64
import json
import mimetypes
import re
import threading
import unicodedata
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlparse

import requests

from .config import (
    DEFAULT_BASE_URL,
    MAX_OUTPUT_TOKENS,
    normalize_effort,
    normalize_official_models,
    search_result_count,
    uses_official_api,
)

SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_INLINE_IMAGE_BYTES = 32 * 1024 * 1024
TITLE_MAX_DISPLAY_UNITS = 24
_TITLE_SYSTEM_PROMPT = (
    "你只负责生成对话历史标题。请根据给出的完整对话，概括当前最核心的主题，"
    "并在主题变化时反映最新语境。严格只输出一个精短标题：优先使用6至12个汉字，"
    "英文不超过24个字符；不要解释，不要加引号、序号、句号、冒号或Markdown标记。"
)

SEARCH_TOOL_NAME = "web_search"
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": SEARCH_TOOL_NAME,
        "description": (
            "检索互联网上的最新信息，用于回答需要实时数据、新闻或外部事实的问题。"
            "返回与查询相关的网页标题、URL 和摘要。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "具体的搜索词，最多 128 个字符，每次只搜一个主题。",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
OPEN_PAGE_TOOL_NAME = "open_page"
WEB_FETCH_TOOL_NAME = "web_fetch"
_PAGE_TOOL = {
    "type": "function",
    "function": {
        "name": OPEN_PAGE_TOOL_NAME,
        "description": (
            "打开一个网页 URL 并读取其中的正文内容，用于查看用户指定的具体页面。"
            "返回页面标题和 Markdown 正文。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要读取的完整 http(s) 网页地址。",
                }
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}
WEB_FETCH_TOOL = {
    "type": "function",
    "function": {
        "name": WEB_FETCH_TOOL_NAME,
        "description": "读取网页 URL 的正文内容，是 open_page 的同义工具。",
        "parameters": _PAGE_TOOL["function"]["parameters"],
    },
}
SEARCH_TOOLS = [SEARCH_TOOL, _PAGE_TOOL, WEB_FETCH_TOOL]
MAX_SEARCH_ROUNDS = 3
_SEARCH_RESULT_PROMPT = (
    "以下是本次联网搜索返回的网页结果，每条带有唯一的 [编号]：\n\n"
    "{results}\n\n"
    "请严格基于上述结果回答用户的问题，并遵守：\n"
    "1. 引用某条结果的内容时，在句末标注该条编号，例如 [1]、[2]。\n"
    "2. 回答末尾用 Markdown 列表输出“参考来源”，"
    "每行形如 `1. [标题](URL)`，编号必须与正文引用一致。\n"
    "3. 只引用上面列出的结果，不要编造 URL 或事实。\n"
    "4. 如果结果不足以回答，请明确说明信息不足，不要臆测。"
)
MAX_SEARCH_QUERY_CHARS = 128
MAX_PAGE_TEXT_CHARS = 12_000
_ZENITH_PARAM_BLOCK_RE = re.compile(
    r"<zenith[_ ]parameter\b[^>]*>.*?</zenith[_ ]parameter\s*>\s*",
    flags=re.IGNORECASE | re.DOTALL,
)
_ZENITH_INVOKE_BLOCK_RE = re.compile(
    r"<zenith[_ ]invoke\b[^>]*>.*?</zenith[_ ]invoke\s*>\s*",
    flags=re.IGNORECASE | re.DOTALL,
)
_ZENITH_CALLS_BLOCK_RE = re.compile(
    r"<zenith[_ ]calls\b[^>]*>.*?</zenith[_ ]calls\s*>\s*",
    flags=re.IGNORECASE | re.DOTALL,
)
_ZENITH_TAG_RE = re.compile(
    r"</?zenith[_ ][^>]*>",
    flags=re.IGNORECASE,
)

def _strip_zenith(text: str) -> str:
    # Strip leaked tool markup from visible output.
    cleaned = text or ""
    if "<zenith" not in cleaned.lower():
        return cleaned
    cleaned = re.sub(
        r"(?i)\s*\b(?:reasoning|response)\b\s*(?=<zenith[_ ])",
        "",
        cleaned,
    )
    for _ in range(6):
        before = cleaned
        cleaned = _ZENITH_PARAM_BLOCK_RE.sub("", cleaned)
        cleaned = _ZENITH_INVOKE_BLOCK_RE.sub("", cleaned)
        cleaned = _ZENITH_CALLS_BLOCK_RE.sub("", cleaned)
        cleaned = _ZENITH_TAG_RE.sub("", cleaned)
        if cleaned == before:
            break
    return cleaned

class APIError(Exception):
    pass

def is_image_path(path: str) -> bool:
    file_path = Path(path)
    return file_path.is_file() and file_path.suffix.lower() in SUPPORTED_IMAGE_EXTS

def _endpoint(cfg: dict, resource: str, *, versioned: bool = False) -> str:
    base = str(cfg.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    if versioned and not base.endswith("/v1"):
        base += "/v1"
    return f"{base}/{resource.lstrip('/')}"

def _encode_image(path: str) -> str:
    file_path = Path(path)
    if file_path.stat().st_size > MAX_INLINE_IMAGE_BYTES:
        raise APIError(f"图片 {file_path.name} 超过 32 MiB，无法以内联方式发送")
    mime = mimetypes.guess_type(str(file_path))[0] or "image/png"
    payload = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"

def payload_messages(history: list[dict]) -> list[dict]:
    result: list[dict] = []
    for message in history:
        role = message.get("role")
        if role not in {"user", "assistant", "system"}:
            continue
        content = message.get("content") or ""
        images = message.get("images") or []
        if role == "user" and images:
            parts: list[dict] = []
            if content.strip():
                parts.append({"type": "text", "text": content})
            for image_path in images:
                try:
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": _encode_image(image_path)},
                        }
                    )
                except OSError:
                    continue
            if not parts:
                parts.append({"type": "text", "text": "请查看图片。"})
            result.append({"role": role, "content": parts})
        else:
            item = {"role": role, "content": content}
            if role == "assistant":
                item["reasoning_content"] = message.get("reasoning_content") or ""
            result.append(item)
    return result

def title_messages(history: list[dict]) -> list[dict]:
    # Summarize text turns without resending images.
    result: list[dict] = [{"role": "system", "content": _TITLE_SYSTEM_PROMPT}]
    for message in history:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = message.get("content") or ""
        if isinstance(content, list):
            text_parts = [
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            content = "\n".join(part for part in text_parts if part)
        else:
            content = str(content)
        images = message.get("images") or []
        if role == "user" and images:
            image_note = f"[本轮包含{len(images)}张图片]"
            content = f"{content}\n{image_note}" if content.strip() else image_note
        if content.strip():
            result.append({"role": role, "content": content})
    result.append(
        {
            "role": "user",
            "content": "现在根据上面的全部对话生成历史栏标题，只输出标题。",
        }
    )
    return result

def _display_units(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
        for character in text
    )

def clean_conversation_title(
    value: str,
    max_display_units: int = TITLE_MAX_DISPLAY_UNITS,
) -> str:
    title = str(value or "").strip()
    title = re.sub(r"^```(?:text|markdown)?[ \t]*\n?", "", title, flags=re.I)
    title = re.sub(r"\n?```$", "", title).strip()
    lines = [line.strip() for line in title.splitlines() if line.strip()]
    title = lines[0] if lines else ""
    title = title.replace("**", "").replace("__", "").replace("`", "")
    title = re.sub(r"^(?:标题|对话标题|主题)\s*[:：]\s*", "", title)
    title = re.sub(r"^\s*(?:[-*#]+|\d+[.)、])\s*", "", title)
    title = " ".join(title.split())
    title = title.strip(" \t\r\n\"'“”‘’《》【】[]()（）:：,，.。!！?？;；")
    if not title:
        return ""
    if _display_units(title) <= max_display_units:
        return title

    kept: list[str] = []
    used = 0
    ellipsis_units = _display_units("…")
    for character in title:
        units = 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
        if used + units + ellipsis_units > max_display_units:
            break
        kept.append(character)
        used += units
    return "".join(kept).rstrip() + "…"

def build_chat_body(
    model: str,
    effort: str,
    deep_thinking: bool,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    web_search: bool = False,
    tool_choice: str | dict | None = None,
) -> dict:
    body: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "thinking": {"type": "enabled" if deep_thinking else "disabled"},
    }
    if deep_thinking:
        body["reasoning_effort"] = normalize_effort(effort)
    else:
        body["temperature"] = temperature
    if max_tokens > 0:
        body["max_tokens"] = min(max_tokens, MAX_OUTPUT_TOKENS)
    if web_search:
        body["messages"] = [
            {**message, "reasoning_content": message.get("reasoning_content") or ""}
            if message.get("role") == "assistant"
            else message
            for message in messages
        ]
        body["tools"] = SEARCH_TOOLS
        body["tool_choice"] = (
            tool_choice
            if tool_choice is not None
            else (
                "auto"
                if deep_thinking
                else {"type": "function", "function": {"name": SEARCH_TOOL_NAME}}
            )
        )
    return body

def _extract_parts(payload: dict) -> list[tuple[str, str]]:
    error = payload.get("error") if isinstance(payload, dict) else None
    if error:
        if isinstance(error, dict):
            raise APIError(str(error.get("message") or error))
        raise APIError(str(error))
    parts: list[tuple[str, str]] = []
    for choice in payload.get("choices") or []:
        message = choice.get("delta") or choice.get("message") or {}
        reasoning = (
            message.get("reasoning_content") or message.get("reasoning") or ""
        )
        content = message.get("content") or ""
        if reasoning:
            cleaned = _strip_zenith(str(reasoning))
            if cleaned:
                parts.append(("reasoning", cleaned))
        if content:
            cleaned = _strip_zenith(str(content))
            if cleaned:
                parts.append(("content", cleaned))
    return parts

def _response_error(response: requests.Response) -> str:
    try:
        data = response.json()
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict) and error.get("message"):
            return f"HTTP {response.status_code}：{error['message']}"
        if error:
            return f"HTTP {response.status_code}：{error}"
    except ValueError:
        pass
    detail = response.text.strip()[:400]
    return f"HTTP {response.status_code}：{detail or '请求失败'}"

def _request_web_tool(
    cfg: dict, name: str, data: dict, session: requests.Session | None
) -> dict:
    headers = {"Authorization": f"Bearer {cfg.get('api_key') or ''}"}
    try:
        with (session or requests).post(
            _endpoint(cfg, f"tools/{name}", versioned=True),
            headers=headers,
            json=data,
            timeout=(5, 30),
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise APIError(_response_error(response))
            try:
                payload = response.json()
            except ValueError as exc:
                raise APIError("DeepSeek 网页工具返回了无效 JSON") from exc
    except requests.RequestException as exc:
        raise APIError(f"DeepSeek 网页工具请求失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise APIError("DeepSeek 网页工具响应格式无效")
    return payload

def run_web_search(
    cfg: dict,
    query: str,
    max_results: int | None = None,
    *,
    session: requests.Session | None = None,
) -> list[dict]:
    text = str(query or "").strip()[:MAX_SEARCH_QUERY_CHARS].rstrip()
    if not text:
        return []
    count = search_result_count(
        cfg.get("search_max_results") if max_results is None else max_results
    )
    payload = _request_web_tool(
        cfg, "search", {"query": text, "count": count, "need_content": False}, session
    )
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise APIError("DeepSeek 搜索结果格式无效")
    results: list[dict] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        summary = str(item.get("summary") or "").strip()
        snippet = summary or str(item.get("snippet") or "").strip()
        if title or url or snippet:
            results.append({"title": title, "url": url, "snippet": snippet})
    return results

def fetch_page_text(
    cfg: dict,
    url: str,
    max_chars: int = MAX_PAGE_TEXT_CHARS,
    *,
    session: requests.Session | None = None,
) -> dict:
    target = str(url or "").strip()
    try:
        parsed = urlparse(target)
    except ValueError as exc:
        raise APIError("页面地址无效，只支持 http(s) URL") from exc
    host = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or len(target) > 8192
    ):
        raise APIError("页面地址无效，只支持不含凭证的 http(s) URL")
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".localhost"):
        raise APIError("不能读取本机回环地址")
    payload = _request_web_tool(cfg, "fetch", {"url": target}, session)
    content = str(payload.get("content") or "").strip()
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "…"
    title = str(payload.get("title") or "").strip() or parsed.netloc
    return {"title": title, "url": target, "snippet": content}

def _tool_argument(arguments: str, *keys: str) -> str:
    try:
        value = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return ""
    if isinstance(value, dict):
        value = next((value[key] for key in keys if value.get(key)), "")
    return value.strip() if isinstance(value, str) else ""

def _sources_tool_content(results: dict[int, dict]) -> str:
    entries: list[str] = []
    for number, item in results.items():
        title = item["title"] or "无标题"
        entry = f"[{number}] {title}"
        if item["url"]:
            entry += f"\nURL: {item['url']}"
        if item["snippet"]:
            entry += f"\n摘要: {item['snippet']}"
        entries.append(entry)
    return _SEARCH_RESULT_PROMPT.format(results="\n\n".join(entries))

def list_models(cfg: dict, timeout: tuple[int, int] = (5, 15)) -> list[str]:
    headers = {"Authorization": f"Bearer {cfg.get('api_key') or ''}"}
    try:
        response = requests.get(
            _endpoint(cfg, "models"), headers=headers, timeout=timeout
        )
    except requests.RequestException as exc:
        raise APIError(f"无法连接 DeepSeek：{exc}") from exc
    if response.status_code != 200:
        raise APIError(_response_error(response))
    try:
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise APIError("模型列表响应格式无效")
        models = [
            str(item["id"])
            for item in data.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
        return (
            normalize_official_models(models)
            if uses_official_api(cfg.get("base_url"))
            else models
        )
    except (ValueError, TypeError) as exc:
        raise APIError("模型列表响应格式无效") from exc

def _iter_chat_payloads(
    response: requests.Response, stop: threading.Event
) -> Iterator[dict]:
    with response:
        if response.status_code != 200:
            raise APIError(_response_error(response))
        response.encoding = "utf-8"
        if "application/json" in response.headers.get("Content-Type", ""):
            try:
                yield response.json()
            except ValueError as exc:
                raise APIError("DeepSeek 返回了无效 JSON") from exc
            return
        for raw_line in response.iter_lines(decode_unicode=True):
            if stop.is_set():
                return
            line = (raw_line or "").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data.upper() == "[DONE]":
                return
            if not data:
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue

def _chat_headers(cfg: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg.get('api_key') or ''}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

def _request_chat_payloads(
    cfg: dict,
    body: dict,
    stop: threading.Event,
    timeout: tuple[int, int],
    response_callback: Callable[[requests.Response | None], None] | None,
    session: requests.Session | None = None,
) -> Iterator[dict]:
    if stop.is_set():
        return
    try:
        response = (session or requests).post(
            _endpoint(cfg, "chat/completions"),
            headers=_chat_headers(cfg),
            json=body,
            stream=True,
            timeout=timeout,
        )
        if response_callback:
            response_callback(response)
        for payload in _iter_chat_payloads(response, stop):
            if stop.is_set():
                return
            yield payload
    except requests.RequestException as exc:
        raise APIError(f"网络请求失败：{exc}") from exc
    finally:
        if response_callback:
            response_callback(None)

def stream_chat(
    cfg: dict,
    model: str,
    effort: str,
    deep_thinking: bool,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    stop: threading.Event,
    timeout: tuple[int, int] = (10, 600),
    response_callback: Callable[[requests.Response | None], None] | None = None,
    *,
    web_search: bool = False,
) -> Iterator[tuple[str, str]]:
    if web_search:
        with requests.Session() as session:
            yield from stream_search_function(
                cfg, model, effort, deep_thinking, messages, temperature, max_tokens,
                stop, timeout, response_callback, session,
            )
        return
    body = build_chat_body(
        model, effort, deep_thinking, messages, temperature, max_tokens
    )
    for payload in _request_chat_payloads(cfg, body, stop, timeout, response_callback):
        yield from _extract_parts(payload)

def stream_search_function(
    cfg: dict,
    model: str,
    effort: str,
    deep_thinking: bool,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    stop: threading.Event,
    timeout: tuple[int, int],
    response_callback: Callable[[requests.Response | None], None] | None,
    session: requests.Session,
) -> Iterator[tuple[str, str]]:
    working = list(messages)
    source_numbers: dict[str, int] = {}

    for round_index in range(MAX_SEARCH_ROUNDS):
        if stop.is_set():
            return
        body = build_chat_body(
            model,
            effort,
            deep_thinking,
            working,
            temperature,
            max_tokens,
            web_search=True,
            tool_choice=None if round_index == 0 else "auto",
        )
        tool_calls: dict[int, dict[str, str]] = {}
        round_content: list[str] = []
        round_reasoning: list[str] = []
        for payload in _request_chat_payloads(
            cfg, body, stop, timeout, response_callback, session
        ):
            if payload.get("error"):
                _extract_parts(payload)
            for choice in payload.get("choices") or []:
                delta = choice.get("delta") or choice.get("message") or {}
                raw_reasoning = str(
                    delta.get("reasoning_content") or delta.get("reasoning") or ""
                )
                if raw_reasoning:
                    round_reasoning.append(raw_reasoning)
                    reasoning = _strip_zenith(raw_reasoning)
                    if reasoning:
                        yield ("reasoning", reasoning)
                content = _strip_zenith(str(delta.get("content") or ""))
                if content:
                    round_content.append(content)
                for call in delta.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    index = int(call.get("index", 0))
                    entry = tool_calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    if call.get("id"):
                        entry["id"] = str(call["id"])
                    function = call.get("function")
                    if isinstance(function, dict):
                        if function.get("name"):
                            entry["name"] = str(function["name"])
                        if function.get("arguments"):
                            entry["arguments"] += str(function["arguments"])

        if stop.is_set():
            return
        if not tool_calls:
            # Only show answer text from a round that finished without tool calls.
            for content in round_content:
                yield ("content", content)
            return

        yield ("search", "正在联网搜索…")
        calls: list[dict] = []
        tool_messages: list[dict] = []
        for index, call in sorted(tool_calls.items()):
            if stop.is_set():
                return
            call_id = call["id"] or f"call_{index}"
            name = call["name"].strip() or SEARCH_TOOL_NAME
            arguments = call["arguments"] or "{}"
            calls.append({
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            })
            try:
                if name in {OPEN_PAGE_TOOL_NAME, WEB_FETCH_TOOL_NAME}:
                    url = _tool_argument(arguments, "url", "link", "href")
                    results = [fetch_page_text(cfg, url, session=session)] if url else []
                else:
                    query = _tool_argument(arguments, "query", "q", "keywords")
                    results = run_web_search(cfg, query, session=session) if query else []
                numbered_results: dict[int, dict] = {}
                for result in results:
                    # Reuse the citation number and keep this call's result text.
                    key = result["url"] or f"{result['title']}|{result['snippet']}"
                    number = source_numbers.setdefault(key, len(source_numbers) + 1)
                    numbered_results.setdefault(number, result)
                content = (
                    _sources_tool_content(numbered_results)
                    if numbered_results
                    else "本次操作没有返回可用结果。"
                )
            except APIError as exc:
                content = f"工具执行失败：{exc}"
            tool_messages.append(
                {"role": "tool", "tool_call_id": call_id, "content": content}
            )

        if stop.is_set():
            return
        if source_numbers:
            yield ("search", f"已获取 {len(source_numbers)} 条结果，正在生成回答…")
        else:
            yield ("search", "未找到可用结果，正在生成回答…")

        working.append(
            {
                "role": "assistant",
                "content": "".join(round_content).strip() or None,
                "reasoning_content": "".join(round_reasoning),
                "tool_calls": calls,
            }
        )
        working.extend(tool_messages)

    working.append(
        {
            "role": "system",
            "content": (
                "请基于已经获取的全部信息直接回答用户的问题，不要再调用任何工具，"
                "也不要输出 <zenith_calls>、<zenith_invoke> 等内部格式。"
            ),
        }
    )
    body = build_chat_body(
        model, effort, deep_thinking, working, temperature, max_tokens,
        web_search=True, tool_choice="none",
    )
    for payload in _request_chat_payloads(
        cfg, body, stop, timeout, response_callback, session
    ):
        yield from _extract_parts(payload)

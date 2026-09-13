from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
import threading
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import parse_qs, unquote, urlparse

import requests

from .config import normalize_official_models, uses_official_api


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
                    "description": "用于搜索的查询词，尽量具体、一次只搜一个主题。",
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
            "返回页面标题和纯文本内容。"
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
DEFAULT_SEARCH_MAX_RESULTS = 5
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
    """Remove harness-style tool-call blocks the model may leak into prose."""

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


def _endpoint(cfg: dict, resource: str) -> str:
    base = str(cfg.get("base_url") or "https://api.deepseek.com").strip().rstrip("/")
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
            result.append({"role": role, "content": content})
    return result


def title_messages(history: list[dict]) -> list[dict]:
    """Build a lightweight title request from every visible dialogue turn."""

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
    """Normalize untrusted model output into one title that fits the sidebar."""

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
        body["reasoning_effort"] = (
            effort if effort in {"low", "high", "max"} else "high"
        )
    else:
        body["temperature"] = temperature
    if max_tokens > 0:
        body["max_tokens"] = max_tokens
    if web_search:
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


def _search_max_results(cfg: dict) -> int:
    try:
        value = int(cfg.get("search_max_results", DEFAULT_SEARCH_MAX_RESULTS))
    except (TypeError, ValueError):
        value = DEFAULT_SEARCH_MAX_RESULTS
    return max(1, min(10, value))


def run_web_search(cfg: dict, query: str, max_results: int | None = None) -> list[dict]:
    """Execute one web query through the configured search provider."""

    text = str(query or "").strip()
    if not text:
        return []
    provider = str(cfg.get("search_provider") or "duckduckgo").strip().lower()
    limit = max_results if max_results is not None else _search_max_results(cfg)
    if provider == "tavily":
        key = str(cfg.get("search_api_key") or "").strip()
        if not key:
            raise APIError("Tavily 联网搜索需要先在设置中填写搜索 API Key")
        return _tavily_search(key, text, limit)
    return _duckduckgo_search(text, limit)


def _search_http_error(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            detail = data.get("message") or data.get("detail")
            if isinstance(detail, dict):
                detail = detail.get("error") or detail.get("message") or detail
            if detail:
                return f"HTTP {response.status_code}：{detail}"
    except ValueError:
        pass
    text = response.text.strip()[:400]
    return f"HTTP {response.status_code}：{text or '搜索服务请求失败'}"


def _tavily_search(key: str, query: str, max_results: int) -> list[dict]:
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
            },
            timeout=(5, 30),
        )
    except requests.RequestException as exc:
        raise APIError(f"联网搜索请求失败：{exc}") from exc
    if response.status_code != 200:
        raise APIError(_search_http_error(response))
    try:
        data = response.json()
    except ValueError as exc:
        raise APIError("搜索服务返回了无效 JSON") from exc
    results: list[dict] = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("content") or "").strip()
        if not (title or snippet or url):
            continue
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_DDG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}
_DDG_LINK_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", flags=re.IGNORECASE | re.DOTALL)
_DDG_SNIPPET_RE = re.compile(
    r"<td\b[^>]*class=[\"']result-snippet[\"'][^>]*>(.*?)</td>",
    flags=re.IGNORECASE | re.DOTALL,
)


def _duckduckgo_search(query: str, max_results: int) -> list[dict]:
    try:
        response = requests.post(
            _DDG_LITE_URL,
            data={"q": query},
            headers=_DDG_HEADERS,
            timeout=(5, 20),
        )
    except requests.RequestException as exc:
        raise APIError(f"联网搜索请求失败：{exc}") from exc
    if response.status_code != 200:
        raise APIError(_search_http_error(response))
    return _parse_duckduckgo_lite(response.text, max_results)


def _strip_html_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))


def _ddg_target(url: str) -> str:
    parsed = urlparse(url.strip())
    target = ""
    if "duckduckgo.com" in parsed.netloc and parsed.path.endswith("/l/"):
        target = (parse_qs(parsed.query).get("uddg") or [""])[0]
    if not target:
        target = url.strip()
    target = unquote(target)
    if target.startswith("//"):
        target = "https:" + target
    return target


def _parse_duckduckgo_lite(page: str, max_results: int) -> list[dict]:
    links: list[tuple[str, str]] = []
    for match in _DDG_LINK_RE.finditer(page or ""):
        attributes = match.group(1)
        if "result-link" not in attributes:
            continue
        href = re.search(r"""href=["']([^"']+)""", attributes, flags=re.IGNORECASE)
        if not href:
            continue
        links.append((href.group(1), match.group(2)))
    snippets = _DDG_SNIPPET_RE.findall(page or "")

    results: list[dict] = []
    seen: set[str] = set()
    for index, (href, title) in enumerate(links):
        url = _ddg_target(href)
        if not url or url in seen:
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        title_text = " ".join(_strip_html_tags(title).split())
        snippet_text = " ".join(_strip_html_tags(snippet).split())
        if not title_text and not snippet_text:
            continue
        results.append({"title": title_text, "url": url, "snippet": snippet_text})
        seen.add(url)
        if len(results) >= max_results:
            break
    return results


class _PageTextExtractor(HTMLParser):
    """Collect visible text from a fetched page while dropping noisy elements."""

    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._capturing_title = False
        self._title: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS:
            self._skip_depth += 1
        elif lowered == "title" and self._skip_depth == 0:
            self._capturing_title = True
        elif lowered in {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "td", "th"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif lowered == "title":
            self._capturing_title = False
        elif lowered in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "td", "th"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._capturing_title:
            self._title.append(data)
        else:
            self._chunks.append(data)

    def title(self) -> str:
        return " ".join("".join(self._title).split())

    def text(self) -> str:
        return re.sub(r"[ \t]*\n[ \t]*", "\n", " ".join(self._chunks)).strip()


def _is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(
        ".localhost"
    )


def fetch_page_text(
    url: str, max_chars: int = MAX_PAGE_TEXT_CHARS
) -> dict:
    """Fetch one page and return its title plus readable plain text."""

    target = str(url or "").strip()
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise APIError("页面地址无效，只支持 http(s) URL")
    if _is_loopback_url(target):
        raise APIError("不能读取本机回环地址")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        response = requests.get(target, headers=headers, timeout=(8, 25), stream=True)
    except requests.RequestException as exc:
        raise APIError(f"打开页面失败：{exc}") from exc
    if response.status_code != 200:
        raise APIError(_search_http_error(response))
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        raise APIError("页面不是可读取的文本或 HTML")
    try:
        chunks: list[bytes] = []
        size = 0
        for piece in response.iter_content(chunk_size=32 * 1024):
            if not piece:
                continue
            chunks.append(piece)
            size += len(piece)
            if size >= 2 * 1024 * 1024:
                break
        raw = b"".join(chunks)
    except requests.RequestException as exc:
        raise APIError(f"读取页面失败：{exc}") from exc
    finally:
        response.close()
    try:
        page = raw.decode(response.encoding or "utf-8", errors="replace")
    except (LookupError, UnicodeDecodeError):
        page = raw.decode("utf-8", errors="replace")
    extractor = _PageTextExtractor()
    extractor.feed(page)
    text = extractor.text()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    title = extractor.title() or parsed.netloc
    return {"title": title, "url": target, "snippet": text}


def _tool_urls(arguments: str) -> list[str]:
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, str):
        return [parsed.strip()] if parsed.strip() else []
    if not isinstance(parsed, dict):
        return []
    url = parsed.get("url") or parsed.get("link") or parsed.get("href")
    if isinstance(url, str) and url.strip():
        return [url.strip()]
    return []


def _dedupe_results(results: list[dict]) -> list[dict]:
    kept: list[dict] = []
    seen: set[str] = set()
    for item in results:
        url = str(item.get("url") or "").strip()
        key = url or f"{item.get('title')}|{item.get('snippet')}"
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def format_search_results(results: list[dict]) -> str:
    """Number sources so the model can cite them inline as [1], [2], ..."""

    entries: list[str] = []
    for index, item in enumerate(_dedupe_results(results), 1):
        title = str(item.get("title") or "无标题").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        entry = f"[{index}] {title}"
        if url:
            entry += f"\nURL: {url}"
        if snippet:
            entry += f"\n摘要: {snippet}"
        entries.append(entry)
    return "\n\n".join(entries) if entries else "本次搜索没有返回可用结果。"


def search_tool_content(results: list[dict]) -> str:
    return _SEARCH_RESULT_PROMPT.format(results=format_search_results(results))


def sources_tool_content(sources: list[dict], indices: list[int]) -> str:
    """Format a subset of a global source registry using its stable numbers."""

    entries: list[str] = []
    for number in indices:
        if number < 1 or number > len(sources):
            continue
        item = sources[number - 1]
        title = str(item.get("title") or "无标题").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        entry = f"[{number}] {title}"
        if url:
            entry += f"\nURL: {url}"
        if snippet:
            entry += f"\n摘要: {snippet}"
        entries.append(entry)
    return _SEARCH_RESULT_PROMPT.format(
        results="\n\n".join(entries) if entries else "本次操作没有返回可用结果。"
    )


def _tool_queries(arguments: str) -> list[str]:
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, str):
        return [parsed.strip()] if parsed.strip() else []
    if not isinstance(parsed, dict):
        return []
    query = parsed.get("query") or parsed.get("q") or parsed.get("keywords")
    if isinstance(query, str) and query.strip():
        return [query.strip()]
    return []


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
    """Yield parsed JSON payloads from a Chat Completions response."""

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
        yield from stream_search_function(
            cfg,
            model,
            effort,
            deep_thinking,
            messages,
            temperature,
            max_tokens,
            stop,
            timeout=timeout,
            response_callback=response_callback,
        )
        return
    body = build_chat_body(
        model, effort, deep_thinking, messages, temperature, max_tokens
    )
    if stop.is_set():
        return
    response: requests.Response | None = None
    try:
        response = requests.post(
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
            yield from _extract_parts(payload)
    except requests.RequestException as exc:
        raise APIError(f"网络请求失败：{exc}") from exc
    finally:
        if response_callback:
            response_callback(None)


def stream_search_function(
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
) -> Iterator[tuple[str, str]]:
    """Run the official tool loop until the model produces a sourced answer.

    Tools stay available in every round, so the model keeps emitting
    structured `tool_calls` instead of leaking harness-style `<zenith_calls>`
    blocks into prose. Search and page results are registered in one global
    source list, which keeps inline citation numbers stable across rounds.
    """

    if stop.is_set():
        return
    working = list(messages)
    sources: list[dict] = []
    source_numbers: dict[str, int] = {}

    def register(result: dict) -> int:
        url = str(result.get("url") or "").strip()
        key = url or f"{result.get('title')}|{result.get('snippet')}"
        if key in source_numbers:
            return source_numbers[key]
        sources.append(result)
        source_numbers[key] = len(sources)
        return len(sources)

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
        response: requests.Response | None = None
        try:
            response = requests.post(
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
                for choice in payload.get("choices") or []:
                    delta = choice.get("delta") or choice.get("message") or {}
                    reasoning = _strip_zenith(
                        str(
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or ""
                        )
                    )
                    content = _strip_zenith(str(delta.get("content") or ""))
                    if reasoning:
                        round_reasoning.append(reasoning)
                        yield ("reasoning", reasoning)
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
        except requests.RequestException as exc:
            raise APIError(f"网络请求失败：{exc}") from exc
        finally:
            if response_callback:
                response_callback(None)

        if stop.is_set():
            return
        if not tool_calls:
            # Content from a round that also contains tool calls is usually
            # only a short preamble (for example, "我先搜索一下"). Do not
            # expose it as the final answer before we know this is the final
            # model round. Reasoning can still stream while the model decides.
            for content in round_content:
                yield ("content", content)
            return

        yield ("search", "正在联网搜索…")
        call_numbers: dict[str, list[int]] = {}
        call_errors: dict[str, list[str]] = {}
        for index in sorted(tool_calls):
            call = tool_calls[index]
            call_id = call["id"] or f"call_{index}"
            name = (call.get("name") or "").strip()
            numbers: list[int] = []
            errors: list[str] = []
            if name in {OPEN_PAGE_TOOL_NAME, WEB_FETCH_TOOL_NAME}:
                for url in _tool_urls(call.get("arguments") or ""):
                    if stop.is_set():
                        return
                    try:
                        numbers.append(register(fetch_page_text(url)))
                    except APIError as exc:
                        errors.append(str(exc))
            else:
                for query in _tool_queries(call.get("arguments") or ""):
                    if stop.is_set():
                        return
                    try:
                        for result in run_web_search(cfg, query):
                            numbers.append(register(result))
                    except APIError as exc:
                        errors.append(str(exc))
            call_numbers[call_id] = numbers
            call_errors[call_id] = errors

        if stop.is_set():
            return
        if sources:
            yield ("search", f"已获取 {len(sources)} 条结果，正在生成回答…")
        else:
            yield ("search", "未找到可用结果，正在生成回答…")

        working.append(
            {
                "role": "assistant",
                "content": "".join(round_content).strip() or None,
                "reasoning_content": "".join(round_reasoning).strip() or None,
                "tool_calls": [
                    {
                        "id": tool_calls[index]["id"] or f"call_{index}",
                        "type": "function",
                        "function": {
                            "name": tool_calls[index]["name"] or SEARCH_TOOL_NAME,
                            "arguments": tool_calls[index]["arguments"] or "{}",
                        },
                    }
                    for index in sorted(tool_calls)
                ],
            }
        )
        for index in sorted(tool_calls):
            call = tool_calls[index]
            call_id = call["id"] or f"call_{index}"
            numbers = call_numbers.get(call_id, [])
            errors = call_errors.get(call_id, [])
            if numbers:
                content = sources_tool_content(sources, numbers)
            elif errors:
                content = "工具执行失败：" + "；".join(errors[:2])
            else:
                content = "本次操作没有返回可用结果。"
            working.append(
                {"role": "tool", "tool_call_id": call_id, "content": content}
            )

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
        model, effort, deep_thinking, working, temperature, max_tokens
    )
    response = None
    try:
        response = requests.post(
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
            yield from _extract_parts(payload)
    except requests.RequestException as exc:
        raise APIError(f"网络请求失败：{exc}") from exc
    finally:
        if response_callback:
            response_callback(None)

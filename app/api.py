from __future__ import annotations

import base64
import json
import mimetypes
import re
import threading
import unicodedata
from pathlib import Path
from typing import Callable, Iterator

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
    return body


def responses_input(history: list[dict]) -> list[dict]:
    """Convert stored dialogue turns into DeepSeek Responses API input items."""

    items: list[dict] = []
    for message in history:
        role = message.get("role")
        if role not in {"user", "assistant", "system"}:
            continue
        content = message.get("content") or ""
        images = message.get("images") or []
        if isinstance(content, list):
            parts: list[dict] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type == "text" and part.get("text"):
                    parts.append({"type": "input_text", "text": str(part["text"])})
                elif part_type == "image_url":
                    image_url = part.get("image_url")
                    url = (
                        image_url.get("url")
                        if isinstance(image_url, dict)
                        else image_url
                    )
                    if url:
                        parts.append({"type": "input_image", "image_url": str(url)})
            if parts:
                items.append({"role": role, "content": parts})
            else:
                items.append({"role": role, "content": ""})
            continue
        if role == "user" and images:
            parts: list[dict] = []
            if str(content).strip():
                parts.append({"type": "input_text", "text": str(content)})
            for image_path in images:
                try:
                    parts.append(
                        {
                            "type": "input_image",
                            "image_url": _encode_image(image_path),
                        }
                    )
                except OSError:
                    continue
            if not parts:
                parts.append({"type": "input_text", "text": "请查看图片。"})
            items.append({"role": "user", "content": parts})
        else:
            items.append({"role": role, "content": str(content)})
    return items


def build_search_body(
    model: str,
    effort: str,
    deep_thinking: bool,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> dict:
    """Build a Responses API request that asks DeepSeek to search the web."""

    body: dict = {
        "model": model,
        "input": responses_input(messages),
        "stream": True,
        "tools": [{"type": "web_search"}],
    }
    if deep_thinking:
        body["reasoning"] = {
            "effort": effort if effort in {"low", "high", "max"} else "high"
        }
    else:
        body["reasoning"] = {"effort": "none"}
        body["temperature"] = temperature
    if max_tokens > 0:
        body["max_output_tokens"] = max_tokens
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
            parts.append(("reasoning", str(reasoning)))
        if content:
            parts.append(("content", str(content)))
    return parts


def _extract_search_delta(payload: dict) -> list[tuple[str, str]]:
    event = str(payload.get("type") or "")
    delta = payload.get("delta")
    if event == "response.reasoning_text.delta" and delta:
        return [("reasoning", str(delta))]
    if event == "response.output_text.delta" and delta:
        return [("content", str(delta))]
    return []


def _extract_search_response(payload: dict) -> list[tuple[str, str]]:
    error = payload.get("error") if isinstance(payload, dict) else None
    if error:
        if isinstance(error, dict):
            raise APIError(str(error.get("message") or error))
        raise APIError(str(error))
    parts: list[tuple[str, str]] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            text = part.get("text") or ""
            if part.get("type") == "reasoning_text" and text:
                parts.append(("reasoning", str(text)))
            elif part.get("type") == "output_text" and text:
                parts.append(("content", str(text)))
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
        yield from stream_search(
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
    headers = {
        "Authorization": f"Bearer {cfg.get('api_key') or ''}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if stop.is_set():
        return
    response: requests.Response | None = None
    try:
        response = requests.post(
            _endpoint(cfg, "chat/completions"),
            headers=headers,
            json=body,
            stream=True,
            timeout=timeout,
        )
        if response_callback:
            response_callback(response)
        with response:
            if response.status_code != 200:
                raise APIError(_response_error(response))
            response.encoding = "utf-8"
            if "application/json" in response.headers.get("Content-Type", ""):
                try:
                    yield from _extract_parts(response.json())
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
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                yield from _extract_parts(payload)
    except requests.RequestException as exc:
        raise APIError(f"网络请求失败：{exc}") from exc
    finally:
        if response_callback:
            response_callback(None)


def stream_search(
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
    """Stream a web-enabled answer through the official Responses API."""

    body = build_search_body(
        model, effort, deep_thinking, messages, temperature, max_tokens
    )
    headers = {
        "Authorization": f"Bearer {cfg.get('api_key') or ''}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if stop.is_set():
        return
    response: requests.Response | None = None
    try:
        response = requests.post(
            _endpoint(cfg, "responses"),
            headers=headers,
            json=body,
            stream=True,
            timeout=timeout,
        )
        if response_callback:
            response_callback(response)
        with response:
            if response.status_code != 200:
                raise APIError(_response_error(response))
            response.encoding = "utf-8"
            if "application/json" in response.headers.get("Content-Type", ""):
                try:
                    yield from _extract_search_response(response.json())
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
                if not data:
                    continue
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                event = str(payload.get("type") or "")
                if event == "response.completed":
                    return
                if event in {"response.failed", "response.incomplete"}:
                    error = payload.get("error")
                    if isinstance(error, dict):
                        detail = error.get("message") or error.get("code") or ""
                        if detail:
                            raise APIError(str(detail))
                    return
                yield from _extract_search_delta(payload)
    except requests.RequestException as exc:
        raise APIError(f"网络请求失败：{exc}") from exc
    finally:
        if response_callback:
            response_callback(None)

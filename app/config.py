from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_CUSTOM_HOME = os.environ.get("DEEPSEEK_CHAT_GUI_HOME")
APP_DIR = (
    Path(_CUSTOM_HOME).expanduser()
    if _CUSTOM_HOME
    else Path.home() / ".deepseek_chat_gui"
)
CONFIG_PATH = APP_DIR / "config.json"
DATA_PATH = APP_DIR / "conversations.json"
MEDIA_DIR = APP_DIR / "media"

DEFAULT_BASE_URL = "https://api.deepseek.com"
MODEL_CATALOG_VERSION = 2
V41_FLASH_LIMITED_MODEL = "deepseek-v4.1-flash-expires-on-0910"
UNLISTED_BUILTIN_MODELS = (V41_FLASH_LIMITED_MODEL,)
DEFAULT_MODELS = [
    "deepseek-v4-flash",
    V41_FLASH_LIMITED_MODEL,
    "deepseek-v4-pro",
    "deepseek-v4-flash-vision-exp",
]
MODEL_LABELS = {
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    V41_FLASH_LIMITED_MODEL: "DeepSeek V4.1 Flash（限时至 9/10）",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "deepseek-v4-flash-vision-exp": "DeepSeek V4 Vision",
}
EFFORT_LEVELS = ["low", "high", "max"]
EFFORT_LABELS = {"low": "Low", "high": "High", "max": "Max"}

MODEL_CAPABILITIES = {
    "deepseek-v4-flash": {
        "vision": False,
        "thinking": True,
        "efforts": tuple(EFFORT_LEVELS),
    },
    V41_FLASH_LIMITED_MODEL: {
        "vision": True,
        "thinking": True,
        "efforts": tuple(EFFORT_LEVELS),
    },
    "deepseek-v4-pro": {
        "vision": False,
        "thinking": True,
        "efforts": tuple(EFFORT_LEVELS),
    },
    "deepseek-v4-flash-vision-exp": {
        "vision": True,
        "thinking": True,
        "efforts": tuple(EFFORT_LEVELS),
    },
}

DEFAULTS: dict[str, Any] = {
    "model_catalog_version": MODEL_CATALOG_VERSION,
    "api_key": "",
    "base_url": DEFAULT_BASE_URL,
    "models": list(DEFAULT_MODELS),
    "default_model": DEFAULT_MODELS[0],
    "last_model": DEFAULT_MODELS[0],
    "default_effort": "high",
    "last_effort": "high",
    "deep_thinking": True,
    "temperature": 1.0,
    "max_tokens": 0,
    "theme": "light",
    "system_prompt": "",
}


def ensure_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def model_label(model: str) -> str:
    return MODEL_LABELS.get(model, model)


def effort_label(effort: str) -> str:
    value = str(effort or "").strip()
    aliases = {
        "低": "low",
        "高": "high",
        "最高": "max",
        "medium": "high",
        "xhigh": "high",
    }
    normalized = aliases.get(value.lower(), value.lower())
    return EFFORT_LABELS.get(normalized, value or "High")


def is_vision_model(model: str) -> bool:
    known = MODEL_CAPABILITIES.get(model or "")
    return bool(known["vision"]) if known else "vision" in (model or "").lower()


def supports_thinking(model: str) -> bool:
    known = MODEL_CAPABILITIES.get(model or "")
    return bool(known["thinking"]) if known else True


def uses_official_api(base_url: Any) -> bool:
    value = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    return value in {DEFAULT_BASE_URL, f"{DEFAULT_BASE_URL}/v1"}


def include_unlisted_builtin_models(models: Any) -> list[str]:
    if isinstance(models, str):
        source = models.splitlines()
    else:
        source = models or []
    merged: list[str] = []
    for item in source:
        model = _normalize_model(item)
        if model and model not in merged:
            merged.append(model)
    if not merged:
        return list(DEFAULT_MODELS)
    for model in UNLISTED_BUILTIN_MODELS:
        if model in merged:
            continue
        try:
            position = merged.index("deepseek-v4-flash") + 1
        except ValueError:
            position = len(merged)
        merged.insert(position, model)
    return merged


def _normalize_model(model: Any) -> str:
    value = str(model or "").strip()
    lowered = value.lower().replace("_", "-")
    # 兼容 1.x 配置中的展示名和无效视觉别名。
    aliases = {
        "deepseek-v4-flash": "deepseek-v4-flash",
        V41_FLASH_LIMITED_MODEL: V41_FLASH_LIMITED_MODEL,
        "deepseek-v4-pro": "deepseek-v4-pro",
        "deepseek-v4-flash-vision-exp": "deepseek-v4-flash-vision-exp",
        "deepseek-v4-flash (modlens vision)": "deepseek-v4-flash-vision-exp",
        "deepseek-v4-pro (modlens vision)": "deepseek-v4-flash-vision-exp",
    }
    return aliases.get(lowered, value)


def _normalize_effort(value: Any) -> str:
    effort = str(value or "high").strip().lower()
    return effort if effort in EFFORT_LEVELS else "high"


def _sanitize(cfg: dict[str, Any]) -> dict[str, Any]:
    raw_models = cfg.get("models") or []
    if isinstance(raw_models, str):
        raw_models = raw_models.splitlines()
    models: list[str] = []
    for item in raw_models:
        model = _normalize_model(item)
        if model and model not in models:
            models.append(model)
    cfg["models"] = models or list(DEFAULT_MODELS)

    default_model = _normalize_model(cfg.get("default_model"))
    last_model = _normalize_model(cfg.get("last_model"))
    cfg["default_model"] = default_model if default_model in cfg["models"] else cfg["models"][0]
    cfg["last_model"] = last_model if last_model in cfg["models"] else cfg["default_model"]
    cfg["default_effort"] = _normalize_effort(cfg.get("default_effort"))
    cfg["last_effort"] = _normalize_effort(cfg.get("last_effort"))
    cfg["deep_thinking"] = bool(cfg.get("deep_thinking", True))

    base_url = str(cfg.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    if base_url == "https://api.deepseek.com/v1":
        base_url = DEFAULT_BASE_URL
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]
    cfg["base_url"] = base_url

    try:
        cfg["temperature"] = min(2.0, max(0.0, float(cfg.get("temperature", 1.0))))
    except (TypeError, ValueError):
        cfg["temperature"] = 1.0
    try:
        cfg["max_tokens"] = min(384000, max(0, int(cfg.get("max_tokens", 0))))
    except (TypeError, ValueError):
        cfg["max_tokens"] = 0
    cfg["theme"] = "dark" if cfg.get("theme") == "dark" else "light"
    cfg["api_key"] = str(cfg.get("api_key") or "").strip()
    cfg["system_prompt"] = str(cfg.get("system_prompt") or "").strip()
    cfg["model_catalog_version"] = MODEL_CATALOG_VERSION
    return cfg


def load_config() -> dict[str, Any]:
    ensure_dir()
    cfg = dict(DEFAULTS)
    cfg["models"] = list(DEFAULT_MODELS)
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                try:
                    saved_catalog_version = int(
                        saved.get("model_catalog_version", 0)
                    )
                except (TypeError, ValueError):
                    saved_catalog_version = 0
                cfg.update({key: value for key, value in saved.items() if key in DEFAULTS})
                if (
                    saved_catalog_version < MODEL_CATALOG_VERSION
                    and uses_official_api(cfg.get("base_url"))
                ):
                    cfg["models"] = include_unlisted_builtin_models(
                        cfg.get("models")
                    )
        except (OSError, json.JSONDecodeError):
            pass
    return _sanitize(cfg)


def save_config(cfg: dict[str, Any]) -> None:
    ensure_dir()
    clean = _sanitize(dict(cfg))
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(CONFIG_PATH)

from __future__ import annotations

import json
import os
import re
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
MODEL_CATALOG_VERSION = 5
MAX_CONTEXT_TOKENS = 1_048_576
MAX_OUTPUT_TOKENS = 393_216

V41_FLASH_MODEL = "deepseek-flash"
V4_PRO_MODEL = "deepseek-v4-pro"
DEFAULT_MODELS = [V41_FLASH_MODEL, V4_PRO_MODEL]
MODEL_LABELS = {
    V41_FLASH_MODEL: "DeepSeek V4.1 Flash",
    V4_PRO_MODEL: "DeepSeek V4 Pro",
}

_COMPACT_MODEL_LABEL_ALIASES = {
    re.sub(r"\s+", "-", label.lower()): model
    for model, label in MODEL_LABELS.items()
}
_LEGACY_FLASH_IDS = {"deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}
EFFORT_LEVELS = ["low", "high", "max"]
EFFORT_LABELS = {"low": "Low", "high": "High", "max": "Max"}
DEFAULT_EFFORT = "high"
_EFFORT_ALIASES = {
    "低": "low",
    "高": "high",
    "最高": "max",
    "minimal": "low",
    "medium": "high",
    "xhigh": "high",
    "ultra": "max",
}
DEFAULT_SEARCH_MAX_RESULTS = 5

MODEL_CAPABILITIES = {
    V41_FLASH_MODEL: {
        "vision": True,
        "thinking": True,
        "efforts": tuple(EFFORT_LEVELS),
        "system_prompt_update": "in-history",
    },
    V4_PRO_MODEL: {
        "vision": False,
        "thinking": True,
        "efforts": tuple(EFFORT_LEVELS),
        "system_prompt_update": "leading-only",
    },
}

DEFAULTS: dict[str, Any] = {
    "model_catalog_version": MODEL_CATALOG_VERSION,
    "api_key": "",
    "base_url": DEFAULT_BASE_URL,
    "models": list(DEFAULT_MODELS),
    "default_model": DEFAULT_MODELS[0],
    "last_model": DEFAULT_MODELS[0],
    "default_effort": DEFAULT_EFFORT,
    "last_effort": DEFAULT_EFFORT,
    "deep_thinking": True,
    "web_search": True,
    "search_max_results": DEFAULT_SEARCH_MAX_RESULTS,
    "temperature": 1.0,
    "max_tokens": 0,
    "theme": "light",
    "system_prompt": "",
    "harness_projects": [],
    "harness_warm_start": True,
}

def ensure_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)

def model_label(model: str) -> str:
    return MODEL_LABELS.get(model, model)

def effort_label(effort: str) -> str:
    value = str(effort or "").strip()
    normalized = _EFFORT_ALIASES.get(value.lower(), value.lower())
    return EFFORT_LABELS.get(normalized, value or EFFORT_LABELS[DEFAULT_EFFORT])

def is_vision_model(model: str) -> bool:
    known = MODEL_CAPABILITIES.get(model or "")
    return bool(known["vision"]) if known else "vision" in (model or "").lower()

def supports_thinking(model: str) -> bool:
    known = MODEL_CAPABILITIES.get(model or "")
    return bool(known["thinking"]) if known else True

def uses_official_api(base_url: Any) -> bool:
    value = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    return value in {DEFAULT_BASE_URL, f"{DEFAULT_BASE_URL}/v1"}

def normalize_official_models(models: Any) -> list[str]:
    # Keep catalog order while collapsing aliases.
    if isinstance(models, str):
        source = models.splitlines()
    else:
        source = models or []
    merged: list[str] = []
    for item in source:
        model = _normalize_model(item, official=True)
        if model in DEFAULT_MODELS and model not in merged:
            merged.append(model)
    return merged

def _normalize_model(model: Any, *, official: bool = False) -> str:
    value = str(model or "").strip()
    lowered = value.lower().replace("_", "-")
    if lowered in DEFAULT_MODELS:
        return lowered
    if official and lowered in _LEGACY_FLASH_IDS:
        return V41_FLASH_MODEL
    compacted = re.sub(r"\s+", "-", lowered)
    return _COMPACT_MODEL_LABEL_ALIASES.get(compacted, value)

def normalize_effort(value: Any) -> str:
    effort = str(value or "").strip().lower()
    effort = _EFFORT_ALIASES.get(effort, effort)
    return effort if effort in EFFORT_LEVELS else DEFAULT_EFFORT

def search_result_count(value: Any) -> int:
    try:
        return min(10, max(1, int(value)))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_SEARCH_MAX_RESULTS

def _sanitize(cfg: dict[str, Any]) -> dict[str, Any]:
    base_url = str(cfg.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]
    official = uses_official_api(base_url)
    cfg["base_url"] = DEFAULT_BASE_URL if official else base_url

    raw_models = cfg.get("models") or []
    if isinstance(raw_models, str):
        raw_models = raw_models.splitlines()
    if official:
        models = normalize_official_models(raw_models)
    else:
        normalized_models = map(_normalize_model, raw_models)
        models = list(dict.fromkeys(model for model in normalized_models if model))
    cfg["models"] = models or list(DEFAULT_MODELS)

    default_model = _normalize_model(cfg.get("default_model"), official=official)
    last_model = _normalize_model(cfg.get("last_model"), official=official)
    cfg["default_model"] = default_model if default_model in cfg["models"] else cfg["models"][0]
    cfg["last_model"] = last_model if last_model in cfg["models"] else cfg["default_model"]
    cfg["default_effort"] = normalize_effort(cfg.get("default_effort"))
    cfg["last_effort"] = normalize_effort(cfg.get("last_effort"))
    cfg["deep_thinking"] = bool(cfg.get("deep_thinking", True))
    cfg["web_search"] = bool(cfg.get("web_search", True))
    cfg.pop("search_provider", None)
    cfg.pop("search_api_key", None)
    cfg["search_max_results"] = search_result_count(cfg.get("search_max_results"))

    try:
        cfg["temperature"] = min(2.0, max(0.0, float(cfg.get("temperature", 1.0))))
    except (TypeError, ValueError):
        cfg["temperature"] = 1.0
    try:
        cfg["max_tokens"] = min(MAX_OUTPUT_TOKENS, max(0, int(cfg.get("max_tokens", 0))))
    except (TypeError, ValueError):
        cfg["max_tokens"] = 0
    cfg["theme"] = "dark" if cfg.get("theme") == "dark" else "light"
    cfg["api_key"] = str(cfg.get("api_key") or "").strip()
    cfg["system_prompt"] = str(cfg.get("system_prompt") or "").strip()
    raw_projects = cfg.get("harness_projects") or []
    if isinstance(raw_projects, str):
        raw_projects = raw_projects.splitlines()
    projects: list[str] = []
    for item in raw_projects:
        path = str(item or "").strip()
        if path and path not in projects:
            projects.append(path)
    cfg["harness_projects"] = projects
    cfg["harness_warm_start"] = bool(cfg.get("harness_warm_start", True))
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
                    saved_models = cfg.get("models") or []
                    if isinstance(saved_models, str):
                        saved_models = saved_models.splitlines()
                    cfg["models"] = normalize_official_models(
                        [*saved_models, *DEFAULT_MODELS]
                    )
        except (OSError, json.JSONDecodeError):
            pass
    return _sanitize(cfg)

def sanitize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return _sanitize(dict(cfg))

def save_config(cfg: dict[str, Any]) -> None:
    ensure_dir()
    clean = sanitize_config(cfg)
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(CONFIG_PATH)

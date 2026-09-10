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
MODEL_CATALOG_VERSION = 3
# The current first-party Harness adapter caps its default output at 256k
# tokens. Keeping the native settings limit in sync avoids generating a
# request the official integration would reject before it reaches the model.
MAX_OUTPUT_TOKENS = 256_000

# DeepSeek's current unified Flash route is returned by the official
# ``/models`` endpoint as ``deepseek-flash``.  The service currently exposes
# text and image input through this route and supports the four thinking
# states below.  Keep this catalog deliberately small: a model ID that is no
# longer returned by the official endpoint must not remain as a built-in
# choice merely because an older local config mentioned it.
V41_FLASH_MODEL = "deepseek-flash"
DEFAULT_MODELS = [V41_FLASH_MODEL]
MODEL_LABELS = {V41_FLASH_MODEL: "DeepSeek V4.1 Flash"}

# IDs from the previous catalog. The desktop client owns this migration
# globally so a retired Pro route cannot remain selectable through a stale
# local config or a manually pasted model list. Unrelated custom-gateway IDs
# are still retained when they do not match one of these retired aliases.
REMOVED_OFFICIAL_MODELS = {
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v4-flash-vision-exp",
}
LEGACY_MODEL_ALIASES = {
    "deepseek-v4.1-flash-expires-on-0910": V41_FLASH_MODEL,
    "deepseek-v41-flash": V41_FLASH_MODEL,
    "deepseek-v4-flash": V41_FLASH_MODEL,
    "deepseek-v4-flash-vision-exp": V41_FLASH_MODEL,
    "deepseek-v4-flash (modlens vision)": V41_FLASH_MODEL,
    "deepseek-v4-pro (modlens vision)": V41_FLASH_MODEL,
}
_COMPACT_LEGACY_MODEL_ALIASES = {
    re.sub(r"\s+", "-", key): target
    for key, target in LEGACY_MODEL_ALIASES.items()
}
EFFORT_LEVELS = ["low", "high", "max"]
EFFORT_LABELS = {"low": "Low", "high": "High", "max": "Max"}

MODEL_CAPABILITIES = {
    V41_FLASH_MODEL: {
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
    "harness_projects": [],
    "harness_warm_start": True,
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


def normalize_official_models(models: Any) -> list[str]:
    """Normalize a live official model response for the app's built-in catalog.

    The endpoint is authoritative for availability, while the client owns the
    user-facing aliases/capabilities.  We retain the current Flash route and
    silently omit explicitly retired routes.  Unknown future IDs are kept as
    manual choices so an account can still use a newly published route before
    a client release updates its capability metadata.
    """

    if isinstance(models, str):
        source = models.splitlines()
    else:
        source = models or []
    merged: list[str] = []
    for item in source:
        model = _normalize_model(item)
        if model and model not in merged:
            merged.append(model)
    return merged


def _normalize_model(model: Any) -> str:
    value = str(model or "").strip()
    lowered = value.lower().replace("_", "-")
    # 兼容旧版本展示名、临时 0910 ID 和旧视觉别名。
    if lowered in LEGACY_MODEL_ALIASES:
        return LEGACY_MODEL_ALIASES[lowered]
    compacted = re.sub(r"\s+", "-", lowered)
    if compacted in _COMPACT_LEGACY_MODEL_ALIASES:
        return _COMPACT_LEGACY_MODEL_ALIASES[compacted]
    if compacted in REMOVED_OFFICIAL_MODELS:
        return ""
    return value


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
                    cfg["models"] = normalize_official_models(cfg.get("models"))
        except (OSError, json.JSONDecodeError):
            pass
    return _sanitize(cfg)


def sanitize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return an in-memory config normalized to the current app catalog."""

    return _sanitize(dict(cfg))


def save_config(cfg: dict[str, Any]) -> None:
    ensure_dir()
    clean = sanitize_config(cfg)
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(CONFIG_PATH)

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config
from app.harness import ensure_harness_defaults
from app.storage import ConversationStore


class ConfigTests(unittest.TestCase):
    def test_system_prompt_is_preserved_and_trimmed(self) -> None:
        cleaned = config._sanitize(
            {**config.DEFAULTS, "system_prompt": "  始终使用简体中文。\n  "}
        )
        self.assertEqual(cleaned["system_prompt"], "始终使用简体中文。")

    def test_web_search_is_enabled_by_default(self) -> None:
        self.assertTrue(config.DEFAULTS["web_search"])
        cleaned = config._sanitize({**config.DEFAULTS, "web_search": False})
        self.assertFalse(cleaned["web_search"])

    def test_legacy_model_names_are_migrated(self) -> None:
        cleaned = config._sanitize(
            {
                **config.DEFAULTS,
                "models": ["DeepSeek-V4-Flash", "DeepSeek V4 Pro"],
                "default_model": "DeepSeek V4 Pro",
                "last_effort": "Medium",
            }
        )
        self.assertEqual(cleaned["models"], ["deepseek-flash"])
        self.assertEqual(cleaned["default_model"], "deepseek-flash")
        self.assertEqual(cleaned["last_effort"], "high")

    def test_official_legacy_base_url_is_normalized(self) -> None:
        cleaned = config._sanitize({**config.DEFAULTS, "base_url": "https://api.deepseek.com/v1"})
        self.assertEqual(cleaned["base_url"], "https://api.deepseek.com")

    def test_existing_official_config_migrates_to_current_flash_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(
                '{"models":["deepseek-v4-flash","deepseek-v4-pro"],'
                '"default_model":"deepseek-v4-pro"}',
                encoding="utf-8",
            )
            with (
                patch("app.config.APP_DIR", root),
                patch("app.config.CONFIG_PATH", config_path),
            ):
                loaded = config.load_config()
        self.assertEqual(
            loaded["models"],
            ["deepseek-flash"],
        )
        self.assertEqual(
            loaded["model_catalog_version"], config.MODEL_CATALOG_VERSION
        )

    def test_current_catalog_replaces_a_retired_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(
                (
                    f'{{"model_catalog_version":{config.MODEL_CATALOG_VERSION},'
                    '"models":["deepseek-v4-pro"],'
                    '"default_model":"deepseek-v4-pro"}'
                ),
                encoding="utf-8",
            )
            with (
                patch("app.config.APP_DIR", root),
                patch("app.config.CONFIG_PATH", config_path),
            ):
                loaded = config.load_config()
        self.assertEqual(loaded["models"], ["deepseek-flash"])

    def test_official_model_catalog_resolves_to_current_flash(self) -> None:
        merged = config.normalize_official_models(
            ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-flash"]
        )
        self.assertEqual(merged, ["deepseek-flash"])
        self.assertTrue(config.uses_official_api("https://api.deepseek.com/v1"))
        self.assertFalse(config.uses_official_api("https://example.com/v1"))

    def test_harness_defaults_are_created_once_and_use_current_flash_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "harness"
            cfg = {**config.DEFAULTS, "base_url": "https://api.deepseek.com"}
            settings = ensure_harness_defaults(home, cfg)
            first = settings.read_text(encoding="utf-8")
            settings.write_text(first + "# user change\n", encoding="utf-8")
            same_settings = ensure_harness_defaults(home, cfg)
            self.assertEqual(same_settings, settings)
            self.assertIn("id: deepseek-flash", first)
            self.assertIn("apiKeyEnv: DEEPSEEK_API_KEY", first)
            self.assertIn("thinking: enabled", first)
            self.assertIn("reasoningEffort: high", first)
            self.assertIn("inputModalities: [text, image]", first)
            self.assertNotIn("deepseek-v4-pro", first)


class StorageTests(unittest.TestCase):
    def test_automatic_title_does_not_change_conversation_recency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "conversations.json"
            with (
                patch("app.storage.DATA_PATH", data_path),
                patch("app.storage.MEDIA_DIR", root / "media"),
                patch(
                    "app.storage.ensure_dir",
                    lambda: root.mkdir(parents=True, exist_ok=True),
                ),
            ):
                store = ConversationStore()
                conversation = store.create("新对话")
                updated_at = conversation["updated_at"]
                store.update_title(conversation["id"], "证据理论正交和")

                self.assertEqual(conversation["title"], "证据理论正交和")
                self.assertEqual(conversation["updated_at"], updated_at)

    def test_conversation_and_media_are_deleted_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "conversations.json"
            media_dir = root / "media"
            with (
                patch("app.storage.DATA_PATH", data_path),
                patch("app.storage.MEDIA_DIR", media_dir),
                patch("app.storage.ensure_dir", lambda: root.mkdir(parents=True, exist_ok=True)),
            ):
                store = ConversationStore()
                conversation = store.create("测试")
                source = root / "source.png"
                source.write_bytes(b"image")
                imported = Path(store.import_image(conversation["id"], str(source)))
                self.assertTrue(imported.exists())
                store.append_message(conversation["id"], {"role": "user", "content": "hi"})
                store.delete(conversation["id"])
                self.assertEqual(store.count(), 0)
                self.assertFalse(imported.parent.exists())


if __name__ == "__main__":
    unittest.main()

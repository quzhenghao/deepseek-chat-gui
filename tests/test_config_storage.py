from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config
from app.storage import ConversationStore


class ConfigTests(unittest.TestCase):
    def test_system_prompt_is_preserved_and_trimmed(self) -> None:
        cleaned = config._sanitize(
            {**config.DEFAULTS, "system_prompt": "  始终使用简体中文。\n  "}
        )
        self.assertEqual(cleaned["system_prompt"], "始终使用简体中文。")

    def test_legacy_model_names_are_migrated(self) -> None:
        cleaned = config._sanitize(
            {
                **config.DEFAULTS,
                "models": ["DeepSeek-V4-Flash", "DeepSeek-V4-Pro"],
                "default_model": "DeepSeek-V4-Pro",
                "last_effort": "Medium",
            }
        )
        self.assertEqual(cleaned["models"], ["deepseek-v4-flash", "deepseek-v4-pro"])
        self.assertEqual(cleaned["default_model"], "deepseek-v4-pro")
        self.assertEqual(cleaned["last_effort"], "high")

    def test_official_legacy_base_url_is_normalized(self) -> None:
        cleaned = config._sanitize({**config.DEFAULTS, "base_url": "https://api.deepseek.com/v1"})
        self.assertEqual(cleaned["base_url"], "https://api.deepseek.com")

    def test_existing_official_config_receives_limited_v41_model_once(self) -> None:
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
            [
                "deepseek-v4-flash",
                config.V41_FLASH_LIMITED_MODEL,
                "deepseek-v4-pro",
            ],
        )
        self.assertEqual(
            loaded["model_catalog_version"], config.MODEL_CATALOG_VERSION
        )

    def test_current_catalog_respects_a_removed_limited_model(self) -> None:
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
        self.assertEqual(loaded["models"], ["deepseek-v4-pro"])

    def test_unlisted_model_is_only_added_to_official_api_catalogs(self) -> None:
        merged = config.include_unlisted_builtin_models(["deepseek-v4-flash"])
        self.assertEqual(
            merged,
            ["deepseek-v4-flash", config.V41_FLASH_LIMITED_MODEL],
        )
        self.assertTrue(config.uses_official_api("https://api.deepseek.com/v1"))
        self.assertFalse(config.uses_official_api("https://example.com/v1"))


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

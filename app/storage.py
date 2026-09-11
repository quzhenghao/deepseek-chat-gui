from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from .config import DATA_PATH, MEDIA_DIR, ensure_dir


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ConversationStore:
    def __init__(self) -> None:
        self._data: dict = {"conversations": []}
        self.load()

    def load(self) -> None:
        ensure_dir()
        if not DATA_PATH.exists():
            return
        try:
            data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("conversations"), list):
                self._data = data
        except (OSError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        ensure_dir()
        temporary = DATA_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(DATA_PATH)

    def conversations(self) -> list[dict]:
        return sorted(
            self._data["conversations"],
            key=lambda item: item.get("updated_at", ""),
            reverse=True,
        )

    def get(self, conversation_id: str) -> dict | None:
        return next(
            (
                item
                for item in self._data["conversations"]
                if item.get("id") == conversation_id
            ),
            None,
        )

    def count(self) -> int:
        return len(self._data["conversations"])

    def create(self, title: str = "新对话") -> dict:
        timestamp = _now()
        conversation = {
            "id": uuid.uuid4().hex,
            "title": title,
            "created_at": timestamp,
            "updated_at": timestamp,
            "messages": [],
        }
        self._data["conversations"].append(conversation)
        self.save()
        return conversation

    def rename(self, conversation_id: str, title: str) -> None:
        conversation = self.get(conversation_id)
        if conversation and title.strip():
            conversation["title"] = title.strip()
            conversation["updated_at"] = _now()
            self.save()

    def update_title(self, conversation_id: str, title: str) -> None:
        """Apply an automatic title without changing the dialogue's recency."""

        conversation = self.get(conversation_id)
        if conversation and title.strip():
            conversation["title"] = title.strip()
            self.save()

    def append_message(self, conversation_id: str, message: dict) -> None:
        conversation = self.get(conversation_id)
        if conversation is None:
            return
        conversation["messages"].append(message)
        conversation["updated_at"] = _now()
        self.save()

    def delete(self, conversation_id: str) -> None:
        self.delete_many([conversation_id])

    def delete_many(self, conversation_ids: list[str]) -> None:
        targets = set(conversation_ids)
        self._data["conversations"] = [
            item
            for item in self._data["conversations"]
            if item.get("id") not in targets
        ]
        for conversation_id in targets:
            media_dir = MEDIA_DIR / conversation_id
            if media_dir.exists():
                shutil.rmtree(media_dir)
        self.save()

    def media_dir(self, conversation_id: str) -> Path:
        directory = MEDIA_DIR / conversation_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def import_image(self, conversation_id: str, source: str) -> str:
        source_path = Path(source)
        suffix = source_path.suffix.lower() or ".png"
        destination = self.media_dir(conversation_id) / f"{uuid.uuid4().hex}{suffix}"
        shutil.copy2(source_path, destination)
        return str(destination)

    def save_image(
        self, conversation_id: str, image: object, suffix: str = ".png"
    ) -> str:
        destination = self.media_dir(conversation_id) / f"{uuid.uuid4().hex}{suffix}"
        if not image.save(str(destination)):
            raise OSError("无法保存图片")
        return str(destination)

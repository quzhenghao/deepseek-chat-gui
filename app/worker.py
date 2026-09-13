from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from . import api


class ChatWorker(QThread):
    chunk = Signal(str)
    reasoning = Signal(str)
    status = Signal(str)
    done = Signal()
    failed = Signal(str)

    def __init__(
        self,
        cfg: dict,
        model: str,
        effort: str,
        deep_thinking: bool,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        web_search: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._cfg = dict(cfg)
        self._model = model
        self._effort = effort
        self._deep_thinking = deep_thinking
        self._messages = messages
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._web_search = web_search
        self._stop = threading.Event()
        self._response_lock = threading.Lock()
        self._response = None

    def cancel(self) -> None:
        self._stop.set()
        with self._response_lock:
            response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def _set_response(self, response) -> None:
        with self._response_lock:
            self._response = response
        if response is not None and self._stop.is_set():
            try:
                response.close()
            except Exception:
                pass

    def run(self) -> None:
        try:
            for kind, text in api.stream_chat(
                self._cfg,
                self._model,
                self._effort,
                self._deep_thinking,
                self._messages,
                self._temperature,
                self._max_tokens,
                self._stop,
                web_search=self._web_search,
                response_callback=self._set_response,
            ):
                if self._stop.is_set():
                    break
                if kind == "search":
                    self.status.emit(text)
                elif kind == "reasoning":
                    self.reasoning.emit(text)
                else:
                    self.chunk.emit(text)
            self.done.emit()
        except api.APIError as exc:
            if self._stop.is_set():
                self.done.emit()
            else:
                self.failed.emit(str(exc))
        except Exception as exc:
            if self._stop.is_set():
                self.done.emit()
            else:
                self.failed.emit(f"请求异常：{exc}")


class TitleWorker(QThread):
    titleReady = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        cfg: dict,
        model: str,
        messages: list[dict],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._cfg = dict(cfg)
        self._model = model
        self._messages = messages
        self._stop = threading.Event()
        self._response_lock = threading.Lock()
        self._response = None

    def cancel(self) -> None:
        self._stop.set()
        with self._response_lock:
            response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def _set_response(self, response) -> None:
        with self._response_lock:
            self._response = response
        if response is not None and self._stop.is_set():
            try:
                response.close()
            except Exception:
                pass

    def run(self) -> None:
        chunks: list[str] = []
        try:
            for kind, text in api.stream_chat(
                self._cfg,
                self._model,
                "low",
                False,
                self._messages,
                0.2,
                64,
                self._stop,
                response_callback=self._set_response,
            ):
                if self._stop.is_set():
                    return
                if kind == "content":
                    chunks.append(text)
            if self._stop.is_set():
                return
            title = api.clean_conversation_title("".join(chunks))
            if title:
                self.titleReady.emit(title)
            else:
                self.failed.emit("标题响应为空")
        except api.APIError as exc:
            if not self._stop.is_set():
                self.failed.emit(str(exc))
        except Exception as exc:
            if not self._stop.is_set():
                self.failed.emit(f"标题请求异常：{exc}")

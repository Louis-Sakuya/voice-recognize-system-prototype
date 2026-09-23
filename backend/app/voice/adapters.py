"""阿里云 Paraformer 与火山大模型流式 ASR。"""

from __future__ import annotations

import asyncio
import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.config import VOLC_RESOURCE_ASR2_DURATION, Settings
from app.voice.events import TranscriptEvent
from app.voice.protocol import (
    build_volc_client_frame,
    map_aliyun_message,
    map_volc_result,
    parse_volc_frame,
)
from app.voice.wsutil import connect_ws

VOLC_FULL_CLIENT = 0b0001
VOLC_AUDIO_ONLY = 0b0010


def volc_auth_headers(settings: Settings, request_id: str) -> dict[str, str]:
    """握手头。新版控制台用 X-Api-Key；旧版用 App ID + Access Token。文档 6561/1354869。"""
    headers = {
        "X-Api-Resource-Id": settings.volc_resource_id or VOLC_RESOURCE_ASR2_DURATION,
        "X-Api-Request-Id": request_id,
        "X-Api-Connect-Id": request_id,
        "X-Api-Sequence": "-1",
    }
    if settings.volc_app_id and settings.volc_access_key:
        headers["X-Api-App-Key"] = settings.volc_app_id
        headers["X-Api-Access-Key"] = settings.volc_access_key
        return headers
    headers["X-Api-Key"] = settings.volc_api_key
    return headers


class AsrAdapter(ABC):
    async def interrupt(self) -> None:
        """Phase 3 打断用。Phase 1 不改变识别会话。"""
        return None

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send_audio(self, pcm: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def receive_text(self) -> AsyncIterator[TranscriptEvent]:
        raise NotImplementedError

    @abstractmethod
    async def finish(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class _QueuedAdapter(AsrAdapter):
    def __init__(self) -> None:
        self._ws: Any = None
        self._queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._reader: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._failed = ""
        self._closed = False

    async def receive_text(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            if item.kind == "error":
                raise RuntimeError(item.text)
            yield item

    async def _fail(self, message: str) -> None:
        self._failed = message
        self._ready.set()
        await self._queue.put(TranscriptEvent("error", message))
        await self._queue.put(None)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._reader and not self._reader.done():
            self._reader.cancel()
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass


class AliyunAsrAdapter(_QueuedAdapter):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._task_id = str(uuid.uuid4())

    async def connect(self) -> None:
        headers = {
            "Authorization": f"Bearer {self._settings.dashscope_api_key}",
            "X-DashScope-WorkSpace": self._settings.aliyun_workspace_id,
        }
        self._ws = await connect_ws(self._settings.aliyun_ws_url, headers)
        self._reader = asyncio.create_task(self._read_loop())
        await self._ws.send(json.dumps(self._run_task(), ensure_ascii=False))
        await asyncio.wait_for(self._ready.wait(), timeout=10)
        if self._failed:
            raise RuntimeError(self._failed)

    async def send_audio(self, pcm: bytes) -> None:
        if not pcm or self._ws is None:
            return
        await self._ws.send(pcm)

    async def finish(self) -> None:
        if self._ws is None:
            return
        await self._ws.send(json.dumps(self._finish_task(), ensure_ascii=False))

    def _run_task(self) -> dict[str, Any]:
        return {
            "header": {
                "action": "run-task",
                "task_id": self._task_id,
                "streaming": "duplex",
            },
            "payload": {
                "task_group": "audio",
                "task": "asr",
                "function": "recognition",
                "model": self._settings.aliyun_asr_model or "paraformer-realtime-v2",
                "input": {},
                "parameters": {
                    "format": "pcm",
                    "sample_rate": 16000,
                    "language_hints": ["zh", "en"],
                    "max_sentence_silence": self._settings.asr_end_window_ms,
                },
            },
        }

    def _finish_task(self) -> dict[str, Any]:
        return {
            "header": {
                "action": "finish-task",
                "task_id": self._task_id,
                "streaming": "duplex",
            },
            "payload": {"input": {}},
        }

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                mapped = map_aliyun_message(json.loads(raw))
                if mapped["started"]:
                    self._ready.set()
                for event in mapped["events"]:
                    await self._queue.put(event)
                if mapped["failed"]:
                    self._failed = str(mapped["failed"])
                    self._ready.set()
                    await self._queue.put(None)
                    return
                if mapped["finished"]:
                    self._ready.set()
                    await self._queue.put(None)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail(str(exc) or "阿里云识别中断")
            return
        if not self._ready.is_set():
            await self._fail("阿里云 ASR 在就绪前断开")
            return
        await self._queue.put(None)


class VolcengineAsrAdapter(_QueuedAdapter):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._request_id = str(uuid.uuid4())

    async def connect(self) -> None:
        headers = volc_auth_headers(self._settings, self._request_id)
        self._ws = await connect_ws(self._settings.volc_ws_url, headers)
        self._reader = asyncio.create_task(self._read_loop())
        payload = json.dumps(self._full_request(), ensure_ascii=False).encode("utf-8")
        await self._ws.send(build_volc_client_frame(VOLC_FULL_CLIENT, payload, json_payload=True))
        await asyncio.wait_for(self._ready.wait(), timeout=10)
        if self._failed:
            raise RuntimeError(self._failed)

    async def send_audio(self, pcm: bytes) -> None:
        await self._send_audio(pcm, last=False)

    async def finish(self) -> None:
        # 末包带一小段静音，方便云端按静音判停。
        await self._send_audio(b"\x00" * 6400, last=True)

    async def _send_audio(self, pcm: bytes, *, last: bool) -> None:
        if self._ws is None:
            return
        await self._ws.send(build_volc_client_frame(VOLC_AUDIO_ONLY, pcm, last=last))

    def _full_request(self) -> dict[str, Any]:
        resource = self._settings.volc_resource_id or VOLC_RESOURCE_ASR2_DURATION
        request: dict[str, Any] = {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "enable_nonstream": True,
            "show_utterances": True,
            "end_window_size": self._settings.asr_end_window_ms,
            "result_type": "full",
        }
        if "seedasr" in resource:
            request["ssd_version"] = "200"
        return {
            "user": {"uid": "voice-rec-demo"},
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
            },
            "request": request,
        }

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                frame = parse_volc_frame(bytes(raw))
                if frame.get("error"):
                    await self._fail(f"火山识别失败（{frame.get('error_code')}）：{frame['error']}")
                    return
                if not self._ready.is_set():
                    self._ready.set()
                for event in map_volc_result(frame.get("body"), is_last=bool(frame["is_last"])):
                    await self._queue.put(event)
                if frame["is_last"]:
                    await self._queue.put(None)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail(str(exc) or "火山识别中断")
            return
        self._ready.set()
        await self._queue.put(None)


def create_adapter(settings: Settings) -> AsrAdapter:
    if settings.asr_provider == "volcengine":
        return VolcengineAsrAdapter(settings)
    return AliyunAsrAdapter(settings)

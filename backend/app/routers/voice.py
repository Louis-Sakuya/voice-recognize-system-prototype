"""Phase 1 语音网关：健康检查与浏览器 WebSocket。"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.voice.adapters import AsrAdapter, create_adapter
from app.voice.probe import probe_cloud

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


@router.get("/health")
async def voice_health() -> dict[str, object]:
    settings = get_settings()
    report = dict(settings.voice_report())
    if report["ready"]:
        reason = await probe_cloud(settings)
        if reason:
            report["ready"] = False
            report["reason"] = reason
    return report


async def _relay(
    adapter: AsrAdapter,
    websocket: WebSocket,
    send_lock: asyncio.Lock,
) -> None:
    try:
        async for event in adapter.receive_text():
            async with send_lock:
                await websocket.send_json(event.as_message())
    except Exception as exc:
        message = str(exc).strip() or "识别中断"
        try:
            async with send_lock:
                await websocket.send_json({"type": "error", "message": message})
        except Exception:
            logger.debug("识别结果回写失败", exc_info=True)


@router.websocket("/stream")
async def voice_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    report = settings.voice_report()
    adapter: AsrAdapter | None = None
    relay: asyncio.Task[None] | None = None
    send_lock = asyncio.Lock()

    async def send_json(payload: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("text") is not None:
                try:
                    payload = json.loads(message["text"])
                except json.JSONDecodeError:
                    await send_json({"type": "error", "message": "控制消息不是合法 JSON"})
                    break
                kind = str((payload or {}).get("type") or "")
                if kind == "start":
                    if adapter is not None:
                        continue
                    if not report["ready"]:
                        await send_json({"type": "error", "message": str(report["reason"])})
                        break
                    adapter = create_adapter(settings)
                    try:
                        await adapter.connect()
                    except Exception as exc:
                        await send_json({"type": "error", "message": f"连接云端 ASR 失败：{exc}"})
                        break
                    await send_json(
                        {
                            "type": "ready",
                            "provider": report["provider"],
                            "model": report["model"],
                        }
                    )
                    relay = asyncio.create_task(_relay(adapter, websocket, send_lock))
                elif kind == "stop":
                    break
                else:
                    await send_json({"type": "error", "message": "未知控制消息"})
                    break
            elif message.get("bytes"):
                if adapter is None:
                    await send_json({"type": "error", "message": "请先发送 start"})
                    break
                await adapter.send_audio(message["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        if adapter is not None:
            try:
                await adapter.finish()
            except Exception:
                logger.debug("结束云端识别失败", exc_info=True)
            if relay is not None:
                try:
                    await asyncio.wait_for(relay, timeout=8)
                except Exception:
                    relay.cancel()
            await adapter.close()

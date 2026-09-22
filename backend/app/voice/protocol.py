"""把阿里云 / 火山的识别回包映射成 partial 或 final。不访问网络。"""

from __future__ import annotations

import gzip
import json
from typing import Any

from app.voice.events import TranscriptEvent


def map_aliyun_message(message: dict[str, Any]) -> dict[str, Any]:
    header = message.get("header") or {}
    event = str(header.get("event") or "")
    if event == "task-started":
        return {"started": True, "finished": False, "failed": "", "events": []}
    if event == "task-finished":
        return {"started": False, "finished": True, "failed": "", "events": []}
    if event == "task-failed":
        reason = str(header.get("error_message") or header.get("error_code") or "阿里云识别失败")
        return {
            "started": False,
            "finished": True,
            "failed": reason,
            "events": [TranscriptEvent("error", reason)],
        }
    if event != "result-generated":
        return {"started": False, "finished": False, "failed": "", "events": []}

    sentence = ((message.get("payload") or {}).get("output") or {}).get("sentence") or {}
    if sentence.get("heartbeat") is True:
        return {"started": False, "finished": False, "failed": "", "events": []}
    text = str(sentence.get("text") or "").strip()
    if not text:
        return {"started": False, "finished": False, "failed": "", "events": []}
    kind = "final" if sentence.get("sentence_end") is True else "partial"
    return {
        "started": False,
        "finished": False,
        "failed": "",
        "events": [TranscriptEvent(kind, text)],
    }


def map_volc_result(body: dict[str, Any] | None, *, is_last: bool) -> list[TranscriptEvent]:
    result = (body or {}).get("result") or {}
    if isinstance(result, list):
        result = result[0] if result else {}
    utterances = result.get("utterances") or []
    events: list[TranscriptEvent] = []
    pending = ""
    if utterances:
        for item in utterances:
            text = str((item or {}).get("text") or "").strip()
            if not text:
                continue
            if (item or {}).get("definite") is True:
                events.append(TranscriptEvent("final", text))
                pending = ""
            else:
                pending = text
        if pending:
            events.append(TranscriptEvent("partial", pending))
        return events

    text = str(result.get("text") or "").strip()
    if not text:
        return []
    kind = "final" if is_last else "partial"
    return [TranscriptEvent(kind, text)]


def parse_volc_frame(data: bytes) -> dict[str, Any]:
    """解析火山服务端二进制帧。整数为大端。"""
    if len(data) < 4:
        raise ValueError("火山回包过短")
    header_size = (data[0] & 0x0F) * 4
    if header_size < 4 or len(data) < header_size:
        raise ValueError("火山回包头长度无效")
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    serialization = data[2] >> 4
    compression = data[2] & 0x0F
    offset = header_size
    is_last = bool(flags & 0b0010)
    if flags & 0b0001:
        if len(data) < offset + 4:
            raise ValueError("火山回包缺少序号")
        sequence = int.from_bytes(data[offset : offset + 4], "big", signed=True)
        offset += 4
        if sequence < 0:
            is_last = True
    else:
        sequence = None

    if message_type == 0b1111:
        if len(data) < offset + 8:
            raise ValueError("火山错误帧过短")
        code = int.from_bytes(data[offset : offset + 4], "big", signed=False)
        size = int.from_bytes(data[offset + 4 : offset + 8], "big", signed=False)
        raw = data[offset + 8 : offset + 8 + size]
        if compression == 1 and raw:
            raw = gzip.decompress(raw)
        text = raw.decode("utf-8", errors="replace")
        return {"is_last": True, "sequence": sequence, "error_code": code, "error": text, "body": None}

    if len(data) < offset + 4:
        raise ValueError("火山回包缺少长度")
    size = int.from_bytes(data[offset : offset + 4], "big", signed=False)
    raw = data[offset + 4 : offset + 4 + size]
    if compression == 1 and raw:
        raw = gzip.decompress(raw)
    body = None
    if serialization == 1 and raw:
        body = json.loads(raw.decode("utf-8"))
    return {"is_last": is_last, "sequence": sequence, "error": "", "body": body}


def build_volc_client_frame(
    message_type: int,
    payload: bytes,
    *,
    last: bool = False,
    json_payload: bool = False,
) -> bytes:
    """构造火山客户端帧：4 字节头 + gzip 后的长度与负载，不带序号。"""
    flags = 0b0010 if last else 0b0000
    serialization = 0b0001 if json_payload else 0b0000
    header = bytes(
        [
            (0b0001 << 4) | 0b0001,
            (message_type << 4) | flags,
            (serialization << 4) | 0b0001,
            0x00,
        ]
    )
    body = gzip.compress(payload)
    return header + len(body).to_bytes(4, "big") + body


def humanize_cloud_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    lowered = text.lower()
    if "127.0.0.1" in text or "proxy" in lowered:
        return "无法连接云端 ASR：本机代理不可用。请确认代理没有指向未启动的 127.0.0.1。"
    if "401" in text or "403" in text:
        return "云端 ASR 拒绝鉴权，请检查密钥。"
    return f"无法连接云端 ASR：{text}"

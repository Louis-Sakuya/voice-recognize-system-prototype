"""健康检查时短连云端，确认密钥和网络，不发送音频。"""

from __future__ import annotations

import asyncio
import uuid

from app.config import Settings
from app.voice.adapters import volc_auth_headers
from app.voice.protocol import humanize_cloud_error
from app.voice.wsutil import connect_ws


async def probe_cloud(settings: Settings) -> str:
    """连通则返回空字符串，否则返回给页面展示的原因。"""
    try:
        if settings.asr_provider == "volcengine":
            headers = volc_auth_headers(settings, str(uuid.uuid4()))
            url = settings.volc_ws_url
        else:
            headers = {
                "Authorization": f"Bearer {settings.dashscope_api_key}",
                "X-DashScope-WorkSpace": settings.aliyun_workspace_id,
            }
            url = settings.aliyun_ws_url
        ws = await asyncio.wait_for(connect_ws(url, headers), timeout=3)
        try:
            await ws.close()
        except Exception:
            pass
        return ""
    except Exception as exc:
        return humanize_cloud_error(exc)

"""兼容不同 websockets 版本的连接参数。"""

from __future__ import annotations

from typing import Any

import websockets


async def connect_ws(url: str, headers: dict[str, str]) -> Any:
    kwargs = {
        "open_timeout": 8,
        "max_size": 8_000_000,
        "ping_interval": 20,
    }
    try:
        return await websockets.connect(url, additional_headers=headers, **kwargs)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, **kwargs)

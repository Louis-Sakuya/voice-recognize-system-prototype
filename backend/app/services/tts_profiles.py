"""TTS A/B 档位表。切换只改 Settings，不改路由。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.config import Settings


def profile_table(settings: Settings) -> dict[str, dict[str, str]]:
    return {
        "A": {
            "model": settings.tts_model_a,
            "voice": settings.tts_voice,
            "kind": "sft",
        },
        "B": {
            "model": settings.tts_model_b,
            "voice": settings.tts_voice,
            "kind": "cosy2",
        },
    }


def active_profile(settings: Settings, voice_override: str = "") -> dict[str, str]:
    key = (settings.tts_profile or "A").strip().upper()
    table = profile_table(settings)
    if key not in table:
        raise HTTPException(status_code=400, detail="TTS_PROFILE 必须是 A 或 B")
    item = dict(table[key])
    item["key"] = key
    if voice_override.strip():
        item["voice"] = voice_override.strip()
    return item


def extra_kwargs(profile: dict[str, str]) -> dict[str, Any]:
    """B 档日后若需流式 / 参考音频，只在这里扩，不改对外契约。"""
    _ = profile.get("kind")
    return {}

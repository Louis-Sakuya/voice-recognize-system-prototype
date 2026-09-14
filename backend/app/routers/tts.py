"""TTS HTTP 接口。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.tts_service import synthesize, tts_health

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])


class SpeechBody(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str = ""


@router.get("/health")
async def health() -> dict[str, object]:
    return await tts_health(get_settings())


@router.post("/speech")
async def speech(body: SpeechBody) -> Response:
    settings = get_settings()
    result = await synthesize(body.text, settings, voice_override=body.voice)
    # HTTP 响应头必须是 Latin-1，不能直接放「中文女」
    return Response(
        content=result["audio"],
        media_type=str(result["media_type"]),
        headers={
            "X-TTS-Profile": str(result["profile"]),
            "X-TTS-Model": str(result["model"]),
            "X-TTS-Cost-Ms": str(result["cost_ms"]),
            "X-TTS-Sentence-Count": str(result["sentence_count"]),
            "Access-Control-Expose-Headers": "X-TTS-Profile, X-TTS-Model, X-TTS-Cost-Ms, X-TTS-Sentence-Count",
        },
    )

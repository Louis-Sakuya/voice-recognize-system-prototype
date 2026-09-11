"""ASR HTTP 接口。"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.config import get_settings
from app.services.asr_service import resolve_ffmpeg, transcribe_upload

router = APIRouter(prefix="/api/v1/asr", tags=["asr"])


@router.get("/health")
async def asr_health() -> dict[str, object]:
    settings = get_settings()
    ffmpeg_ok = True
    ffmpeg_error = ""
    try:
        ffmpeg_bin = resolve_ffmpeg(settings.ffmpeg_path)
    except Exception as exc:
        ffmpeg_ok = False
        ffmpeg_bin = settings.ffmpeg_path
        ffmpeg_error = str(getattr(exc, "detail", exc))
    return {
        "ok": ffmpeg_ok,
        "ffmpeg": ffmpeg_bin,
        "ffmpeg_error": ffmpeg_error,
        "xinference_url": settings.xinference_url,
        "asr_model": settings.asr_model,
    }


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict[str, object]:
    settings = get_settings()
    return await transcribe_upload(file, settings)

"""ASR HTTP 接口。"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from app.config import get_settings
from app.services.asr_service import resolve_ffmpeg, transcribe_upload
from app.services.hotwords import layer_counts, load_hotwords

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
    hotwords = load_hotwords(settings.hotwords_dir)
    return {
        "ok": ffmpeg_ok,
        "ffmpeg": ffmpeg_bin,
        "ffmpeg_error": ffmpeg_error,
        "xinference_url": settings.xinference_url,
        "asr_model": settings.asr_model,
        "hotword_count": len(hotwords),
        "hotword_layers": layer_counts(settings.hotwords_dir),
        "postprocess_enabled": settings.postprocess_enabled,
        "itn_enabled": settings.itn_enabled,
    }


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    hotword: str = Form(""),
) -> dict[str, object]:
    settings = get_settings()
    return await transcribe_upload(file, settings, hotword_override=hotword)

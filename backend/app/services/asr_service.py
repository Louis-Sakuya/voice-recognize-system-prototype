"""音频转码并调用 Xinference OpenAI 兼容转写接口。"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
import wave
from pathlib import Path

import httpx
from fastapi import HTTPException, UploadFile

from app.config import Settings
from app.services.hotwords import hotword_string
from app.services.postprocess import postprocess_text

_AUDIO_SUFFIXES = {
    ".webm",
    ".wav",
    ".mp3",
    ".m4a",
    ".ogg",
    ".opus",
    ".flac",
    ".mp4",
    ".mpeg",
    ".mpga",
}


def resolve_ffmpeg(ffmpeg_path: str) -> str:
    configured = Path(ffmpeg_path)
    if configured.is_file():
        return str(configured)
    found = shutil.which(ffmpeg_path)
    if found:
        return found
    raise HTTPException(
        status_code=500,
        detail=f"未找到 ffmpeg，请安装后加入 PATH，或在 .env 中设置 FFMPEG_PATH。当前值：{ffmpeg_path}",
    )


def _suffix_from_upload(file: UploadFile) -> str:
    name = Path(file.filename or "").suffix.lower()
    if name in _AUDIO_SUFFIXES:
        return name
    content_type = (file.content_type or "").lower()
    if "webm" in content_type:
        return ".webm"
    if "wav" in content_type:
        return ".wav"
    if "mpeg" in content_type or "mp3" in content_type:
        return ".mp3"
    return ".webm"


def _wav_duration_ms(wav_path: Path) -> int:
    with wave.open(str(wav_path), "rb") as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate() or 1
        return int(frames * 1000 / rate)


async def _run_ffmpeg(ffmpeg_bin: str, src: Path, dst: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        "-y",
        "-i",
        str(src),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(dst),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="ignore").strip()[-400:]
        raise HTTPException(status_code=400, detail=f"音频转码失败，请确认文件是有效音频。{message}")


def _extract_text(payload: object) -> str:
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str):
            return text.strip()
        nested = payload.get("data")
        if isinstance(nested, dict) and isinstance(nested.get("text"), str):
            return str(nested.get("text")).strip()
    raise HTTPException(status_code=502, detail="Xinference 未返回识别文本")


async def transcribe_upload(
    file: UploadFile,
    settings: Settings,
    hotword_override: str = "",
) -> dict[str, object]:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="音频内容为空，请重新录音")
    if not (file.content_type or "").startswith("audio/") and Path(file.filename or "").suffix.lower() not in _AUDIO_SUFFIXES:
        if not file.filename and not file.content_type:
            raise HTTPException(status_code=400, detail="请上传音频文件")

    ffmpeg_bin = resolve_ffmpeg(settings.ffmpeg_path)
    started = time.perf_counter()
    suffix = _suffix_from_upload(file)

    with tempfile.TemporaryDirectory(prefix="asr-") as tmp_dir:
        src = Path(tmp_dir) / f"source{suffix}"
        wav = Path(tmp_dir) / "converted.wav"
        src.write_bytes(raw)
        await _run_ffmpeg(ffmpeg_bin, src, wav)
        if not wav.exists() or wav.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="转码后音频为空，请重新录音")
        duration_ms = _wav_duration_ms(wav)
        wav_bytes = wav.read_bytes()

    headers: dict[str, str] = {}
    if settings.xinference_api_key:
        headers["Authorization"] = f"Bearer {settings.xinference_api_key}"

    hotword = hotword_string(settings.hotwords_dir, hotword_override)
    form: dict[str, str] = {"model": settings.asr_model, "response_format": "json"}
    model_l = settings.asr_model.lower()
    if hotword and ("paraformer" in model_l or "seaco" in model_l):
        form["kwargs"] = json.dumps({"hotword": hotword}, ensure_ascii=False)

    try:
        async with httpx.AsyncClient(timeout=settings.asr_timeout_seconds) as client:
            response = await client.post(
                settings.transcriptions_url,
                headers=headers,
                data=form,
                files={"file": ("voice.wav", wav_bytes, "audio/wav")},
            )
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"无法连接 Xinference（{settings.xinference_url}），请确认推理服务已启动",
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Xinference 识别超时，请缩短录音或增大 ASR_TIMEOUT_SECONDS") from exc

    if response.status_code == 401:
        raise HTTPException(status_code=502, detail="Xinference 鉴权失败，请设置 XINFERENCE_API_KEY 或将 XINFERENCE_AUTH_ADVANCED=0")
    if response.status_code >= 400:
        detail = response.text.strip()[-300:] or f"HTTP {response.status_code}"
        raise HTTPException(status_code=502, detail=f"Xinference 转写失败：{detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Xinference 返回了无法解析的内容") from exc

    raw_text = _extract_text(payload)
    text = postprocess_text(
        raw_text,
        settings.replacements_file,
        enabled=settings.postprocess_enabled,
        itn_enabled=settings.itn_enabled,
    )
    cost_ms = int((time.perf_counter() - started) * 1000)
    return {
        "text": text,
        "raw_text": raw_text,
        "model": settings.asr_model,
        "duration_ms": duration_ms,
        "cost_ms": cost_ms,
    }

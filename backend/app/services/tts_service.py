"""调用 Xinference OpenAI 兼容语音合成接口。"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.services.asr_service import resolve_ffmpeg
from app.services.tts_preprocess import merge_for_synthesis, preprocess_text
from app.services.tts_profiles import active_profile, extra_kwargs, profile_table

_AUDIO_SNIFF = (
    (b"ID3", "audio/mpeg", ".mp3"),
    (b"\xff\xfb", "audio/mpeg", ".mp3"),
    (b"\xff\xf3", "audio/mpeg", ".mp3"),
    (b"\xff\xf2", "audio/mpeg", ".mp3"),
    (b"RIFF", "audio/wav", ".wav"),
    (b"OggS", "audio/ogg", ".ogg"),
)


def _auth_headers(settings: Settings) -> dict[str, str]:
    if settings.xinference_api_key:
        return {"Authorization": f"Bearer {settings.xinference_api_key}"}
    return {}


def sniff_audio(data: bytes, content_type: str = "") -> tuple[str, str]:
    header = (content_type or "").split(";")[0].strip().lower()
    if header.startswith("audio/"):
        suffix = ".mp3" if "mpeg" in header or "mp3" in header else ".wav" if "wav" in header else ".bin"
        if "ogg" in header:
            suffix = ".ogg"
        return header, suffix
    for magic, media, suffix in _AUDIO_SNIFF:
        if data.startswith(magic):
            return media, suffix
    return "audio/mpeg", ".mp3"


def _model_aliases(item: object) -> set[str]:
    names: set[str] = set()
    if not isinstance(item, dict):
        return names
    for key in ("id", "model_uid", "model_name", "name"):
        value = str(item.get(key) or "").strip()
        if value:
            names.add(value)
    return names


async def list_running_models(settings: Settings) -> tuple[set[str], str]:
    try:
        async with httpx.AsyncClient(timeout=min(8, settings.tts_timeout_seconds)) as client:
            response = await client.get(settings.models_url, headers=_auth_headers(settings))
    except httpx.ConnectError:
        return set(), f"无法连接 Xinference（{settings.xinference_url}），请确认推理服务已启动"
    except httpx.TimeoutException:
        return set(), "查询 Xinference 模型列表超时"
    if response.status_code == 401:
        return set(), "Xinference 鉴权失败，请设置 XINFERENCE_API_KEY 或将 XINFERENCE_AUTH_ADVANCED=0"
    if response.status_code >= 400:
        return set(), f"Xinference 模型列表失败：{response.text.strip()[-200:] or response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return set(), "Xinference 模型列表无法解析"
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return set(), "Xinference 模型列表格式不正确"
    names: set[str] = set()
    for item in rows:
        names.update(_model_aliases(item))
    return names, ""


def model_is_launched(running: set[str], model: str) -> bool:
    target = (model or "").strip()
    if not target:
        return False
    lowered = target.lower()
    for name in running:
        current = name.lower()
        if current == lowered or current.startswith(f"{lowered}-"):
            return True
    return False


async def tts_health(settings: Settings) -> dict[str, object]:
    running, error = await list_running_models(settings)
    table = profile_table(settings)
    profiles: dict[str, object] = {}
    for key, item in table.items():
        profiles[key] = {
            **item,
            "launched": model_is_launched(running, item["model"]),
        }
    current = active_profile(settings)
    current_ready = model_is_launched(running, current["model"])
    return {
        "ok": not error and current_ready,
        "xinference_url": settings.xinference_url,
        "tts_profile": current["key"],
        "tts_model": current["model"],
        "tts_voice": current["voice"],
        "tts_profiles": profiles,
        "xinference_error": error,
        "current_launched": current_ready,
    }


async def _speech_once(text: str, profile: dict[str, str], settings: Settings) -> tuple[bytes, str]:
    body: dict[str, object] = {
        "model": profile["model"],
        "input": text,
        "voice": profile["voice"],
    }
    kwargs = extra_kwargs(profile)
    if kwargs:
        body["kwargs"] = kwargs
    try:
        async with httpx.AsyncClient(timeout=settings.tts_timeout_seconds) as client:
            response = await client.post(
                settings.speech_url,
                headers={**_auth_headers(settings), "Accept": "audio/*"},
                json=body,
            )
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"无法连接 Xinference（{settings.xinference_url}），请确认推理服务已启动",
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Xinference 在 {settings.tts_timeout_seconds}s 内没有返回音频。"
                f"短文本超时通常不是字数问题，而是 CosyVoice 仍在加载、子进程已崩，或和多份 ASR 抢内存。"
                f"请先看 GET /api/v1/tts/health 的 current_launched，并确认 xinference list 里只有一份 ASR + 一份 TTS。"
            ),
        ) from exc
    if response.status_code == 401:
        raise HTTPException(status_code=502, detail="Xinference 鉴权失败，请设置 XINFERENCE_API_KEY 或将 XINFERENCE_AUTH_ADVANCED=0")
    if response.status_code >= 400:
        detail = response.text.strip()[-300:] or f"HTTP {response.status_code}"
        raise HTTPException(status_code=502, detail=f"Xinference 合成失败：{detail}")
    data = response.content
    if not data:
        raise HTTPException(status_code=502, detail="Xinference 未返回音频")
    media_type, _suffix = sniff_audio(data, response.headers.get("content-type", ""))
    return data, media_type


async def _concat_audio(parts: list[bytes], settings: Settings, suffix: str) -> bytes:
    if len(parts) == 1:
        return parts[0]
    ffmpeg_bin = resolve_ffmpeg(settings.ffmpeg_path)
    with tempfile.TemporaryDirectory(prefix="tts-") as tmp_dir:
        folder = Path(tmp_dir)
        list_file = folder / "concat.txt"
        lines: list[str] = []
        for index, chunk in enumerate(parts):
            path = folder / f"part-{index}{suffix}"
            path.write_bytes(chunk)
            lines.append(f"file '{path.as_posix()}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")
        output = folder / f"merged{suffix}"
        process = await asyncio.create_subprocess_exec(
            ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode == 0 and output.exists() and output.stat().st_size > 0:
            return output.read_bytes()
        inputs: list[str] = []
        for index, _chunk in enumerate(parts):
            inputs.extend(["-i", str(folder / f"part-{index}{suffix}")])
        filter_complex = "".join(f"[{index}:a]" for index in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[a]"
        process = await asyncio.create_subprocess_exec(
            ffmpeg_bin,
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[a]",
            str(output),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            message = stderr.decode("utf-8", errors="ignore").strip()[-300:]
            raise HTTPException(status_code=502, detail=f"拼接朗读音频失败。{message}")
        return output.read_bytes()


async def synthesize(text: str, settings: Settings, voice_override: str = "") -> dict[str, object]:
    spoken = preprocess_text(text, settings.tts_readings_file)
    chunks = merge_for_synthesis(spoken)
    if not chunks:
        raise HTTPException(status_code=400, detail="朗读文本为空")
    profile = active_profile(settings, voice_override)
    running, error = await list_running_models(settings)
    if error and "无法连接" in error:
        raise HTTPException(status_code=503, detail=error)
    if error:
        raise HTTPException(status_code=502, detail=error)
    if not model_is_launched(running, profile["model"]):
        raise HTTPException(
            status_code=503,
            detail=(
                f"TTS 模型未启动（profile {profile['key']} / {profile['model']}）。"
                f"请先运行 scripts/launch-models.ps1；CLI 报 100% 但 list 里没有该模型，说明加载失败，不是合成超时。"
            ),
        )
    started = time.perf_counter()
    audios: list[bytes] = []
    media_type = "audio/mpeg"
    suffix = ".mp3"
    for chunk in chunks:
        data, media_type = await _speech_once(chunk, profile, settings)
        _media, suffix = sniff_audio(data, media_type)
        audios.append(data)
    audio = await _concat_audio(audios, settings, suffix) if len(audios) > 1 else audios[0]
    return {
        "audio": audio,
        "media_type": media_type,
        "profile": profile["key"],
        "model": profile["model"],
        "voice": profile["voice"],
        "spoken_text": spoken,
        "sentence_count": len(chunks),
        "cost_ms": int((time.perf_counter() - started) * 1000),
    }

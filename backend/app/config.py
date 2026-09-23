"""读取本仓库 FastAPI 使用的环境变量。

Phase 1 只依赖云端流式 ASR。旧的 Xinference / TTS 字段仍保留默认值，
缺省或写错不会阻止进程启动。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env", encoding="utf-8")

ALIYUN_PROVIDER = "aliyun"
VOLC_PROVIDER = "volcengine"
VOICE_PROVIDERS = {ALIYUN_PROVIDER, VOLC_PROVIDER}
# 豆包流式识别 2.0 小时版。文档：https://docs.volcengine.com/docs/6561/1354869
VOLC_RESOURCE_ASR2_DURATION = "volc.seedasr.sauc.duration"
VOLC_WS_URL_DEFAULT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _env_flag(name: str, default: str = "1") -> bool:
    return _env(name, default).lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_under_backend(raw: str, default_relative: str) -> Path:
    value = Path(raw or default_relative)
    if not value.is_absolute():
        value = BACKEND_DIR / value
    return value


@dataclass(frozen=True)
class Settings:
    asr_provider: str
    dashscope_api_key: str
    aliyun_workspace_id: str
    aliyun_asr_model: str
    volc_api_key: str
    volc_app_id: str
    volc_access_key: str
    volc_resource_id: str
    volc_ws_url_override: str
    asr_end_window_ms: int
    app_host: str
    app_port: int
    xinference_url: str
    xinference_api_key: str
    asr_model: str
    asr_timeout_seconds: int
    ffmpeg_path: str
    hotwords_dir: Path
    replacements_file: Path
    postprocess_enabled: bool
    itn_enabled: bool
    tts_profile: str
    tts_model_a: str
    tts_model_b: str
    tts_voice: str
    tts_timeout_seconds: int
    tts_readings_file: Path

    @property
    def transcriptions_url(self) -> str:
        return f"{self.xinference_url.rstrip('/')}/v1/audio/transcriptions"

    @property
    def speech_url(self) -> str:
        return f"{self.xinference_url.rstrip('/')}/v1/audio/speech"

    @property
    def models_url(self) -> str:
        return f"{self.xinference_url.rstrip('/')}/v1/models"

    @property
    def aliyun_ws_url(self) -> str:
        return f"wss://{self.aliyun_workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"

    @property
    def volc_ws_url(self) -> str:
        return self.volc_ws_url_override or VOLC_WS_URL_DEFAULT

    def voice_report(self) -> dict[str, object]:
        return describe_voice(self)


def describe_voice(settings: Settings) -> dict[str, object]:
    """凭证是否齐备。ready 只表示可以让用户打开语音，不表示已经打开。"""
    provider = settings.asr_provider
    if provider not in VOICE_PROVIDERS:
        return {
            "ready": False,
            "provider": provider,
            "model": "",
            "reason": "请在 backend/.env 设置 ASR_PROVIDER=aliyun 或 volcengine",
        }
    if provider == ALIYUN_PROVIDER:
        model = settings.aliyun_asr_model or "paraformer-realtime-v2"
        missing = []
        if not settings.dashscope_api_key:
            missing.append("DASHSCOPE_API_KEY")
        if not settings.aliyun_workspace_id:
            missing.append("ALIYUN_WORKSPACE_ID")
        if missing:
            return {
                "ready": False,
                "provider": provider,
                "model": model,
                "reason": "缺少 " + "、".join(missing),
            }
        return {"ready": True, "provider": provider, "model": model, "reason": ""}

    model = "bigmodel"
    has_new = bool(settings.volc_api_key)
    has_old = bool(settings.volc_app_id and settings.volc_access_key)
    if not has_new and not has_old:
        return {
            "ready": False,
            "provider": provider,
            "model": model,
            "reason": "缺少 VOLC_API_KEY，或同时填写旧控制台的 VOLC_APP_ID 与 VOLC_ACCESS_KEY",
        }
    return {
        "ready": True,
        "provider": provider,
        "model": model,
        "resource_id": settings.volc_resource_id or VOLC_RESOURCE_ASR2_DURATION,
        "reason": "",
    }


def get_settings() -> Settings:
    return Settings(
        asr_provider=_env("ASR_PROVIDER").lower(),
        dashscope_api_key=_env("DASHSCOPE_API_KEY"),
        aliyun_workspace_id=_env("ALIYUN_WORKSPACE_ID"),
        aliyun_asr_model=_env("ALIYUN_ASR_MODEL", "paraformer-realtime-v2"),
        volc_api_key=_env("VOLC_API_KEY"),
        volc_app_id=_env("VOLC_APP_ID"),
        volc_access_key=_env("VOLC_ACCESS_KEY"),
        volc_resource_id=_env("VOLC_RESOURCE_ID", VOLC_RESOURCE_ASR2_DURATION),
        volc_ws_url_override=_env("VOLC_WS_URL"),
        asr_end_window_ms=min(6000, max(500, _env_int("ASR_END_WINDOW_MS", 2000))),
        app_host=_env("APP_HOST", "127.0.0.1"),
        app_port=_env_int("APP_PORT", 8000),
        xinference_url=_env("XINFERENCE_URL", "http://127.0.0.1:9997"),
        xinference_api_key=_env("XINFERENCE_API_KEY"),
        asr_model=_env("ASR_MODEL", "seaco-paraformer-zh"),
        asr_timeout_seconds=max(1, _env_int("ASR_TIMEOUT_SECONDS", 60)),
        ffmpeg_path=_env("FFMPEG_PATH", "ffmpeg"),
        hotwords_dir=_resolve_under_backend(_env("ASR_HOTWORDS_DIR"), "data/hotwords"),
        replacements_file=_resolve_under_backend(_env("ASR_REPLACEMENTS_FILE"), "data/replacements.yaml"),
        postprocess_enabled=_env_flag("ASR_POSTPROCESS_ENABLED", "1"),
        itn_enabled=_env_flag("ASR_ITN_ENABLED", "1"),
        tts_profile=_env("TTS_PROFILE", "A").upper() or "A",
        tts_model_a=_env("TTS_MODEL_A", "CosyVoice-300M-SFT"),
        tts_model_b=_env("TTS_MODEL_B", "CosyVoice2-0.5B"),
        tts_voice=_env("TTS_VOICE", "中文女"),
        tts_timeout_seconds=max(1, _env_int("TTS_TIMEOUT_SECONDS", 180)),
        tts_readings_file=_resolve_under_backend(_env("TTS_READINGS_FILE"), "data/tts_readings.yaml"),
    )

"""读取本仓库 FastAPI 使用的环境变量（B 套）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _env_flag(name: str, default: str = "1") -> bool:
    return _env(name, default).lower() not in {"0", "false", "no", "off"}


def _resolve_under_backend(raw: str, default_relative: str) -> Path:
    value = Path(raw or default_relative)
    if not value.is_absolute():
        value = BACKEND_DIR / value
    return value


@dataclass(frozen=True)
class Settings:
    xinference_url: str
    xinference_api_key: str
    asr_model: str
    asr_timeout_seconds: int
    ffmpeg_path: str
    app_host: str
    app_port: int
    hotwords_dir: Path
    replacements_file: Path
    postprocess_enabled: bool
    itn_enabled: bool

    @property
    def transcriptions_url(self) -> str:
        return f"{self.xinference_url.rstrip('/')}/v1/audio/transcriptions"


def get_settings() -> Settings:
    timeout_raw = _env("ASR_TIMEOUT_SECONDS", "60")
    port_raw = _env("APP_PORT", "8000")
    try:
        timeout_seconds = max(1, int(timeout_raw))
    except ValueError as exc:
        raise ValueError("ASR_TIMEOUT_SECONDS 必须是正整数") from exc
    try:
        app_port = int(port_raw)
    except ValueError as exc:
        raise ValueError("APP_PORT 必须是整数") from exc
    return Settings(
        xinference_url=_env("XINFERENCE_URL", "http://127.0.0.1:9997"),
        xinference_api_key=_env("XINFERENCE_API_KEY"),
        asr_model=_env("ASR_MODEL", "seaco-paraformer-zh"),
        asr_timeout_seconds=timeout_seconds,
        ffmpeg_path=_env("FFMPEG_PATH", "ffmpeg"),
        app_host=_env("APP_HOST", "127.0.0.1"),
        app_port=app_port,
        hotwords_dir=_resolve_under_backend(_env("ASR_HOTWORDS_DIR"), "data/hotwords"),
        replacements_file=_resolve_under_backend(_env("ASR_REPLACEMENTS_FILE"), "data/replacements.yaml"),
        postprocess_enabled=_env_flag("ASR_POSTPROCESS_ENABLED", "1"),
        itn_enabled=_env_flag("ASR_ITN_ENABLED", "1"),
    )

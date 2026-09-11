"""FastAPI 入口：ASR 接口 + 托管前端演示页。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers.asr import router as asr_router

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="voice-rec-system", version="0.1.0")
app.include_router(asr_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if FRONTEND_DIR.is_dir():
    index_file = FRONTEND_DIR / "index.html"

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(index_file, media_type="text/html; charset=utf-8")

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="frontend-static")

"""EchoMind · 声忆多用户全龄段智能音箱与有声伴学平台 FastAPI 入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import WEB_DIST_DIR, ensure_directories
from app.db import init_db
from app.gateways import speaker_ws, web_ws, xiaozhi_ws
from app.routers import (
    auth_users,
    books,
    dashboard,
    devices,
    english,
    media,
    members,
    playback,
    schedules,
    settings_api,
    sources,
)
from app.services.scheduler import scheduler_service
from app.services.tts_asr import TTS_CACHE_DIR


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_directories()
    await init_db()
    await scheduler_service.start()
    try:
        yield
    finally:
        scheduler_service.shutdown()


app = FastAPI(
    title="EchoMind（声忆·家庭智能音箱中枢）",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_users.router)
app.include_router(dashboard.router)
app.include_router(devices.router)
app.include_router(books.router)
app.include_router(sources.router)
app.include_router(members.router)
app.include_router(english.router)
app.include_router(media.router)
app.include_router(playback.router)
app.include_router(schedules.router)
app.include_router(settings_api.router)

app.include_router(speaker_ws.router)
app.include_router(xiaozhi_ws.router)
app.include_router(web_ws.router)


@app.get("/api/tts-cache/{filename}")
async def serve_tts_cache(filename: str):
    """安全返回 TTS 缓存音频文件。"""
    safe_name = Path(filename).name
    target = TTS_CACHE_DIR / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="音频已过期或不存在")
    return FileResponse(str(target), media_type="audio/mpeg")


if (WEB_DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST_DIR / "assets")), name="assets")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith(("api/", "ws/", "xiaozhi/")):
        raise HTTPException(status_code=404, detail="Not Found")
    index_file = WEB_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "name": "EchoMind（声忆·家庭智能音箱中枢）API",
        "message": "前端尚未构建，请运行 npm --prefix web run build 或访问 Vite 开发端口。",
    }

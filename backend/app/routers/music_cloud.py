"""全网多源音乐搜索、热歌榜、歌单解析、实时代理试听与云端批量下载路由。"""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import get_db
from app.services.music_dl import (
    SUPPORTED_MUSIC_SOURCES,
    build_upstream_download_url,
    check_music_dl_health,
    cloud_collection_songs,
    cloud_search,
    cloud_toplist_songs,
    cloud_toplists,
    enqueue_cloud_batch_download,
    normalize_music_dl_base,
    try_switch_source,
)

router = APIRouter(prefix="/api/cloud-music", tags=["cloud-music"])


class BatchDownloadSongItem(BaseModel):
    id: str
    source: str
    name: str
    artist: str = ""
    album: str = ""
    cover: str = ""
    duration: int = 0
    extra: dict[str, Any] = {}


class BatchDownloadRequest(BaseModel):
    songs: list[BatchDownloadSongItem]
    series_id: int | None = None
    album_id: int | None = None
    new_series_title: str = ""
    season_label: str = ""
    new_album_title: str = "云端下载精选"
    auto_group_by_artist: bool = False
    category: Literal["music", "story", "english", "podcast"] = "music"
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] = "S6_ALL"


@router.get("/status")
async def cloud_music_status(_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    health = await check_music_dl_health()
    return {
        **health,
        "supported_sources": SUPPORTED_MUSIC_SOURCES,
    }


@router.get("/search")
async def cloud_music_search(
    q: str = Query(..., min_length=1),
    search_type: Literal["song", "playlist", "album"] = Query(default="song"),
    sources: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    src_list = [s.strip() for s in (sources or "").split(",") if s.strip()] or None
    try:
        return await cloud_search(q=q, search_type=search_type, sources=src_list, page=page)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"多源搜索失败（请确认音乐引擎已运行）: {exc}")


@router.get("/toplists")
async def cloud_music_toplists(
    sources: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    src_list = [s.strip() for s in (sources or "").split(",") if s.strip()] or None
    try:
        return await cloud_toplists(sources=src_list)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"获取热歌榜单失败: {exc}")


@router.get("/toplists/songs")
async def cloud_music_toplist_songs(
    source: str = Query(...),
    toplist_id: str = Query(...),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    try:
        return await cloud_toplist_songs(source=source, toplist_id=toplist_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"加载榜单歌曲失败: {exc}")


@router.get("/collections/songs")
async def cloud_music_collection_songs(
    source: str = Query(...),
    id: str = Query(...),
    kind: Literal["playlist", "album"] = Query(default="playlist"),
    page: int = Query(default=1, ge=1),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    try:
        return await cloud_collection_songs(source=source, collection_id=id, kind=kind, page=page)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"加载歌单/专辑详情失败: {exc}")


@router.get("/stream")
async def cloud_music_stream(
    id: str = Query(...),
    source: str = Query(...),
    name: str = Query(default=""),
    artist: str = Query(default=""),
    album: str = Query(default=""),
    extra: str = Query(default="{}"),
):
    """代理流式转发上游音频（支持自动换源兜底，免认证便于浏览器 Audio 直播）。"""
    base = normalize_music_dl_base()
    if not base:
        raise HTTPException(status_code=503, detail="多源音乐服务未配置")

    try:
        extra_dict = json.loads(extra) if extra else {}
    except Exception:
        extra_dict = {}

    song: dict[str, Any] = {
        "id": id,
        "source": source,
        "name": name,
        "artist": artist,
        "album": album,
        "extra": extra_dict if isinstance(extra_dict, dict) else {},
    }
    target_url = build_upstream_download_url(song, base_url=base, stream_only=True)
    headers = {"X-Requested-With": "XMLHttpRequest"}

    client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    try:
        req = client.build_request("GET", target_url, headers=headers)
        resp = await client.send(req, stream=True)
        if resp.status_code >= 400 and name.strip():
            await resp.aclose()
            alt = await try_switch_source(name=name, artist=artist, current_source=source, base_url=base)
            if alt:
                alt_url = build_upstream_download_url(alt, base_url=base, stream_only=True)
                req2 = client.build_request("GET", alt_url, headers=headers)
                resp = await client.send(req2, stream=True)

        if resp.status_code >= 400:
            code = resp.status_code
            await resp.aclose()
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"上游音源暂不可播 (HTTP {code})")
    except HTTPException:
        raise
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"连接多源音频流失败: {exc}")

    media_type = resp.headers.get("content-type", "audio/mpeg")
    if "application/json" in media_type or "text/html" in media_type:
        media_type = "audio/mpeg"

    async def _iter_chunks():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=32768):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(_iter_chunks(), media_type=media_type)


@router.post("/batch-download")
async def cloud_music_batch_download(
    req: BatchDownloadRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.songs:
        raise HTTPException(status_code=400, detail="请至少选择 1 首歌曲")
    if len(req.songs) > 500:
        raise HTTPException(status_code=400, detail="单次批量任务最多支持 500 首歌曲")
    try:
        return await enqueue_cloud_batch_download(
            songs=[s.model_dump() for s in req.songs],
            album_id=req.album_id,
            series_id=req.series_id,
            new_series_title=req.new_series_title,
            season_label=req.season_label,
            new_album_title=req.new_album_title,
            auto_group_by_artist=req.auto_group_by_artist,
            category=req.category,
            age_stage=req.age_stage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/jobs")
async def list_cloud_download_jobs(
    limit: int = Query(default=20, ge=1, le=50),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT j.*, a.title AS album_title
            FROM download_jobs j
            LEFT JOIN media_albums a ON j.target_album_id = a.id
            WHERE j.source_url LIKE 'cloud_batch://%'
            ORDER BY j.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]

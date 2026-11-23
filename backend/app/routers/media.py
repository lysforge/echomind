"""自有分级媒体库、实时边播边缓存、本地目录扫描与本地文件汇总路由。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.auth import get_current_user, require_admin
from app.config import DATA_DIR, MEDIA_RAW_DIR, MEDIA_TRACKS_DIR, load_settings
from app.db import ENGLISH_LEVEL_TO_STAGE, ENGLISH_STAGE_TO_LEVEL, _default_channel_emoji, _default_season_label, get_db, now_iso
from app.gateways.manager import device_manager
from app.services.ai_curator import (
    enqueue_ai_collect,
    ensure_series_and_season,
    update_playback_progress,
)
from app.services.tts_asr import TTS_CACHE_DIR
from app.services.webdav_sync import preview_webdav_directory, sync_webdav_mount
from app.services.collector import (
    LIVE_STREAM_SESSIONS,
    _looks_like_direct_audio_url,
    add_track_from_text,
    ensure_default_local_folder,
    ingest_uploaded_file,
    resolve_or_prepare_online_stream,
    run_rss_job,
    run_yt_dlp_job,
    scan_local_folder,
    search_online_audio,
    synthesize_track_audio_if_missing,
)

router = APIRouter(prefix="/api/media", tags=["media"])


class CategoryTagCreate(BaseModel):
    channel: Literal["music", "story", "english", "podcast"]
    name: str
    sort_order: int = 10


class SeriesCreate(BaseModel):
    title: str
    channel: Literal["music", "story", "english", "podcast"] = "story"
    level_code: str = ""
    cover_emoji: str = ""
    author: str = ""
    description: str = ""
    auto_create_first_season: bool = True
    first_season_label: str = ""


class SeriesPatch(BaseModel):
    title: str | None = None
    channel: Literal["music", "story", "english", "podcast"] | None = None
    level_code: str | None = None
    cover_emoji: str | None = None
    author: str | None = None
    description: str | None = None


class SeasonCreate(BaseModel):
    season_num: int | None = None
    season_label: str = ""
    title: str = ""
    description: str = ""
    play_mode: Literal["sequential", "shuffle"] = "sequential"


class AiCollectRequest(BaseModel):
    query: str
    channel_hint: Literal["music", "story", "english", "podcast"] | None = None
    series_id: int | None = None
    album_id: int | None = None
    max_items: int = 5
    device_id: str = ""
    notify_speaker: bool = True


class AlbumCreate(BaseModel):
    title: str
    category: Literal["music", "story", "english", "podcast"] = "music"
    series_id: int | None = None
    season_num: int = 1
    season_label: str = ""
    sub_tag: str = ""
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] = "S6_ALL"
    english_level: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS", "adult"] = "Pre_A1"
    play_mode: Literal["sequential", "shuffle"] = "sequential"
    cover_emoji: str = ""
    author: str = ""
    language: str = "zh"
    is_inbox: bool = False
    description: str = ""


class AlbumPatch(BaseModel):
    title: str | None = None
    category: Literal["music", "story", "english", "podcast"] | None = None
    series_id: int | None = None
    season_num: int | None = None
    season_label: str | None = None
    sub_tag: str | None = None
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] | None = None
    english_level: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS", "adult"] | None = None
    play_mode: Literal["sequential", "shuffle"] | None = None
    cover_emoji: str | None = None
    author: str | None = None
    language: str | None = None
    is_inbox: bool | None = None
    description: str | None = None


class TrackPatch(BaseModel):
    title: str | None = None
    episode_num: int | None = None
    text_content: str | None = None
    completed: bool | None = None
    album_id: int | None = None


class TextTrackCreate(BaseModel):
    title: str
    text_content: str
    language: str = "zh"
    objective: str = ""
    vocab: list[dict[str, str]] = []


class ProgressUpdate(BaseModel):
    track_id: int
    position_sec: float = 0.0
    member_key: str = ""


class WebDavMountCreate(BaseModel):
    name: str
    base_url: str
    username: str = ""
    password: str = ""
    remote_path: str = "/"
    channel: Literal["music", "story", "english", "podcast"] = "story"
    level_code: str = ""


class WebDavPreviewRequest(BaseModel):
    base_url: str
    remote_path: str = "/"
    username: str = ""
    password: str = ""


class CastRequest(BaseModel):
    device_id: str


class YtDlpCollectRequest(BaseModel):
    url: str
    album_id: int
    max_items: int = 10


class RssCollectRequest(BaseModel):
    rss_url: str
    album_id: int
    limit: int = 5


class PlayAndCacheRequest(BaseModel):
    title: str
    url: str
    category: Literal["music", "story", "english", "podcast"] = "music"
    album_id: int | None = None
    source_id: int | None = None
    external_guid: str = ""
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] = "S6_ALL"
    device_id: str = ""
    online_stream_id: int | None = None


class LocalFolderCreate(BaseModel):
    name: str
    folder_path: str
    media_type: Literal["auto", "music", "story", "book"] = "auto"
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] = "S6_ALL"


class OnlineStreamCreate(BaseModel):
    title: str
    url: str
    stream_kind: Literal["direct_audio", "playlist_url"] = "direct_audio"
    category: Literal["music", "story", "english", "podcast"] = "music"
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] = "S6_ALL"
    description: str = ""


# -------------------- 二级分类标签 CRUD --------------------


@router.get("/tags")
async def list_tags(
    channel: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    async with get_db() as conn:
        if channel and channel != "all":
            cur = await conn.execute(
                "SELECT * FROM category_tags WHERE channel = ? ORDER BY sort_order ASC, id ASC",
                (channel,),
            )
        else:
            cur = await conn.execute("SELECT * FROM category_tags ORDER BY channel ASC, sort_order ASC, id ASC")
        return [dict(r) for r in await cur.fetchall()]


@router.post("/tags")
async def create_tag(
    req: CategoryTagCreate,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    tname = req.name.strip()
    if not tname:
        raise HTTPException(status_code=400, detail="分类标签名称不能为空")
    async with get_db() as conn:
        try:
            cur = await conn.execute(
                "INSERT INTO category_tags (channel, name, sort_order, created_at) VALUES (?, ?, ?, ?)",
                (req.channel, tname, req.sort_order, now_iso()),
            )
            await conn.commit()
            cur2 = await conn.execute("SELECT * FROM category_tags WHERE id = ?", (cur.lastrowid,))
            return dict(await cur2.fetchone())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"新增分类标签失败: {exc}")


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: int,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM category_tags WHERE id = ?", (tag_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="标签不存在")
        await conn.execute(
            "UPDATE media_albums SET sub_tag = '' WHERE category = ? AND sub_tag = ?",
            (row["channel"], row["name"]),
        )
        await conn.execute("DELETE FROM category_tags WHERE id = ?", (tag_id,))
        await conn.commit()
    return {"status": "deleted"}


# -------------------- 一级系列 → 二级季/专辑 → 三级单集 树形 CRUD --------------------


@router.get("/series")
async def list_series_tree(
    channel: str | None = Query(default=None),
    level_code: str | None = Query(default=None),
    q: str | None = Query(default=None),
    member_key: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """返回清晰的三级树：一级系列合集 → 二级季/专辑/单元列表 → 三级单集列表及精确断点续播摘要（支持多人独立进度）。"""
    async with get_db() as conn:
        # 兜底确保所有非收件箱专辑都挂在 series 下
        cur_orphan = await conn.execute("SELECT id FROM media_albums WHERE series_id IS NULL AND is_inbox = 0 LIMIT 1")
        if await cur_orphan.fetchone():
            from app.db import _backfill_series_for_orphan_albums

            await _backfill_series_for_orphan_albums(conn)
            await conn.commit()

        clauses: list[str] = []
        params: list[Any] = []
        if channel and channel != "all":
            clauses.append("channel = ?")
            params.append(channel)
        if level_code and level_code != "all":
            clauses.append("level_code = ?")
            params.append(level_code)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur_s = await conn.execute(
            f"SELECT * FROM media_series {where_sql} ORDER BY COALESCE(last_played_at, '') DESC, id DESC",
            params,
        )
        series_list = [dict(r) for r in await cur_s.fetchall()]

        cur_a = await conn.execute(
            "SELECT * FROM media_albums WHERE is_inbox = 0 ORDER BY season_num ASC, id ASC"
        )
        albums_raw = [dict(r) for r in await cur_a.fetchall()]

        cur_t = await conn.execute(
            "SELECT * FROM media_tracks ORDER BY album_id ASC, episode_num ASC, id ASC"
        )
        tracks_raw = [dict(r) for r in await cur_t.fetchall()]

        member_progress: dict[int, dict[str, Any]] = {}
        mk = (member_key or "").strip()
        if mk:
            cur_mp = await conn.execute(
                "SELECT * FROM user_playback_progress WHERE member_key = ?",
                (mk,),
            )
            for mr in await cur_mp.fetchall():
                member_progress[int(mr["series_id"])] = dict(mr)

    tracks_by_album: dict[int, list[dict[str, Any]]] = {}
    tracks_by_id: dict[int, dict[str, Any]] = {}
    for t in tracks_raw:
        try:
            t["vocab"] = json.loads(t.get("vocab_json") or "[]")
        except Exception:
            t["vocab"] = []
        t["stream_url"] = f"/api/media/tracks/{t['id']}/stream"
        tracks_by_album.setdefault(int(t["album_id"]), []).append(t)
        tracks_by_id[int(t["id"])] = t

    albums_by_series: dict[int, list[dict[str, Any]]] = {}
    albums_by_id: dict[int, dict[str, Any]] = {}
    for a in albums_raw:
        a["tracks"] = tracks_by_album.get(int(a["id"]), [])
        a["track_count"] = len(a["tracks"])
        a["season_label"] = (a.get("season_label") or "").strip() or _default_season_label(a["category"], int(a.get("season_num") or 1))
        if a.get("series_id"):
            albums_by_series.setdefault(int(a["series_id"]), []).append(a)
        albums_by_id[int(a["id"])] = a

    kw = (q or "").strip().lower()
    out: list[dict[str, Any]] = []
    for s in series_list:
        sid = int(s["id"])
        seasons = albums_by_series.get(sid, [])
        all_tracks = [t for sea in seasons for t in sea.get("tracks", [])]
        if kw:
            hit_s = kw in s["title"].lower() or kw in (s.get("author") or "").lower() or kw in (s.get("level_code") or "").lower()
            hit_sea = any(kw in sea["title"].lower() or kw in sea["season_label"].lower() for sea in seasons)
            hit_tr = any(kw in t["title"].lower() for t in all_tracks)
            if not (hit_s or hit_sea or hit_tr):
                continue

        # 精确构造断点续播信息（若传入 member_key 则严格按该成员的独立进度返回）
        resume_info: dict[str, Any] | None = None
        mp = member_progress.get(sid)
        if mk:
            last_tid = mp.get("track_id") if mp else None
            last_aid = mp.get("album_id") if mp else None
            saved_pos = float(mp.get("position_sec") or 0.0) if mp else 0.0
            saved_at = mp.get("updated_at") if mp else None
        else:
            last_tid = s.get("last_track_id")
            last_aid = s.get("last_album_id")
            saved_pos = float(s.get("last_position_sec") or 0.0)
            saved_at = s.get("last_played_at")

        if last_tid and int(last_tid) in tracks_by_id:
            tr = tracks_by_id[int(last_tid)]
            alb = albums_by_id.get(int(tr["album_id"])) or (albums_by_id.get(int(last_aid)) if last_aid else None)
            if alb:
                resume_info = {
                    "album_id": alb["id"],
                    "season_num": int(alb.get("season_num") or 1),
                    "season_label": alb["season_label"],
                    "track_id": tr["id"],
                    "track_title": tr["title"],
                    "episode_num": int(tr.get("episode_num") or 1),
                    "position_sec": saved_pos if saved_pos > 0 else float(tr.get("last_position_sec") or 0.0),
                    "last_played_at": saved_at or tr.get("last_played_at"),
                }
        elif not mk and seasons:
            # 兜底看季里的全局播放记录
            for sea in seasons:
                if sea.get("last_track_id") and int(sea["last_track_id"]) in tracks_by_id:
                    tr = tracks_by_id[int(sea["last_track_id"])]
                    resume_info = {
                        "album_id": sea["id"],
                        "season_num": int(sea.get("season_num") or 1),
                        "season_label": sea["season_label"],
                        "track_id": tr["id"],
                        "track_title": tr["title"],
                        "episode_num": int(tr.get("episode_num") or 1),
                        "position_sec": float(sea.get("last_position_sec") or 0.0),
                        "last_played_at": tr.get("last_played_at"),
                    }
                    break

        s["seasons"] = seasons
        s["season_count"] = len(seasons)
        s["total_tracks"] = len(all_tracks)
        s["completed_tracks"] = sum(1 for t in all_tracks if int(t.get("completed") or 0) == 1)
        s["resume_info"] = resume_info
        out.append(s)

    return out


@router.post("/series")
async def create_series(
    req: SeriesCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="合集/系列名称不能为空")
    level_code = req.level_code.strip()
    if req.channel == "english" and level_code not in ("L1", "L2", "L3", "L4", "L5"):
        level_code = "L1"
    emoji = req.cover_emoji.strip() or _default_channel_emoji(req.channel)
    ts = now_iso()

    if req.auto_create_first_season:
        series, first_album = await ensure_series_and_season(
            channel=req.channel,
            series_title=title,
            season_num=1,
            season_label=req.first_season_label.strip() or _default_season_label(req.channel, 1),
            level_code=level_code,
            cover_emoji=emoji,
            author=req.author.strip(),
            description=req.description.strip(),
        )
        first_album["tracks"] = []
        first_album["track_count"] = 0
        series["seasons"] = [first_album]
        series["season_count"] = 1
        series["total_tracks"] = 0
        series["completed_tracks"] = 0
        series["resume_info"] = None
        return series

    async with get_db() as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO media_series (title, channel, level_code, cover_emoji, author, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, req.channel, level_code, emoji, req.author.strip(), req.description.strip(), ts),
            )
            await conn.commit()
            cur2 = await conn.execute("SELECT * FROM media_series WHERE id = ?", (cur.lastrowid,))
            s = dict(await cur2.fetchone())
            s["seasons"] = []
            s["season_count"] = 0
            s["total_tracks"] = 0
            s["completed_tracks"] = 0
            s["resume_info"] = None
            return s
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"创建系列失败（可能已存在同名合集）: {exc}")


@router.patch("/series/{series_id}")
async def update_series(
    series_id: int,
    req: SeriesPatch,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM media_series WHERE id = ?", (series_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="系列不存在")
        data = dict(row)
        for k, v in req.model_dump(exclude_none=True).items():
            data[k] = v.strip() if isinstance(v, str) else v
        await conn.execute(
            """
            UPDATE media_series
            SET title = ?, channel = ?, level_code = ?, cover_emoji = ?, author = ?, description = ?
            WHERE id = ?
            """,
            (
                data["title"],
                data["channel"],
                data.get("level_code", ""),
                data.get("cover_emoji", ""),
                data.get("author", ""),
                data.get("description", ""),
                series_id,
            ),
        )
        # 同步频道与英语级别至下属季/专辑
        eng_stage = ENGLISH_LEVEL_TO_STAGE.get(data.get("level_code", ""), "Pre_A1") if data["channel"] == "english" else None
        if eng_stage:
            await conn.execute(
                "UPDATE media_albums SET category = ?, english_level = ? WHERE series_id = ?",
                (data["channel"], eng_stage, series_id),
            )
        else:
            await conn.execute(
                "UPDATE media_albums SET category = ? WHERE series_id = ?",
                (data["channel"], series_id),
            )
        await conn.commit()
    return data


@router.delete("/series/{series_id}")
async def delete_series(
    series_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """删除一级系列及其下属季/专辑和本地音频文件。"""
    files: list[str] = []
    async with get_db() as conn:
        cur_a = await conn.execute("SELECT id FROM media_albums WHERE series_id = ?", (series_id,))
        aids = [int(r["id"]) for r in await cur_a.fetchall()]
        if aids:
            ph = ",".join("?" for _ in aids)
            cur_f = await conn.execute(f"SELECT file_path FROM media_tracks WHERE album_id IN ({ph})", aids)
            files = [r["file_path"] for r in await cur_f.fetchall() if r["file_path"]]
            await conn.execute(f"DELETE FROM media_albums WHERE id IN ({ph})", aids)
        await conn.execute("DELETE FROM media_series WHERE id = ?", (series_id,))
        await conn.commit()
    for fp in files:
        Path(fp).unlink(missing_ok=True)
    return {"status": "deleted"}


@router.post("/series/{series_id}/seasons")
async def create_season_under_series(
    series_id: int,
    req: SeasonCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """在指定系列下新增一季 / 一张专辑 / 一个英语单元（自动递增季号）。"""
    async with get_db() as conn:
        cur_s = await conn.execute("SELECT * FROM media_series WHERE id = ?", (series_id,))
        srow = await cur_s.fetchone()
        if not srow:
            raise HTTPException(status_code=404, detail="所属系列不存在")
        series = dict(srow)
        cur_max = await conn.execute(
            "SELECT COALESCE(MAX(season_num), 0) FROM media_albums WHERE series_id = ?",
            (series_id,),
        )
        next_num = int((await cur_max.fetchone())[0] or 0) + 1
        snum = int(req.season_num) if req.season_num and req.season_num > 0 else next_num
        slabel = req.season_label.strip() or _default_season_label(series["channel"], snum)
        base_title = req.title.strip() or f"{series['title']} · {slabel}"
        final_title = base_title
        suffix = 2
        while True:
            chk = await conn.execute("SELECT id FROM media_albums WHERE title = ?", (final_title,))
            if not await chk.fetchone():
                break
            final_title = f"{base_title} ({suffix})"
            suffix += 1

        eng_stage = ENGLISH_LEVEL_TO_STAGE.get(series.get("level_code") or "L1", "Pre_A1") if series["channel"] == "english" else "Pre_A1"
        cur_ins = await conn.execute(
            """
            INSERT INTO media_albums
            (series_id, season_num, season_label, title, category, sub_tag, age_stage, english_level,
             play_mode, cover_emoji, author, language, is_inbox, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'S6_ALL', ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                series_id,
                snum,
                slabel,
                final_title,
                series["channel"],
                series.get("level_code") or slabel,
                eng_stage,
                req.play_mode,
                series.get("cover_emoji") or _default_channel_emoji(series["channel"]),
                series.get("author") or "",
                "en" if series["channel"] == "english" else "zh",
                req.description.strip(),
                now_iso(),
            ),
        )
        await conn.commit()
        cur2 = await conn.execute("SELECT * FROM media_albums WHERE id = ?", (cur_ins.lastrowid,))
        alb = dict(await cur2.fetchone())
        alb["tracks"] = []
        alb["track_count"] = 0
        return alb


# -------------------- 专辑与曲目 CRUD --------------------


@router.get("/albums")
async def list_albums(
    category: str | None = Query(default=None),
    sub_tag: str | None = Query(default=None),
    age_stage: str | None = Query(default=None),
    q: str | None = Query(default=None),
    only_inbox: bool = Query(default=False),
    exclude_inbox: bool = Query(default=False),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    async with get_db() as conn:
        clauses = []
        params: list[Any] = []
        if category and category != "all":
            clauses.append("category = ?")
            params.append(category)
        if sub_tag and sub_tag != "all":
            clauses.append("sub_tag = ?")
            params.append(sub_tag)
        if age_stage and age_stage != "all":
            clauses.append("age_stage = ?")
            params.append(age_stage)
        if only_inbox:
            clauses.append("is_inbox = 1")
        elif exclude_inbox:
            clauses.append("is_inbox = 0")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = await conn.execute(f"SELECT * FROM media_albums {where_sql} ORDER BY is_inbox ASC, id DESC", params)
        albums = [dict(r) for r in await cur.fetchall()]
        cur = await conn.execute("SELECT * FROM media_tracks ORDER BY album_id ASC, episode_num ASC, id ASC")
        tracks_raw = [dict(r) for r in await cur.fetchall()]

    grouped: dict[int, list[dict[str, Any]]] = {}
    kw = (q or "").strip().lower()
    for t in tracks_raw:
        try:
            t["vocab"] = json.loads(t.get("vocab_json") or "[]")
        except Exception:
            t["vocab"] = []
        t["stream_url"] = f"/api/media/tracks/{t['id']}/stream"
        if kw and kw not in t["title"].lower():
            continue
        grouped.setdefault(t["album_id"], []).append(t)

    result = []
    for alb in albums:
        alb_tracks = grouped.get(alb["id"], [])
        if kw and not alb_tracks and kw not in alb["title"].lower():
            continue
        alb["tracks"] = alb_tracks if not kw or alb_tracks else []
        result.append(alb)
    return result


@router.post("/albums")
async def create_album(
    req: AlbumCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="专辑名称不能为空")
    series_id = req.series_id
    snum = max(1, int(req.season_num or 1))
    slabel = req.season_label.strip() or _default_season_label(req.category, snum)
    ts = now_iso()
    async with get_db() as conn:
        try:
            if not series_id and not req.is_inbox:
                level_code = (
                    ENGLISH_STAGE_TO_LEVEL.get(req.english_level, "L1")
                    if req.category == "english"
                    else req.sub_tag.strip()
                )
                cur_s = await conn.execute(
                    "SELECT id FROM media_series WHERE channel = ? AND title = ?",
                    (req.category, req.title.strip()),
                )
                srow = await cur_s.fetchone()
                if srow:
                    series_id = int(srow["id"])
                else:
                    cur_si = await conn.execute(
                        """
                        INSERT INTO media_series (title, channel, level_code, cover_emoji, author, description, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            req.title.strip(),
                            req.category,
                            level_code,
                            req.cover_emoji.strip() or _default_channel_emoji(req.category),
                            req.author.strip(),
                            req.description.strip(),
                            ts,
                        ),
                    )
                    series_id = int(cur_si.lastrowid)

            cur = await conn.execute(
                """
                INSERT INTO media_albums
                (series_id, season_num, season_label, title, category, sub_tag, age_stage, english_level, play_mode, cover_emoji, author, language, is_inbox, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    series_id,
                    snum,
                    slabel,
                    req.title.strip(),
                    req.category,
                    req.sub_tag.strip(),
                    req.age_stage,
                    req.english_level,
                    req.play_mode,
                    req.cover_emoji.strip(),
                    req.author.strip(),
                    req.language.strip() or "zh",
                    1 if req.is_inbox else 0,
                    req.description.strip(),
                    ts,
                ),
            )
            await conn.commit()
            cur2 = await conn.execute("SELECT * FROM media_albums WHERE id = ?", (cur.lastrowid,))
            return dict(await cur2.fetchone())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"创建专辑失败: {exc}")


@router.patch("/albums/{album_id}")
async def update_album(
    album_id: int,
    req: AlbumPatch,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM media_albums WHERE id = ?", (album_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="专辑不存在")
        data = dict(row)
        for k, v in req.model_dump(exclude_none=True).items():
            if k == "is_inbox":
                data[k] = 1 if v else 0
            else:
                data[k] = v
        await conn.execute(
            """
            UPDATE media_albums
            SET series_id = ?, season_num = ?, season_label = ?, title = ?, category = ?, sub_tag = ?, age_stage = ?, english_level = ?,
                play_mode = ?, cover_emoji = ?, author = ?, language = ?, is_inbox = ?, description = ?
            WHERE id = ?
            """,
            (
                data.get("series_id"),
                int(data.get("season_num") or 1),
                data.get("season_label", ""),
                data["title"],
                data["category"],
                data.get("sub_tag", ""),
                data["age_stage"],
                data["english_level"],
                data["play_mode"],
                data.get("cover_emoji", ""),
                data.get("author", ""),
                data.get("language", "zh"),
                int(data.get("is_inbox", 0)),
                data["description"],
                album_id,
            ),
        )
        await conn.commit()
    return data


@router.delete("/albums/{album_id}")
async def delete_album(
    album_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """删除专辑并同步清理磁盘上的音频文件。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT file_path FROM media_tracks WHERE album_id = ?", (album_id,))
        files = [r["file_path"] for r in await cur.fetchall()]
        await conn.execute("DELETE FROM media_albums WHERE id = ?", (album_id,))
        await conn.commit()
    for fp in files:
        if fp:
            Path(fp).unlink(missing_ok=True)
    return {"status": "deleted"}


@router.post("/albums/{album_id}/tracks/from-text")
async def create_track_from_text_endpoint(
    album_id: int,
    req: TextTrackCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.title.strip() or not req.text_content.strip():
        raise HTTPException(status_code=400, detail="单集标题与正文内容不能为空")
    async with get_db() as conn:
        cur = await conn.execute("SELECT id, language FROM media_albums WHERE id = ?", (album_id,))
        alb = await cur.fetchone()
        if not alb:
            raise HTTPException(status_code=404, detail="专辑不存在")
    return await add_track_from_text(
        album_id=album_id,
        title=req.title,
        text_content=req.text_content,
        language=req.language or alb["language"] or "zh",
        vocab_json=json.dumps(req.vocab, ensure_ascii=False),
        objective=req.objective,
    )


@router.patch("/tracks/{track_id}")
async def update_track(
    track_id: int,
    req: TrackPatch,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM media_tracks WHERE id = ?", (track_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="单曲不存在")
        data = dict(row)
        target_album_id = data["album_id"]
        ep = data["episode_num"]

        if req.album_id is not None and req.album_id != data["album_id"]:
            chk_alb = await conn.execute("SELECT id FROM media_albums WHERE id = ?", (req.album_id,))
            if not await chk_alb.fetchone():
                raise HTTPException(status_code=404, detail="目标专辑不存在")
            target_album_id = req.album_id
            cur_max = await conn.execute("SELECT COALESCE(MAX(episode_num), 0) FROM media_tracks WHERE album_id = ?", (target_album_id,))
            ep = int((await cur_max.fetchone())[0] or 0) + 1

        if req.episode_num is not None:
            ep = int(req.episode_num)
        title = req.title.strip() if req.title is not None else data["title"]
        text_content = req.text_content if req.text_content is not None else data.get("text_content", "")
        completed = (1 if req.completed else 0) if req.completed is not None else int(data.get("completed", 0))

        await conn.execute(
            """
            UPDATE media_tracks
            SET album_id = ?, title = ?, episode_num = ?, text_content = ?, completed = ?
            WHERE id = ?
            """,
            (target_album_id, title, ep, text_content, completed, track_id),
        )
        await conn.commit()
        cur2 = await conn.execute("SELECT * FROM media_tracks WHERE id = ?", (track_id,))
        res = dict(await cur2.fetchone())
        res["stream_url"] = f"/api/media/tracks/{track_id}/stream"
        return res


@router.delete("/tracks/{track_id}")
async def delete_track(
    track_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT file_path FROM media_tracks WHERE id = ?", (track_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="单曲不存在")
        fp = row["file_path"]
        await conn.execute("DELETE FROM media_tracks WHERE id = ?", (track_id,))
        await conn.commit()
    if fp:
        Path(fp).unlink(missing_ok=True)
    return {"status": "deleted"}


@router.post("/albums/{album_id}/progress")
async def save_album_progress(
    album_id: int,
    req: ProgressUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    mk = req.member_key.strip() or f"user:{user['id']}"
    res = await update_playback_progress(
        album_id=album_id,
        track_id=req.track_id,
        position_sec=req.position_sec,
        increment_play=False,
        member_key=mk,
    )
    return {"status": "saved", **res}


@router.post("/tracks/{track_id}/cast")
async def cast_track_to_speaker(
    track_id: int,
    req: CastRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM media_tracks WHERE id = ?", (track_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="音频条目不存在")
        track = dict(row)
        track["media_kind"] = "track"

    await update_playback_progress(album_id=int(track["album_id"]), track_id=track_id, position_sec=0.0, increment_play=True)
    await device_manager.cast_track_to_device(req.device_id, track)
    return {
        "status": "casted",
        "device_id": req.device_id,
        "track": track,
        "track_url": f"/api/media/tracks/{track_id}/stream",
    }


@router.get("/tracks/{track_id}/stream")
async def stream_track(track_id: int, request: Request):
    """支持标准 HTTP Range（206 Partial Content）的高音质音频流接口，若文本单集音频未生成则即时按需合成。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM media_tracks WHERE id = ?", (track_id,))
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="音频条目不存在")

    file_path = Path(row["file_path"]) if row["file_path"] else Path("__missing__")
    if not row["file_path"] or not file_path.exists():
        if row["text_content"]:
            file_path, _ = await synthesize_track_audio_if_missing(track_id)
        else:
            raise HTTPException(status_code=404, detail="音频文件尚未就绪")

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path=str(file_path), media_type="audio/mpeg", headers={"Accept-Ranges": "bytes"})

    match = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not match:
        raise HTTPException(status_code=416, detail="无效 Range 头")

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        raise HTTPException(status_code=416, detail="Range 越界")

    chunk_len = end - start + 1

    def iter_bytes():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = chunk_len
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        iter_bytes(),
        status_code=206,
        media_type="audio/mpeg",
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_len),
        },
    )


# -------------------- 在线即播 + 自动缓存到本地 --------------------


@router.post("/play-and-cache")
async def play_and_cache_online(
    req: PlayAndCacheRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请提供合法的 http/https 音频地址")
    track = await resolve_or_prepare_online_stream(
        title=req.title.strip() or "在线音频",
        url=req.url.strip(),
        category=req.category,
        album_id=req.album_id,
        source_id=req.source_id,
        external_guid=req.external_guid,
        age_stage=req.age_stage,
        online_stream_id=req.online_stream_id,
    )
    if req.online_stream_id:
        async with get_db() as conn:
            await conn.execute(
                "UPDATE online_streams SET play_count = play_count + 1 WHERE id = ?",
                (req.online_stream_id,),
            )
            await conn.commit()

    if req.device_id:
        await device_manager.cast_track_to_device(req.device_id, track)

    return {
        "track": track,
        "stream_url": track["stream_url"],
        "is_cached": bool(track.get("is_cached", False)),
        "caching": bool(track.get("caching", False)),
    }


@router.get("/live-stream/{token}")
async def stream_online_live(token: str):
    """实时转码推流在线音频（若后台已缓存落盘则自动切换本地 FileResponse）。"""
    session = LIVE_STREAM_SESSIONS.get(token)
    if not session:
        raise HTTPException(status_code=404, detail="实时播放会话不存在或已过期")

    cached_tid = session.get("cached_track_id")
    if cached_tid:
        async with get_db() as conn:
            cur = await conn.execute("SELECT file_path FROM media_tracks WHERE id = ?", (cached_tid,))
            row = await cur.fetchone()
        if row and row["file_path"] and Path(row["file_path"]).exists():
            return FileResponse(path=str(row["file_path"]), media_type="audio/mpeg", headers={"Accept-Ranges": "bytes"})

    url = str(session["url"])
    settings = load_settings()

    if _looks_like_direct_audio_url(url):
        ff = await asyncio.create_subprocess_exec(
            settings.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            url,
            "-vn",
            "-acodec",
            "libmp3lame",
            "-ab",
            "128k",
            "-f",
            "mp3",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _iter_direct():
            try:
                assert ff.stdout is not None
                while True:
                    chunk = await ff.stdout.read(32768)
                    if not chunk:
                        break
                    yield chunk
            finally:
                with contextlib.suppress(Exception):
                    ff.kill()
                    await ff.wait()

        return StreamingResponse(_iter_direct(), media_type="audio/mpeg")

    # 网页地址（如 Bilibili/YouTube）通过 yt-dlp | ffmpeg 边拉边播
    yt_proc = await asyncio.create_subprocess_exec(
        settings.yt_dlp_bin,
        "--no-warnings",
        "--no-playlist",
        "-f",
        "ba/best",
        "-o",
        "-",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    ff_proc = await asyncio.create_subprocess_exec(
        settings.ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-vn",
        "-acodec",
        "libmp3lame",
        "-ab",
        "128k",
        "-f",
        "mp3",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _pump_yt_to_ff():
        try:
            assert yt_proc.stdout is not None and ff_proc.stdin is not None
            while True:
                buf = await yt_proc.stdout.read(65536)
                if not buf:
                    break
                ff_proc.stdin.write(buf)
                await ff_proc.stdin.drain()
        except Exception:
            pass
        finally:
            with contextlib.suppress(Exception):
                if ff_proc.stdin:
                    ff_proc.stdin.close()

    async def _iter_piped():
        pump_task = asyncio.create_task(_pump_yt_to_ff())
        try:
            assert ff_proc.stdout is not None
            while True:
                chunk = await ff_proc.stdout.read(32768)
                if not chunk:
                    break
                yield chunk
        finally:
            pump_task.cancel()
            for p in (yt_proc, ff_proc):
                with contextlib.suppress(Exception):
                    p.kill()
                    await p.wait()

    return StreamingResponse(_iter_piped(), media_type="audio/mpeg")


# -------------------- 本地目录挂载扫描 & 本地文件总览 --------------------


@router.get("/local-folders")
async def list_local_folders(_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    await ensure_default_local_folder()
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM local_folders ORDER BY id ASC")
        folders = [dict(r) for r in await cur.fetchall()]

    suggested: list[dict[str, str]] = []
    for candidate_name, p in [
        ("Mac 本机音乐目录", Path.home() / "Music"),
        ("Mac 下载目录", Path.home() / "Downloads"),
    ]:
        if p.exists() and p.is_dir():
            suggested.append({"name": candidate_name, "path": str(p)})
    return {"folders": folders, "suggested_paths": suggested}


@router.post("/local-folders")
async def create_local_folder(
    req: LocalFolderCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    resolved = Path(req.folder_path.strip()).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"磁盘目录不存在或不可访问：{resolved}")
    ts = now_iso()
    async with get_db() as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO local_folders (name, folder_path, media_type, age_stage, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (req.name.strip() or resolved.name, str(resolved), req.media_type, req.age_stage, ts),
            )
            await conn.commit()
            cur2 = await conn.execute("SELECT * FROM local_folders WHERE id = ?", (cur.lastrowid,))
            return dict(await cur2.fetchone())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"添加目录失败（可能已存在）: {exc}")


@router.delete("/local-folders/{folder_id}")
async def delete_local_folder(
    folder_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        await conn.execute("DELETE FROM local_folders WHERE id = ?", (folder_id,))
        await conn.commit()
    return {"status": "deleted"}


@router.post("/local-folders/{folder_id}/scan")
async def scan_local_folder_endpoint(
    folder_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await scan_local_folder(folder_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/local-files")
async def list_local_files(
    kind: str = Query(default="all"),
    q: str = Query(default=""),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """聚合返回本地磁盘全部已入库音轨（含音乐、故事、播客及有声绘本/图书章节）。"""
    kw = q.strip().lower()
    items: list[dict[str, Any]] = []
    async with get_db() as conn:
        if kind != "book":
            cur = await conn.execute(
                """
                SELECT t.id, t.album_id, t.title, t.duration_sec, t.file_path, t.source_url, t.play_count, t.created_at,
                       a.title AS album_title, a.category AS album_category, a.age_stage
                FROM media_tracks t
                JOIN media_albums a ON t.album_id = a.id
                ORDER BY t.id DESC
                """
            )
            for r in await cur.fetchall():
                if not r["file_path"] or not Path(r["file_path"]).exists():
                    continue
                if kind not in ("all", "") and r["album_category"] != kind:
                    continue
                if kw and kw not in r["title"].lower() and kw not in r["album_title"].lower():
                    continue
                items.append(
                    {
                        "uid": f"track_{r['id']}",
                        "id": r["id"],
                        "kind": "track",
                        "sub_category": r["album_category"],
                        "title": r["title"],
                        "container_id": r["album_id"],
                        "container_title": r["album_title"],
                        "age_stage": r["age_stage"],
                        "duration_sec": r["duration_sec"],
                        "play_count": r["play_count"],
                        "file_path": r["file_path"],
                        "stream_url": f"/api/media/tracks/{r['id']}/stream",
                        "created_at": r["created_at"],
                    }
                )

        if kind in ("all", "", "book"):
            cur_b = await conn.execute(
                """
                SELECT c.id, c.book_id, c.title, c.duration_sec, c.file_path, c.play_count, c.created_at,
                       b.title AS book_title, b.category AS book_category, b.age_stage
                FROM book_chapters c
                JOIN books b ON c.book_id = b.id
                ORDER BY c.id DESC
                """
            )
            for r in await cur_b.fetchall():
                if not r["file_path"] or not Path(r["file_path"]).exists():
                    continue
                if kw and kw not in r["title"].lower() and kw not in r["book_title"].lower():
                    continue
                items.append(
                    {
                        "uid": f"chapter_{r['id']}",
                        "id": r["id"],
                        "kind": "chapter",
                        "sub_category": "book",
                        "title": r["title"],
                        "container_id": r["book_id"],
                        "container_title": f"《{r['book_title']}》",
                        "age_stage": r["age_stage"],
                        "duration_sec": r["duration_sec"],
                        "play_count": r["play_count"],
                        "file_path": r["file_path"],
                        "stream_url": f"/api/books/chapters/{r['id']}/stream",
                        "created_at": r["created_at"],
                    }
                )
    return items


# -------------------- 常驻在线音乐 / 电台源 --------------------


@router.get("/online-streams")
async def list_online_streams(_user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM online_streams ORDER BY id DESC")
        rows = []
        for r in await cur.fetchall():
            d = dict(r)
            d["cached"] = False
            if d.get("cached_track_id"):
                c2 = await conn.execute("SELECT file_path FROM media_tracks WHERE id = ?", (d["cached_track_id"],))
                t2 = await c2.fetchone()
                d["cached"] = bool(t2 and t2["file_path"] and Path(t2["file_path"]).exists())
            rows.append(d)
        return rows


@router.post("/online-streams")
async def create_online_stream(
    req: OnlineStreamCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.title.strip() or not req.url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请填写标题与合法 http/https 地址")
    async with get_db() as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO online_streams (title, url, stream_kind, category, age_stage, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (req.title.strip(), req.url.strip(), req.stream_kind, req.category, req.age_stage, req.description.strip(), now_iso()),
            )
            await conn.commit()
            cur2 = await conn.execute("SELECT * FROM online_streams WHERE id = ?", (cur.lastrowid,))
            return dict(await cur2.fetchone())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"保存失败（可能已存在相同URL）: {exc}")


@router.delete("/online-streams/{stream_id}")
async def delete_online_stream(
    stream_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        await conn.execute("DELETE FROM online_streams WHERE id = ?", (stream_id,))
        await conn.commit()
    return {"status": "deleted"}


# -------------------- 在线关键词搜歌 & 抓取队列 --------------------


@router.get("/search-online")
async def search_online(
    q: str = Query(..., min_length=1),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    try:
        return await search_online_audio(q, limit=8)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/jobs")
async def list_jobs(_user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT j.*, a.title AS album_title
            FROM download_jobs j
            LEFT JOIN media_albums a ON j.target_album_id = a.id
            ORDER BY j.id DESC
            LIMIT 25
            """
        )
        return [dict(r) for r in await cur.fetchall()]


@router.post("/collect/ytdlp")
async def collect_ytdlp(
    req: YtDlpCollectRequest,
    background_tasks: BackgroundTasks,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请输入合法的 http/https 链接")
    ts = now_iso()
    async with get_db() as conn:
        cur = await conn.execute(
            """
            INSERT INTO download_jobs (job_type, source_url, target_album_id, status, progress_text, created_at, updated_at)
            VALUES ('yt_dlp', ?, ?, 'pending', '排队等待 yt-dlp 解析...', ?, ?)
            """,
            (req.url.strip(), req.album_id, ts, ts),
        )
        job_id = int(cur.lastrowid)
        await conn.commit()

    background_tasks.add_task(run_yt_dlp_job, job_id, req.url.strip(), req.album_id, req.max_items)
    return {"job_id": job_id, "status": "pending"}


@router.post("/collect/rss")
async def collect_rss(
    req: RssCollectRequest,
    background_tasks: BackgroundTasks,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.rss_url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请输入合法的 RSS 订阅链接")
    ts = now_iso()
    async with get_db() as conn:
        cur = await conn.execute(
            """
            INSERT INTO download_jobs (job_type, source_url, target_album_id, status, progress_text, created_at, updated_at)
            VALUES ('rss', ?, ?, 'pending', '排队等待 RSS 抓取...', ?, ?)
            """,
            (req.rss_url.strip(), req.album_id, ts, ts),
        )
        job_id = int(cur.lastrowid)
        await conn.commit()

    background_tasks.add_task(run_rss_job, job_id, req.rss_url.strip(), req.album_id, req.limit)
    return {"job_id": job_id, "status": "pending"}


@router.post("/collect/ai-collect")
async def collect_with_ai_classification(
    req: AiCollectRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """一键全网采集并由 AI 自动分类到「系列 → 季/专辑 → 单集」，完成后音箱播报+网页通知。"""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="请输入要采集的内容名称，如「汪汪队第2季」或「周杰伦」")
    try:
        return await enqueue_ai_collect(
            query=req.query.strip(),
            channel_hint=req.channel_hint,
            target_series_id=req.series_id,
            target_album_id=req.album_id,
            max_items=req.max_items,
            device_id=req.device_id.strip(),
            notify_speaker=req.notify_speaker,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/collect/upload")
async def collect_upload(
    album_id: int = Form(...),
    file: UploadFile = File(...),
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    content = await file.read()
    if len(content) < 256:
        raise HTTPException(status_code=400, detail="上传音频为空或已损坏")
    return await ingest_uploaded_file(album_id, file.filename or "audio.mp3", content)


# -------------------- WebDAV / 网盘挂载与三级同步 --------------------


@router.get("/webdav-mounts")
async def list_webdav_mounts(_user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM webdav_mounts ORDER BY id DESC")
        rows = []
        for r in await cur.fetchall():
            d = dict(r)
            d["has_password"] = bool(d.get("password"))
            d["password"] = "******" if d.get("password") else ""
            rows.append(d)
        return rows


@router.post("/webdav-mounts/preview")
async def preview_webdav_mount_endpoint(
    req: WebDavPreviewRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.base_url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请输入合法的 http/https WebDAV 地址")
    try:
        items = await preview_webdav_directory(req.base_url, req.remote_path, req.username, req.password)
        return {"entries": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"连接 WebDAV 失败：{exc}")


@router.post("/webdav-mounts")
async def create_webdav_mount(
    req: WebDavMountCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.name.strip() or not req.base_url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请填写名称与合法的 WebDAV 地址")
    ts = now_iso()
    async with get_db() as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO webdav_mounts (name, base_url, username, password, remote_path, channel, level_code, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.name.strip(),
                    req.base_url.strip(),
                    req.username.strip(),
                    req.password,
                    req.remote_path.strip() or "/",
                    req.channel,
                    req.level_code.strip(),
                    ts,
                ),
            )
            await conn.commit()
            cur2 = await conn.execute("SELECT * FROM webdav_mounts WHERE id = ?", (cur.lastrowid,))
            d = dict(await cur2.fetchone())
            d["password"] = "******" if d.get("password") else ""
            return d
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"创建 WebDAV 挂载失败: {exc}")


@router.delete("/webdav-mounts/{mount_id}")
async def delete_webdav_mount(
    mount_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        await conn.execute("DELETE FROM webdav_mounts WHERE id = ?", (mount_id,))
        await conn.commit()
    return {"status": "deleted"}


@router.post("/webdav-mounts/{mount_id}/sync")
async def sync_webdav_mount_endpoint(
    mount_id: int,
    max_files: int = Query(default=80, ge=1, le=300),
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await sync_webdav_mount(mount_id, max_files=max_files)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"WebDAV 同步失败：{exc}")


# -------------------- 服务器磁盘空间与存储清理运维 --------------------


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


@router.get("/storage")
async def get_storage_overview(_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """返回云服务器磁盘剩余容量、音频库占用、各系列空间排行与缓存可清理量。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(str(DATA_DIR))
    tracks_bytes = _dir_size_bytes(MEDIA_TRACKS_DIR)
    raw_bytes = _dir_size_bytes(MEDIA_RAW_DIR)
    tts_bytes = _dir_size_bytes(TTS_CACHE_DIR)

    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT s.id AS series_id, s.title AS series_title, s.channel, s.cover_emoji,
                   t.id AS track_id, t.file_path, t.title AS track_title
            FROM media_series s
            LEFT JOIN media_albums a ON a.series_id = s.id
            LEFT JOIN media_tracks t ON t.album_id = a.id
            """
        )
        rows = [dict(r) for r in await cur.fetchall()]

    series_stats: dict[int, dict[str, Any]] = {}
    channel_bytes: dict[str, int] = {"story": 0, "music": 0, "english": 0, "podcast": 0}
    seen_titles: set[str] = set()
    duplicate_count = 0

    for r in rows:
        sid = int(r["series_id"])
        st = series_stats.setdefault(
            sid,
            {
                "series_id": sid,
                "title": r["series_title"],
                "channel": r["channel"],
                "cover_emoji": r.get("cover_emoji") or "",
                "track_count": 0,
                "bytes": 0,
            },
        )
        if r.get("track_id"):
            st["track_count"] += 1
            fp = Path(r["file_path"]) if r.get("file_path") else None
            sz = fp.stat().st_size if (fp and fp.exists()) else 0
            st["bytes"] += sz
            channel_bytes[r["channel"]] = channel_bytes.get(r["channel"], 0) + sz
            tkey = f"{sid}:{str(r.get('track_title') or '').strip().lower()}"
            if tkey in seen_titles:
                duplicate_count += 1
            seen_titles.add(tkey)

    series_ranked = sorted(series_stats.values(), key=lambda x: x["bytes"], reverse=True)
    for item in series_ranked:
        item["size_mb"] = round(item["bytes"] / (1024 * 1024), 2)

    return {
        "data_dir": str(DATA_DIR),
        "disk_total_gb": round(usage.total / (1024**3), 2),
        "disk_used_gb": round(usage.used / (1024**3), 2),
        "disk_free_gb": round(usage.free / (1024**3), 2),
        "disk_used_pct": round((usage.used / usage.total) * 100, 1) if usage.total else 0.0,
        "media_tracks_mb": round(tracks_bytes / (1024 * 1024), 2),
        "raw_cache_mb": round(raw_bytes / (1024 * 1024), 2),
        "tts_cache_mb": round(tts_bytes / (1024 * 1024), 2),
        "duplicate_track_count": duplicate_count,
        "channel_usage_mb": {k: round(v / (1024 * 1024), 2) for k, v in channel_bytes.items()},
        "series_usage": series_ranked[:50],
    }


@router.post("/storage/clean-cache")
async def clean_storage_caches(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """一键清理临时下载残留文件与超过 6 小时的 TTS 语音缓存，绝不删除任何已入库正式音频。"""
    freed = 0
    removed_files = 0
    cutoff = time.time() - 6 * 3600

    for root_dir, check_age in ((MEDIA_RAW_DIR, False), (TTS_CACHE_DIR, True)):
        if not root_dir.exists():
            continue
        for p in list(root_dir.rglob("*")):
            if not p.is_file():
                continue
            try:
                if check_age and p.stat().st_mtime > cutoff:
                    continue
                sz = p.stat().st_size
                p.unlink(missing_ok=True)
                freed += sz
                removed_files += 1
            except OSError:
                pass

    return {
        "status": "cleaned",
        "removed_files": removed_files,
        "freed_mb": round(freed / (1024 * 1024), 2),
    }

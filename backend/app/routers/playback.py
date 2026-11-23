"""Sonos / Connect 级跨房间音箱连播队列、睡眠定时与统一推送路由。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import get_db
from app.gateways.manager import device_manager

router = APIRouter(prefix="/api/playback", tags=["playback"])


class PushPlaybackRequest(BaseModel):
    device_ids: list[str]
    series_id: int | None = None
    album_id: int | None = None
    track_ids: list[int] | None = None
    start_index: int | None = None
    start_position_sec: float | None = None
    resume: bool = True
    loop_mode: Literal["sequential", "repeat_one", "shuffle"] = "sequential"
    sleep_minutes: int | None = None
    sleep_episodes: int | None = None


class RoomControlRequest(BaseModel):
    action: Literal["pause", "resume", "stop", "next", "prev", "jump", "replay", "seek_delta", "set_loop", "set_sleep"]
    index: int | None = None
    delta_sec: float | None = None
    loop_mode: Literal["sequential", "repeat_one", "shuffle"] | None = None
    sleep_minutes: int | None = None
    sleep_episodes: int | None = None


@router.get("/rooms")
async def list_playback_rooms(_user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    """返回全屋已绑定音箱及其当前实时播放队列/睡眠定时快照。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM devices WHERE paired = 1 ORDER BY online DESC, created_at DESC")
        devices = [dict(r) for r in await cur.fetchall()]
    return [device_manager.get_room_playback_snapshot(d) for d in devices]


@router.post("/push")
async def push_playback_to_rooms(
    req: PushPlaybackRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """将整张专辑或自选单集列表推送给一台或多台音箱连播。"""
    if not req.device_ids:
        raise HTTPException(status_code=400, detail="请至少选择一台目标音箱设备")

    tracks: list[dict[str, Any]] = []
    album_title = ""
    album_id = req.album_id
    series_id = req.series_id
    resolved_start_index = req.start_index if req.start_index is not None else 0
    resolved_start_pos = float(req.start_position_sec) if req.start_position_sec is not None else 0.0

    async with get_db() as conn:
        if req.series_id is not None and req.album_id is None and not req.track_ids:
            cur_s = await conn.execute("SELECT * FROM media_series WHERE id = ?", (req.series_id,))
            srow = await cur_s.fetchone()
            if not srow:
                raise HTTPException(status_code=404, detail="目标合集系列不存在")
            sdata = dict(srow)
            cur_seas = await conn.execute(
                "SELECT * FROM media_albums WHERE series_id = ? AND is_inbox = 0 ORDER BY season_num ASC, id ASC",
                (req.series_id,),
            )
            seasons = [dict(r) for r in await cur_seas.fetchall()]
            target_alb = None
            if req.resume and sdata.get("last_album_id"):
                target_alb = next((a for a in seasons if a["id"] == sdata["last_album_id"]), None)
            if not target_alb and seasons:
                # 选第一个有音轨的季
                for sea in seasons:
                    cnt = int((await (await conn.execute("SELECT COUNT(*) FROM media_tracks WHERE album_id = ?", (sea["id"],))).fetchone())[0] or 0)
                    if cnt > 0:
                        target_alb = sea
                        break
            if not target_alb:
                raise HTTPException(status_code=400, detail="该系列下暂无可播放单集")
            album_id = int(target_alb["id"])
            album_title = str(target_alb["title"])
            cur_t = await conn.execute(
                "SELECT * FROM media_tracks WHERE album_id = ? ORDER BY episode_num ASC, id ASC",
                (album_id,),
            )
            tracks = [dict(r) for r in await cur_t.fetchall()]
            if req.resume and req.start_index is None and sdata.get("last_track_id"):
                found_idx = next((i for i, tr in enumerate(tracks) if tr["id"] == sdata["last_track_id"]), -1)
                if found_idx >= 0:
                    resolved_start_index = found_idx
                    if req.start_position_sec is None:
                        resolved_start_pos = float(sdata.get("last_position_sec") or 0.0)
        elif req.album_id is not None:
            cur_a = await conn.execute("SELECT id, title, series_id, last_track_id, last_position_sec FROM media_albums WHERE id = ?", (req.album_id,))
            arow = await cur_a.fetchone()
            if not arow:
                raise HTTPException(status_code=404, detail="目标专辑不存在")
            album_title = arow["title"]
            if series_id is None and arow["series_id"]:
                series_id = int(arow["series_id"])
            cur_t = await conn.execute(
                "SELECT * FROM media_tracks WHERE album_id = ? ORDER BY episode_num ASC, id ASC",
                (req.album_id,),
            )
            tracks = [dict(r) for r in await cur_t.fetchall()]
            if req.resume and req.start_index is None and arow["last_track_id"]:
                found_idx = next((i for i, tr in enumerate(tracks) if tr["id"] == arow["last_track_id"]), -1)
                if found_idx >= 0:
                    resolved_start_index = found_idx
                    if req.start_position_sec is None:
                        resolved_start_pos = float(arow["last_position_sec"] or 0.0)
        elif req.track_ids:
            placeholders = ",".join("?" for _ in req.track_ids)
            cur_t = await conn.execute(
                f"""
                SELECT t.*, a.title AS album_title, a.series_id
                FROM media_tracks t
                LEFT JOIN media_albums a ON t.album_id = a.id
                WHERE t.id IN ({placeholders})
                """,
                req.track_ids,
            )
            by_id = {int(r["id"]): dict(r) for r in await cur_t.fetchall()}
            tracks = [by_id[tid] for tid in req.track_ids if tid in by_id]
            if tracks:
                album_title = str(tracks[0].get("album_title") or "")
                album_id = tracks[0].get("album_id")
                if series_id is None and tracks[0].get("series_id"):
                    series_id = int(tracks[0]["series_id"])

        if not tracks:
            raise HTTPException(status_code=400, detail="待推送的曲目列表为空")

        for tr in tracks:
            tr["media_kind"] = "track"
            tr["stream_url"] = f"/api/media/tracks/{tr['id']}/stream"

        placeholders_d = ",".join("?" for _ in req.device_ids)
        cur_d = await conn.execute(
            f"SELECT id FROM devices WHERE id IN ({placeholders_d}) AND paired = 1",
            req.device_ids,
        )
        valid_ids = {r["id"] for r in await cur_d.fetchall()}

    if not valid_ids:
        raise HTTPException(status_code=404, detail="未找到有效的已绑定音箱")

    snapshots = []
    for did in req.device_ids:
        if did not in valid_ids:
            continue
        snap = await device_manager.push_queue_to_device(
            device_id=did,
            tracks=tracks,
            album_id=album_id,
            album_title=album_title,
            start_index=resolved_start_index,
            loop_mode=req.loop_mode,
            sleep_minutes=req.sleep_minutes,
            sleep_episodes=req.sleep_episodes,
            series_id=series_id,
            start_position_sec=resolved_start_pos,
        )
        snapshots.append(snap)

    return {"status": "pushed", "rooms": snapshots}


@router.post("/rooms/{device_id}/control")
async def control_room_playback(
    device_id: str,
    req: RoomControlRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """控制单台音箱的队列暂停/继续/停止/上下集/跳集/循环模式/睡眠定时。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM devices WHERE id = ?", (device_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="音箱设备不存在")

    return await device_manager.control_device_queue(
        device_id=device_id,
        action=req.action,
        index=req.index,
        delta_sec=req.delta_sec,
        loop_mode=req.loop_mode,
        sleep_minutes=req.sleep_minutes,
        sleep_episodes=req.sleep_episodes,
    )

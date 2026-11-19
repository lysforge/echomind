"""每日定时播控与夜间睡眠免打扰路由（支持星期几多选、预设音量与有声书定时）。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import load_settings, save_settings
from app.db import get_db
from app.gateways.manager import device_manager
from app.services.brain import SafeMotionGuard, is_quiet_hours_active
from app.services.scheduler import scheduler_service

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


class ScheduleCreate(BaseModel):
    name: str
    cron_time: str
    days_of_week: str = "1,2,3,4,5,6,7"
    task_type: Literal["play_album", "play_book", "english_immersion", "bedtime_story", "quiet_mode"] = "play_album"
    target_device_id: str | None = None
    album_id: int | None = None
    book_id: int | None = None
    target_volume: int = 50
    max_episodes: int = 1
    fade_out: bool = False
    enabled: bool = True


class SchedulePut(BaseModel):
    name: str
    cron_time: str
    days_of_week: str = "1,2,3,4,5,6,7"
    task_type: Literal["play_album", "play_book", "english_immersion", "bedtime_story", "quiet_mode"] = "play_album"
    target_device_id: str | None = None
    album_id: int | None = None
    book_id: int | None = None
    target_volume: int = 50
    max_episodes: int = 1
    fade_out: bool = False
    enabled: bool = True


class SchedulePatch(BaseModel):
    enabled: bool | None = None
    cron_time: str | None = None
    days_of_week: str | None = None
    target_volume: int | None = None
    fade_out: bool | None = None


class QuietToggleRequest(BaseModel):
    active: bool


@router.get("")
async def list_schedules(_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    settings = load_settings()
    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT s.*, a.title AS album_title, b.title AS book_title, d.name AS device_name
            FROM schedules s
            LEFT JOIN media_albums a ON s.album_id = a.id
            LEFT JOIN books b ON s.book_id = b.id
            LEFT JOIN devices d ON s.target_device_id = d.id
            ORDER BY s.cron_time ASC
            """
        )
        rows = [dict(r) for r in await cur.fetchall()]
    return {
        "quiet_hours_active": is_quiet_hours_active(),
        "quiet_hours_start": settings.quiet_hours_start,
        "quiet_hours_end": settings.quiet_hours_end,
        "quiet_hours_force_active": settings.quiet_hours_force_active,
        "items": rows,
    }


@router.post("")
async def create_schedule(
    req: ScheduleCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO schedules
                (name, cron_time, days_of_week, task_type, target_device_id, album_id, book_id, target_volume, max_episodes, fade_out, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.name.strip(),
                    req.cron_time,
                    req.days_of_week,
                    req.task_type,
                    req.target_device_id or None,
                    req.album_id,
                    req.book_id,
                    max(0, min(100, int(req.target_volume))),
                    req.max_episodes,
                    1 if req.fade_out else 0,
                    1 if req.enabled else 0,
                ),
            )
            await conn.commit()
            new_id = cur.lastrowid
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"创建课表失败: {exc}")
    await scheduler_service.reload_jobs()
    return {"id": new_id, "name": req.name}


@router.put("/{schedule_id}")
async def replace_schedule(
    schedule_id: int,
    req: SchedulePut,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM schedules WHERE id = ?", (schedule_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="定时任务不存在")
        await conn.execute(
            """
            UPDATE schedules
            SET name = ?, cron_time = ?, days_of_week = ?, task_type = ?, target_device_id = ?,
                album_id = ?, book_id = ?, target_volume = ?, max_episodes = ?, fade_out = ?, enabled = ?
            WHERE id = ?
            """,
            (
                req.name.strip(),
                req.cron_time,
                req.days_of_week,
                req.task_type,
                req.target_device_id or None,
                req.album_id,
                req.book_id,
                max(0, min(100, int(req.target_volume))),
                req.max_episodes,
                1 if req.fade_out else 0,
                1 if req.enabled else 0,
                schedule_id,
            ),
        )
        await conn.commit()
    await scheduler_service.reload_jobs()
    return {"id": schedule_id, "name": req.name.strip(), "days_of_week": req.days_of_week}


@router.patch("/{schedule_id}")
async def patch_schedule(
    schedule_id: int,
    req: SchedulePatch,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="定时任务不存在")
        enabled = int(req.enabled) if req.enabled is not None else row["enabled"]
        cron_time = req.cron_time if req.cron_time is not None else row["cron_time"]
        days = req.days_of_week if req.days_of_week is not None else row["days_of_week"]
        vol = max(0, min(100, int(req.target_volume))) if req.target_volume is not None else row["target_volume"]
        fade_out = int(req.fade_out) if req.fade_out is not None else row["fade_out"]
        await conn.execute(
            "UPDATE schedules SET enabled = ?, cron_time = ?, days_of_week = ?, target_volume = ?, fade_out = ? WHERE id = ?",
            (enabled, cron_time, days, vol, fade_out, schedule_id),
        )
        await conn.commit()
    await scheduler_service.reload_jobs()
    return {"id": schedule_id, "enabled": bool(enabled), "cron_time": cron_time}


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        await conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        await conn.commit()
    await scheduler_service.reload_jobs()
    return {"status": "deleted"}


@router.post("/{schedule_id}/trigger")
async def trigger_schedule(
    schedule_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await scheduler_service.execute_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/quiet-toggle")
async def toggle_quiet_hours(
    req: QuietToggleRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    settings = load_settings()
    settings.quiet_hours_force_active = req.active
    save_settings(settings)

    motion = SafeMotionGuard.sanitize("nod", 800, 25)
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM devices WHERE device_type = 'esp32_robot'")
        for r in await cur.fetchall():
            await device_manager.update_device_state(
                r["id"],
                playing_title="夜间免打扰锁止" if req.active else "待机中",
                motion_locked=req.active,
            )
    return {"quiet_hours_active": is_quiet_hours_active(), "motion_guard": motion}

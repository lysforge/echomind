"""每日定时播控与内容源自动同步调度引擎（APScheduler）。"""

from __future__ import annotations

from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import load_settings, save_settings
from app.db import get_db, now_iso
from app.gateways.manager import device_manager
from app.services.brain import SafeMotionGuard, pick_book_chapter, pick_track_for_album
from app.services.collector import sync_content_source
from app.services.tts_asr import synthesize_speech

_WEEK_MAP = {
    "1": "mon",
    "2": "tue",
    "3": "wed",
    "4": "thu",
    "5": "fri",
    "6": "sat",
    "7": "sun",
}


def _to_apscheduler_dow(days_csv: str) -> str:
    tokens = [t.strip() for t in (days_csv or "1,2,3,4,5,6,7").split(",") if t.strip()]
    mapped = [_WEEK_MAP[t] for t in tokens if t in _WEEK_MAP]
    return ",".join(mapped) if mapped else "*"


class DailySchedulerService:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.started = False

    async def start(self) -> None:
        if not self.started:
            self.scheduler.start()
            self.started = True
        await self.reload_jobs()

    def shutdown(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False

    async def reload_jobs(self) -> None:
        if not self.started:
            return
        self.scheduler.remove_all_jobs()

        async with get_db() as conn:
            cur = await conn.execute("SELECT * FROM schedules WHERE enabled = 1")
            rows = [dict(r) for r in await cur.fetchall()]
            cur_s = await conn.execute("SELECT * FROM content_sources WHERE auto_sync = 1")
            sources = [dict(r) for r in await cur_s.fetchall()]

        for row in rows:
            try:
                hh, mm = row["cron_time"].split(":")
                dow = _to_apscheduler_dow(row.get("days_of_week", "1,2,3,4,5,6,7"))
                trigger = CronTrigger(hour=int(hh), minute=int(mm), day_of_week=dow)
                self.scheduler.add_job(
                    self.execute_schedule,
                    trigger=trigger,
                    args=[row["id"]],
                    id=f"schedule_{row['id']}",
                    replace_existing=True,
                )
            except Exception:
                continue

        for src in sources:
            try:
                hours = max(1, int(src.get("sync_interval_hours") or 12))
                self.scheduler.add_job(
                    self._safe_sync_source,
                    trigger=IntervalTrigger(hours=hours),
                    args=[src["id"]],
                    id=f"source_sync_{src['id']}",
                    replace_existing=True,
                )
            except Exception:
                continue

    async def _safe_sync_source(self, source_id: int) -> None:
        try:
            await sync_content_source(source_id)
        except Exception:
            pass

    async def execute_schedule(self, schedule_id: int) -> dict[str, Any]:
        async with get_db() as conn:
            cur = await conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
            row = await cur.fetchone()
            if not row:
                raise ValueError("定时任务不存在")
            sched = dict(row)
            await conn.execute("UPDATE schedules SET last_run_at = ? WHERE id = ?", (now_iso(), schedule_id))
            await conn.commit()

        settings = load_settings()
        task_type = sched["task_type"]
        device_id = sched.get("target_device_id") or ""
        target_vol = int(sched.get("target_volume") or 50)

        if device_id:
            await device_manager.set_device_volume(device_id, target_vol)

        if task_type == "quiet_mode":
            settings.quiet_hours_force_active = True
            save_settings(settings)
            motion = SafeMotionGuard.sanitize("quiet_lock", force_quiet_check=True)
            msg = f"夜深啦，{settings.assistant_name}已进入夜间睡眠免打扰模式，大家晚安好梦～"
            tts_path = await synthesize_speech(msg, settings.tts_voice_child, settings.tts_rate_child)
            if device_id:
                await device_manager.push_announcement(device_id=device_id, text=msg, motion=motion, tts_path=tts_path)
            return {"status": "quiet_mode_activated", "message": msg, "motion": motion}

        track = None
        if task_type == "play_book" and sched.get("book_id"):
            async with get_db() as conn:
                cur = await conn.execute(
                    "SELECT * FROM book_chapters WHERE book_id = ? ORDER BY chapter_num ASC LIMIT 1",
                    (sched["book_id"],),
                )
                ch = await cur.fetchone()
                if ch:
                    track = dict(ch)
                    track["media_kind"] = "book_chapter"
                    track["stream_url"] = f"/api/books/chapters/{track['id']}/stream"
        elif sched.get("album_id"):
            async with get_db() as conn:
                cur = await conn.execute(
                    "SELECT * FROM media_tracks WHERE album_id = ? ORDER BY episode_num ASC LIMIT 1",
                    (sched["album_id"],),
                )
                hit = await cur.fetchone()
                if hit:
                    track = dict(hit)
                    track["media_kind"] = "track"
        else:
            cat_map = {"play_album": "music", "english_immersion": "english", "bedtime_story": "story"}
            if task_type == "play_book":
                track = await pick_book_chapter()
            else:
                track = await pick_track_for_album(category=cat_map.get(task_type, "story"), resume=True)

        fade_note = "（已启用最后 2 分钟睡前音量渐弱）" if sched.get("fade_out") else ""
        intro = (
            f"{sched['name']}时间到啦。"
            + (f"接下来播放《{track['title']}》。" if track else "")
            + fade_note
        )
        tts_path = await synthesize_speech(intro, settings.tts_voice_child, settings.tts_rate_child)
        if device_id:
            await device_manager.push_announcement(device_id=device_id, text=intro, tts_path=tts_path, track=track)
        return {"status": "triggered", "message": intro, "track": track}


scheduler_service = DailySchedulerService()

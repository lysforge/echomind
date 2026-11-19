"""概览统计、Onboarding 完成标记与互动入口路由。"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import get_lan_ip, load_settings, save_settings
from app.db import compute_age_label, compute_age_months, get_db, recommend_age_stage
from app.gateways.manager import device_manager
from app.services.brain import is_quiet_hours_active, process_user_turn
from app.services.tts_asr import synthesize_speech
from app.services.voiceprint import identify_speaker

router = APIRouter(prefix="/api", tags=["dashboard"])


class InteractRequest(BaseModel):
    text: str
    simulated_member_id: int | None = None
    device_id: str = ""


class OnboardingCompleteRequest(BaseModel):
    home_name: str | None = None
    assistant_name: str | None = None


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "EchoMind"}


@router.get("/dashboard")
async def get_dashboard(_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    settings = load_settings()
    today_prefix = date.today().isoformat()

    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT id, name, nickname, role, birth_date, age_stage, english_stage, tts_voice, tts_rate, voiceprint_samples, created_at FROM family_members ORDER BY id ASC"
        )
        members = []
        for r in await cur.fetchall():
            d = dict(r)
            d["age_months"] = compute_age_months(d.get("birth_date"))
            d["age_label"] = compute_age_label(d.get("birth_date"))
            d["recommended_age_stage"] = recommend_age_stage(d.get("birth_date"))
            d["has_voiceprint"] = int(d.get("voiceprint_samples") or 0) > 0
            members.append(d)

        cur = await conn.execute("SELECT * FROM devices WHERE paired = 1 ORDER BY created_at DESC")
        devices = [dict(r) for r in await cur.fetchall()]

        cur = await conn.execute("SELECT * FROM devices WHERE paired = 0 ORDER BY last_seen_at DESC")
        pending_devices = [dict(r) for r in await cur.fetchall()]

        cur = await conn.execute("SELECT * FROM english_items ORDER BY stage ASC, id ASC")
        english_items = [dict(r) for r in await cur.fetchall()]

        cur = await conn.execute(
            """
            SELECT a.*, COUNT(t.id) AS track_count
            FROM media_albums a
            LEFT JOIN media_tracks t ON a.id = t.album_id
            GROUP BY a.id
            ORDER BY a.id DESC
            """
        )
        albums = [dict(r) for r in await cur.fetchall()]

        cur = await conn.execute("SELECT COUNT(*) FROM books")
        book_count = int((await cur.fetchone())[0] or 0)

        cur = await conn.execute("SELECT COUNT(*) FROM content_sources")
        source_count = int((await cur.fetchone())[0] or 0)

        cur = await conn.execute("SELECT * FROM schedules ORDER BY cron_time ASC")
        schedules = [dict(r) for r in await cur.fetchall()]

        cur = await conn.execute("SELECT * FROM interaction_logs ORDER BY id DESC LIMIT 15")
        logs = [dict(r) for r in await cur.fetchall()]

        cur = await conn.execute(
            "SELECT COUNT(*) FROM interaction_logs WHERE created_at LIKE ?",
            (f"{today_prefix}%",),
        )
        today_interactions = int((await cur.fetchone())[0] or 0)

        cur = await conn.execute(
            "SELECT COUNT(*) FROM english_items WHERE last_played_at LIKE ?",
            (f"{today_prefix}%",),
        )
        today_english_count = int((await cur.fetchone())[0] or 0)

        cur = await conn.execute("SELECT SUM(play_count) FROM media_tracks")
        total_plays = int((await cur.fetchone())[0] or 0)

    return {
        "brand": "EchoMind（声忆·家庭智能音箱中枢）",
        "home_name": settings.home_name,
        "assistant_name": settings.assistant_name,
        "onboarding_completed": settings.onboarding_completed,
        "lan_ip": get_lan_ip(),
        "server_port": settings.server_port,
        "quiet_hours_active": is_quiet_hours_active(),
        "llm_configured": bool(settings.llm_api_key.strip() or settings.llm_provider == "ollama"),
        "members": members,
        "devices": devices,
        "pending_devices": pending_devices,
        "english_items": english_items,
        "albums": albums,
        "book_count": book_count,
        "source_count": source_count,
        "schedules": schedules,
        "recent_logs": logs,
        "growth_summary": {
            "today_interactions": today_interactions,
            "today_english_count": today_english_count,
            "total_media_plays": total_plays,
            "recent_moments": [
                {"user_text": l["user_text"], "assistant_text": l["assistant_text"], "time": l["created_at"]}
                for l in logs[:5]
            ],
        },
    }


@router.post("/onboarding/complete")
async def complete_onboarding(
    req: OnboardingCompleteRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    s = load_settings()
    if req.home_name and req.home_name.strip():
        s.home_name = req.home_name.strip()
    if req.assistant_name and req.assistant_name.strip():
        s.assistant_name = req.assistant_name.strip()
    s.onboarding_completed = True
    save_settings(s)
    return {"onboarding_completed": True, "home_name": s.home_name, "assistant_name": s.assistant_name}


@router.post("/interact")
async def interact_http(
    req: InteractRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="输入内容不能为空")

    speaker = await identify_speaker(simulated_member_id=req.simulated_member_id)
    brain_resp = await process_user_turn(text, speaker, device_id=req.device_id or "web-console")
    tts_path = await synthesize_speech(brain_resp.reply_text, voice=speaker.tts_voice, rate=speaker.tts_rate)
    if brain_resp.play_track and req.device_id and not brain_resp.skip_device_push:
        q_list = brain_resp.queue_tracks or [brain_resp.play_track]
        idx = next((i for i, t in enumerate(q_list) if t.get("id") == brain_resp.play_track.get("id") and t.get("title") == brain_resp.play_track.get("title")), 0)
        await device_manager.push_queue_to_device(
            device_id=req.device_id,
            tracks=q_list,
            album_id=brain_resp.play_track.get("album_id"),
            album_title=str(brain_resp.play_track.get("album_title") or ""),
            start_index=idx,
        )
    track_url = None
    if brain_resp.play_track:
        track_url = brain_resp.play_track.get("stream_url") or f"/api/media/tracks/{brain_resp.play_track['id']}/stream"
    return {
        "user_text": text,
        "reply_text": brain_resp.reply_text,
        "motion": brain_resp.motion_command,
        "speaker": speaker.__dict__,
        "memory_scope_used": brain_resp.memory_scope_used,
        "used_llm": brain_resp.used_llm,
        "tts_url": f"/api/tts-cache/{tts_path.name}",
        "play_track": brain_resp.play_track,
        "queue_tracks": brain_resp.queue_tracks,
        "control_action": brain_resp.control_action,
        "track_url": track_url,
        "learned_item": brain_resp.learned_item,
    }

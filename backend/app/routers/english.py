"""全周期分级英语（Pre_A1 ~ B2+）系列课程、课时音频流与词句库路由。"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import load_settings
from app.db import get_db, now_iso
from app.gateways.manager import device_manager
from app.services.collector import sync_legacy_to_unified_albums
from app.services.english_courses import (
    generate_custom_english_course,
    get_course_detail,
    seed_builtin_english_courses,
    synthesize_lesson_audio,
)
from app.services.tts_asr import synthesize_speech, transcribe_audio

router = APIRouter(prefix="/api/english", tags=["english"])


class PracticeRequest(BaseModel):
    record_spoken: bool = False
    device_id: str = ""


class EnglishItemCreate(BaseModel):
    phrase: str
    zh_meaning: str
    stage: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS"] = "Pre_A1"
    category: Literal["daily", "animal", "nature", "science", "dialogue"] = "daily"
    audio_prompt: str


class EnglishItemPatch(BaseModel):
    phrase: str | None = None
    zh_meaning: str | None = None
    stage: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS"] | None = None
    category: Literal["daily", "animal", "nature", "science", "dialogue"] | None = None
    audio_prompt: str | None = None


class CourseGenerateRequest(BaseModel):
    topic: str
    stage: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS"] = "A1"


class LessonPlayRequest(BaseModel):
    device_id: str = ""
    mark_completed: bool = False


class LessonPatchRequest(BaseModel):
    completed: bool | None = None


class PronounceRequest(BaseModel):
    text: str
    rate: str = "-8%"
    device_id: str = ""


class CheckinRequest(BaseModel):
    track_id: int | None = None
    duration_min: float = 5.0
    spoken_score: int = 0
    note: str = ""
    member_key: str = ""


# -------------------- 结构化系列课程 (Courses & Lessons) --------------------


@router.get("/courses")
async def list_english_courses(
    stage: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    async with get_db() as conn:
        if stage and stage != "all":
            cur = await conn.execute(
                "SELECT * FROM english_courses WHERE stage = ? ORDER BY id ASC",
                (stage,),
            )
        else:
            cur = await conn.execute("SELECT * FROM english_courses ORDER BY stage ASC, id ASC")
        courses = [dict(r) for r in await cur.fetchall()]

        cur_l = await conn.execute(
            "SELECT * FROM english_lessons ORDER BY course_id ASC, lesson_num ASC, id ASC"
        )
        all_lessons = [dict(r) for r in await cur_l.fetchall()]

    grouped: dict[int, list[dict[str, Any]]] = {}
    for l in all_lessons:
        try:
            l["vocab"] = json.loads(l.get("vocab_json") or "[]")
        except Exception:
            l["vocab"] = []
        l["stream_url"] = f"/api/english/lessons/{l['id']}/stream"
        grouped.setdefault(int(l["course_id"]), []).append(l)

    for c in courses:
        ls = grouped.get(int(c["id"]), [])
        c["lessons"] = ls
        c["total_lessons"] = len(ls)
        c["completed_lessons"] = sum(1 for x in ls if int(x.get("completed") or 0) == 1)

    return courses


@router.post("/courses/seed-builtin")
async def seed_courses_endpoint(
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, int]:
    """幂等导入内置 6 套 24 节全阶英语系列课程（Pre-A1 -> B2+）并同步至统一分级媒体库。"""
    res = await seed_builtin_english_courses()
    await sync_legacy_to_unified_albums()
    return res


@router.post("/courses/generate")
async def generate_course_endpoint(
    req: CourseGenerateRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.topic.strip():
        raise HTTPException(status_code=400, detail="请输入感兴趣的课程主题")
    course = await generate_custom_english_course(req.topic.strip(), req.stage)
    await sync_legacy_to_unified_albums()
    return course


@router.post("/pronounce")
async def pronounce_english_word(
    req: PronounceRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """英语启蒙词卡/例句即时点读发音（可选同时推音箱跟读）。"""
    txt = req.text.strip()
    if not txt:
        raise HTTPException(status_code=400, detail="点读内容不能为空")
    tts_path = await synthesize_speech(txt, voice="en-US-AriaNeural", rate=req.rate or "-8%")
    if req.device_id.strip():
        await device_manager.push_announcement(req.device_id.strip(), txt, tts_path=tts_path)
    return {"text": txt, "tts_url": f"/api/tts-cache/{tts_path.name}"}


@router.post("/checkin")
async def record_english_checkin(
    req: CheckinRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """记录一次每日英语磨耳朵/跟读打卡，并同步标记对应课时完成。"""
    mk = req.member_key.strip() or f"user:{user['id']}"
    today = date.today().isoformat()
    ts = now_iso()
    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO study_checkins (member_key, checkin_date, track_id, duration_min, spoken_score, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (mk, today, req.track_id, max(0.5, float(req.duration_min or 5.0)), int(req.spoken_score or 0), req.note.strip(), ts),
        )
        if req.track_id:
            await conn.execute("UPDATE media_tracks SET completed = 1 WHERE id = ?", (req.track_id,))
        await conn.commit()
    return await get_english_checkin_stats(member_key=mk, user=user)


@router.get("/stats")
async def get_english_checkin_stats(
    member_key: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """返回英语启蒙连续打卡天数、累计磨耳朵分钟数与近 7 天打卡日历。"""
    mk = (member_key or "").strip() or f"user:{user['id']}"
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT checkin_date, COUNT(*) AS cnt, SUM(duration_min) AS mins, MAX(spoken_score) AS best_score FROM study_checkins WHERE member_key = ? GROUP BY checkin_date ORDER BY checkin_date DESC",
            (mk,),
        )
        by_date = {r["checkin_date"]: dict(r) for r in await cur.fetchall()}

    today = date.today()
    # 计算连续打卡天数（今天或昨天开始连续往前）
    streak = 0
    cursor = today if today.isoformat() in by_date else (today - timedelta(days=1))
    while cursor.isoformat() in by_date:
        streak += 1
        cursor -= timedelta(days=1)

    weekdays_zh = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    last_7: list[dict[str, Any]] = []
    for offset in range(6, -1, -1):
        d = today - timedelta(days=offset)
        ds = d.isoformat()
        info = by_date.get(ds)
        last_7.append(
            {
                "date": ds,
                "label": "今天" if offset == 0 else weekdays_zh[d.weekday()],
                "checked": bool(info),
                "count": int(info["cnt"]) if info else 0,
                "minutes": round(float(info["mins"] or 0.0), 1) if info else 0.0,
            }
        )

    total_checkins = sum(int(v["cnt"]) for v in by_date.values())
    total_minutes = round(sum(float(v["mins"] or 0.0) for v in by_date.values()), 1)
    return {
        "member_key": mk,
        "streak_days": streak,
        "total_checkins": total_checkins,
        "total_minutes": total_minutes,
        "today_checked": today.isoformat() in by_date,
        "last_7_days": last_7,
    }


@router.post("/evaluate-speech")
async def evaluate_english_speech(
    expected_text: str = Form(...),
    track_id: int | None = Form(default=None),
    member_key: str = Form(default=""),
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """接收儿童英语跟读录音，做 ASR 词匹配或有效音频检测并给出鼓励星级与自动打卡。"""
    audio_bytes = await file.read()
    if len(audio_bytes) < 256:
        raise HTTPException(status_code=400, detail="录音时间太短，请再试一次哦")

    exp = expected_text.strip()
    ext = ".webm" if (file.filename or "").endswith(".webm") else ".wav"
    recognized = ""
    try:
        recognized = (await transcribe_audio(audio_bytes, input_ext=ext)).strip()
    except Exception:
        recognized = ""

    exp_words = re.findall(r"[a-zA-Z]+", exp.lower())
    rec_words = re.findall(r"[a-zA-Z]+", recognized.lower())

    if exp_words and rec_words:
        matched = sum(1 for w in exp_words if w in rec_words)
        ratio = matched / max(1, len(exp_words))
        stars = 5 if ratio >= 0.85 else 4 if ratio >= 0.6 else 3 if ratio >= 0.35 else 2
        feedback = (
            "太棒啦！发音非常标准，给你 5 颗星！"
            if stars == 5
            else "读得很不错，再大声慢读一遍会更棒哦！"
            if stars >= 4
            else "勇敢开口就是进步，可以点上面的原声再跟读一遍！"
        )
    else:
        # 未配在线 ASR 时，依据录音有效字节数给正向鼓励星级
        stars = 5 if len(audio_bytes) >= 8000 else 4
        feedback = "声音洪亮、开口很棒！点击旁边按钮回放听听自己的发音，再打卡一颗小红花吧！"

    mk = member_key.strip() or f"user:{user['id']}"
    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO study_checkins (member_key, checkin_date, track_id, duration_min, spoken_score, note, created_at)
            VALUES (?, ?, ?, 3.0, ?, ?, ?)
            """,
            (mk, date.today().isoformat(), track_id, stars, f"跟读：{exp[:40]}", now_iso()),
        )
        await conn.commit()

    return {
        "expected_text": exp,
        "recognized_text": recognized,
        "stars": stars,
        "feedback": feedback,
    }


@router.get("/courses/{course_id}")
async def get_course_endpoint(
    course_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await get_course_detail(course_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="课程不存在")


@router.delete("/courses/{course_id}")
async def delete_course_endpoint(
    course_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM english_courses WHERE id = ?", (course_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="课程不存在")
        await conn.execute("DELETE FROM english_courses WHERE id = ?", (course_id,))
        await conn.commit()
    return {"status": "deleted"}


@router.post("/lessons/{lesson_id}/play")
async def play_english_lesson(
    lesson_id: int,
    req: LessonPlayRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """按需合成并播放课时音频（可同时推送音箱或标记完成）。"""
    try:
        _, dur = await synthesize_lesson_audio(lesson_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="课时不存在")

    ts = now_iso()
    async with get_db() as conn:
        if req.mark_completed:
            await conn.execute(
                "UPDATE english_lessons SET listen_count = listen_count + 1, completed = 1, last_studied_at = ? WHERE id = ?",
                (ts, lesson_id),
            )
        else:
            await conn.execute(
                "UPDATE english_lessons SET listen_count = listen_count + 1, last_studied_at = ? WHERE id = ?",
                (ts, lesson_id),
            )
        await conn.commit()
        cur = await conn.execute("SELECT * FROM english_lessons WHERE id = ?", (lesson_id,))
        lesson = dict(await cur.fetchone())

    try:
        lesson["vocab"] = json.loads(lesson.get("vocab_json") or "[]")
    except Exception:
        lesson["vocab"] = []
    lesson["duration_sec"] = dur
    lesson["stream_url"] = f"/api/english/lessons/{lesson_id}/stream"

    if req.device_id:
        await device_manager.cast_track_to_device(
            req.device_id,
            {
                "id": lesson_id,
                "title": lesson["title"],
                "media_kind": "english_lesson",
                "stream_url": lesson["stream_url"],
            },
        )

    return {"lesson": lesson, "stream_url": lesson["stream_url"]}


@router.patch("/lessons/{lesson_id}")
async def patch_english_lesson(
    lesson_id: int,
    req: LessonPatchRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM english_lessons WHERE id = ?", (lesson_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="课时不存在")
        if req.completed is not None:
            await conn.execute(
                "UPDATE english_lessons SET completed = ?, last_studied_at = ? WHERE id = ?",
                (1 if req.completed else 0, now_iso(), lesson_id),
            )
            await conn.commit()
        cur2 = await conn.execute("SELECT * FROM english_lessons WHERE id = ?", (lesson_id,))
        return dict(await cur2.fetchone())


@router.get("/lessons/{lesson_id}/stream")
async def stream_english_lesson(lesson_id: int):
    """直接供 <audio> 与智能音箱拉流的课时伴学音频端点（未合成时自动即时生成）。"""
    try:
        audio_path, _ = await synthesize_lesson_audio(lesson_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="课时不存在")
    return FileResponse(path=str(audio_path), media_type="audio/mpeg", headers={"Accept-Ranges": "bytes"})


# -------------------- 补充单词短语库 (兼容原 CRUD + 点读) --------------------


@router.get("/items")
async def list_english_items(
    stage: str | None = Query(default=None),
    q: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    async with get_db() as conn:
        clauses = []
        params: list[Any] = []
        if stage and stage != "all":
            clauses.append("stage = ?")
            params.append(stage)
        if q and q.strip():
            clauses.append("(phrase LIKE ? OR zh_meaning LIKE ?)")
            kw = f"%{q.strip()}%"
            params.extend([kw, kw])
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = await conn.execute(f"SELECT * FROM english_items {where_sql} ORDER BY stage ASC, id ASC", params)
        return [dict(r) for r in await cur.fetchall()]


@router.post("/items")
async def create_english_item(
    req: EnglishItemCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO english_items (phrase, zh_meaning, stage, category, audio_prompt, listen_count, mastery_level)
                VALUES (?, ?, ?, ?, ?, 0, 0)
                """,
                (req.phrase.strip(), req.zh_meaning.strip(), req.stage, req.category, req.audio_prompt.strip()),
            )
            await conn.commit()
            cur2 = await conn.execute("SELECT * FROM english_items WHERE id = ?", (cur.lastrowid,))
            return dict(await cur2.fetchone())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"新增词句失败: {exc}")


@router.patch("/items/{item_id}")
async def update_english_item(
    item_id: int,
    req: EnglishItemPatch,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM english_items WHERE id = ?", (item_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="英语词句不存在")
        data = dict(row)
        for k, v in req.model_dump(exclude_none=True).items():
            data[k] = v
        await conn.execute(
            """
            UPDATE english_items
            SET phrase = ?, zh_meaning = ?, stage = ?, category = ?, audio_prompt = ?
            WHERE id = ?
            """,
            (data["phrase"], data["zh_meaning"], data["stage"], data["category"], data["audio_prompt"], item_id),
        )
        await conn.commit()
    return data


@router.delete("/items/{item_id}")
async def delete_english_item(
    item_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        await conn.execute("DELETE FROM english_items WHERE id = ?", (item_id,))
        await conn.commit()
    return {"status": "deleted"}


@router.post("/items/{item_id}/practice")
async def practice_english_item(
    item_id: int,
    req: PracticeRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM english_items WHERE id = ?", (item_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="英语词句不存在")

        new_mastery = min(5, int(row["mastery_level"]) + (1 if req.record_spoken else 0))
        new_count = int(row["listen_count"]) + 1
        ts = now_iso()
        await conn.execute(
            "UPDATE english_items SET listen_count = ?, mastery_level = ?, last_played_at = ? WHERE id = ?",
            (new_count, new_mastery, ts, item_id),
        )
        await conn.commit()

        cur = await conn.execute("SELECT * FROM english_items WHERE id = ?", (item_id,))
        updated = dict(await cur.fetchone())

    settings = load_settings()
    voice = "en-US-AriaNeural" if updated["stage"] in ("B1", "B2_PLUS") else settings.tts_voice_child
    rate = "+0%" if updated["stage"] in ("B1", "B2_PLUS") else settings.tts_rate_child
    tts_path = await synthesize_speech(updated["audio_prompt"], voice=voice, rate=rate)
    if req.device_id:
        await device_manager.push_announcement(device_id=req.device_id, text=updated["audio_prompt"], tts_path=tts_path)

    return {"item": updated, "tts_url": f"/api/tts-cache/{tts_path.name}"}

"""全周期分级英语（Pre_A1 ~ B2+）系列课程、课时音频流与词句库路由。"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import load_settings
from app.db import get_db, now_iso
from app.gateways.manager import device_manager
from app.services.english_courses import (
    generate_custom_english_course,
    get_course_detail,
    seed_builtin_english_courses,
    synthesize_lesson_audio,
)
from app.services.tts_asr import synthesize_speech

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
    """幂等导入内置 6 套 24 节全阶英语系列课程（Pre-A1 -> B2+）。"""
    return await seed_builtin_english_courses()


@router.post("/courses/generate")
async def generate_course_endpoint(
    req: CourseGenerateRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.topic.strip():
        raise HTTPException(status_code=400, detail="请输入感兴趣的课程主题")
    return await generate_custom_english_course(req.topic.strip(), req.stage)


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

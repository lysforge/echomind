"""家庭成员成长档案、音色试听、声纹录入/重置与三层记忆完整 CRUD 路由。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import load_settings
from app.db import compute_age_label, compute_age_months, get_db, now_iso, recommend_age_stage
from app.services.tts_asr import synthesize_speech
from app.services.voiceprint import clear_member_voiceprint, enroll_member_voiceprint, identify_speaker

router = APIRouter(prefix="/api", tags=["members"])


class MemberCreate(BaseModel):
    name: str
    nickname: str
    role: Literal["child", "adult"] = "adult"
    birth_date: str = ""
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] | None = None
    english_stage: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS", "adult"] | None = None
    tts_voice: str | None = None
    tts_rate: str | None = None


class MemberPatch(BaseModel):
    name: str | None = None
    nickname: str | None = None
    role: Literal["child", "adult"] | None = None
    birth_date: str | None = None
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] | None = None
    english_stage: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS", "adult"] | None = None
    tts_voice: str | None = None
    tts_rate: str | None = None


class PreviewTTSRequest(BaseModel):
    voice: str = "zh-CN-XiaoyiNeural"
    rate: str = "-10%"
    text: str = "你好，这是当前选中音色的试听效果。"


class MemoryCreate(BaseModel):
    member_id: int | None = None
    scope: Literal["personal", "family", "growth"] = "family"
    category: str = "note"
    content: str
    importance: int = 3


class MemoryPatch(BaseModel):
    content: str | None = None
    category: str | None = None
    importance: int | None = None


def _enrich_member(row: dict[str, Any]) -> dict[str, Any]:
    bd = row.get("birth_date")
    row["age_months"] = compute_age_months(bd)
    row["age_label"] = compute_age_label(bd)
    row["recommended_age_stage"] = recommend_age_stage(bd)
    row["has_voiceprint"] = int(row.get("voiceprint_samples") or 0) > 0
    return row


@router.get("/members")
async def list_members(_user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT id, owner_user_id, name, nickname, role, birth_date, age_stage, english_stage, tts_voice, tts_rate, voiceprint_samples, created_at FROM family_members ORDER BY id ASC"
        )
        return [_enrich_member(dict(r)) for r in await cur.fetchall()]


@router.post("/members")
async def create_member(
    req: MemberCreate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="成员称呼不能为空")
    settings = load_settings()
    voice = req.tts_voice or (settings.tts_voice_child if req.role == "child" else settings.tts_voice_adult)
    rate = req.tts_rate or (settings.tts_rate_child if req.role == "child" else settings.tts_rate_adult)
    age_stage = req.age_stage or (recommend_age_stage(req.birth_date) if req.role == "child" else "S6_ALL")
    e_stage = req.english_stage or ("Pre_A1" if req.role == "child" else "adult")

    async with get_db() as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO family_members
                (owner_user_id, name, nickname, role, birth_date, age_stage, english_stage, tts_voice, tts_rate, voiceprint_vector, voiceprint_samples, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 0, ?)
                """,
                (user["id"], req.name.strip(), (req.nickname or req.name).strip(), req.role, req.birth_date, age_stage, e_stage, voice, rate, now_iso()),
            )
            await conn.commit()
            cur2 = await conn.execute(
                "SELECT id, owner_user_id, name, nickname, role, birth_date, age_stage, english_stage, tts_voice, tts_rate, voiceprint_samples, created_at FROM family_members WHERE id = ?",
                (cur.lastrowid,),
            )
            return _enrich_member(dict(await cur2.fetchone()))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"创建成员失败: {exc}")


@router.patch("/members/{member_id}")
async def update_member(
    member_id: int,
    req: MemberPatch,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM family_members WHERE id = ?", (member_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="成员不存在")
        current = dict(row)
        updates = req.model_dump(exclude_none=True)
        for k, v in updates.items():
            current[k] = v
        # 如果更新了 birth_date 且未显式指定 age_stage，自动按出生年月推算最新成长阶段
        if "birth_date" in updates and "age_stage" not in updates and current["role"] == "child":
            current["age_stage"] = recommend_age_stage(current["birth_date"])

        await conn.execute(
            """
            UPDATE family_members
            SET name = ?, nickname = ?, role = ?, birth_date = ?, age_stage = ?, english_stage = ?, tts_voice = ?, tts_rate = ?
            WHERE id = ?
            """,
            (
                current["name"],
                current["nickname"],
                current["role"],
                current["birth_date"],
                current["age_stage"],
                current["english_stage"],
                current["tts_voice"],
                current["tts_rate"],
                member_id,
            ),
        )
        await conn.commit()
        cur2 = await conn.execute(
            "SELECT id, owner_user_id, name, nickname, role, birth_date, age_stage, english_stage, tts_voice, tts_rate, voiceprint_samples, created_at FROM family_members WHERE id = ?",
            (member_id,),
        )
        return _enrich_member(dict(await cur2.fetchone()))


@router.delete("/members/{member_id}")
async def delete_member(
    member_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM family_members WHERE id = ?", (member_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="成员不存在")
        await conn.execute("DELETE FROM family_members WHERE id = ?", (member_id,))
        await conn.commit()
    return {"status": "deleted"}


@router.post("/members/preview-tts")
async def preview_tts_voice(
    req: PreviewTTSRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    path = await synthesize_speech(req.text, voice=req.voice, rate=req.rate)
    return {"tts_url": f"/api/tts-cache/{path.name}"}


@router.post("/members/{member_id}/voiceprint")
async def upload_voiceprint(
    member_id: int,
    file: UploadFile = File(...),
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    content = await file.read()
    if len(content) < 512:
        raise HTTPException(status_code=400, detail="音频过短，请至少录制 2～5 秒清晰说话声音")
    ext = Path(file.filename or "sample.webm").suffix or ".webm"
    try:
        return await enroll_member_voiceprint(member_id, content, input_ext=ext)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/members/{member_id}/voiceprint")
async def reset_member_voiceprint(
    member_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await clear_member_voiceprint(member_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/members/identify-audio")
async def identify_audio_endpoint(
    file: UploadFile = File(...),
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    content = await file.read()
    ext = Path(file.filename or "test.webm").suffix or ".webm"
    ctx = await identify_speaker(audio_bytes=content, input_ext=ext)
    return ctx.__dict__


@router.get("/memories")
async def list_memories(
    scope: str | None = Query(default=None),
    member_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    async with get_db() as conn:
        clauses = []
        params: list[Any] = []
        if scope and scope != "all":
            clauses.append("m.scope = ?")
            params.append(scope)
        if member_id is not None:
            clauses.append("m.member_id = ?")
            params.append(member_id)
        if q and q.strip():
            clauses.append("m.content LIKE ?")
            params.append(f"%{q.strip()}%")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = await conn.execute(
            f"""
            SELECT m.*, fm.name AS member_name
            FROM memories m
            LEFT JOIN family_members fm ON m.member_id = fm.id
            {where_sql}
            ORDER BY m.id DESC
            """,
            params,
        )
        return [dict(r) for r in await cur.fetchall()]


@router.post("/memories")
async def create_memory(
    req: MemoryCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="记忆内容不能为空")
    member_id = None if req.scope == "family" else req.member_id
    async with get_db() as conn:
        cur = await conn.execute(
            "INSERT INTO memories (member_id, scope, category, content, importance, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (member_id, req.scope, req.category, req.content.strip(), req.importance, now_iso()),
        )
        await conn.commit()
        return {"id": cur.lastrowid, "scope": req.scope, "content": req.content.strip()}


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: int,
    req: MemoryPatch,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="记忆不存在")
        data = dict(row)
        for k, v in req.model_dump(exclude_none=True).items():
            data[k] = v
        await conn.execute(
            "UPDATE memories SET content = ?, category = ?, importance = ? WHERE id = ?",
            (data["content"], data["category"], data["importance"], memory_id),
        )
        await conn.commit()
    return data


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        await conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await conn.commit()
    return {"status": "deleted"}

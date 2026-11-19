"""全成长阶段有声书架与双模式章节合成（文本转护耳音频 / 上传音频）路由。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import get_db, now_iso
from app.gateways.manager import device_manager
from app.services.collector import ingest_uploaded_book_chapter, synthesize_book_chapter_audio

router = APIRouter(prefix="/api/books", tags=["books"])


class BookCreate(BaseModel):
    title: str
    author: str = ""
    category: Literal["picture_book", "bridge_book", "chapter_lit", "science", "english_graded"] = "picture_book"
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] = "S2_3_6"
    english_level: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS", "adult"] = "Pre_A1"
    language: Literal["zh", "en", "bilingual"] = "zh"
    description: str = ""


class BookPatch(BaseModel):
    title: str | None = None
    author: str | None = None
    category: Literal["picture_book", "bridge_book", "chapter_lit", "science", "english_graded"] | None = None
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] | None = None
    english_level: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS", "adult"] | None = None
    language: Literal["zh", "en", "bilingual"] | None = None
    description: str | None = None


class ChapterFromTextCreate(BaseModel):
    chapter_num: int | None = None
    title: str
    text_content: str
    voice: str | None = None


class BookProgressUpdate(BaseModel):
    member_id: int = 0
    chapter_id: int
    position_sec: float = 0.0


class ChapterCastRequest(BaseModel):
    device_id: str


@router.get("")
async def list_books(
    age_stage: str | None = Query(default=None),
    category: str | None = Query(default=None),
    q: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    async with get_db() as conn:
        clauses = []
        params: list[Any] = []
        if age_stage and age_stage != "all":
            clauses.append("age_stage = ?")
            params.append(age_stage)
        if category and category != "all":
            clauses.append("category = ?")
            params.append(category)
        if q and q.strip():
            clauses.append("(title LIKE ? OR author LIKE ? OR description LIKE ?)")
            kw = f"%{q.strip()}%"
            params.extend([kw, kw, kw])
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = await conn.execute(f"SELECT * FROM books {where_sql} ORDER BY id DESC", params)
        books = [dict(r) for r in await cur.fetchall()]

        cur_c = await conn.execute("SELECT * FROM book_chapters ORDER BY book_id ASC, chapter_num ASC, id ASC")
        chapters = [dict(r) for r in await cur_c.fetchall()]

        cur_p = await conn.execute("SELECT * FROM reading_progress WHERE member_id = 0")
        prog_map = {r["book_id"]: dict(r) for r in await cur_p.fetchall()}

    grouped: dict[int, list[dict[str, Any]]] = {}
    for c in chapters:
        grouped.setdefault(c["book_id"], []).append(c)

    for b in books:
        b["chapters"] = grouped.get(b["id"], [])
        b["progress"] = prog_map.get(b["id"])
    return books


@router.post("")
async def create_book(
    req: BookCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="书名不能为空")
    async with get_db() as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO books (title, author, category, age_stage, english_level, language, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.title.strip(),
                    req.author.strip(),
                    req.category,
                    req.age_stage,
                    req.english_level,
                    req.language,
                    req.description.strip(),
                    now_iso(),
                ),
            )
            await conn.commit()
            cur2 = await conn.execute("SELECT * FROM books WHERE id = ?", (cur.lastrowid,))
            res = dict(await cur2.fetchone())
            res["chapters"] = []
            return res
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"创建书籍失败: {exc}")


@router.patch("/{book_id}")
async def update_book(
    book_id: int,
    req: BookPatch,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="书籍不存在")
        data = dict(row)
        for k, v in req.model_dump(exclude_none=True).items():
            data[k] = v
        await conn.execute(
            """
            UPDATE books
            SET title = ?, author = ?, category = ?, age_stage = ?, english_level = ?, language = ?, description = ?
            WHERE id = ?
            """,
            (data["title"], data["author"], data["category"], data["age_stage"], data["english_level"], data["language"], data["description"], book_id),
        )
        await conn.commit()
    return data


@router.delete("/{book_id}")
async def delete_book(
    book_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """删除书籍并同步清理磁盘上的所有有声章节文件。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT file_path FROM book_chapters WHERE book_id = ?", (book_id,))
        files = [r["file_path"] for r in await cur.fetchall()]
        await conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        await conn.commit()
    for fp in files:
        if fp:
            Path(fp).unlink(missing_ok=True)
    return {"status": "deleted"}


@router.post("/{book_id}/chapters/from-text")
async def add_chapter_from_text(
    book_id: int,
    req: ChapterFromTextCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """填入章节正文，自动按书籍语种合成为 -16 LUFS 护耳有声章节。"""
    if not req.title.strip() or not req.text_content.strip():
        raise HTTPException(status_code=400, detail="章节标题与正文不能为空")
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        book = await cur.fetchone()
        if not book:
            raise HTTPException(status_code=404, detail="书籍不存在")
        cur_num = await conn.execute(
            "SELECT COALESCE(MAX(chapter_num), 0) FROM book_chapters WHERE book_id = ?",
            (book_id,),
        )
        ch_num = req.chapter_num or int((await cur_num.fetchone())[0] or 0) + 1

    dst, dur, norm = await synthesize_book_chapter_audio(
        book_id, ch_num, req.title.strip(), req.text_content.strip(), book["language"], req.voice
    )
    async with get_db() as conn:
        cur = await conn.execute(
            """
            INSERT INTO book_chapters (book_id, chapter_num, title, text_content, file_path, duration_sec, lufs_normalized, play_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (book_id, ch_num, req.title.strip(), req.text_content.strip(), str(dst), dur, norm, now_iso()),
        )
        await conn.commit()
        cur2 = await conn.execute("SELECT * FROM book_chapters WHERE id = ?", (cur.lastrowid,))
        return dict(await cur2.fetchone())


@router.post("/{book_id}/chapters/upload")
async def add_chapter_upload(
    book_id: int,
    title: str = Form(...),
    chapter_num: int | None = Form(default=None),
    file: UploadFile = File(...),
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    raw_bytes = await file.read()
    if len(raw_bytes) < 256:
        raise HTTPException(status_code=400, detail="音频文件无效")
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM books WHERE id = ?", (book_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="书籍不存在")
        cur_num = await conn.execute(
            "SELECT COALESCE(MAX(chapter_num), 0) FROM book_chapters WHERE book_id = ?",
            (book_id,),
        )
        ch_num = chapter_num or int((await cur_num.fetchone())[0] or 0) + 1

    dst, dur, norm = await ingest_uploaded_book_chapter(book_id, ch_num, title.strip(), raw_bytes, file.filename or "chapter.mp3")
    async with get_db() as conn:
        cur = await conn.execute(
            """
            INSERT INTO book_chapters (book_id, chapter_num, title, text_content, file_path, duration_sec, lufs_normalized, play_count, created_at)
            VALUES (?, ?, ?, '', ?, ?, ?, 0, ?)
            """,
            (book_id, ch_num, title.strip(), str(dst), dur, norm, now_iso()),
        )
        await conn.commit()
        cur2 = await conn.execute("SELECT * FROM book_chapters WHERE id = ?", (cur.lastrowid,))
        return dict(await cur2.fetchone())


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(
    chapter_id: int,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT file_path FROM book_chapters WHERE id = ?", (chapter_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="章节不存在")
        fp = row["file_path"]
        await conn.execute("DELETE FROM book_chapters WHERE id = ?", (chapter_id,))
        await conn.commit()
    if fp:
        Path(fp).unlink(missing_ok=True)
    return {"status": "deleted"}


@router.get("/chapters/{chapter_id}/stream")
async def stream_chapter(chapter_id: int, request: Request):
    """支持 HTTP Range 206 流式播放有声书章节（免前端登录供智能音箱直接拉流）。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM book_chapters WHERE id = ?", (chapter_id,))
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="章节不存在")
    file_path = Path(row["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="章节音频尚未就绪")

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


@router.post("/{book_id}/progress")
async def save_reading_progress(
    book_id: int,
    req: BookProgressUpdate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO reading_progress (book_id, member_id, last_chapter_id, position_sec, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(book_id, member_id) DO UPDATE SET
                last_chapter_id = excluded.last_chapter_id,
                position_sec = excluded.position_sec,
                updated_at = excluded.updated_at
            """,
            (book_id, req.member_id, req.chapter_id, req.position_sec, now_iso()),
        )
        await conn.execute("UPDATE book_chapters SET play_count = play_count + 1 WHERE id = ?", (req.chapter_id,))
        await conn.commit()
    return {"status": "saved", "book_id": book_id, "chapter_id": req.chapter_id}


@router.post("/chapters/{chapter_id}/cast")
async def cast_chapter_to_device(
    chapter_id: int,
    req: ChapterCastRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM book_chapters WHERE id = ?", (chapter_id,))
        ch = await cur.fetchone()
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        ch_dict = dict(ch)
        ch_dict["media_kind"] = "book_chapter"
        ch_dict["stream_url"] = f"/api/books/chapters/{chapter_id}/stream"
        await conn.execute("UPDATE book_chapters SET play_count = play_count + 1 WHERE id = ?", (chapter_id,))
        await conn.commit()

    await device_manager.cast_track_to_device(req.device_id, ch_dict)
    return {"status": "casted", "device_id": req.device_id, "stream_url": ch_dict["stream_url"]}

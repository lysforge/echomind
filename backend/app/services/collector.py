"""全阶段媒体采集、本地目录扫描、高速在线双引擎搜索、边播边缓存与示范库管线。"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from app.config import DATA_DIR, MEDIA_RAW_DIR, MEDIA_TRACKS_DIR, load_settings
from app.db import get_db, now_iso
from app.services.audio_norm import normalize_audio_to_lufs
from app.services.english_courses import seed_builtin_english_courses
from app.services.tts_asr import synthesize_speech

BOOKS_AUDIO_DIR = DATA_DIR / "books"
LOCAL_LIBRARY_DIR = DATA_DIR / "local_library"
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac"}

# 实时在线流式播放与后台自动缓存会话池
LIVE_STREAM_SESSIONS: dict[str, dict[str, Any]] = {}


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name).strip("_")
    return cleaned[:80] or uuid.uuid4().hex[:8]


async def _next_episode_num(album_id: int) -> int:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT COALESCE(MAX(episode_num), 0) FROM media_tracks WHERE album_id = ?",
            (album_id,),
        )
        row = await cur.fetchone()
        return int(row[0] or 0) + 1


async def insert_normalized_track(
    album_id: int,
    title: str,
    raw_file: Path,
    source_url: str = "",
    episode_num: int | None = None,
    source_id: int | None = None,
    external_guid: str = "",
    text_content: str = "",
    vocab_json: str = "[]",
    objective: str = "",
) -> int:
    """将音轨转码校准至 -16 LUFS 后存入专辑（支持按 source_url / external_guid 去重）。"""
    async with get_db() as conn:
        if source_url or external_guid:
            cur = await conn.execute(
                """
                SELECT id, file_path FROM media_tracks
                WHERE album_id = ?
                  AND ((? != '' AND source_url = ?) OR (? != '' AND external_guid = ?))
                LIMIT 1
                """,
                (album_id, source_url, source_url, external_guid, external_guid),
            )
            exist = await cur.fetchone()
            if exist and exist["file_path"] and Path(exist["file_path"]).exists():
                return int(exist["id"])

    MEDIA_TRACKS_DIR.mkdir(parents=True, exist_ok=True)
    ep = episode_num if episode_num is not None else await _next_episode_num(album_id)
    out_name = f"album{album_id}_ep{ep:03d}_{_safe_filename(title)}_{uuid.uuid4().hex[:6]}.mp3"
    dst_path = MEDIA_TRACKS_DIR / out_name
    normalized, duration = await normalize_audio_to_lufs(raw_file, dst_path)

    ts = now_iso()
    async with get_db() as conn:
        cur = await conn.execute(
            """
            INSERT INTO media_tracks
            (album_id, source_id, external_guid, title, episode_num, duration_sec, file_path, source_url, text_content, vocab_json, objective, lufs_normalized, play_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (album_id, source_id, external_guid, title, ep, duration, str(dst_path), source_url, text_content, vocab_json, objective, 1 if normalized else 0, ts),
        )
        track_id = cur.lastrowid
        await conn.execute(
            "UPDATE media_albums SET last_track_id = COALESCE(last_track_id, ?) WHERE id = ?",
            (track_id, album_id),
        )
        await conn.commit()
    return int(track_id)


async def add_track_from_text(
    album_id: int,
    title: str,
    text_content: str,
    language: str = "zh",
    voice_override: str | None = None,
    vocab_json: str = "[]",
    objective: str = "",
) -> dict[str, Any]:
    """根据正文文本一键合成 -16 LUFS 护耳有声单集并归入统一专辑。"""
    MEDIA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    if voice_override:
        voice, rate = voice_override, "+0%"
    elif language == "en":
        voice, rate = "en-US-AriaNeural", "-4%"
    elif language == "bilingual":
        voice, rate = "zh-CN-XiaoxiaoNeural", "-6%"
    else:
        voice, rate = "zh-CN-XiaoxiaoNeural", "-4%"

    raw_tmp = MEDIA_RAW_DIR / f"text_track_{album_id}_{uuid.uuid4().hex[:8]}.mp3"
    try:
        await synthesize_speech(text_content.strip(), voice=voice, rate=rate, output_path=raw_tmp, normalize_lufs=False)
        tid = await insert_normalized_track(
            album_id=album_id,
            title=title.strip(),
            raw_file=raw_tmp,
            source_url=f"tts://{album_id}/{uuid.uuid4().hex[:8]}",
            text_content=text_content.strip(),
            vocab_json=vocab_json,
            objective=objective,
        )
    finally:
        raw_tmp.unlink(missing_ok=True)

    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM media_tracks WHERE id = ?", (tid,))
        d = dict(await cur.fetchone())
        d["stream_url"] = f"/api/media/tracks/{tid}/stream"
        return d


async def synthesize_track_audio_if_missing(track_id: int) -> tuple[Path, float]:
    """当统一专辑内的单集仅有讲稿文本尚未合成磁盘音频时，按需即时合成并校准落盘。"""
    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT t.*, a.category AS album_category, a.english_level AS album_eng, a.language AS album_lang
            FROM media_tracks t
            JOIN media_albums a ON t.album_id = a.id
            WHERE t.id = ?
            """,
            (track_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise ValueError("音频条目不存在")
        tr = dict(row)

    fp = Path(tr["file_path"]) if tr.get("file_path") else None
    if fp and fp.exists() and fp.stat().st_size > 128:
        return fp, float(tr.get("duration_sec") or 0.0)

    text = (tr.get("text_content") or "").strip() or tr["title"]
    eng_lvl = tr.get("album_eng") or "Pre_A1"
    lang = tr.get("album_lang") or "zh"
    if eng_lvl in ("B1", "B2_PLUS") or lang == "en":
        voice, rate = "en-US-AriaNeural", "+0%"
    else:
        voice, rate = "zh-CN-XiaoxiaoNeural", "-6%"

    MEDIA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_TRACKS_DIR.mkdir(parents=True, exist_ok=True)
    raw_tmp = MEDIA_RAW_DIR / f"lazy_tr_{track_id}_{uuid.uuid4().hex[:6]}.mp3"
    dst = MEDIA_TRACKS_DIR / f"album{tr['album_id']}_ep{int(tr['episode_num']):03d}_{_safe_filename(tr['title'])}_{uuid.uuid4().hex[:6]}.mp3"
    try:
        await synthesize_speech(text, voice=voice, rate=rate, output_path=raw_tmp, normalize_lufs=False)
        normalized, duration = await normalize_audio_to_lufs(raw_tmp, dst)
    finally:
        raw_tmp.unlink(missing_ok=True)

    async with get_db() as conn:
        await conn.execute(
            "UPDATE media_tracks SET file_path = ?, duration_sec = ?, lufs_normalized = ? WHERE id = ?",
            (str(dst), duration, 1 if normalized else 0, track_id),
        )
        await conn.commit()
    return dst, duration


async def sync_legacy_to_unified_albums() -> dict[str, int]:
    """将已有 books/book_chapters 与 english_courses/english_lessons 幂等融汇到统一 media_albums/media_tracks 模型。"""
    ts = now_iso()
    synced_albums = 0
    synced_tracks = 0

    book_cat_map = {
        "science": ("podcast", "科学百科", "🔬"),
        "bridge_book": ("story", "桥梁章节书", "📗"),
        "chapter_lit": ("story", "名著文学", "📕"),
        "english_graded": ("english", "故事与思辨", "🔤"),
        "picture_book": ("story", "睡前绘本", "📖"),
    }
    stage_tag_map = {
        "Pre_A1": "零基础韵律",
        "A1": "日常口语课",
        "A2": "自然科普课",
        "B1": "故事与思辨",
        "B2_PLUS": "故事与思辨",
    }

    async with get_db() as conn:
        # 1. 同步有声书 -> 统一专辑
        cur_b = await conn.execute("SELECT * FROM books ORDER BY id ASC")
        books = [dict(r) for r in await cur_b.fetchall()]
        for b in books:
            cat, sub_tag, emoji = book_cat_map.get(b["category"], ("story", "睡前绘本", "📖"))
            cur_a = await conn.execute("SELECT id FROM media_albums WHERE title = ?", (b["title"],))
            arow = await cur_a.fetchone()
            if arow:
                aid = int(arow["id"])
                await conn.execute(
                    """
                    UPDATE media_albums
                    SET sub_tag = CASE WHEN sub_tag = '' THEN ? ELSE sub_tag END,
                        cover_emoji = CASE WHEN cover_emoji = '' THEN ? ELSE cover_emoji END,
                        author = CASE WHEN author = '' THEN ? ELSE author END,
                        language = ?
                    WHERE id = ?
                    """,
                    (sub_tag, emoji, b.get("author") or "", b.get("language") or "zh", aid),
                )
            else:
                cur_ins = await conn.execute(
                    """
                    INSERT INTO media_albums
                    (title, category, sub_tag, age_stage, english_level, play_mode, cover_emoji, author, language, description, created_at)
                    VALUES (?, ?, ?, ?, ?, 'sequential', ?, ?, ?, ?, ?)
                    """,
                    (
                        b["title"],
                        cat,
                        sub_tag,
                        b["age_stage"],
                        b["english_level"],
                        emoji,
                        b.get("author") or "",
                        b.get("language") or "zh",
                        b.get("description") or "",
                        b.get("created_at") or ts,
                    ),
                )
                aid = int(cur_ins.lastrowid)
                synced_albums += 1

            cur_ch = await conn.execute("SELECT * FROM book_chapters WHERE book_id = ? ORDER BY chapter_num ASC, id ASC", (b["id"],))
            for raw_ch in await cur_ch.fetchall():
                ch = dict(raw_ch)
                guid = f"book_ch:{ch['id']}"
                cur_t = await conn.execute("SELECT id FROM media_tracks WHERE external_guid = ?", (guid,))
                if not await cur_t.fetchone():
                    cur_ti = await conn.execute(
                        """
                        INSERT INTO media_tracks
                        (album_id, external_guid, title, episode_num, duration_sec, file_path, source_url, text_content, lufs_normalized, play_count, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            aid,
                            guid,
                            ch["title"],
                            ch["chapter_num"],
                            ch["duration_sec"],
                            ch["file_path"],
                            guid,
                            ch.get("text_content") or "",
                            ch.get("lufs_normalized", 1),
                            ch.get("play_count", 0),
                            ch.get("created_at") or ts,
                        ),
                    )
                    await conn.execute(
                        "UPDATE media_albums SET last_track_id = COALESCE(last_track_id, ?) WHERE id = ?",
                        (cur_ti.lastrowid, aid),
                    )
                    synced_tracks += 1

        # 2. 同步英语系列课程 -> 统一专辑
        cur_c = await conn.execute("SELECT * FROM english_courses ORDER BY id ASC")
        courses = [dict(r) for r in await cur_c.fetchall()]
        for c in courses:
            sub_tag = stage_tag_map.get(c["stage"], "日常口语课")
            emoji = c.get("cover_emoji") or "🎓"
            cur_a = await conn.execute("SELECT id FROM media_albums WHERE title = ?", (c["title"],))
            arow = await cur_a.fetchone()
            if arow:
                aid = int(arow["id"])
                await conn.execute(
                    """
                    UPDATE media_albums
                    SET sub_tag = CASE WHEN sub_tag = '' THEN ? ELSE sub_tag END,
                        cover_emoji = CASE WHEN cover_emoji = '' THEN ? ELSE cover_emoji END,
                        english_level = ?
                    WHERE id = ?
                    """,
                    (sub_tag, emoji, c["stage"], aid),
                )
            else:
                cur_ins = await conn.execute(
                    """
                    INSERT INTO media_albums
                    (title, category, sub_tag, age_stage, english_level, play_mode, cover_emoji, author, language, description, created_at)
                    VALUES (?, 'english', ?, ?, ?, 'sequential', ?, 'EchoMind 英语教研', 'bilingual', ?, ?)
                    """,
                    (
                        c["title"],
                        sub_tag,
                        c["age_stage"],
                        c["stage"],
                        emoji,
                        c.get("description") or c.get("subtitle") or "",
                        c.get("created_at") or ts,
                    ),
                )
                aid = int(cur_ins.lastrowid)
                synced_albums += 1

            cur_ls = await conn.execute("SELECT * FROM english_lessons WHERE course_id = ? ORDER BY lesson_num ASC, id ASC", (c["id"],))
            for raw_ls in await cur_ls.fetchall():
                ls = dict(raw_ls)
                guid = f"eng_lesson:{ls['id']}"
                cur_t = await conn.execute("SELECT id FROM media_tracks WHERE external_guid = ?", (guid,))
                if not await cur_t.fetchone():
                    cur_ti = await conn.execute(
                        """
                        INSERT INTO media_tracks
                        (album_id, external_guid, title, episode_num, duration_sec, file_path, source_url, text_content, vocab_json, objective, completed, lufs_normalized, play_count, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (
                            aid,
                            guid,
                            ls["title"],
                            ls["lesson_num"],
                            ls["duration_sec"],
                            ls.get("audio_path") or "",
                            guid,
                            ls.get("dialogue_script") or "",
                            ls.get("vocab_json") or "[]",
                            ls.get("objective") or "",
                            ls.get("completed", 0),
                            ls.get("listen_count", 0),
                            ls.get("created_at") or ts,
                        ),
                    )
                    await conn.execute(
                        "UPDATE media_albums SET last_track_id = COALESCE(last_track_id, ?) WHERE id = ?",
                        (cur_ti.lastrowid, aid),
                    )
                    synced_tracks += 1

        await conn.commit()
    return {"synced_albums": synced_albums, "synced_tracks": synced_tracks}


async def synthesize_book_chapter_audio(
    book_id: int,
    chapter_num: int,
    title: str,
    text_content: str,
    language: str = "zh",
    voice_override: str | None = None,
) -> tuple[Path, float, int]:
    """根据书籍语言与正文文本，自动合成 -16 LUFS 护耳有声书章节 MP3。"""
    BOOKS_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_RAW_DIR.mkdir(parents=True, exist_ok=True)

    if voice_override:
        voice = voice_override
        rate = "+0%"
    elif language == "en":
        voice = "en-US-AriaNeural"
        rate = "-6%"
    elif language == "bilingual":
        voice = "zh-CN-XiaoxiaoNeural"
        rate = "-6%"
    else:
        voice = "zh-CN-XiaoxiaoNeural"
        rate = "-4%"

    raw_tmp = MEDIA_RAW_DIR / f"book_{book_id}_ch{chapter_num}_{uuid.uuid4().hex[:6]}.mp3"
    dst = BOOKS_AUDIO_DIR / f"book_{book_id}_ch{chapter_num:03d}_{_safe_filename(title)}_{uuid.uuid4().hex[:6]}.mp3"
    try:
        await synthesize_speech(text_content, voice=voice, rate=rate, output_path=raw_tmp, normalize_lufs=False)
        normalized, duration = await normalize_audio_to_lufs(raw_tmp, dst)
        return dst, duration, 1 if normalized else 0
    finally:
        raw_tmp.unlink(missing_ok=True)


async def ingest_uploaded_book_chapter(
    book_id: int,
    chapter_num: int,
    title: str,
    raw_bytes: bytes,
    filename: str,
) -> tuple[Path, float, int]:
    BOOKS_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix or ".mp3"
    raw_tmp = MEDIA_RAW_DIR / f"book_up_{uuid.uuid4().hex[:8]}{ext}"
    raw_tmp.write_bytes(raw_bytes)
    dst = BOOKS_AUDIO_DIR / f"book_{book_id}_ch{chapter_num:03d}_{_safe_filename(title)}_{uuid.uuid4().hex[:6]}.mp3"
    try:
        normalized, duration = await normalize_audio_to_lufs(raw_tmp, dst)
        return dst, duration, 1 if normalized else 0
    finally:
        raw_tmp.unlink(missing_ok=True)


def _parse_duration_str(dur_raw: Any) -> int:
    if isinstance(dur_raw, (int, float)):
        return int(dur_raw)
    s = str(dur_raw or "").strip()
    if not s:
        return 0
    parts = [int(p) for p in s.split(":") if p.isdigit()]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


async def _search_bilibili_api(q: str, limit: int = 6) -> list[dict[str, Any]]:
    """高速请求 Bilibili 公开搜索接口，0.5s 级别响应中文儿歌与故事。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    }
    params = {"search_type": "video", "keyword": q, "page": 1, "page_size": max(limit * 2, 10)}
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        resp = await client.get("https://api.bilibili.com/x/web-interface/search/type", params=params, headers=headers)
        resp.raise_for_status()
        payload = resp.json()

    items = (payload.get("data") or {}).get("result") or []
    results: list[dict[str, Any]] = []
    for it in items:
        bvid = it.get("bvid") or ""
        if not bvid:
            continue
        dur_sec = _parse_duration_str(it.get("duration"))
        if dur_sec > 2700:
            continue
        raw_title = html.unescape(str(it.get("title") or "未命名音频"))
        clean_title = re.sub(r"<[^>]+>", "", raw_title).strip()
        results.append(
            {
                "title": clean_title,
                "duration_sec": dur_sec,
                "uploader": str(it.get("author") or "Bilibili"),
                "url": f"https://www.bilibili.com/video/{bvid}",
            }
        )
        if len(results) >= limit:
            break
    return results


async def _search_ytdlp(prefix: str, q: str, limit: int = 6, timeout_sec: float = 12.0) -> list[dict[str, Any]]:
    settings = load_settings()
    target = f"{prefix}{limit}:{q}"
    proc = await asyncio.create_subprocess_exec(
        settings.yt_dlp_bin,
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        "--skip-download",
        target,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        proc.kill()
        return []

    results: list[dict[str, Any]] = []
    for line in stdout.decode(errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = item.get("webpage_url") or item.get("url") or ""
        if url and not url.startswith("http") and item.get("id"):
            url = f"https://www.youtube.com/watch?v={item['id']}"
        if not url:
            continue
        dur = int(item.get("duration") or 0)
        if dur > 2700:
            continue
        results.append(
            {
                "title": item.get("title") or "未命名音频",
                "duration_sec": dur,
                "uploader": item.get("uploader") or item.get("channel") or "",
                "url": url,
            }
        )
    return results[:limit]


async def search_online_audio(query: str, limit: int = 6) -> list[dict[str, Any]]:
    """多源音乐检索（优先复用已连通的 go-music-dl 10+ 源原唱引擎，未启动时平滑回退 Bilibili/YouTube）。"""
    q = query.strip()
    if not q:
        return []

    if os.environ.get("ECHOMIND_DISABLE_MUSIC_DL", "0") != "1" and (load_settings().music_dl_url or "").strip():
        try:
            from app.services.music_dl import build_upstream_download_url, cloud_search

            cloud_res = await cloud_search(q=q, search_type="song", timeout_sec=4.0)
            songs = cloud_res.get("songs") or []
            if songs:
                return [
                    {
                        "title": f"{s['name']} - {s['artist']}" if s.get("artist") else s["name"],
                        "duration_sec": int(s.get("duration") or 0),
                        "uploader": str(s.get("source") or "cloud"),
                        "url": build_upstream_download_url(s, stream_only=False),
                    }
                    for s in songs[:limit]
                ]
        except Exception:
            pass

    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", q))
    if has_cjk:
        try:
            res = await _search_bilibili_api(q, limit=limit)
            if res:
                return res
        except Exception:
            pass
        res = await _search_ytdlp("bilisearch", q, limit=limit, timeout_sec=10.0)
        if res:
            return res
        return await _search_ytdlp("ytsearch", q, limit=limit, timeout_sec=12.0)

    res = await _search_ytdlp("ytsearch", q, limit=limit, timeout_sec=12.0)
    if res:
        return res
    try:
        return await _search_bilibili_api(q, limit=limit)
    except Exception:
        return []


async def ensure_auto_cache_album(category: str = "music", age_stage: str = "S6_ALL") -> tuple[int, str]:
    """为语音/在线即播自动缓存准备目标本地缓存池专辑。"""
    names = {
        "music": "在线点播·音乐缓存",
        "story": "在线点播·故事缓存",
        "english": "在线点播·英语缓存",
        "podcast": "在线点播·播客缓存",
    }
    cat = category if category in names else "music"
    title = names[cat]
    async with get_db() as conn:
        cur = await conn.execute("SELECT id, title FROM media_albums WHERE title = ?", (title,))
        row = await cur.fetchone()
        if row:
            await conn.execute(
                "UPDATE media_albums SET is_inbox = 1, sub_tag = '语音缓存池', cover_emoji = '📥' WHERE id = ?",
                (row["id"],),
            )
            await conn.commit()
            return int(row["id"]), str(row["title"])
        cur_ins = await conn.execute(
            """
            INSERT INTO media_albums (title, category, sub_tag, age_stage, english_level, play_mode, cover_emoji, is_inbox, description, created_at)
            VALUES (?, ?, '语音缓存池', ?, 'Pre_A1', 'sequential', '📥', 1, '由在线播放及语音点播自动护耳缓存归档到本地收件箱，可在后台一键转正到正式专辑', ?)
            """,
            (title, cat, age_stage if age_stage in ("S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL") else "S6_ALL", now_iso()),
        )
        await conn.commit()
        return int(cur_ins.lastrowid), title


def _looks_like_direct_audio_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith("/download") and "source=" in parsed.query and "id=" in parsed.query:
        return True
    return path.endswith((".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".flac"))


async def _background_cache_online_item(token: str) -> None:
    """后台异步将在线音频下载并执行 -16 LUFS 护耳校准落盘到本地专辑。"""
    session = LIVE_STREAM_SESSIONS.get(token)
    if not session:
        return
    url = str(session["url"])
    title = str(session["title"])
    album_id = int(session["album_id"])
    source_id = session.get("source_id")
    external_guid = str(session.get("external_guid") or "")
    online_stream_id = session.get("online_stream_id")

    settings = load_settings()
    job_dir = MEDIA_RAW_DIR / f"cache_{token}"
    job_dir.mkdir(parents=True, exist_ok=True)
    ts = now_iso()

    async with get_db() as conn:
        cur = await conn.execute(
            """
            INSERT INTO download_jobs (job_type, source_url, target_album_id, status, progress_text, created_at, updated_at)
            VALUES ('yt_dlp', ?, ?, 'running', ?, ?, ?)
            """,
            (url, album_id, f"[自动缓存] 正在保存到本地：《{title}》", ts, ts),
        )
        job_id = int(cur.lastrowid)
        await conn.commit()

    try:
        raw_audio: Path | None = None
        if _looks_like_direct_audio_url(url):
            ext = Path(urlparse(url).path).suffix or ".mp3"
            raw_audio = job_dir / f"direct{ext}"
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                r = await client.get(url)
                r.raise_for_status()
                raw_audio.write_bytes(r.content)
        else:
            out_tmpl = str(job_dir / "item.%(ext)s")
            proc = await asyncio.create_subprocess_exec(
                settings.yt_dlp_bin,
                "--no-warnings",
                "--no-playlist",
                "--extract-audio",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "5",
                "--ffmpeg-location",
                str(Path(settings.ffmpeg_bin).parent),
                "-o",
                out_tmpl,
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
            if proc.returncode != 0:
                raise RuntimeError(stderr.decode(errors="ignore")[-300:] or "下载缓存失败")
            candidates = [p for p in job_dir.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
            if not candidates:
                raise RuntimeError("未能提取到音频文件")
            raw_audio = candidates[0]

        track_id = await insert_normalized_track(
            album_id=album_id,
            title=title,
            raw_file=raw_audio,
            source_url=url,
            source_id=source_id,
            external_guid=external_guid or url,
        )
        session["cached_track_id"] = track_id
        session["status"] = "cached"
        if online_stream_id:
            async with get_db() as conn:
                await conn.execute(
                    "UPDATE online_streams SET cached_track_id = ? WHERE id = ?",
                    (track_id, online_stream_id),
                )
                await conn.commit()
        await _update_job(job_id, "done", f"[自动缓存完成] 《{title}》已入本地库", tracks_added=1)
    except Exception as exc:
        session["status"] = "failed"
        await _update_job(job_id, "failed", f"[自动缓存失败] 《{title}》", error_msg=str(exc)[:300])
    finally:
        for p in job_dir.glob("*"):
            p.unlink(missing_ok=True)
        if job_dir.exists():
            job_dir.rmdir()


async def resolve_or_prepare_online_stream(
    title: str,
    url: str,
    category: str = "music",
    album_id: int | None = None,
    source_id: int | None = None,
    external_guid: str = "",
    age_stage: str = "S6_ALL",
    online_stream_id: int | None = None,
) -> dict[str, Any]:
    """
    先检查是否已有本地缓存；命中直接返回本地轨道流，
    未命中立即签发 /api/media/live-stream/{token} 实时流秒播，并启动后台异步 -16 LUFS 缓存落盘。
    """
    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT t.*, a.title AS album_title
            FROM media_tracks t
            JOIN media_albums a ON t.album_id = a.id
            WHERE (t.source_url = ? AND t.source_url != '')
               OR (? != '' AND t.external_guid = ?)
            ORDER BY t.id DESC
            LIMIT 1
            """,
            (url, external_guid, external_guid),
        )
        cached = await cur.fetchone()
        if cached and cached["file_path"] and Path(cached["file_path"]).exists():
            res = dict(cached)
            res["media_kind"] = "track"
            res["is_cached"] = True
            res["caching"] = False
            res["stream_url"] = f"/api/media/tracks/{res['id']}/stream"
            return res

        album_title = ""
        if album_id:
            cur_a = await conn.execute("SELECT title FROM media_albums WHERE id = ?", (album_id,))
            arow = await cur_a.fetchone()
            if arow:
                album_title = arow["title"]
            else:
                album_id = None

    if not album_id:
        album_id, album_title = await ensure_auto_cache_album(category, age_stage)

    # 避免对同一 URL 重复并发下载
    for tok, sess in LIVE_STREAM_SESSIONS.items():
        if sess.get("url") == url and sess.get("status") != "failed":
            if sess.get("cached_track_id"):
                async with get_db() as conn:
                    c2 = await conn.execute(
                        "SELECT t.*, a.title AS album_title FROM media_tracks t JOIN media_albums a ON t.album_id = a.id WHERE t.id = ?",
                        (sess["cached_track_id"],),
                    )
                    r2 = await c2.fetchone()
                    if r2 and Path(r2["file_path"]).exists():
                        d2 = dict(r2)
                        d2["media_kind"] = "track"
                        d2["is_cached"] = True
                        d2["caching"] = False
                        d2["stream_url"] = f"/api/media/tracks/{d2['id']}/stream"
                        return d2
            return {
                "id": 0,
                "title": title,
                "album_id": album_id,
                "album_title": album_title,
                "media_kind": "online_live",
                "is_cached": False,
                "caching": True,
                "source_url": url,
                "stream_url": f"/api/media/live-stream/{tok}",
                "duration_sec": 0.0,
            }

    token = uuid.uuid4().hex[:16]
    LIVE_STREAM_SESSIONS[token] = {
        "token": token,
        "title": title,
        "url": url,
        "album_id": album_id,
        "album_title": album_title,
        "source_id": source_id,
        "external_guid": external_guid,
        "online_stream_id": online_stream_id,
        "cached_track_id": None,
        "status": "caching",
        "created_at": now_iso(),
    }
    asyncio.create_task(_background_cache_online_item(token))

    return {
        "id": 0,
        "title": title,
        "album_id": album_id,
        "album_title": album_title,
        "media_kind": "online_live",
        "is_cached": False,
        "caching": True,
        "source_url": url,
        "stream_url": f"/api/media/live-stream/{token}",
        "duration_sec": 0.0,
    }


async def ensure_default_local_folder() -> None:
    """确保默认本地媒体目录存在并在 local_folders 为空时自动挂载（不注入任何假音箱/假成员）。"""
    for sub in ("music", "story", "books"):
        (LOCAL_LIBRARY_DIR / sub).mkdir(parents=True, exist_ok=True)
    async with get_db() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM local_folders")
        if int((await cur.fetchone())[0] or 0) == 0:
            await conn.execute(
                """
                INSERT INTO local_folders (name, folder_path, media_type, age_stage, last_scan_summary, file_count, created_at)
                VALUES ('EchoMind 本地媒体仓（音乐/故事/绘本）', ?, 'auto', 'S6_ALL', '已自动挂载，可放音频后点击扫描入库', 0, ?)
                """,
                (str(LOCAL_LIBRARY_DIR), now_iso()),
            )
            await conn.commit()


def _infer_media_kind(folder_media_type: str, rel_parts: tuple[str, ...]) -> str:
    if folder_media_type in ("music", "story", "book"):
        return folder_media_type
    joined = "/".join(rel_parts).lower()
    if any(k in joined for k in ("book", "picture", "绘本", "图书", "read")):
        return "book"
    if any(k in joined for k in ("story", "故事", "睡前", "童话")):
        return "story"
    return "music"


def _read_audio_id3_tags(af: Path) -> dict[str, Any]:
    """借助 mutagen 安全读取本地音频文件内嵌 ID3/FLAC/MP4 元数据（歌手/专辑/曲名/音轨号）。"""
    try:
        import mutagen

        mf = mutagen.File(str(af), easy=True)
        if not mf:
            return {}

        def _first(key: str) -> str:
            val = mf.get(key)
            if isinstance(val, list) and val:
                return str(val[0]).strip()
            return str(val).strip() if val else ""

        track_raw = _first("tracknumber").split("/")[0].strip()
        track_num = int(track_raw) if track_raw.isdigit() else None
        return {
            "artist": _first("artist") or _first("albumartist"),
            "album": _first("album"),
            "title": _first("title"),
            "track_num": track_num,
        }
    except Exception:
        return {}


async def scan_local_folder(folder_id: int) -> dict[str, Any]:
    """扫描已挂载本地文件夹内的音频（支持音乐、故事专辑以及绘本图书章节+.txt文本伴读）。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM local_folders WHERE id = ?", (folder_id,))
        folder = await cur.fetchone()
        if not folder:
            raise ValueError("本地目录不存在")
        folder_dict = dict(folder)

    root = Path(folder_dict["folder_path"])
    if not root.exists() or not root.is_dir():
        raise ValueError(f"磁盘目录不可用: {root}")

    audio_files = sorted(
        [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    )
    tracks_added = 0
    chapters_added = 0
    ts = now_iso()

    for af in audio_files:
        rel = af.relative_to(root)
        kind = _infer_media_kind(folder_dict["media_type"], rel.parts[:-1])
        parent_name = af.parent.name if af.parent != root else f"{folder_dict['name']}·精选"
        if kind == "book" and af.parent.name.lower() in ("books", "绘本", "图书"):
            book_title = af.stem
        else:
            book_title = parent_name if kind == "book" else ""

        if kind == "book":
            # 入库到全阶有声书架 books + book_chapters
            async with get_db() as conn:
                cur_b = await conn.execute("SELECT id FROM books WHERE title = ?", (book_title,))
                brow = await cur_b.fetchone()
                if brow:
                    book_id = int(brow["id"])
                else:
                    cur_ins = await conn.execute(
                        """
                        INSERT INTO books (title, author, category, age_stage, english_level, language, description, created_at)
                        VALUES (?, '本地图书导入', 'picture_book', ?, 'Pre_A1', 'zh', ?, ?)
                        """,
                        (book_title, folder_dict["age_stage"], f"从本地目录 {af.parent} 扫描导入", ts),
                    )
                    book_id = int(cur_ins.lastrowid)
                cur_c = await conn.execute(
                    "SELECT id FROM book_chapters WHERE book_id = ? AND title = ?",
                    (book_id, af.stem),
                )
                exists_ch = await cur_c.fetchone()
                cur_num = await conn.execute(
                    "SELECT COALESCE(MAX(chapter_num), 0) FROM book_chapters WHERE book_id = ?",
                    (book_id,),
                )
                next_ch = int((await cur_num.fetchone())[0] or 0) + 1
                await conn.commit()

            if not exists_ch:
                txt_path = af.with_suffix(".txt")
                text_content = txt_path.read_text(encoding="utf-8", errors="ignore").strip() if txt_path.exists() else ""
                dst, dur, norm = await ingest_uploaded_book_chapter(book_id, next_ch, af.stem, af.read_bytes(), af.name)
                async with get_db() as conn:
                    await conn.execute(
                        """
                        INSERT INTO book_chapters
                        (book_id, chapter_num, title, text_content, file_path, duration_sec, lufs_normalized, play_count, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                        """,
                        (book_id, next_ch, af.stem, text_content, str(dst), dur, norm, ts),
                    )
                    await conn.commit()
                chapters_added += 1
        else:
            from app.services.ai_curator import ensure_series_and_season, extract_episode_number_from_title, parse_cn_number

            meaningful_dirs = [
                p for p in rel.parts[:-1] if p.lower() not in ("music", "story", "english", "podcast", "音乐", "故事", "英语", "播客")
            ]
            tags = _read_audio_id3_tags(af) if kind == "music" else {}
            track_title = tags.get("title") or af.stem
            ep_num = tags.get("track_num") or extract_episode_number_from_title(af.stem)

            if len(meaningful_dirs) >= 2:
                # 两级子目录（例如 汪汪队/第2季/01_海上巡逻.mp3）直接映射为三级分类树
                series_title = meaningful_dirs[-2]
                raw_season = meaningful_dirs[-1]
                m_s = re.search(r"第\s*([一二两三四五六七八九十\d]+)\s*([季部辑册单元])", raw_season)
                if m_s:
                    s_num = parse_cn_number(m_s.group(1)) or 1
                    s_label = f"第{s_num}{m_s.group(2)}"
                else:
                    m_s2 = re.search(r"[Ss](?:eason)?\s*0*(\d+)", raw_season)
                    s_num = max(1, int(m_s2.group(1))) if m_s2 else 1
                    s_label = f"第{s_num}季" if m_s2 else raw_season
                _, alb_dict = await ensure_series_and_season(
                    channel=kind,
                    series_title=series_title,
                    season_num=s_num,
                    season_label=s_label,
                )
                alb_id = int(alb_dict["id"])
            elif kind == "music" and tags.get("artist"):
                # 音乐文件含 ID3 歌手标签：自动按 歌手(Series) -> 专辑(Season) -> 单曲 归档
                _, alb_dict = await ensure_series_and_season(
                    channel="music",
                    series_title=tags["artist"],
                    season_num=1,
                    season_label=tags.get("album") or "精选辑",
                    author=tags["artist"],
                )
                alb_id = int(alb_dict["id"])
            else:
                album_title = parent_name
                if parent_name.lower() in ("music", "story", "音乐", "故事"):
                    album_title = f"{folder_dict['name']}·{'故事集' if kind == 'story' else '本地曲库'}"
                async with get_db() as conn:
                    cur_a = await conn.execute("SELECT id FROM media_albums WHERE title = ?", (album_title,))
                    arow = await cur_a.fetchone()
                    if arow:
                        alb_id = int(arow["id"])
                    else:
                        cur_ins = await conn.execute(
                            """
                            INSERT INTO media_albums (title, category, age_stage, english_level, play_mode, description, created_at)
                            VALUES (?, ?, ?, 'Pre_A1', 'sequential', ?, ?)
                            """,
                            (album_title, kind, folder_dict["age_stage"], f"本地目录 {af.parent} 扫描归档", ts),
                        )
                        alb_id = int(cur_ins.lastrowid)
                    await conn.commit()

            before_url = f"localfile://{af.resolve()}"
            async with get_db() as conn:
                cur_chk = await conn.execute(
                    "SELECT id FROM media_tracks WHERE album_id = ? AND source_url = ?",
                    (alb_id, before_url),
                )
                already = await cur_chk.fetchone()
            if not already:
                await insert_normalized_track(alb_id, track_title, af, source_url=before_url, episode_num=ep_num)
                tracks_added += 1

    summary = f"发现 {len(audio_files)} 个本地音频 · 新入库 {tracks_added} 首音轨 / {chapters_added} 个绘本章节"
    async with get_db() as conn:
        await conn.execute(
            "UPDATE local_folders SET last_scanned_at = ?, last_scan_summary = ?, file_count = ? WHERE id = ?",
            (ts, summary, len(audio_files), folder_id),
        )
        await conn.commit()

    await sync_legacy_to_unified_albums()

    return {
        "folder_id": folder_id,
        "total_files": len(audio_files),
        "tracks_added": tracks_added,
        "chapters_added": chapters_added,
        "summary": summary,
    }


async def quick_find_and_ingest_local_keyword(keyword: str) -> dict[str, Any] | None:
    """语音点播前先扫描已挂载磁盘目录看是否有匹配文件名的未入库本地音频。"""
    kw = keyword.strip().lower()
    if not kw:
        return None
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM local_folders ORDER BY id ASC")
        folders = [dict(r) for r in await cur.fetchall()]

    for f in folders:
        root = Path(f["folder_path"])
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS and kw in p.stem.lower():
                rel = p.relative_to(root)
                kind = _infer_media_kind(f["media_type"], rel.parts[:-1])
                if kind == "book":
                    await scan_local_folder(f["id"])
                    async with get_db() as conn:
                        c = await conn.execute(
                            "SELECT c.*, b.title AS book_title FROM book_chapters c JOIN books b ON c.book_id = b.id WHERE LOWER(c.title) LIKE ? LIMIT 1",
                            (f"%{kw}%",),
                        )
                        row = await c.fetchone()
                        if row:
                            d = dict(row)
                            d["media_kind"] = "book_chapter"
                            d["album_title"] = d["book_title"]
                            d["stream_url"] = f"/api/books/chapters/{d['id']}/stream"
                            return d
                else:
                    alb_id, alb_title = await ensure_auto_cache_album(kind, f["age_stage"])
                    tid = await insert_normalized_track(alb_id, p.stem, p, source_url=f"localfile://{p.resolve()}")
                    async with get_db() as conn:
                        c = await conn.execute("SELECT * FROM media_tracks WHERE id = ?", (tid,))
                        row = await c.fetchone()
                        if row:
                            d = dict(row)
                            d["media_kind"] = "track"
                            d["album_title"] = alb_title
                            d["stream_url"] = f"/api/media/tracks/{d['id']}/stream"
                            return d
    return None


async def probe_content_source(source_type: str, url: str) -> dict[str, Any]:
    """探测播客 RSS 源或 yt-dlp 频道合集，返回标题与前 5 条条目预览。"""
    settings = load_settings()
    if source_type == "podcast_rss":
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        feed_title = getattr(feed.feed, "title", "") or "RSS 播客源"
        items = []
        for entry in getattr(feed, "entries", [])[:5]:
            audio_url = ""
            for enc in entry.get("enclosures", []):
                if enc.get("href") or enc.get("url"):
                    audio_url = enc.get("href") or enc.get("url")
                    break
            items.append(
                {
                    "title": entry.get("title", "未命名单集"),
                    "published": entry.get("published", ""),
                    "audio_url": audio_url,
                }
            )
        return {"source_title": feed_title, "count": len(getattr(feed, "entries", [])), "preview": items}

    proc = await asyncio.create_subprocess_exec(
        settings.yt_dlp_bin,
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        "--playlist-end",
        "5",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25.0)
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode(errors="ignore")[-300:] or "无法解析该合集源")
    items = []
    for line in stdout.decode(errors="ignore").splitlines():
        try:
            obj = json.loads(line)
            items.append({"title": obj.get("title", "未命名"), "url": obj.get("webpage_url") or obj.get("url") or ""})
        except Exception:
            continue
    return {"source_title": items[0]["title"] if items else "在线合集源", "count": len(items), "preview": items}


async def list_source_episodes(source_id: int, limit: int = 20) -> dict[str, Any]:
    """获取播客订阅源的最新单集列表，并与本地已缓存曲目对齐合并。"""
    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT s.*, a.title AS album_title
            FROM content_sources s
            LEFT JOIN media_albums a ON s.target_album_id = a.id
            WHERE s.id = ?
            """,
            (source_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise ValueError("内容源不存在")
        src = dict(row)

        local_tracks = []
        if src.get("target_album_id"):
            cur_t = await conn.execute(
                "SELECT * FROM media_tracks WHERE album_id = ? ORDER BY episode_num ASC, id ASC",
                (src["target_album_id"],),
            )
            local_tracks = [dict(t) for t in await cur_t.fetchall()]

    cached_by_guid = {t["external_guid"]: t for t in local_tracks if t.get("external_guid")}
    cached_by_url = {t["source_url"]: t for t in local_tracks if t.get("source_url")}
    cached_by_title = {t["title"]: t for t in local_tracks if t.get("title")}

    episodes: list[dict[str, Any]] = []
    remote_ok = False
    remote_error = ""

    try:
        if src["source_type"] == "podcast_rss":
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(src["url"])
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
            for idx, entry in enumerate(getattr(feed, "entries", [])[:limit], start=1):
                audio_url = ""
                for enc in entry.get("enclosures", []):
                    if enc.get("href") or enc.get("url"):
                        audio_url = enc.get("href") or enc.get("url")
                        break
                if not audio_url:
                    continue
                guid = str(entry.get("id") or entry.get("guid") or audio_url)
                title = entry.get("title", f"第{idx}期")
                local_hit = cached_by_guid.get(guid) or cached_by_url.get(audio_url) or cached_by_title.get(title)
                local_ok = bool(local_hit and local_hit.get("file_path") and Path(local_hit["file_path"]).exists())
                episodes.append(
                    {
                        "guid": guid,
                        "title": title,
                        "published": entry.get("published", ""),
                        "audio_url": audio_url,
                        "cached": local_ok,
                        "local_track_id": local_hit["id"] if local_ok else None,
                        "stream_url": f"/api/media/tracks/{local_hit['id']}/stream" if local_ok else None,
                        "duration_sec": local_hit["duration_sec"] if local_ok else 0,
                    }
                )
            remote_ok = True
    except Exception as exc:
        remote_error = str(exc)[:180]

    # 若远程无法直连，将已本地缓存单集展示给用户可点播
    if not episodes and local_tracks:
        for t in local_tracks:
            if t.get("file_path") and Path(t["file_path"]).exists():
                episodes.append(
                    {
                        "guid": t.get("external_guid") or str(t["id"]),
                        "title": t["title"],
                        "published": t.get("created_at", ""),
                        "audio_url": t.get("source_url") or "",
                        "cached": True,
                        "local_track_id": t["id"],
                        "stream_url": f"/api/media/tracks/{t['id']}/stream",
                        "duration_sec": t["duration_sec"],
                    }
                )

    return {
        "source": src,
        "remote_ok": remote_ok,
        "remote_error": remote_error,
        "episodes": episodes,
    }


async def sync_content_source(source_id: int) -> dict[str, Any]:
    """按 content_sources 规则增量同步未入库节目。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM content_sources WHERE id = ?", (source_id,))
        row = await cur.fetchone()
        if not row:
            raise ValueError("内容源不存在")
        src = dict(row)

        album_id = src.get("target_album_id")
        if not album_id:
            cat = "podcast" if src["source_type"] == "podcast_rss" else "music"
            cur2 = await conn.execute(
                "INSERT INTO media_albums (title, category, age_stage, english_level, play_mode, description, created_at) VALUES (?, ?, ?, ?, 'sequential', ?, ?)",
                (src["name"], cat, src["age_stage"], src["english_level"], f"来自采集源：{src['url']}", now_iso()),
            )
            album_id = int(cur2.lastrowid)
            await conn.execute("UPDATE content_sources SET target_album_id = ? WHERE id = ?", (album_id, source_id))
            await conn.commit()

        cur_g = await conn.execute(
            "SELECT external_guid, source_url FROM media_tracks WHERE album_id = ?",
            (album_id,),
        )
        existing = {r["external_guid"] for r in await cur_g.fetchall() if r["external_guid"]}
        await conn.execute("UPDATE content_sources SET last_status = '正在同步...' WHERE id = ?", (source_id,))
        await conn.commit()

    added = 0
    job_dir = MEDIA_RAW_DIR / f"src_{source_id}_{uuid.uuid4().hex[:6]}"
    job_dir.mkdir(parents=True, exist_ok=True)
    limit = int(src.get("max_items_per_sync") or 5)

    try:
        if src["source_type"] == "podcast_rss":
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(src["url"])
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
            entries = getattr(feed, "entries", [])[:limit]
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                for idx, entry in enumerate(entries, start=1):
                    audio_url = ""
                    for enc in entry.get("enclosures", []):
                        if enc.get("href") or enc.get("url"):
                            audio_url = enc.get("href") or enc.get("url")
                            break
                    if not audio_url:
                        continue
                    guid = str(entry.get("id") or entry.get("guid") or audio_url)
                    if guid in existing:
                        continue
                    title = entry.get("title", f"播客第{idx}期")
                    ext = Path(urlparse(audio_url).path).suffix or ".mp3"
                    raw_f = job_dir / f"ep_{idx}{ext}"
                    r = await client.get(audio_url)
                    r.raise_for_status()
                    raw_f.write_bytes(r.content)
                    await insert_normalized_track(
                        album_id, title, raw_f, source_url=audio_url, source_id=source_id, external_guid=guid
                    )
                    existing.add(guid)
                    added += 1
        else:
            settings = load_settings()
            out_tmpl = str(job_dir / "%(id)s__%(title).60s.%(ext)s")
            proc = await asyncio.create_subprocess_exec(
                settings.yt_dlp_bin,
                "--no-warnings",
                "--extract-audio",
                "--audio-format",
                "mp3",
                "--playlist-end",
                str(limit),
                "--ffmpeg-location",
                str(Path(settings.ffmpeg_bin).parent),
                "-o",
                out_tmpl,
                src["url"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(stderr.decode(errors="ignore")[-300:] or "yt-dlp 同步失败")
            for f in sorted(job_dir.iterdir()):
                if not f.is_file():
                    continue
                vid_id, _, title_part = f.stem.partition("__")
                guid = f"yt:{vid_id}"
                if guid in existing:
                    continue
                await insert_normalized_track(
                    album_id,
                    title_part or f.stem,
                    f,
                    source_url=src["url"],
                    source_id=source_id,
                    external_guid=guid,
                )
                existing.add(guid)
                added += 1

        status_text = f"同步成功：新增 {added} 条（已去重）"
        async with get_db() as conn:
            await conn.execute(
                "UPDATE content_sources SET last_synced_at = ?, last_status = ? WHERE id = ?",
                (now_iso(), status_text, source_id),
            )
            await conn.commit()
        return {"source_id": source_id, "added": added, "status": status_text}
    except Exception as exc:
        err_text = f"同步失败: {str(exc)[:200]}"
        async with get_db() as conn:
            await conn.execute(
                "UPDATE content_sources SET last_synced_at = ?, last_status = ? WHERE id = ?",
                (now_iso(), err_text, source_id),
            )
            await conn.commit()
        raise
    finally:
        for p in job_dir.glob("*"):
            p.unlink(missing_ok=True)
        if job_dir.exists():
            job_dir.rmdir()


async def seed_sample_catalog() -> dict[str, int]:
    """
    管理员按需导入全年龄段（0-3 / 3-6 / 6-9 / 9-12 / 12-18 / 全龄）示范书库、专辑（含真实示范音频）、英语系列课程与播客源模板。
    绝不插入任何假音箱硬件或假家庭成员。
    """
    ts = now_iso()
    books_added = 0
    chapters_added = 0
    albums_added = 0
    tracks_added = 0
    english_added = 0
    sources_added = 0

    await ensure_default_local_folder()

    async with get_db() as conn:
        # 1. 全阶段示范书籍
        sample_books = [
            ("晚安小月亮（幼童感知绘本）", "EchoMind 绘本组", "picture_book", "S1_0_3", "Pre_A1", "zh", "适合 0-3 岁听觉感知与睡前安抚的短篇有声绘本。"),
            ("森林里的为什么（学前百科故事）", "EchoMind 科普组", "picture_book", "S2_3_6", "A1", "bilingual", "适合 3-6 岁小朋友的趣味自然故事与双语小词。"),
            ("The Little Fox's Journey（桥梁故事）", "Reading Studio", "bridge_book", "S3_6_9", "A2", "en", "适合 6-9 岁小学低年级衔接章节听力训练。"),
            ("宇宙漫游指南：太阳系奥秘", "少年科学社", "science", "S4_9_12", "B1", "zh", "适合 9-12 岁高年级少年的天文科普有声读物。"),
            ("Classic Short Essays for Teens", "Literature Hub", "chapter_lit", "S5_12_18", "B2_PLUS", "en", "适合 12-18 岁青少年的原版短篇文学与思辨听力。"),
        ]
        for title, author, cat, stage, elvl, lang, desc in sample_books:
            cur = await conn.execute("SELECT id FROM books WHERE title = ?", (title,))
            if not await cur.fetchone():
                await conn.execute(
                    "INSERT INTO books (title, author, category, age_stage, english_level, language, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (title, author, cat, stage, elvl, lang, desc, ts),
                )
                books_added += 1

        # 2. 全阶段音乐与播客专辑
        sample_albums = [
            ("全龄轻音乐与经典歌单", "music", "经典歌单", "S6_ALL", "adult", "shuffle", "🎵", "经过 -16 LUFS 均衡的家庭共享曲库。"),
            ("少儿科普与历史故事电台", "story", "百科童话", "S3_6_9", "A2", "sequential", "🦊", "适合 6-12 岁睡前或餐后收听的音频故事。"),
            ("英语磨耳朵与听说训练集", "english", "日常口语课", "S2_3_6", "A1", "sequential", "🔤", "可按阶段持续扩充的英语听力音频专辑。"),
            ("家庭播客精选（可配RSS自动同步）", "podcast", "家庭电台", "S6_ALL", "adult", "sequential", "🎙️", "绑定播客 RSS 源后可自动增量追更。"),
        ]
        for title, cat, stag, stage, elvl, mode, emoji, desc in sample_albums:
            cur = await conn.execute("SELECT id FROM media_albums WHERE title = ?", (title,))
            row = await cur.fetchone()
            if not row:
                await conn.execute(
                    "INSERT INTO media_albums (title, category, sub_tag, age_stage, english_level, play_mode, cover_emoji, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (title, cat, stag, stage, elvl, mode, emoji, desc, ts),
                )
                albums_added += 1
            else:
                await conn.execute(
                    "UPDATE media_albums SET sub_tag = CASE WHEN sub_tag='' THEN ? ELSE sub_tag END, cover_emoji = CASE WHEN cover_emoji='' THEN ? ELSE cover_emoji END WHERE id = ?",
                    (stag, emoji, row["id"]),
                )

        # 3. 覆盖 Pre_A1 ~ B2_PLUS 全周期英语词句库
        sample_english = [
            ("Apple", "苹果（感知词）", "Pre_A1", "daily", "大红苹果 Apple，咔嚓咬一口！Apple！"),
            ("Duck", "小鸭子（拟声词）", "Pre_A1", "animal", "小鸭子 Duck！Quack quack quack！"),
            ("Time to brush teeth", "该刷牙啦（日常短句）", "A1", "daily", "Time to brush teeth！我们来刷刷牙齿吧！"),
            ("Let's explore nature", "去探索大自然吧（动作句）", "A1", "nature", "Put on your shoes, let's explore nature!"),
            ("What caused the rainbow?", "彩虹是怎么形成的？", "A2", "science", "Sunlight and raindrops together make a colorful rainbow!"),
            ("Could you summarize the story?", "你能概括一下故事吗？", "B1", "dialogue", "Think about the beginning, the challenge, and how the hero solved it."),
            ("How does curiosity drive science?", "好奇心如何推动科学？", "B2_PLUS", "science", "Every major scientific breakthrough began with someone asking why."),
        ]
        for phrase, zh, stage, cat, prompt in sample_english:
            cur = await conn.execute("SELECT id FROM english_items WHERE phrase = ?", (phrase,))
            if not await cur.fetchone():
                await conn.execute(
                    "INSERT INTO english_items (phrase, zh_meaning, stage, category, audio_prompt, listen_count, mastery_level) VALUES (?, ?, ?, ?, ?, 0, 0)",
                    (phrase, zh, stage, cat, prompt),
                )
                english_added += 1

        await conn.commit()

        cur = await conn.execute("SELECT id, title, language FROM books")
        book_rows = [dict(r) for r in await cur.fetchall()]
        cur = await conn.execute("SELECT id, title FROM media_albums")
        album_map = {r["title"]: r["id"] for r in await cur.fetchall()}

        # 4. 预置播客源模板
        pod_aid = album_map.get("家庭播客精选（可配RSS自动同步）")
        if pod_aid:
            for sname, surl, sstage, selvl, sstatus in [
                ("BBC Global News Podcast（青少年英语新闻）", "https://podcasts.files.bbci.co.uk/p02nq0gn.rss", "S5_12_18", "B2_PLUS", "已配置，点击展开单集即可在线听与缓存"),
                ("科普故事示例播客源（NPR Short Wave）", "https://feeds.npr.org/510351/podcast.xml", "S4_9_12", "B1", "模板已就绪，点击查看单集或同步到本地"),
            ]:
                cur_s = await conn.execute("SELECT id FROM content_sources WHERE name = ?", (sname,))
                if not await cur_s.fetchone():
                    await conn.execute(
                        """
                        INSERT INTO content_sources
                        (name, source_type, url, target_album_id, age_stage, english_level, auto_sync, sync_interval_hours, max_items_per_sync, last_status, created_at)
                        VALUES (?, 'podcast_rss', ?, ?, ?, ?, 0, 24, 3, ?, ?)
                        """,
                        (sname, surl, pod_aid, sstage, selvl, sstatus, ts),
                    )
                    sources_added += 1

        # 5. 示例常驻在线音频地址
        for stitle, surl, scategory, sstage, sdesc in [
            ("小星星 · 经典哄睡儿歌（在线搜播示例）", "https://www.bilibili.com/video/av116436143969318", "music", "S1_0_3", "示例在线曲目：支持边播边护耳缓存到本地曲库"),
        ]:
            cur_os = await conn.execute("SELECT id FROM online_streams WHERE url = ?", (surl,))
            if not await cur_os.fetchone():
                await conn.execute(
                    "INSERT INTO online_streams (title, url, stream_kind, category, age_stage, description, created_at) VALUES (?, ?, 'playlist_url', ?, ?, ?, ?)",
                    (stitle, surl, scategory, sstage, sdesc, ts),
                )
        await conn.commit()

    # 6. 为每本示例书至少生成 1 个真实有声章节
    chapter_texts = {
        "晚安小月亮（幼童感知绘本）": (1, "第1章：小熊找星星", "天黑啦，月亮公公升起来了。小熊在草地上找到了亮晶晶的小星星，晚安。", "zh"),
        "森林里的为什么（学前百科故事）": (1, "第1章：为什么树叶会变黄", "秋天风一吹，树叶里的叶绿素慢慢休息了，Leaves turn yellow and red，像小蝴蝶一样飘下来。", "bilingual"),
        "The Little Fox's Journey（桥梁故事）": (1, "Chapter 1: Across the Stream", "One sunny morning, a curious little fox packed two apples and stepped onto the wooden bridge across the clear blue stream.", "en"),
        "宇宙漫游指南：太阳系奥秘": (1, "第1章：为什么木星那么大", "太阳系里最大的行星是木星，它是一颗气态巨行星，表面那个旋转了几百年的大红斑甚至比整个地球还要大。", "zh"),
        "Classic Short Essays for Teens": (1, "Chapter 1: On Curiosity", "Curiosity is not merely asking what things are, but imagining how unseen connections shape the world around us.", "en"),
    }
    for b in book_rows:
        if b["title"] not in chapter_texts:
            continue
        async with get_db() as c2:
            cur2 = await c2.execute("SELECT COUNT(*) FROM book_chapters WHERE book_id = ?", (b["id"],))
            if (await cur2.fetchone())[0] > 0:
                continue
        cnum, ctitle, ctext, clang = chapter_texts[b["title"]]
        dst, dur, norm = await synthesize_book_chapter_audio(b["id"], cnum, ctitle, ctext, clang)
        async with get_db() as c2:
            await c2.execute(
                """
                INSERT INTO book_chapters (book_id, chapter_num, title, text_content, file_path, duration_sec, lufs_normalized, play_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (b["id"], cnum, ctitle, ctext, str(dst), dur, norm, ts),
            )
            await c2.commit()
        chapters_added += 1

    # 7. 为所有 4 张示范专辑都至少填充 1 首可播 -16 LUFS 示范音频
    music_aid = album_map.get("全龄轻音乐与经典歌单")
    if music_aid:
        async with get_db() as c2:
            cur2 = await c2.execute("SELECT COUNT(*) FROM media_tracks WHERE album_id = ?", (music_aid,))
            if (await cur2.fetchone())[0] == 0:
                demo_mp3_env = os.environ.get("ECHOMIND_DEMO_MP3", "").strip()
                sample_mp3 = Path(demo_mp3_env) if demo_mp3_env else None
                if sample_mp3 and sample_mp3.is_file():
                    await insert_normalized_track(music_aid, f"{sample_mp3.stem}（护耳均衡版）", sample_mp3, source_url="demo://local/sample", episode_num=1)
                else:
                    raw_f = MEDIA_RAW_DIR / "demo_music.mp3"
                    try:
                        await synthesize_speech("欢迎收听家庭全龄音频库示范曲目。", voice="zh-CN-XiaoxiaoNeural", rate="+0%", output_path=raw_f)
                        await insert_normalized_track(music_aid, "家庭音乐库示范曲", raw_f, source_url="demo://music/1", episode_num=1)
                    finally:
                        raw_f.unlink(missing_ok=True)
                tracks_added += 1

    demo_spoken_albums = [
        ("少儿科普与历史故事电台", "第1集：为什么大海是咸的", "小朋友你知道吗？陆地上的岩石里藏着好多盐分，雨水把它们冲进小河，又流到大海里，日积月累，大海就变得咸咸的啦。", "zh-CN-XiaoxiaoNeural", "demo://story/1"),
        ("英语磨耳朵与听说训练集", "Track 1 · Morning Rhythm 英语磨耳朵", "Good morning! Brush your teeth, wash your face, and smile to the bright sun!", "en-US-AriaNeural", "demo://english/1"),
        ("家庭播客精选（可配RSS自动同步）", "先导期 · 家庭播客追更指南", "欢迎来到家庭播客精选专辑！您可在上方播客频道或管理员中心随时添加喜爱的 RSS 节目源并收听缓存单集。", "zh-CN-YunxiNeural", "demo://podcast/1"),
    ]
    for alb_title, tr_title, tr_text, tr_voice, tr_src in demo_spoken_albums:
        aid = album_map.get(alb_title)
        if not aid:
            continue
        async with get_db() as c2:
            cur2 = await c2.execute("SELECT COUNT(*) FROM media_tracks WHERE album_id = ?", (aid,))
            if (await cur2.fetchone())[0] > 0:
                continue
        raw_f = MEDIA_RAW_DIR / f"demo_{aid}.mp3"
        try:
            await synthesize_speech(tr_text, voice=tr_voice, rate="+0%", output_path=raw_f)
            await insert_normalized_track(aid, tr_title, raw_f, source_url=tr_src, episode_num=1)
            tracks_added += 1
        finally:
            raw_f.unlink(missing_ok=True)

    # 8. 同步导入 6 套 24 节全阶英语系列课程，并融合为统一专辑结构
    course_stats = await seed_builtin_english_courses()
    await sync_legacy_to_unified_albums()

    return {
        "books_added": books_added,
        "chapters_added": chapters_added,
        "albums_added": albums_added,
        "tracks_added": tracks_added,
        "english_added": english_added,
        "sources_added": sources_added,
        "courses_added": course_stats["courses_added"],
        "lessons_added": course_stats["lessons_added"],
    }


async def _update_job(
    job_id: int,
    status: str,
    progress_text: str = "",
    error_msg: str = "",
    tracks_added: int | None = None,
) -> None:
    async with get_db() as conn:
        if tracks_added is not None:
            await conn.execute(
                """
                UPDATE download_jobs
                SET status = ?, progress_text = ?, error_msg = ?, tracks_added = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, progress_text, error_msg, tracks_added, now_iso(), job_id),
            )
        else:
            await conn.execute(
                """
                UPDATE download_jobs
                SET status = ?, progress_text = ?, error_msg = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, progress_text, error_msg, now_iso(), job_id),
            )
        await conn.commit()


async def run_yt_dlp_job(job_id: int, url: str, album_id: int, max_items: int = 12) -> None:
    settings = load_settings()
    job_dir = MEDIA_RAW_DIR / f"job_{job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)
    await _update_job(job_id, "running", "正在解析并提取音频流...")

    try:
        out_tmpl = str(job_dir / "%(playlist_index|01)s_%(title).60s.%(ext)s")
        proc = await asyncio.create_subprocess_exec(
            settings.yt_dlp_bin,
            "--no-warnings",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "5",
            "--playlist-end",
            str(max_items),
            "--ffmpeg-location",
            str(Path(settings.ffmpeg_bin).parent),
            "-o",
            out_tmpl,
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="ignore")[-400:] or "yt-dlp 执行失败")

        audio_files = sorted(
            [p for p in job_dir.iterdir() if p.is_file() and p.suffix.lower() in {".mp3", ".m4a", ".wav", ".ogg", ".opus"}]
        )
        if not audio_files:
            raise RuntimeError("未从该链接提取到可用音频文件")

        await _update_job(job_id, "running", f"已抓回 {len(audio_files)} 条音频，正在执行 -16 LUFS 护耳均衡...")
        added = 0
        for f in audio_files:
            clean_title = re.sub(r"^\d+_", "", f.stem)
            await insert_normalized_track(album_id, clean_title, f, source_url=url)
            added += 1

        await _update_job(job_id, "done", f"成功入库并护耳均衡 {added} 首音频", tracks_added=added)
    except Exception as exc:
        await _update_job(job_id, "failed", "抓取失败", error_msg=str(exc)[:400])
    finally:
        for p in job_dir.glob("*"):
            p.unlink(missing_ok=True)
        if job_dir.exists():
            job_dir.rmdir()


async def run_rss_job(job_id: int, rss_url: str, album_id: int, limit: int = 5) -> None:
    job_dir = MEDIA_RAW_DIR / f"rss_{job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)
    await _update_job(job_id, "running", "正在读取播客 RSS 订阅...")

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(rss_url)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

        entries = getattr(feed, "entries", [])[:limit]
        if not entries:
            raise RuntimeError("RSS 中未发现可订阅的节目条目")

        added = 0
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            for idx, entry in enumerate(entries, start=1):
                audio_url = ""
                for enc in entry.get("enclosures", []):
                    href = enc.get("href") or enc.get("url")
                    if href:
                        audio_url = href
                        break
                if not audio_url:
                    continue
                title = entry.get("title", f"播客第{idx}期")
                await _update_job(job_id, "running", f"正在下载并均衡第 {idx}/{len(entries)} 期：{title}")
                ext = Path(urlparse(audio_url).path).suffix or ".mp3"
                raw_file = job_dir / f"ep_{idx}{ext}"
                r = await client.get(audio_url)
                r.raise_for_status()
                raw_file.write_bytes(r.content)
                await insert_normalized_track(album_id, title, raw_file, source_url=audio_url, external_guid=audio_url)
                added += 1

        if added == 0:
            raise RuntimeError("RSS 条目中未包含可下载的音频 enclosure 链接")
        await _update_job(job_id, "done", f"已更新并护耳均衡 {added} 期播客", tracks_added=added)
    except Exception as exc:
        await _update_job(job_id, "failed", "RSS 订阅失败", error_msg=str(exc)[:400])
    finally:
        for p in job_dir.glob("*"):
            p.unlink(missing_ok=True)
        if job_dir.exists():
            job_dir.rmdir()


async def ingest_uploaded_file(album_id: int, filename: str, content: bytes) -> dict:
    MEDIA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix or ".mp3"
    title = Path(filename).stem
    raw_file = MEDIA_RAW_DIR / f"upload_{uuid.uuid4().hex[:8]}{ext}"
    raw_file.write_bytes(content)
    ts = now_iso()

    async with get_db() as conn:
        cur = await conn.execute(
            """
            INSERT INTO download_jobs
            (job_type, source_url, target_album_id, status, progress_text, created_at, updated_at)
            VALUES ('upload', ?, ?, 'running', '正在进行 -16 LUFS 护耳均衡...', ?, ?)
            """,
            (filename, album_id, ts, ts),
        )
        job_id = int(cur.lastrowid)
        await conn.commit()

    try:
        from app.services.ai_curator import extract_episode_number_from_title

        ep_num = extract_episode_number_from_title(title)
        track_id = await insert_normalized_track(album_id, title, raw_file, source_url=f"upload://{filename}", episode_num=ep_num)
        await _update_job(job_id, "done", f"已上传并护耳均衡：{title}", tracks_added=1)
        return {"id": track_id, "job_id": job_id, "track_id": track_id, "title": title}
    except Exception as exc:
        await _update_job(job_id, "failed", "上传音频处理失败", error_msg=str(exc)[:300])
        raise
    finally:
        raw_file.unlink(missing_ok=True)

"""EchoMind 商业级 SQLite 数据库 Schema、全龄段年龄推算与零假数据初始化。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime
import re
from typing import AsyncIterator

import aiosqlite

from app.config import DB_FILE, ensure_directories

AGE_STAGES = ("S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL")
ENGLISH_LEVELS = ("Pre_A1", "A1", "A2", "B1", "B2_PLUS", "adult")

ENGLISH_STAGE_TO_LEVEL = {
    "Pre_A1": "L1",
    "A1": "L2",
    "A2": "L3",
    "B1": "L4",
    "B2_PLUS": "L5",
    "adult": "L5",
}

ENGLISH_LEVEL_TO_STAGE = {
    "L1": "Pre_A1",
    "L2": "A1",
    "L3": "A2",
    "L4": "B1",
    "L5": "B2_PLUS",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def compute_age_months(birth_date: str | None) -> int | None:
    """根据出生年月（YYYY-MM 或 YYYY-MM-DD）动态计算当前月龄。"""
    if not birth_date or not birth_date.strip():
        return None
    parts = birth_date.strip().split("-")
    if len(parts) < 2:
        return None
    try:
        y = int(parts[0])
        m = int(parts[1])
        today = date.today()
        months = (today.year - y) * 12 + (today.month - m)
        return max(0, months)
    except ValueError:
        return None


def compute_age_label(birth_date: str | None) -> str:
    """将出生年月实时格式化为中文易读年龄。"""
    months = compute_age_months(birth_date)
    if months is None:
        return ""
    years, rem = divmod(months, 12)
    if years == 0:
        return f"{rem}个月"
    if rem == 0:
        return f"{years}岁"
    return f"{years}岁{rem}个月"


def recommend_age_stage(birth_date: str | None) -> str:
    """根据出生年月动态推算成长阶段（0岁 -> 18岁+ 全覆盖）。"""
    months = compute_age_months(birth_date)
    if months is None:
        return "S6_ALL"
    if months < 36:
        return "S1_0_3"
    if months < 72:
        return "S2_3_6"
    if months < 108:
        return "S3_6_9"
    if months < 144:
        return "S4_9_12"
    if months <= 216:
        return "S5_12_18"
    return "S6_ALL"


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin', 'user')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS user_sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS family_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    name TEXT NOT NULL UNIQUE,
    nickname TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('child', 'adult')),
    birth_date TEXT NOT NULL DEFAULT '',
    age_stage TEXT NOT NULL DEFAULT 'S6_ALL' CHECK(age_stage IN ('S1_0_3', 'S2_3_6', 'S3_6_9', 'S4_9_12', 'S5_12_18', 'S6_ALL')),
    english_stage TEXT NOT NULL DEFAULT 'Pre_A1' CHECK(english_stage IN ('Pre_A1', 'A1', 'A2', 'B1', 'B2_PLUS', 'adult')),
    tts_voice TEXT NOT NULL,
    tts_rate TEXT NOT NULL DEFAULT '+0%',
    voiceprint_vector TEXT NOT NULL DEFAULT '[]',
    voiceprint_samples INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER REFERENCES family_members(id) ON DELETE CASCADE,
    scope TEXT NOT NULL CHECK(scope IN ('personal', 'family', 'growth')),
    category TEXT NOT NULL DEFAULT 'note',
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    device_type TEXT NOT NULL CHECK(device_type IN ('speaker_xiaoai', 'esp32_robot')),
    room TEXT NOT NULL DEFAULT '未分配房间',
    auth_token TEXT NOT NULL DEFAULT '',
    pair_code TEXT NOT NULL DEFAULT '',
    paired INTEGER NOT NULL DEFAULT 1,
    online INTEGER NOT NULL DEFAULT 0,
    volume INTEGER NOT NULL DEFAULT 50,
    max_volume INTEGER NOT NULL DEFAULT 75,
    wake_word TEXT NOT NULL DEFAULT '你好小音',
    playing_title TEXT NOT NULL DEFAULT '待机中',
    client_ip TEXT NOT NULL DEFAULT '',
    motion_locked INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    capabilities_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS media_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    channel TEXT NOT NULL CHECK(channel IN ('music', 'story', 'english', 'podcast')),
    level_code TEXT NOT NULL DEFAULT '',
    cover_emoji TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    last_album_id INTEGER,
    last_track_id INTEGER,
    last_position_sec REAL NOT NULL DEFAULT 0.0,
    last_played_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(channel, title)
);

CREATE TABLE IF NOT EXISTS media_albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER REFERENCES media_series(id) ON DELETE SET NULL,
    season_num INTEGER NOT NULL DEFAULT 1,
    season_label TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL CHECK(category IN ('music', 'story', 'english', 'podcast')),
    sub_tag TEXT NOT NULL DEFAULT '',
    age_stage TEXT NOT NULL DEFAULT 'S6_ALL' CHECK(age_stage IN ('S1_0_3', 'S2_3_6', 'S3_6_9', 'S4_9_12', 'S5_12_18', 'S6_ALL')),
    english_level TEXT NOT NULL DEFAULT 'Pre_A1' CHECK(english_level IN ('Pre_A1', 'A1', 'A2', 'B1', 'B2_PLUS', 'adult')),
    play_mode TEXT NOT NULL DEFAULT 'sequential' CHECK(play_mode IN ('sequential', 'shuffle')),
    cover_emoji TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'zh',
    is_inbox INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    last_track_id INTEGER,
    last_position_sec REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK(source_type IN ('podcast_rss', 'ytdlp_playlist')),
    url TEXT NOT NULL,
    target_album_id INTEGER REFERENCES media_albums(id) ON DELETE SET NULL,
    age_stage TEXT NOT NULL DEFAULT 'S6_ALL' CHECK(age_stage IN ('S1_0_3', 'S2_3_6', 'S3_6_9', 'S4_9_12', 'S5_12_18', 'S6_ALL')),
    english_level TEXT NOT NULL DEFAULT 'Pre_A1' CHECK(english_level IN ('Pre_A1', 'A1', 'A2', 'B1', 'B2_PLUS', 'adult')),
    auto_sync INTEGER NOT NULL DEFAULT 1,
    sync_interval_hours INTEGER NOT NULL DEFAULT 12,
    max_items_per_sync INTEGER NOT NULL DEFAULT 5,
    last_synced_at TEXT,
    last_status TEXT NOT NULL DEFAULT '尚未同步',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id INTEGER NOT NULL REFERENCES media_albums(id) ON DELETE CASCADE,
    source_id INTEGER REFERENCES content_sources(id) ON DELETE SET NULL,
    external_guid TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    episode_num INTEGER NOT NULL DEFAULT 1,
    duration_sec REAL NOT NULL DEFAULT 0.0,
    file_path TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    text_content TEXT NOT NULL DEFAULT '',
    vocab_json TEXT NOT NULL DEFAULT '[]',
    objective TEXT NOT NULL DEFAULT '',
    completed INTEGER NOT NULL DEFAULT 0,
    last_position_sec REAL NOT NULL DEFAULT 0.0,
    last_played_at TEXT,
    lufs_normalized INTEGER NOT NULL DEFAULT 0,
    play_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    author TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'picture_book' CHECK(category IN ('picture_book', 'bridge_book', 'chapter_lit', 'science', 'english_graded')),
    age_stage TEXT NOT NULL DEFAULT 'S2_3_6' CHECK(age_stage IN ('S1_0_3', 'S2_3_6', 'S3_6_9', 'S4_9_12', 'S5_12_18', 'S6_ALL')),
    english_level TEXT NOT NULL DEFAULT 'Pre_A1' CHECK(english_level IN ('Pre_A1', 'A1', 'A2', 'B1', 'B2_PLUS', 'adult')),
    language TEXT NOT NULL DEFAULT 'zh' CHECK(language IN ('zh', 'en', 'bilingual')),
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS book_chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_num INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    text_content TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL,
    duration_sec REAL NOT NULL DEFAULT 0.0,
    lufs_normalized INTEGER NOT NULL DEFAULT 0,
    play_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reading_progress (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL DEFAULT 0,
    last_chapter_id INTEGER,
    position_sec REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (book_id, member_id)
);

CREATE TABLE IF NOT EXISTS english_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT NOT NULL UNIQUE,
    zh_meaning TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'Pre_A1' CHECK(stage IN ('Pre_A1', 'A1', 'A2', 'B1', 'B2_PLUS')),
    category TEXT NOT NULL DEFAULT 'daily' CHECK(category IN ('daily', 'animal', 'nature', 'science', 'dialogue')),
    audio_prompt TEXT NOT NULL,
    listen_count INTEGER NOT NULL DEFAULT 0,
    mastery_level INTEGER NOT NULL DEFAULT 0,
    last_played_at TEXT
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    cron_time TEXT NOT NULL,
    days_of_week TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7',
    task_type TEXT NOT NULL CHECK(task_type IN ('play_album', 'play_book', 'english_immersion', 'bedtime_story', 'quiet_mode')),
    target_device_id TEXT REFERENCES devices(id) ON DELETE SET NULL,
    album_id INTEGER REFERENCES media_albums(id) ON DELETE SET NULL,
    book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    target_volume INTEGER NOT NULL DEFAULT 50,
    max_episodes INTEGER NOT NULL DEFAULT 1,
    fade_out INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL CHECK(job_type IN ('yt_dlp', 'rss', 'upload', 'tts_seed', 'source_sync')),
    source_url TEXT NOT NULL DEFAULT '',
    target_album_id INTEGER REFERENCES media_albums(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'done', 'failed')),
    progress_text TEXT NOT NULL DEFAULT '',
    error_msg TEXT NOT NULL DEFAULT '',
    tracks_added INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interaction_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL DEFAULT 'web-console',
    speaker_member_id INTEGER REFERENCES family_members(id) ON DELETE SET NULL,
    speaker_name TEXT NOT NULL DEFAULT '儿童安全模式',
    speaker_confidence REAL NOT NULL DEFAULT 0.0,
    safety_mode TEXT NOT NULL DEFAULT 'child_safe',
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    played_track_title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS local_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    folder_path TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL DEFAULT 'auto' CHECK(media_type IN ('auto', 'music', 'story', 'book')),
    age_stage TEXT NOT NULL DEFAULT 'S6_ALL' CHECK(age_stage IN ('S1_0_3', 'S2_3_6', 'S3_6_9', 'S4_9_12', 'S5_12_18', 'S6_ALL')),
    last_scanned_at TEXT,
    last_scan_summary TEXT NOT NULL DEFAULT '尚未扫描',
    file_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS online_streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    stream_kind TEXT NOT NULL DEFAULT 'direct_audio' CHECK(stream_kind IN ('direct_audio', 'playlist_url')),
    category TEXT NOT NULL DEFAULT 'music' CHECK(category IN ('music', 'story', 'english', 'podcast')),
    age_stage TEXT NOT NULL DEFAULT 'S6_ALL' CHECK(age_stage IN ('S1_0_3', 'S2_3_6', 'S3_6_9', 'S4_9_12', 'S5_12_18', 'S6_ALL')),
    description TEXT NOT NULL DEFAULT '',
    cached_track_id INTEGER REFERENCES media_tracks(id) ON DELETE SET NULL,
    play_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS english_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    subtitle TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT 'Pre_A1' CHECK(stage IN ('Pre_A1', 'A1', 'A2', 'B1', 'B2_PLUS')),
    age_stage TEXT NOT NULL DEFAULT 'S2_3_6' CHECK(age_stage IN ('S1_0_3', 'S2_3_6', 'S3_6_9', 'S4_9_12', 'S5_12_18', 'S6_ALL')),
    theme TEXT NOT NULL DEFAULT 'daily',
    cover_emoji TEXT NOT NULL DEFAULT '📘',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS english_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES english_courses(id) ON DELETE CASCADE,
    lesson_num INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    objective TEXT NOT NULL DEFAULT '',
    vocab_json TEXT NOT NULL DEFAULT '[]',
    dialogue_script TEXT NOT NULL DEFAULT '',
    audio_path TEXT NOT NULL DEFAULT '',
    duration_sec REAL NOT NULL DEFAULT 0.0,
    listen_count INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    last_studied_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL CHECK(channel IN ('music', 'story', 'english', 'podcast')),
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 10,
    created_at TEXT NOT NULL,
    UNIQUE(channel, name)
);
"""

DEFAULT_CATEGORY_TAGS: list[tuple[str, str, int]] = [
    ("music", "哄睡轻音乐", 1),
    ("music", "童谣律动", 2),
    ("music", "经典歌单", 3),
    ("music", "古典熏陶", 4),
    ("story", "睡前绘本", 1),
    ("story", "桥梁章节书", 2),
    ("story", "百科童话", 3),
    ("story", "名著文学", 4),
    ("english", "零基础韵律", 1),
    ("english", "日常口语课", 2),
    ("english", "自然科普课", 3),
    ("english", "故事与思辨", 4),
    ("podcast", "科学百科", 1),
    ("podcast", "英语新闻", 2),
    ("podcast", "历史文化", 3),
    ("podcast", "家庭电台", 4),
]


async def _ensure_table_columns(conn: aiosqlite.Connection, table: str, col_defs: list[tuple[str, str]]) -> None:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    existing = {r["name"] for r in await cur.fetchall()}
    for col_name, col_sql in col_defs:
        if col_name not in existing:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_sql}")


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """获取异步 SQLite 连接。"""
    ensure_directories()
    conn = await aiosqlite.connect(str(DB_FILE))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        await conn.close()


def _default_season_label(channel: str, season_num: int) -> str:
    if channel == "story":
        return f"第{season_num}季"
    if channel == "english":
        return f"第{season_num}单元"
    if channel == "podcast":
        return f"第{season_num}季"
    return "精选辑" if season_num == 1 else f"专辑 {season_num}"


def _default_channel_emoji(channel: str) -> str:
    return {"story": "📖", "music": "🎵", "english": "🔤", "podcast": "🎙️"}.get(channel, "🎵")


def _parse_series_and_season_from_title(title: str, channel: str) -> tuple[str, int, str]:
    """从旧专辑标题智能解析一级系列名与二级季/单元号。"""
    t = title.strip()
    m = re.search(r"[\s·\-—_]*第\s*(\d+)\s*([季辑部册单元])\s*$", t)
    if m:
        num = max(1, int(m.group(1)))
        unit = m.group(2)
        base = t[: m.start()].strip() or t
        return base, num, f"第{num}{unit}"
    m2 = re.search(r"[\s·\-—_]*[Ss](?:eason)?\s*(\d+)\s*$", t)
    if m2:
        num = max(1, int(m2.group(1)))
        base = t[: m2.start()].strip() or t
        return base, num, f"第{num}季"
    return t, 1, _default_season_label(channel, 1)


async def _backfill_series_for_orphan_albums(conn: aiosqlite.Connection) -> None:
    """幂等将尚未绑定 series_id 的已有专辑平滑归入一级 media_series（零破坏旧数据）。"""
    ts = now_iso()
    cur = await conn.execute(
        "SELECT * FROM media_albums WHERE series_id IS NULL ORDER BY id ASC"
    )
    orphans = [dict(r) for r in await cur.fetchall()]
    for alb in orphans:
        if int(alb.get("is_inbox") or 0) == 1:
            continue
        channel = alb["category"]
        series_title, season_num, season_label = _parse_series_and_season_from_title(alb["title"], channel)
        level_code = (
            ENGLISH_STAGE_TO_LEVEL.get(alb.get("english_level") or "Pre_A1", "L1")
            if channel == "english"
            else (alb.get("sub_tag") or "")
        )
        emoji = alb.get("cover_emoji") or _default_channel_emoji(channel)

        cur_s = await conn.execute(
            "SELECT * FROM media_series WHERE channel = ? AND title = ?",
            (channel, series_title),
        )
        srow = await cur_s.fetchone()
        if srow:
            series_id = int(srow["id"])
        else:
            cur_ins = await conn.execute(
                """
                INSERT INTO media_series
                (title, channel, level_code, cover_emoji, author, description, last_album_id, last_track_id, last_position_sec, last_played_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    series_title,
                    channel,
                    level_code,
                    emoji,
                    alb.get("author") or "",
                    alb.get("description") or "",
                    alb["id"] if alb.get("last_track_id") else None,
                    alb.get("last_track_id"),
                    float(alb.get("last_position_sec") or 0.0),
                    ts if alb.get("last_track_id") else None,
                    alb.get("created_at") or ts,
                ),
            )
            series_id = int(cur_ins.lastrowid)

        final_snum = int(alb.get("season_num") or season_num or 1)
        final_slabel = (alb.get("season_label") or "").strip() or season_label
        await conn.execute(
            "UPDATE media_albums SET series_id = ?, season_num = ?, season_label = ? WHERE id = ?",
            (series_id, final_snum, final_slabel, alb["id"]),
        )


async def init_db() -> None:
    """初始化商业级数据库 Schema 与标准分类字典（严格零初始假设备/假成员/假专辑）。"""
    ts = now_iso()
    async with get_db() as conn:
        await conn.executescript(SCHEMA_SQL)
        await _ensure_table_columns(
            conn,
            "media_albums",
            [
                ("series_id", "INTEGER REFERENCES media_series(id) ON DELETE SET NULL"),
                ("season_num", "INTEGER NOT NULL DEFAULT 1"),
                ("season_label", "TEXT NOT NULL DEFAULT ''"),
                ("sub_tag", "TEXT NOT NULL DEFAULT ''"),
                ("cover_emoji", "TEXT NOT NULL DEFAULT ''"),
                ("author", "TEXT NOT NULL DEFAULT ''"),
                ("language", "TEXT NOT NULL DEFAULT 'zh'"),
                ("is_inbox", "INTEGER NOT NULL DEFAULT 0"),
            ],
        )
        await _ensure_table_columns(
            conn,
            "media_tracks",
            [
                ("text_content", "TEXT NOT NULL DEFAULT ''"),
                ("vocab_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("objective", "TEXT NOT NULL DEFAULT ''"),
                ("completed", "INTEGER NOT NULL DEFAULT 0"),
                ("last_position_sec", "REAL NOT NULL DEFAULT 0.0"),
                ("last_played_at", "TEXT"),
            ],
        )
        cur = await conn.execute("SELECT COUNT(*) FROM category_tags")
        if int((await cur.fetchone())[0] or 0) == 0:
            for ch, tname, s_order in DEFAULT_CATEGORY_TAGS:
                await conn.execute(
                    "INSERT OR IGNORE INTO category_tags (channel, name, sort_order, created_at) VALUES (?, ?, ?, ?)",
                    (ch, tname, s_order, ts),
                )
        await _backfill_series_for_orphan_albums(conn)
        await conn.commit()

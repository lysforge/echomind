"""AI 自动分类整理、语音/后台一键全网采集、三级进度记忆与音箱完成播报引擎。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.config import MEDIA_RAW_DIR, load_settings
from app.db import (
    ENGLISH_LEVEL_TO_STAGE,
    ENGLISH_STAGE_TO_LEVEL,
    _default_channel_emoji,
    _default_season_label,
    get_db,
    now_iso,
)
from app.gateways.manager import device_manager
from app.services.collector import (
    insert_normalized_track,
    search_online_audio,
)
from app.services.music_dl import (
    build_upstream_download_url,
    check_music_dl_health,
    cloud_search,
    normalize_music_dl_base,
    try_switch_source,
)
from app.services.tts_asr import synthesize_speech

_CURATOR_BG_TASKS: set[asyncio.Task] = set()

_CN_DIGIT = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def parse_cn_number(raw: str | int | None) -> int | None:
    """将阿拉伯数字或常见中文数字（一~九十九，如 十二、二十五、两）转为正整数。"""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    s = str(raw).strip()
    if not s:
        return None
    if s.isdigit():
        val = int(s)
        return val if val > 0 else None
    if s == "十":
        return 10
    if "十" in s:
        parts = s.split("十", 1)
        tens = 1 if not parts[0] else _CN_DIGIT.get(parts[0], 0)
        ones = 0 if not parts[1] else _CN_DIGIT.get(parts[1], 0)
        val = tens * 10 + ones
        return val if val > 0 else None
    if len(s) == 1 and s in _CN_DIGIT:
        val = _CN_DIGIT[s]
        return val if val > 0 else None
    # 逐位兜底，例如 "一二"
    digits = [_CN_DIGIT.get(ch) for ch in s]
    if all(d is not None for d in digits):
        val = int("".join(str(d) for d in digits))
        return val if val > 0 else None
    return None


def extract_episode_number_from_title(title: str) -> int | None:
    """从单集/音轨标题中智能提取集号（支持 第5集 / 第三集 / EP08 / S02E05 / 05-标题）。"""
    t = title.strip()
    if not t:
        return None
    m1 = re.search(r"第\s*([一二两三四五六七八九十\d]+)\s*[集章课期话回首]", t)
    if m1:
        return parse_cn_number(m1.group(1))
    m2 = re.search(r"(?:[Ss]\d+\s*)?[Ee][Pp]?\s*0*(\d+)", t)
    if m2:
        return int(m2.group(1))
    m3 = re.match(r"^0*(\d{1,3})[\s._\-—:：]+", t)
    if m3:
        return int(m3.group(1))
    return None


def _rule_classify_request(
    query: str,
    channel_hint: str | None = None,
    sample_titles: list[str] | None = None,
) -> dict[str, Any]:
    """高精度本地规则分类器（零延迟、免 API Key 兜底）。"""
    raw = query.strip()
    combined = f"{raw} {' '.join(sample_titles or [])}"
    lower = combined.lower()

    # 1. 提取季/单元号
    season_num = 1
    season_unit = ""
    cleaned = raw

    m_season = re.search(r"第\s*([一二两三四五六七八九十\d]+)\s*([季部辑册单元])", cleaned)
    if m_season:
        parsed_s = parse_cn_number(m_season.group(1))
        if parsed_s:
            season_num = parsed_s
        season_unit = m_season.group(2)
        cleaned = (cleaned[: m_season.start()] + cleaned[m_season.end() :]).strip()
    else:
        m_s_en = re.search(r"\b[Ss](?:eason)?\s*0*(\d+)\b", cleaned)
        if m_s_en:
            season_num = max(1, int(m_s_en.group(1)))
            season_unit = "季"
            cleaned = (cleaned[: m_s_en.start()] + cleaned[m_s_en.end() :]).strip()

    # 2. 提取英语等级 L1~L5
    level_code = ""
    m_lvl = re.search(r"\b[Ll]([1-5])\b", combined)
    if m_lvl:
        level_code = f"L{m_lvl.group(1)}"
        cleaned = re.sub(r"\b[Ll][1-5]\b", "", cleaned).strip()
    elif any(k in combined for k in ("一级", "零基础", "磨耳朵", "Pre-A1", "pre_a1", "启蒙一")):
        level_code = "L1"
    elif any(k in combined for k in ("二级", "拼读", "phonics", "日常短句", "A1")):
        level_code = "L2"
    elif any(k in combined for k in ("三级", "分级绘本", "牛津树", "raz", "桥梁", "A2")):
        level_code = "L3"
    elif any(k in combined for k in ("四级", "章节故事", "B1")):
        level_code = "L4"
    elif any(k in combined for k in ("五级", "原版进阶", "B2")):
        level_code = "L5"

    # 3. 判定一级频道
    channel = channel_hint if channel_hint in ("story", "music", "english", "podcast") else ""
    if not channel:
        if any(
            k in lower
            for k in (
                "英语",
                "英文",
                "english",
                "phonics",
                "自然拼读",
                "磨耳朵",
                "牛津树",
                "raz",
                "super simple",
                "peppa",
                "绘本英语",
                "启蒙英语",
            )
        ):
            channel = "english"
        elif any(k in lower for k in ("播客", "电台", "podcast", "新闻", "财经", "脱口秀", "访谈", "专栏")):
            channel = "podcast"
        elif any(
            k in lower
            for k in (
                "故事",
                "有声书",
                "绘本",
                "睡前",
                "汪汪队",
                "小猪佩奇",
                "西游记",
                "海底小纵队",
                "奥特曼",
                "凯叔",
                "童话",
                "寓言",
                "三国",
                "百科故事",
                "米小圈",
                "超级飞侠",
                "恐龙故事",
                "第1季",
                "第2季",
                "第3季",
                "第一季",
                "第二季",
                "第三季",
            )
        ):
            channel = "story"
        elif any(k in lower for k in ("歌", "音乐", "儿歌", "童谣", "专辑", "歌单", "轻音乐", "钢琴", "古典", "民谣", "流行", "摇滚", "单曲")):
            channel = "music"
        else:
            channel = "story" if season_unit in ("季", "部", "册") else "music"

    if channel == "english" and not level_code:
        level_code = "L1"

    # 4. 提炼干净的一级系列名
    cleaned = re.sub(
        r"(的音频故事|的有声故事|音频故事|睡前故事|儿童故事|的故事|故事合集|故事全集|的歌曲|的歌|歌曲合集|全集|合集|音频|英语启蒙|启蒙英语|启蒙课程|播客节目|播客)$",
        "",
        cleaned,
    ).strip(" ·-_—《》\"'，,。")
    cleaned = re.sub(r"^(一些|几集|几首|一套|全套|最新|经典)\s*", "", cleaned).strip()
    series_title = cleaned or raw[:24] or "新建合集"

    if season_unit:
        season_label = f"第{season_num}{season_unit}"
    else:
        season_label = _default_season_label(channel, season_num)

    emoji_hints = [
        ("汪汪队", "🐶"),
        ("佩奇", "🐷"),
        ("西游", "🐒"),
        ("恐龙", "🦕"),
        ("海洋", "🐳"),
        ("海底", "🐙"),
        ("飞侠", "✈️"),
        ("睡前", "🌙"),
        ("哄睡", "🌙"),
        ("钢琴", "🎹"),
        ("古典", "🎻"),
        ("儿歌", "🧸"),
        ("英语", "🔤"),
        ("科学", "🔬"),
        ("历史", "🏛️"),
    ]
    cover_emoji = _default_channel_emoji(channel)
    for kw, em in emoji_hints:
        if kw in combined:
            cover_emoji = em
            break

    if not level_code:
        level_code = {"story": "故事连载", "music": "音乐合集", "podcast": "播客专栏"}.get(channel, "")

    return {
        "channel": channel,
        "series_title": series_title,
        "season_num": season_num,
        "season_label": season_label,
        "level_code": level_code,
        "cover_emoji": cover_emoji,
        "used_llm": False,
    }


async def classify_media_request(
    query: str,
    channel_hint: str | None = None,
    sample_titles: list[str] | None = None,
) -> dict[str, Any]:
    """优先调用已配置大模型进行结构化自动分类，未配置或超时则秒切高精度本地规则引擎。"""
    fallback = _rule_classify_request(query, channel_hint=channel_hint, sample_titles=sample_titles)
    settings = load_settings()
    if not (settings.llm_api_key.strip() or settings.llm_provider == "ollama"):
        return fallback

    prompt = (
        "你是家庭智能音箱媒体库自动分类专家。请将用户的采集需求归类为严格 JSON 对象，不要输出其他任何文字：\n"
        '{"channel":"story|music|english|podcast","series_title":"一级系列/歌手/课程名","season_num":1,'
        '"season_label":"第1季/精选辑/第1单元","level_code":"英语填L1-L5其余填简短标签","cover_emoji":"单个合适emoji"}\n'
        f"用户请求：{query}\n"
        f"指定频道提示：{channel_hint or '无'}\n"
        f"参考标题列表：{json.dumps((sample_titles or [])[:5], ensure_ascii=False)}"
    )
    try:
        url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key.strip():
            headers["Authorization"] = f"Bearer {settings.llm_api_key.strip()}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers=headers,
                json={
                    "model": settings.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 180,
                },
            )
            resp.raise_for_status()
            raw_text = (resp.json()["choices"][0]["message"].get("content") or "").strip()
            m_json = re.search(r"\{[\s\S]*\}", raw_text)
            if not m_json:
                return fallback
            parsed = json.loads(m_json.group(0))
            ch = parsed.get("channel") if parsed.get("channel") in ("story", "music", "english", "podcast") else fallback["channel"]
            if channel_hint in ("story", "music", "english", "podcast"):
                ch = channel_hint
            stitle = str(parsed.get("series_title") or "").strip() or fallback["series_title"]
            snum = parse_cn_number(parsed.get("season_num")) or fallback["season_num"]
            slabel = str(parsed.get("season_label") or "").strip() or _default_season_label(ch, snum)
            lvl = str(parsed.get("level_code") or "").strip() or fallback["level_code"]
            if ch == "english" and lvl not in ("L1", "L2", "L3", "L4", "L5"):
                lvl = fallback["level_code"] if fallback["level_code"] in ("L1", "L2", "L3", "L4", "L5") else "L1"
            emoji = str(parsed.get("cover_emoji") or "").strip() or fallback["cover_emoji"]
            return {
                "channel": ch,
                "series_title": stitle,
                "season_num": snum,
                "season_label": slabel,
                "level_code": lvl,
                "cover_emoji": emoji,
                "used_llm": True,
            }
    except Exception:
        return fallback


async def ensure_series_and_season(
    *,
    channel: str,
    series_title: str,
    season_num: int = 1,
    season_label: str = "",
    level_code: str = "",
    cover_emoji: str = "",
    author: str = "",
    description: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """幂等创建或复用「一级系列 media_series -> 二级季/专辑 media_albums」。"""
    ch = channel if channel in ("story", "music", "english", "podcast") else "story"
    stitle = series_title.strip() or "新建合集"
    snum = max(1, int(season_num or 1))
    slabel = season_label.strip() or _default_season_label(ch, snum)
    emoji = cover_emoji.strip() or _default_channel_emoji(ch)
    eng_stage = ENGLISH_LEVEL_TO_STAGE.get(level_code, "Pre_A1") if ch == "english" else "Pre_A1"
    ts = now_iso()

    async with get_db() as conn:
        # 1. 查找或创建一级系列
        cur_s = await conn.execute(
            "SELECT * FROM media_series WHERE channel = ? AND title = ?",
            (ch, stitle),
        )
        srow = await cur_s.fetchone()
        if srow:
            series = dict(srow)
            series_id = int(series["id"])
        else:
            cur_ins = await conn.execute(
                """
                INSERT INTO media_series
                (title, channel, level_code, cover_emoji, author, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (stitle, ch, level_code, emoji, author.strip(), description.strip(), ts),
            )
            series_id = int(cur_ins.lastrowid)
            cur_s2 = await conn.execute("SELECT * FROM media_series WHERE id = ?", (series_id,))
            series = dict(await cur_s2.fetchone())

        # 2. 查找或创建该系列下的指定季/专辑
        cur_a = await conn.execute(
            "SELECT * FROM media_albums WHERE series_id = ? AND season_num = ? ORDER BY id ASC LIMIT 1",
            (series_id, snum),
        )
        arow = await cur_a.fetchone()
        if arow:
            album = dict(arow)
        else:
            base_album_title = f"{stitle} · {slabel}"
            album_title = base_album_title
            # 防止 UNIQUE(title) 冲突
            suffix = 2
            while True:
                chk = await conn.execute("SELECT id FROM media_albums WHERE title = ?", (album_title,))
                if not await chk.fetchone():
                    break
                album_title = f"{base_album_title} ({suffix})"
                suffix += 1

            cur_ai = await conn.execute(
                """
                INSERT INTO media_albums
                (series_id, season_num, season_label, title, category, sub_tag, age_stage, english_level,
                 play_mode, cover_emoji, author, language, is_inbox, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'S6_ALL', ?, 'sequential', ?, ?, ?, 0, ?, ?)
                """,
                (
                    series_id,
                    snum,
                    slabel,
                    album_title,
                    ch,
                    level_code or slabel,
                    eng_stage,
                    emoji,
                    author.strip(),
                    "en" if ch == "english" else "zh",
                    description.strip(),
                    ts,
                ),
            )
            aid = int(cur_ai.lastrowid)
            cur_a2 = await conn.execute("SELECT * FROM media_albums WHERE id = ?", (aid,))
            album = dict(await cur_a2.fetchone())

        await conn.commit()
    return series, album


async def update_playback_progress(
    album_id: int,
    track_id: int,
    position_sec: float = 0.0,
    increment_play: bool = False,
) -> dict[str, Any]:
    """同步更新三级续播进度：单集(track) -> 季/专辑(album) -> 系列合集(series)。"""
    ts = now_iso()
    pos = max(0.0, float(position_sec or 0.0))
    series_id: int | None = None
    async with get_db() as conn:
        if increment_play:
            await conn.execute(
                "UPDATE media_tracks SET play_count = play_count + 1, last_position_sec = ?, last_played_at = ? WHERE id = ?",
                (pos, ts, track_id),
            )
        else:
            await conn.execute(
                "UPDATE media_tracks SET last_position_sec = ?, last_played_at = ? WHERE id = ?",
                (pos, ts, track_id),
            )
        await conn.execute(
            "UPDATE media_albums SET last_track_id = ?, last_position_sec = ? WHERE id = ?",
            (track_id, pos, album_id),
        )
        cur_a = await conn.execute("SELECT series_id FROM media_albums WHERE id = ?", (album_id,))
        arow = await cur_a.fetchone()
        if arow and arow["series_id"]:
            series_id = int(arow["series_id"])
            await conn.execute(
                """
                UPDATE media_series
                SET last_album_id = ?, last_track_id = ?, last_position_sec = ?, last_played_at = ?
                WHERE id = ?
                """,
                (album_id, track_id, pos, ts, series_id),
            )
        await conn.commit()
    return {
        "album_id": album_id,
        "series_id": series_id,
        "track_id": track_id,
        "position_sec": pos,
        "updated_at": ts,
    }


async def _download_ytdlp_single_item(url: str, album_id: int, title_hint: str = "") -> int | None:
    """使用 yt-dlp 下载单个音视频链接音频并校准入库。"""
    settings = load_settings()
    MEDIA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = MEDIA_RAW_DIR / f"ai_dl_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.yt_dlp_bin,
            "--no-warnings",
            "--no-playlist",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "128K",
            "-o",
            str(tmp_dir / "%(title).80s.%(ext)s"),
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=90.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return None

        files = sorted([p for p in tmp_dir.glob("*") if p.is_file() and p.stat().st_size > 512])
        if not files:
            return None
        f = files[0]
        final_title = title_hint.strip() or f.stem
        ep = extract_episode_number_from_title(final_title)
        tid = await insert_normalized_track(
            album_id=album_id,
            title=final_title,
            raw_file=f,
            source_url=url,
            episode_num=ep,
        )
        return tid
    finally:
        for fp in tmp_dir.glob("*"):
            fp.unlink(missing_ok=True)
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


async def _download_cloud_music_songs(query: str, album_id: int, max_items: int) -> tuple[int, list[str]]:
    """当音乐引擎可用时，通过 go-music-dl 多源搜索并下载歌曲入库。"""
    base = normalize_music_dl_base()
    if not base:
        return 0, []
    health = await check_music_dl_health(base)
    if not health.get("healthy"):
        return 0, []

    res = await cloud_search(q=query, search_type="song", page=1)
    songs = (res.get("songs") or [])[:max_items]
    if not songs:
        return 0, []

    MEDIA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    added = 0
    titles: list[str] = []
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
        for song in songs:
            name = str(song.get("name") or "").strip()
            artist = str(song.get("artist") or "").strip()
            display_title = f"{name} - {artist}" if artist else (name or "云端歌曲")
            target_url = build_upstream_download_url(song, base_url=base, stream_only=False)
            raw_tmp = MEDIA_RAW_DIR / f"ai_music_{uuid.uuid4().hex[:8]}.mp3"
            try:
                resp = await client.get(target_url, headers={"X-Requested-With": "XMLHttpRequest"})
                if resp.status_code >= 400 and name:
                    alt = await try_switch_source(name=name, artist=artist, current_source=str(song.get("source") or ""), base_url=base)
                    if alt:
                        resp = await client.get(
                            build_upstream_download_url(alt, base_url=base, stream_only=False),
                            headers={"X-Requested-With": "XMLHttpRequest"},
                        )
                if resp.status_code < 400 and len(resp.content) > 2048:
                    raw_tmp.write_bytes(resp.content)
                    await insert_normalized_track(
                        album_id=album_id,
                        title=display_title,
                        raw_file=raw_tmp,
                        source_url=f"cloud_music://{song.get('source')}/{song.get('id')}",
                        external_guid=f"cloud:{song.get('source')}:{song.get('id')}",
                    )
                    added += 1
                    titles.append(display_title)
            except Exception:
                continue
            finally:
                raw_tmp.unlink(missing_ok=True)
    return added, titles


CHANNEL_LABELS_ZH = {
    "story": "故事书架",
    "music": "音乐曲库",
    "english": "英语启蒙",
    "podcast": "播客电台",
}


async def run_ai_collect_job(
    *,
    job_id: int,
    query: str,
    channel_hint: str | None = None,
    target_series_id: int | None = None,
    target_album_id: int | None = None,
    max_items: int = 5,
    device_id: str = "",
    notify_speaker: bool = True,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+0%",
) -> dict[str, Any]:
    """执行全自动采集 + AI 分类入库 + 音箱语音主动播报结果 + 网页实时通知。"""
    ts_start = now_iso()
    limit = max(1, min(int(max_items or 5), 20))

    async def _set_job(status: str, progress: str, tracks_added: int = 0, error_msg: str = "", album_id: int | None = None):
        async with get_db() as conn:
            if album_id is not None:
                await conn.execute(
                    """
                    UPDATE download_jobs
                    SET status = ?, progress_text = ?, tracks_added = ?, error_msg = ?, target_album_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, progress, tracks_added, error_msg, album_id, now_iso(), job_id),
                )
            else:
                await conn.execute(
                    """
                    UPDATE download_jobs
                    SET status = ?, progress_text = ?, tracks_added = ?, error_msg = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, progress, tracks_added, error_msg, now_iso(), job_id),
                )
            await conn.commit()

    await _set_job("running", f"正在智能分析并全网搜索「{query}」...")

    # 1. AI 分类（若指定了目标专辑或目标系列则尊重目标归属）
    classification = await classify_media_request(query, channel_hint=channel_hint)
    series: dict[str, Any] | None = None
    album: dict[str, Any] | None = None

    async with get_db() as conn:
        if target_album_id:
            cur_a = await conn.execute("SELECT * FROM media_albums WHERE id = ?", (target_album_id,))
            ar = await cur_a.fetchone()
            if ar:
                album = dict(ar)
                if album.get("series_id"):
                    cur_s = await conn.execute("SELECT * FROM media_series WHERE id = ?", (album["series_id"],))
                    sr = await cur_s.fetchone()
                    if sr:
                        series = dict(sr)
        elif target_series_id:
            cur_s = await conn.execute("SELECT * FROM media_series WHERE id = ?", (target_series_id,))
            sr = await cur_s.fetchone()
            if sr:
                series = dict(sr)
                classification["channel"] = series["channel"]
                classification["series_title"] = series["title"]
                classification["level_code"] = series.get("level_code") or classification["level_code"]

    if album is None:
        series, album = await ensure_series_and_season(
            channel=classification["channel"],
            series_title=classification["series_title"],
            season_num=classification["season_num"],
            season_label=classification["season_label"],
            level_code=classification["level_code"],
            cover_emoji=classification["cover_emoji"],
        )

    assert album is not None
    album_id = int(album["id"])
    series_id = int(series["id"]) if series else album.get("series_id")
    series_title = series["title"] if series else album["title"]
    season_label = album.get("season_label") or classification["season_label"]
    channel = album["category"]
    channel_zh = CHANNEL_LABELS_ZH.get(channel, "媒体库")

    await _set_job(
        "running",
        f"AI 已分类为「{channel_zh} → {series_title} → {season_label}」，开始全网采集...",
        album_id=album_id,
    )

    tracks_added = 0
    collected_titles: list[str] = []
    err_detail = ""

    try:
        # 2. 音乐频道优先走多源云音乐引擎（若在线可用）
        if channel == "music":
            m_added, m_titles = await _download_cloud_music_songs(query, album_id, limit)
            tracks_added += m_added
            collected_titles.extend(m_titles)

        # 3. 故事/英语/播客或云音乐未命中时走全网音频搜索 + yt-dlp 下载
        if tracks_added == 0 and os.getenv("ECHOMIND_DISABLE_ONLINE_SEARCH") != "1":
            search_q = query.strip()
            if channel == "story" and not any(k in search_q for k in ("故事", "音频", "有声")):
                search_q = f"{search_q} 故事 音频"
            candidates = await search_online_audio(search_q, limit=limit)
            for idx, item in enumerate(candidates[:limit], start=1):
                item_url = str(item.get("url") or "").strip()
                item_title = str(item.get("title") or "").strip()
                if not item_url:
                    continue
                await _set_job(
                    "running",
                    f"正在采集并护耳转码第 {idx}/{min(len(candidates), limit)} 集：{item_title[:28]}...",
                    tracks_added=tracks_added,
                    album_id=album_id,
                )
                tid = await _download_ytdlp_single_item(item_url, album_id, title_hint=item_title)
                if tid:
                    tracks_added += 1
                    collected_titles.append(item_title or f"第{idx}集")
    except Exception as exc:
        err_detail = str(exc)

    # 4. 汇报结果与音箱/网页双端通知
    if tracks_added > 0:
        summary_text = (
            f"采集任务完成啦！已为您收录《{series_title}》{season_label} 共 {tracks_added} 集，"
            f"并自动分类到{channel_zh}的「{series_title} → {season_label}」。"
            f"现在直接对我说“播放{series_title}”就可以收听哦！"
        )
        await _set_job("done", f"采集并 AI 分类完成：共入库 {tracks_added} 集（{series_title} · {season_label}）", tracks_added=tracks_added, album_id=album_id)
        final_status = "done"
    else:
        reason = err_detail or "暂未在可用音源中找到匹配音频"
        summary_text = f"抱歉，刚才帮您采集「{query}」未能下载到音频（{reason[:60]}）。您可以换个关键词再试，或在网页手动上传或粘贴链接导入。"
        await _set_job("failed", f"未采集到音频：{reason[:120]}", tracks_added=0, error_msg=reason[:200], album_id=album_id)
        final_status = "failed"

    tts_path: Path | None = None
    tts_url: str | None = None
    try:
        tts_path = await synthesize_speech(summary_text, voice=voice, rate=rate)
        tts_url = f"/api/tts-cache/{tts_path.name}"
    except Exception:
        tts_path = None

    # 实体音箱主动语音播报
    if notify_speaker and device_id and device_id != "web-console":
        try:
            await device_manager.push_announcement(
                device_id=device_id,
                text=summary_text,
                tts_path=tts_path,
            )
        except Exception:
            pass

    # 网页端实时事件通知（驱动通知栏、自动刷新与可选播报）
    result_payload = {
        "type": "collect_completed",
        "job_id": job_id,
        "status": final_status,
        "query": query,
        "channel": channel,
        "channel_label": channel_zh,
        "series_id": series_id,
        "series_title": series_title,
        "album_id": album_id,
        "season_num": album.get("season_num", 1),
        "season_label": season_label,
        "level_code": classification.get("level_code", ""),
        "tracks_added": tracks_added,
        "titles": collected_titles,
        "summary_text": summary_text,
        "tts_url": tts_url,
        "device_id": device_id,
        "started_at": ts_start,
        "finished_at": now_iso(),
    }
    try:
        await device_manager.broadcast_web(result_payload)
    except Exception:
        pass
    return result_payload


async def enqueue_ai_collect(
    *,
    query: str,
    channel_hint: str | None = None,
    target_series_id: int | None = None,
    target_album_id: int | None = None,
    max_items: int = 5,
    device_id: str = "",
    notify_speaker: bool = True,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+0%",
) -> dict[str, Any]:
    """创建采集任务并在后台异步启动「全网采集 → AI 自动分类 → 音箱播报通知」。"""
    q = query.strip()
    if not q:
        raise ValueError("采集关键词不能为空")

    preview = _rule_classify_request(q, channel_hint=channel_hint)
    ts = now_iso()
    async with get_db() as conn:
        cur = await conn.execute(
            """
            INSERT INTO download_jobs
            (job_type, source_url, target_album_id, status, progress_text, created_at, updated_at)
            VALUES ('yt_dlp', ?, ?, 'pending', ?, ?, ?)
            """,
            (
                f"ai_collect://{q}",
                target_album_id,
                f"排队等待 AI 采集并分类：{q}",
                ts,
                ts,
            ),
        )
        job_id = int(cur.lastrowid)
        await conn.commit()

    task = asyncio.create_task(
        run_ai_collect_job(
            job_id=job_id,
            query=q,
            channel_hint=channel_hint,
            target_series_id=target_series_id,
            target_album_id=target_album_id,
            max_items=max_items,
            device_id=device_id,
            notify_speaker=notify_speaker,
            voice=voice,
            rate=rate,
        )
    )
    _CURATOR_BG_TASKS.add(task)
    task.add_done_callback(_CURATOR_BG_TASKS.discard)

    return {
        "job_id": job_id,
        "status": "pending",
        "query": q,
        "preview": preview,
    }

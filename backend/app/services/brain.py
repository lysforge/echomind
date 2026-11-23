"""全成长阶段双模家庭智能音箱大脑（0-18+ 全阶段适配 · 有声书/专辑点播 · 声纹记忆隔离）。"""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.config import load_settings
from app.db import get_db, now_iso
from app.gateways.manager import device_manager
from app.services.ai_curator import (
    CHANNEL_LABELS_ZH,
    enqueue_ai_collect,
    parse_cn_number,
    update_playback_progress,
)
from app.services.collector import (
    ensure_auto_cache_album,
    insert_normalized_track,
    quick_find_and_ingest_local_keyword,
    resolve_or_prepare_online_stream,
    search_online_audio,
    synthesize_book_chapter_audio,
)
from app.services.voiceprint import SpeakerContext

ALLOWED_MOTIONS = {
    "idle",
    "nod",
    "wave",
    "wiggle",
    "wave_arms",
    "step_forward",
    "spin_slow",
    "stop",
    "quiet_lock",
}


def is_quiet_hours_active() -> bool:
    settings = load_settings()
    if settings.quiet_hours_force_active:
        return True
    if not settings.quiet_hours_enabled:
        return False
    try:
        now_t = datetime.now().strftime("%H:%M")
        start = settings.quiet_hours_start
        end = settings.quiet_hours_end
        if start <= end:
            return start <= now_t < end
        return now_t >= start or now_t < end
    except Exception:
        return False


class SafeMotionGuard:
    """ESP32 可选机器人舵机安全限幅器（速度<=40%，单次<=2000ms，夜间免打扰锁止）。"""

    @staticmethod
    def sanitize(
        action: str,
        duration_ms: int = 1200,
        speed: int = 30,
        force_quiet_check: bool = True,
    ) -> dict[str, Any]:
        if force_quiet_check and is_quiet_hours_active():
            return {
                "allowed": False,
                "blocked_reason": "夜间睡眠免打扰已开启，机器人舵机已安全锁止",
                "action": "quiet_lock",
                "duration_ms": 0,
                "speed": 0,
            }
        safe_action = action if action in ALLOWED_MOTIONS else "nod"
        safe_duration = min(max(int(duration_ms), 200), 2000)
        safe_speed = min(max(int(speed), 10), 40)
        return {
            "allowed": True,
            "blocked_reason": "",
            "action": safe_action,
            "duration_ms": safe_duration,
            "speed": safe_speed,
        }


@dataclass
class BrainResponse:
    reply_text: str
    motion_command: dict[str, Any] = field(default_factory=dict)
    play_track: dict[str, Any] | None = None
    queue_tracks: list[dict[str, Any]] = field(default_factory=list)
    control_action: dict[str, Any] = field(default_factory=dict)
    learned_item: dict[str, Any] | None = None
    background_job: dict[str, Any] | None = None
    memory_scope_used: list[str] = field(default_factory=list)
    used_llm: bool = False
    skip_device_push: bool = False


async def fetch_accessible_memories(speaker: SpeakerContext) -> tuple[list[dict], list[str]]:
    """严格按声纹安全上下文执行三层记忆隔离。"""
    async with get_db() as conn:
        if speaker.safety_mode == "adult_private" and speaker.member_id is not None:
            cur = await conn.execute(
                """
                SELECT m.*, fm.name AS owner_name, fm.role AS owner_role
                FROM memories m
                LEFT JOIN family_members fm ON m.member_id = fm.id
                WHERE m.scope = 'family'
                   OR (m.scope = 'personal' AND m.member_id = ?)
                   OR (m.scope = 'growth')
                ORDER BY m.id DESC
                LIMIT 15
                """,
                (speaker.member_id,),
            )
            scopes = ["family", f"personal:{speaker.nickname}", "growth"]
        else:
            cur = await conn.execute(
                """
                SELECT m.*, fm.name AS owner_name, fm.role AS owner_role
                FROM memories m
                LEFT JOIN family_members fm ON m.member_id = fm.id
                WHERE m.scope = 'family'
                   OR (m.scope IN ('personal', 'growth') AND fm.role = 'child')
                ORDER BY m.id DESC
                LIMIT 12
                """
            )
            scopes = ["family", "child_only"]

        rows = [dict(r) for r in await cur.fetchall()]
    return rows, scopes


async def pick_track_for_album(
    category: str | None = None,
    keyword: str | None = None,
    age_stage: str | None = None,
    resume: bool = True,
    next_episode: bool = False,
) -> dict[str, Any] | None:
    """从曲库或有声书库挑选音频（优先匹配用户当前成长阶段）。"""
    async with get_db() as conn:
        if keyword:
            cur = await conn.execute(
                """
                SELECT t.*, a.title AS album_title, a.category AS album_category, a.play_mode, a.last_track_id, a.last_position_sec,
                       'track' AS media_kind
                FROM media_tracks t
                JOIN media_albums a ON t.album_id = a.id
                WHERE t.title LIKE ? OR a.title LIKE ?
                ORDER BY t.episode_num ASC
                LIMIT 1
                """,
                (f"%{keyword}%", f"%{keyword}%"),
            )
            hit = await cur.fetchone()
            if hit:
                return dict(hit)

        # 优先查匹配阶段且有曲目的专辑
        album = None
        if category and age_stage:
            cur = await conn.execute(
                """
                SELECT a.* FROM media_albums a
                WHERE a.category = ? AND a.age_stage = ?
                  AND EXISTS (SELECT 1 FROM media_tracks t WHERE t.album_id = a.id)
                ORDER BY a.id ASC LIMIT 1
                """,
                (category, age_stage),
            )
            album = await cur.fetchone()

        if not album and category:
            cur = await conn.execute(
                """
                SELECT a.* FROM media_albums a
                WHERE a.category = ? AND EXISTS (SELECT 1 FROM media_tracks t WHERE t.album_id = a.id)
                ORDER BY a.id ASC LIMIT 1
                """,
                (category,),
            )
            album = await cur.fetchone()

        if not album:
            cur = await conn.execute(
                "SELECT a.* FROM media_albums a WHERE EXISTS (SELECT 1 FROM media_tracks t WHERE t.album_id = a.id) ORDER BY a.id ASC LIMIT 1"
            )
            album = await cur.fetchone()

        if not album:
            return None

        cur = await conn.execute(
            "SELECT * FROM media_tracks WHERE album_id = ? ORDER BY episode_num ASC, id ASC",
            (album["id"],),
        )
        tracks = [dict(r) for r in await cur.fetchall() if r["file_path"] and Path(r["file_path"]).exists()]
        if not tracks:
            return None

        chosen = tracks[0]
        if album["play_mode"] == "shuffle" and not next_episode:
            chosen = random.choice(tracks)
        elif (resume or next_episode) and album["last_track_id"]:
            for idx, t in enumerate(tracks):
                if t["id"] == album["last_track_id"]:
                    chosen = tracks[(idx + 1) % len(tracks)] if next_episode else t
                    break

        chosen["album_title"] = album["title"]
        chosen["album_category"] = album["category"]
        chosen["play_mode"] = album["play_mode"]
        chosen["last_position_sec"] = album["last_position_sec"]
        chosen["media_kind"] = "track"
        chosen["stream_url"] = f"/api/media/tracks/{chosen['id']}/stream"
        return chosen


async def pick_book_chapter(
    keyword: str | None = None,
    age_stage: str | None = None,
) -> dict[str, Any] | None:
    """从全阶有声书库挑书并取最新或第一章真实存在磁盘的有声章节。"""
    async with get_db() as conn:
        if keyword:
            cur = await conn.execute(
                """
                SELECT c.*, b.title AS book_title
                FROM book_chapters c
                JOIN books b ON c.book_id = b.id
                WHERE b.title LIKE ? OR c.title LIKE ?
                ORDER BY c.chapter_num ASC, c.id ASC
                """,
                (f"%{keyword}%", f"%{keyword}%"),
            )
            for row in await cur.fetchall():
                if row["file_path"] and Path(row["file_path"]).exists():
                    res = dict(row)
                    res["album_title"] = res["book_title"]
                    res["media_kind"] = "book_chapter"
                    res["stream_url"] = f"/api/books/chapters/{res['id']}/stream"
                    return res
            return None

        book = None
        if age_stage:
            cur = await conn.execute(
                "SELECT * FROM books WHERE age_stage = ? AND EXISTS (SELECT 1 FROM book_chapters c WHERE c.book_id = books.id) ORDER BY id ASC LIMIT 1",
                (age_stage,),
            )
            book = await cur.fetchone()
        if not book:
            cur = await conn.execute(
                "SELECT * FROM books WHERE EXISTS (SELECT 1 FROM book_chapters c WHERE c.book_id = books.id) ORDER BY id ASC LIMIT 1"
            )
            book = await cur.fetchone()
        if not book:
            return None

        cur = await conn.execute(
            "SELECT * FROM book_chapters WHERE book_id = ? ORDER BY chapter_num ASC, id ASC",
            (book["id"],),
        )
        for ch in await cur.fetchall():
            if ch["file_path"] and Path(ch["file_path"]).exists():
                res = dict(ch)
                res["book_title"] = book["title"]
                res["album_title"] = book["title"]
                res["media_kind"] = "book_chapter"
                res["stream_url"] = f"/api/books/chapters/{res['id']}/stream"
                return res
        return None


GENERIC_PLAY_TERMS = {"", "歌", "一首歌", "首歌", "一首", "音乐", "故事", "一个故事", "绘本", "童谣", "英语", "英文", "播客", "电台", "儿歌"}

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def extract_collect_intent(text: str) -> dict[str, Any] | None:
    """识别语音采集/下载请求：如「帮我采集汪汪队第二季」「帮我下载5首周杰伦的歌」。"""
    t = text.strip()
    if not t:
        return None
    collect_triggers = ("采集", "下载", "抓取", "搜集", "收录", "去网上找", "帮我找并下载")
    if not any(k in t for k in collect_triggers):
        return None

    max_items = 5
    m_cnt = re.search(r"([一二两三四五六七八九十\d]+)\s*[集首期课个]", t)
    if m_cnt:
        # 排除“第X集”这种指代集号的场景
        prefix = t[: m_cnt.start()]
        if not prefix.endswith("第"):
            parsed_cnt = parse_cn_number(m_cnt.group(1))
            if parsed_cnt:
                max_items = max(1, min(parsed_cnt, 20))

    channel_hint: str | None = None
    if any(k in t for k in ("英语", "英文", "自然拼读", "磨耳朵", "启蒙英语", "牛津树", "raz", "RAZ")):
        channel_hint = "english"
    elif any(k in t for k in ("播客", "电台", "新闻")):
        channel_hint = "podcast"
    elif any(k in t for k in ("故事", "绘本", "有声书", "睡前", "童话", "第1季", "第2季", "第3季", "第一季", "第二季", "第三季")):
        channel_hint = "story"
    elif any(k in t for k in ("歌曲", "的歌", "儿歌", "童谣", "音乐", "歌单", "专辑", "首")):
        channel_hint = "music"

    q = re.sub(
        r"^(你好)?(小音|助手)?[,，、 ]*(请)?(帮我|给我|我要|去|上后台|在后台)*(去网上|全网|网上)*(采集|下载|抓取|搜集|收录|找一下并下载|找并下载)[一下点些：:，, ]*",
        "",
        t,
    ).strip()
    q = re.sub(r"^(?:[一二两三四五六七八九十\d]+\s*[集首期课个])(?:的)?", "", q).strip()
    q = re.sub(r"(吧|呀|哦|好不好|好吗|！|!|。|\.)+$", "", q).strip()
    if not q:
        return None
    return {"query": q, "channel_hint": channel_hint, "max_items": max_items}


def extract_playback_control_intent(text: str) -> dict[str, Any] | None:
    """识别纯硬件/队列播控指令：暂停、停止、续播、上下集、跳集、音量调节、睡眠定时。"""
    t = text.strip()
    if not t:
        return None

    # 1. 睡眠定时（xx分钟后停止 / 播完几集停）
    if "半小时后" in t and any(k in t for k in ("停", "关")):
        return {"action": "sleep_minutes", "minutes": 30}
    m_min = re.search(r"(\d+)\s*分钟后.*?(?:停|关)", t)
    if m_min:
        return {"action": "sleep_minutes", "minutes": max(1, int(m_min.group(1)))}
    m_ep_stop = re.search(r"播完\s*([一二两三四五六七八九十\d]+)\s*[集首章课]?(?:就|自动)?(?:停|关)", t)
    if m_ep_stop:
        ep = parse_cn_number(m_ep_stop.group(1)) or 1
        return {"action": "sleep_episodes", "episodes": max(1, ep)}

    # 2. 音量调节
    m_vol = re.search(r"(?:音量|声音)(?:调到|设为|放到|改到)?\s*(\d+)", t)
    if m_vol:
        return {"action": "volume_set", "value": max(0, min(100, int(m_vol.group(1))))}
    if any(k in t for k in ("大声点", "声音大一点", "调大音量", "音量大点", "声音大些")):
        return {"action": "volume_delta", "delta": 15}
    if any(k in t for k in ("小声点", "声音小一点", "轻一点", "调小音量", "音量小点", "声音轻些")):
        return {"action": "volume_delta", "delta": -15}

    # 3. 当前队列内直接跳集（例如：“跳到第5集”、“切换到第三集”、“跳到第8首”，不含具体新作品名）
    m_jump = re.match(
        r"^(?:请)?(?:帮我)?(?:跳到|跳转到|切换到|换到|直接播|播|播放)?\s*第\s*([一二两三四五六七八九十\d]+)\s*[集章课期首]\s*[吧呀哦！!。.]*$",
        t,
    )
    if m_jump:
        ep_val = parse_cn_number(m_jump.group(1))
        if ep_val:
            return {"action": "jump_episode", "episode_num": ep_val}

    # 3.5 重播 / 快进快退 / 循环模式 / 当前播放与书库查询
    if any(k in t for k in ("重播", "再放一遍", "重新播放这", "再听一遍", "从头放这")):
        return {"action": "replay"}

    m_seek = re.search(r"(快进|前进|往前跳|快退|倒退|后退|往回退)\s*([一二两三四五六七八九十\d]+)\s*(秒|分钟|分)", t)
    if m_seek:
        direction = -1 if m_seek.group(1) in ("快退", "倒退", "后退", "往回退") else 1
        num = parse_cn_number(m_seek.group(2)) or 15
        unit = m_seek.group(3)
        sec = num * 60 if unit in ("分", "分钟") else num
        return {"action": "seek_delta", "delta_sec": direction * sec}
    if any(k in t for k in ("快进一点", "快进一下")):
        return {"action": "seek_delta", "delta_sec": 15}
    if any(k in t for k in ("快退一点", "倒退一点", "退回一点")):
        return {"action": "seek_delta", "delta_sec": -15}

    if "单曲循环" in t or "单集循环" in t:
        return {"action": "set_loop", "loop_mode": "repeat_one"}
    if "随机播放" in t or "随便播" in t:
        return {"action": "set_loop", "loop_mode": "shuffle"}
    if "顺序播放" in t or "顺序循环" in t or "列表循环" in t:
        return {"action": "set_loop", "loop_mode": "sequential"}

    if any(k in t for k in ("现在放的是什么", "正在放什么", "这是什么歌", "这是什么故事", "这是第几集", "在放什么")):
        return {"action": "whats_playing"}

    m_qseries = re.search(r"^(.+?)(?:一共有|共有|有)(?:几季|多少季|几集|多少集|几首|多少首)", t)
    if m_qseries:
        kw_s = re.sub(r"^(?:请问|帮我查一下|查一下|看看)", "", m_qseries.group(1)).strip(" 的")
        if kw_s:
            return {"action": "query_series_info", "keyword": kw_s}

    # 4. 暂停 / 停止 / 续播 / 上下集
    if t in ("暂停", "暂停播放", "停一下", "先暂停", "帮我暂停") or "暂停播放" in t:
        return {"action": "pause"}
    if t in ("停止播放", "停止", "别放了", "别唱了", "关闭音乐", "关掉声音", "退出播放") or "停止播放" in t:
        return {"action": "stop"}
    # 仅纯续播短语走此分支；若带有明确合集名（如“继续放汪汪队”），交由点播路由精准按系列续播
    if re.match(r"^(?:请)?(?:帮我)?(?:继续播放|接着播放|接着听|继续放|继续听|恢复播放)[吧呀哦！!。.]*$", t):
        return {"action": "resume_or_continue"}
    if any(k in t for k in ("下一首", "下一集", "下一章", "下一课", "换一首", "切歌")):
        return {"action": "next"}
    if any(k in t for k in ("上一首", "上一集", "上一章", "上一课")):
        return {"action": "prev"}

    return None


async def _load_album_playable_tracks(album_id: int) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cur_a = await conn.execute("SELECT * FROM media_albums WHERE id = ?", (album_id,))
        alb = await cur_a.fetchone()
        alb_title = alb["title"] if alb else ""
        cur = await conn.execute(
            "SELECT * FROM media_tracks WHERE album_id = ? ORDER BY episode_num ASC, id ASC",
            (album_id,),
        )
        out = []
        for r in await cur.fetchall():
            d = dict(r)
            has_disk = bool(d.get("file_path") and Path(d["file_path"]).exists())
            has_text = bool((d.get("text_content") or "").strip())
            if has_disk or has_text:
                d["album_title"] = alb_title
                d["media_kind"] = "track"
                d["stream_url"] = f"/api/media/tracks/{d['id']}/stream"
                d["is_cached"] = True
                out.append(d)
        return out


async def _execute_playback_control(ctrl: dict[str, Any], device_id: str, speaker: SpeakerContext) -> BrainResponse:
    act = ctrl["action"]
    scopes = ["family", f"personal:{speaker.nickname}"] if speaker.safety_mode == "adult_private" else ["family", "child_only"]

    is_real_dev = False
    dev_row: dict[str, Any] | None = None
    if device_id and device_id != "web-console":
        async with get_db() as conn:
            cur = await conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            r = await cur.fetchone()
            if r:
                is_real_dev = True
                dev_row = dict(r)

    if act == "replay":
        if is_real_dev and device_manager.playback_sessions.get(device_id):
            snap = await device_manager.control_device_queue(device_id, "replay")
            cur_t = (snap.get("session") or {}).get("current_track")
            return BrainResponse(
                reply_text=f"好的，为您从头重播《{cur_t['title']}》。" if cur_t else "好的，为您重播本集。",
                play_track=cur_t,
                control_action={"action": "replay"},
                memory_scope_used=scopes,
                skip_device_push=True,
            )
        return BrainResponse(reply_text="好的，为您从头重播当前音频。", control_action={"action": "replay"}, memory_scope_used=scopes)

    if act == "seek_delta":
        dsec = int(ctrl.get("delta_sec") or 15)
        verb = f"快进 {dsec} 秒" if dsec > 0 else f"倒退 {abs(dsec)} 秒"
        if is_real_dev and device_manager.playback_sessions.get(device_id):
            await device_manager.control_device_queue(device_id, "seek_delta", delta_sec=float(dsec))
        return BrainResponse(
            reply_text=f"好的，已为您{verb}。",
            control_action={"action": "seek_delta", "delta_sec": dsec},
            memory_scope_used=scopes,
            skip_device_push=True,
        )

    if act == "set_loop":
        lmode = str(ctrl.get("loop_mode") or "sequential")
        lmap = {"repeat_one": "单曲循环", "shuffle": "随机播放", "sequential": "顺序连播"}
        if is_real_dev and device_manager.playback_sessions.get(device_id):
            await device_manager.control_device_queue(device_id, "set_loop", loop_mode=lmode)
        return BrainResponse(
            reply_text=f"好的，播放模式已切换为{lmap.get(lmode, '顺序连播')}。",
            control_action={"action": "set_loop", "loop_mode": lmode},
            memory_scope_used=scopes,
        )

    if act == "whats_playing":
        sess = device_manager.playback_sessions.get(device_id) if is_real_dev else None
        if sess and sess.get("queue"):
            idx = int(sess.get("current_index") or 0)
            tr = sess["queue"][idx] if 0 <= idx < len(sess["queue"]) else None
            if tr:
                sea_lbl = sess.get("season_label") or ""
                return BrainResponse(
                    reply_text=f"现在正在播放的是《{sess.get('album_title', '')}》{sea_lbl} 第{tr.get('episode_num', idx + 1)}集：{tr['title']}。",
                    control_action={"action": "whats_playing"},
                    memory_scope_used=scopes,
                )
        async with get_db() as conn:
            cur_s = await conn.execute(
                """
                SELECT s.title AS stitle, a.season_label, t.episode_num, t.title AS ttitle
                FROM media_series s
                JOIN media_albums a ON s.last_album_id = a.id
                JOIN media_tracks t ON s.last_track_id = t.id
                ORDER BY COALESCE(s.last_played_at, '') DESC
                LIMIT 1
                """
            )
            r = await cur_s.fetchone()
        if r:
            return BrainResponse(
                reply_text=f"最近收听的是《{r['stitle']}》{r['season_label']} 第{r['episode_num']}集：{r['ttitle']}。",
                control_action={"action": "whats_playing"},
                memory_scope_used=scopes,
            )
        return BrainResponse(reply_text="当前暂时没有正在播放的内容哦。", control_action={"action": "whats_playing"}, memory_scope_used=scopes)

    if act == "query_series_info":
        kw_s = str(ctrl.get("keyword") or "").strip()
        async with get_db() as conn:
            cur_s = await conn.execute("SELECT * FROM media_series WHERE title LIKE ? LIMIT 1", (f"%{kw_s}%",))
            srow = await cur_s.fetchone()
            if srow:
                cur_a = await conn.execute(
                    """
                    SELECT a.season_num, a.season_label, COUNT(t.id) AS cnt
                    FROM media_albums a
                    LEFT JOIN media_tracks t ON t.album_id = a.id
                    WHERE a.series_id = ?
                    GROUP BY a.id
                    ORDER BY a.season_num ASC
                    """,
                    (srow["id"],),
                )
                seas = [dict(x) for x in await cur_a.fetchall()]
                total_eps = sum(int(x["cnt"] or 0) for x in seas)
                detail = "，".join(f"{x['season_label'] or ('第' + str(x['season_num']) + '季')}{x['cnt']}集" for x in seas)
                return BrainResponse(
                    reply_text=f"《{srow['title']}》目前收录了 {len(seas)} 季，共 {total_eps} 集（{detail}）。",
                    control_action={"action": "query_series_info"},
                    memory_scope_used=scopes,
                )
        return BrainResponse(
            reply_text=f"书架里还没有收录《{kw_s}》，你可以对我说「帮我采集{kw_s}」由我自动上网搜集并分类哦。",
            control_action={"action": "query_series_info"},
            memory_scope_used=scopes,
        )

    if act == "volume_set":
        val = int(ctrl["value"])
        if is_real_dev:
            clamped = await device_manager.set_device_volume(device_id, val)
            hint = f"（已触及 {dev_row['max_volume']}% 护耳上限）" if val > int(dev_row["max_volume"]) else ""
            return BrainResponse(reply_text=f"好的，音箱音量已调整为 {clamped}%{hint}。", control_action={"action": "volume_set", "value": clamped}, memory_scope_used=scopes)
        return BrainResponse(reply_text=f"好的，已将音量调整为 {val}%。", control_action={"action": "volume_set", "value": val}, memory_scope_used=scopes)

    if act == "volume_delta":
        delta = int(ctrl["delta"])
        if is_real_dev and dev_row:
            new_v = max(0, min(100, int(dev_row["volume"]) + delta))
            clamped = await device_manager.set_device_volume(device_id, new_v)
            return BrainResponse(reply_text=f"好的，音量已调到 {clamped}%。", control_action={"action": "volume_set", "value": clamped}, memory_scope_used=scopes)
        return BrainResponse(reply_text="好的，已为您调节音量。", control_action=ctrl, memory_scope_used=scopes)

    if act == "sleep_minutes":
        mins = int(ctrl["minutes"])
        if is_real_dev:
            await device_manager.control_device_queue(device_id, "set_sleep", sleep_minutes=mins)
        return BrainResponse(reply_text=f"已设好睡眠定时，{mins} 分钟后将轻柔停止播放。", control_action=ctrl, memory_scope_used=scopes)

    if act == "sleep_episodes":
        eps = int(ctrl["episodes"])
        if is_real_dev:
            await device_manager.control_device_queue(device_id, "set_sleep", sleep_episodes=eps)
        return BrainResponse(reply_text=f"好的，将在播完本 {eps} 集后自动停止播放。", control_action=ctrl, memory_scope_used=scopes)

    if act in ("pause", "stop"):
        if is_real_dev:
            await device_manager.control_device_queue(device_id, act)
        return BrainResponse(
            reply_text="好的，已暂停播放。" if act == "pause" else "好的，已停止播放。",
            control_action={"action": act},
            memory_scope_used=scopes,
        )

    if act in ("next", "prev"):
        delta = 1 if act == "next" else -1
        if is_real_dev and device_manager.playback_sessions.get(device_id):
            snap = await device_manager.advance_device_queue(device_id, delta=delta, auto_triggered=False)
            cur_t = (snap or {}).get("session", {}).get("current_track") if snap else None
            if cur_t:
                return BrainResponse(
                    reply_text=f"好的，为您切换至《{cur_t['title']}》。",
                    play_track=cur_t,
                    control_action={"action": act},
                    memory_scope_used=scopes,
                    skip_device_push=True,
                )
        return BrainResponse(
            reply_text="好的，为您切换下一首。" if delta > 0 else "好的，回到上一首。",
            control_action={"action": act},
            memory_scope_used=scopes,
        )

    if act == "jump_episode":
        ep_num = int(ctrl["episode_num"])
        if is_real_dev and device_manager.playback_sessions.get(device_id):
            sess = device_manager.playback_sessions[device_id]
            q = sess.get("queue") or []
            idx = next((i for i, item in enumerate(q) if int(item.get("episode_num") or 0) == ep_num), -1)
            if idx < 0 and 1 <= ep_num <= len(q):
                idx = ep_num - 1
            if idx >= 0:
                snap = await device_manager.control_device_queue(device_id, "jump", index=idx)
                cur_t = (snap.get("session") or {}).get("current_track")
                return BrainResponse(
                    reply_text=f"好的，已为您跳到第 {ep_num} 集《{cur_t['title']}》。" if cur_t else f"已跳到第 {ep_num} 集。",
                    play_track=cur_t,
                    control_action={"action": "jump", "index": idx, "episode_num": ep_num},
                    memory_scope_used=scopes,
                    skip_device_push=True,
                )
            return BrainResponse(
                reply_text=f"当前播放列表共有 {len(q)} 集，没找到第 {ep_num} 集哦。",
                control_action={"action": "jump", "episode_num": ep_num},
                memory_scope_used=scopes,
            )
        # 网页端或暂无活跃会话时，从最近听过的专辑中精准跳集
        async with get_db() as conn:
            cur = await conn.execute(
                "SELECT id, title FROM media_albums WHERE is_inbox = 0 AND last_track_id IS NOT NULL ORDER BY id DESC LIMIT 1"
            )
            alb = await cur.fetchone()
        if alb:
            tracks = await _load_album_playable_tracks(int(alb["id"]))
            idx = next((i for i, item in enumerate(tracks) if int(item.get("episode_num") or 0) == ep_num), -1)
            if idx < 0 and 1 <= ep_num <= len(tracks):
                idx = ep_num - 1
            if idx >= 0:
                chosen = tracks[idx]
                await update_playback_progress(int(alb["id"]), int(chosen["id"]), position_sec=0.0, increment_play=True)
                return BrainResponse(
                    reply_text=f"好的，为您跳到《{alb['title']}》第 {ep_num} 集：{chosen['title']}。",
                    play_track=chosen,
                    queue_tracks=tracks,
                    control_action={"action": "jump", "index": idx, "episode_num": ep_num},
                    memory_scope_used=scopes,
                )
        return BrainResponse(
            reply_text=f"好的，跳到第 {ep_num} 集。",
            control_action={"action": "jump", "episode_num": ep_num},
            memory_scope_used=scopes,
        )

    # resume_or_continue
    if is_real_dev and device_manager.playback_sessions.get(device_id):
        snap = await device_manager.control_device_queue(device_id, "resume")
        cur_t = (snap.get("session") or {}).get("current_track")
        return BrainResponse(
            reply_text=f"继续为您播放《{cur_t['title']}》。" if cur_t else "好的，继续播放。",
            play_track=cur_t,
            control_action={"action": "resume"},
            memory_scope_used=scopes,
            skip_device_push=True,
        )

    # 没活跃会话时优先从最近收听过的 media_series 精准续播（第几季第几集第几秒）
    async with get_db() as conn:
        cur_s = await conn.execute(
            """
            SELECT * FROM media_series
            WHERE last_album_id IS NOT NULL AND last_track_id IS NOT NULL
            ORDER BY COALESCE(last_played_at, '') DESC, id DESC
            LIMIT 1
            """
        )
        srow = await cur_s.fetchone()
        if srow:
            sdata = dict(srow)
            cur_a = await conn.execute("SELECT * FROM media_albums WHERE id = ?", (sdata["last_album_id"],))
            arow = await cur_a.fetchone()
            if arow:
                tracks = await _load_album_playable_tracks(int(arow["id"]))
                if tracks:
                    start_idx = next((i for i, x in enumerate(tracks) if x["id"] == sdata["last_track_id"]), 0)
                    chosen = dict(tracks[start_idx])
                    chosen["start_position_sec"] = float(sdata.get("last_position_sec") or 0.0)
                    chosen["season_num"] = int(arow["season_num"] or 1)
                    chosen["season_label"] = arow["season_label"] or f"第{arow['season_num'] or 1}季"
                    chosen["series_title"] = sdata["title"]
                    return BrainResponse(
                        reply_text=f"继续为您收听《{sdata['title']}》{chosen['season_label']} 第{chosen['episode_num']}集：{chosen['title']}。",
                        play_track=chosen,
                        queue_tracks=tracks,
                        control_action={"action": "resume", "album_id": arow["id"], "start_index": start_idx},
                        memory_scope_used=scopes,
                    )

        cur = await conn.execute(
            "SELECT id, title, last_track_id, last_position_sec FROM media_albums WHERE is_inbox = 0 AND last_track_id IS NOT NULL ORDER BY id DESC LIMIT 1"
        )
        alb = await cur.fetchone()
    if alb:
        tracks = await _load_album_playable_tracks(int(alb["id"]))
        if tracks:
            start_idx = next((i for i, x in enumerate(tracks) if x["id"] == alb["last_track_id"]), 0)
            chosen = dict(tracks[start_idx])
            chosen["start_position_sec"] = float(alb["last_position_sec"] or 0.0)
            return BrainResponse(
                reply_text=f"继续为您收听《{alb['title']}》：{chosen['title']}。",
                play_track=chosen,
                queue_tracks=tracks,
                control_action={"action": "resume", "album_id": alb["id"], "start_index": start_idx},
                memory_scope_used=scopes,
            )
    return BrainResponse(reply_text="当前还没有可继续收听的专辑，可以先告诉我你想听什么歌或故事哦。", control_action={"action": "resume"}, memory_scope_used=scopes)


def extract_play_intent(text: str) -> dict[str, Any] | None:
    """识别点歌/听故事/听绘本/指定季数与集数/英语分级续学意图。"""
    t = text.strip()
    if not t:
        return None
    next_ep = any(k in t for k in ("下一集", "下一首", "换一首"))
    explicit_resume = any(k in t for k in ("继续放", "继续听", "继续播", "接着听", "接着放", "继续学"))
    cat = None
    if any(k in t for k in ("书", "绘本", "故事", "睡前", "章节", "科普", "童话")):
        cat = "story"
    elif any(k in t for k in ("英语", "磨耳朵", "英文", "课程", "启蒙")):
        cat = "english"
    elif any(k in t for k in ("播客", "电台")):
        cat = "podcast"
    elif any(k in t for k in ("歌", "音乐", "唱", "童谣", "儿歌")):
        cat = "music"

    triggers = (
        "播放",
        "放一",
        "放点",
        "放首",
        "放个",
        "放",
        "来一首",
        "来首",
        "来个",
        "来一节",
        "我想听",
        "我要听",
        "想听",
        "听一",
        "听个",
        "听",
        "接着听",
        "接着放",
        "继续放",
        "继续听",
        "继续学",
        "唱一首",
        "唱个",
        "讲个",
        "讲一个",
        "讲一下",
        "读一本",
        "读个",
        "学",
    )
    has_play_verb = any(t.startswith(v) or v in t for v in triggers) or next_ep or cat is not None
    if not has_play_verb:
        return None

    t_work = t
    # 1. 提取季/单元号（第2季 / 第二季 / 第3单元 / S2）
    season_num: int | None = None
    m_sea = re.search(r"的?第\s*([一二两三四五六七八九十\d]+)\s*[季部辑册单元]", t_work)
    if m_sea:
        season_num = parse_cn_number(m_sea.group(1))
        t_work = (t_work[: m_sea.start()] + t_work[m_sea.end() :]).strip()
    else:
        m_sea_en = re.search(r"\b[Ss](?:eason)?\s*0*(\d+)\b", t_work)
        if m_sea_en:
            season_num = int(m_sea_en.group(1))
            t_work = (t_work[: m_sea_en.start()] + t_work[m_sea_en.end() :]).strip()

    # 2. 提取集/课/章号（支持中文数字和阿拉伯数字：第五集 / 第12集 / 第三课）
    ep_num: int | None = None
    m_ep = re.search(r"的?第\s*([一二两三四五六七八九十\d]+)\s*[集章课期首话回]", t_work)
    if m_ep:
        ep_num = parse_cn_number(m_ep.group(1))
        t_work = (t_work[: m_ep.start()] + t_work[m_ep.end() :]).strip()

    # 3. 提取英语启蒙等级（L1~L5 / 一级~五级）
    level_code: str | None = None
    m_lvl = re.search(r"\b[Ll]([1-5])\b", t_work)
    if m_lvl:
        level_code = f"L{m_lvl.group(1)}"
        t_work = re.sub(r"\b[Ll][1-5]\b", "", t_work).strip()
        if cat is None:
            cat = "english"
    elif cat == "english":
        m_lvl_zh = re.search(r"(?:第)?([一二三四五1-5])级", t_work)
        if m_lvl_zh:
            n = parse_cn_number(m_lvl_zh.group(1))
            if n and 1 <= n <= 5:
                level_code = f"L{n}"
                t_work = (t_work[: m_lvl_zh.start()] + t_work[m_lvl_zh.end() :]).strip()

    kw = re.sub(
        r"^(你好)?(小音|助手)?[,，、 ]*(请)?(帮我|给我|我要|我想)?(继续播放|继续放|继续听|继续学|接着听|接着放|播放|放一首|放点|放个|放一|放|来一首|来首|来一节|来个|听一下|听一首|听个|听|唱一首|唱个|唱|讲一个|讲个|讲一下|讲|读一本|读个|学一下|学)[：:，, ]*",
        "",
        t_work,
    ).strip()
    kw = re.sub(r"(这首歌|的歌曲|的歌|这本绘本|这本书|的音频故事|的故事|的音频|启蒙课|启蒙|吧|呀|哦|好不好|好吗|！|!|。|\.)+$", "", kw).strip()
    if kw in GENERIC_PLAY_TERMS:
        kw = ""

    return {
        "category": cat or ("story" if season_num else "music"),
        "keyword": kw,
        "season_num": season_num,
        "episode_num": ep_num,
        "level_code": level_code,
        "next_episode": next_ep,
        "explicit_resume": explicit_resume,
    }


async def _pick_from_series(
    series: dict[str, Any],
    *,
    season_num: int | None = None,
    episode_num: int | None = None,
    next_episode: bool = False,
    member_key: str | None = None,
) -> dict[str, Any] | None:
    """在命中的一级系列 media_series 中精准定位季、集、断点秒数并组装整季连播队列（支持多人独立进度）。"""
    sid = int(series["id"])
    mem_prog: dict[str, Any] | None = None
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT * FROM media_albums WHERE series_id = ? AND is_inbox = 0 ORDER BY season_num ASC, id ASC",
            (sid,),
        )
        seasons = [dict(r) for r in await cur.fetchall()]
        if member_key:
            cur_mp = await conn.execute(
                "SELECT * FROM user_playback_progress WHERE member_key = ? AND series_id = ?",
                (member_key, sid),
            )
            mprow = await cur_mp.fetchone()
            if mprow:
                mem_prog = dict(mprow)
    if not seasons:
        return None

    eff_last_album_id = (mem_prog or {}).get("album_id") or series.get("last_album_id")
    eff_last_track_id = (mem_prog or {}).get("track_id") or series.get("last_track_id")
    eff_last_pos = float((mem_prog or {}).get("position_sec") if mem_prog else (series.get("last_position_sec") or 0.0))

    # 1. 指定季号精准定位
    target_season: dict[str, Any] | None = None
    if season_num is not None:
        target_season = next((s for s in seasons if int(s.get("season_num") or 1) == season_num), None)
        if not target_season and 1 <= season_num <= len(seasons):
            target_season = seasons[season_num - 1]
    elif episode_num is not None:
        # 只说集号没说季号：先查上次播到的季，找不到再跨季找
        preferred: list[dict[str, Any]] = []
        if eff_last_album_id:
            la = next((s for s in seasons if s["id"] == eff_last_album_id), None)
            if la:
                preferred.append(la)
        preferred.extend([s for s in seasons if s not in preferred])
        for sea in preferred:
            tracks = await _load_album_playable_tracks(int(sea["id"]))
            hit = next((t for t in tracks if int(t.get("episode_num") or 0) == episode_num), None)
            if hit:
                chosen = dict(hit)
                chosen["series_id"] = sid
                chosen["series_title"] = series["title"]
                chosen["season_num"] = int(sea.get("season_num") or 1)
                chosen["season_label"] = sea.get("season_label") or f"第{sea.get('season_num') or 1}季"
                chosen["start_position_sec"] = 0.0
                return {
                    "type": "play_track",
                    "source": "local",
                    "resumed": False,
                    "track": chosen,
                    "queue_tracks": tracks,
                    "keyword": series["title"],
                }
    else:
        # 既没指定季也没指定集 -> 优先使用该成员/系列记忆的上次播放季（断点续播）
        if eff_last_album_id:
            target_season = next((s for s in seasons if s["id"] == eff_last_album_id), None)

    # 若还没确定季，取第一个有可播单集的季
    if target_season is None:
        for sea in seasons:
            if await _load_album_playable_tracks(int(sea["id"])):
                target_season = sea
                break
    if target_season is None:
        return None

    tracks = await _load_album_playable_tracks(int(target_season["id"]))
    if not tracks:
        return None

    chosen: dict[str, Any] | None = None
    start_pos = 0.0
    resumed = False

    if episode_num is not None:
        chosen = next((t for t in tracks if int(t.get("episode_num") or 0) == episode_num), None)
        if chosen is None and 1 <= episode_num <= len(tracks):
            chosen = tracks[episode_num - 1]
    elif season_num is not None:
        if target_season.get("last_track_id"):
            idx = next((i for i, t in enumerate(tracks) if t["id"] == target_season["last_track_id"]), -1)
            if idx >= 0:
                chosen = tracks[(idx + 1) % len(tracks)] if next_episode else tracks[idx]
                start_pos = 0.0 if next_episode else float(target_season.get("last_position_sec") or 0.0)
                resumed = not next_episode
    else:
        mem_tid = eff_last_track_id or target_season.get("last_track_id")
        if mem_tid:
            idx = next((i for i, t in enumerate(tracks) if t["id"] == mem_tid), -1)
            if idx >= 0:
                chosen = tracks[(idx + 1) % len(tracks)] if next_episode else tracks[idx]
                start_pos = 0.0 if next_episode else (eff_last_pos or float(target_season.get("last_position_sec") or 0.0))
                resumed = not next_episode

    if chosen is None:
        chosen = tracks[0]

    chosen = dict(chosen)
    chosen["series_id"] = sid
    chosen["series_title"] = series["title"]
    chosen["season_num"] = int(target_season.get("season_num") or 1)
    chosen["season_label"] = target_season.get("season_label") or f"第{target_season.get('season_num') or 1}季"
    chosen["start_position_sec"] = start_pos
    return {
        "type": "play_track",
        "source": "local",
        "resumed": resumed,
        "track": chosen,
        "queue_tracks": tracks,
        "keyword": series["title"],
    }


async def resolve_voice_play_request(
    category: str | None,
    keyword: str | None,
    age_stage: str,
    next_episode: bool = False,
    episode_num: int | None = None,
    season_num: int | None = None,
    level_code: str | None = None,
    member_key: str | None = None,
) -> dict[str, Any]:
    """
    核心音频多级查找解析策略：
    0) 一级系列精准优先（media_series）：支持“汪汪队第2季第5集”精准跳季跳集、“播放汪汪队”自动断点续播、“播放L2英语”分级续学；
    1) 本地曲库/专辑/标签/书库/挂载目录兜底；命中附带整季/整张专辑连播队列；
    2) 本地未命中：高速在线搜索，签发 /api/media/live-stream/{token} 实时流秒播并后台 -16 LUFS 缓存；
    3) 极端断网且为特定故事需求：即时合成温暖短故事并落盘。
    """
    cat = category or "music"
    kw = (keyword or "").strip()

    # 0. 一级系列 media_series 匹配（含精准跳季跳集与断点续播）
    async with get_db() as conn:
        matched_series: dict[str, Any] | None = None
        if kw:
            cur_s = await conn.execute(
                """
                SELECT * FROM media_series
                WHERE title LIKE ? OR author LIKE ?
                ORDER BY
                    CASE WHEN title = ? THEN 0 WHEN title LIKE ? THEN 1 ELSE 2 END,
                    COALESCE(last_played_at, '') DESC, id DESC
                LIMIT 1
                """,
                (f"%{kw}%", f"%{kw}%", kw, f"{kw}%"),
            )
            srow = await cur_s.fetchone()
            if srow:
                matched_series = dict(srow)
        elif cat == "english" and level_code:
            cur_s = await conn.execute(
                """
                SELECT * FROM media_series
                WHERE channel = 'english' AND level_code = ?
                ORDER BY COALESCE(last_played_at, '') DESC, id ASC
                LIMIT 1
                """,
                (level_code,),
            )
            srow = await cur_s.fetchone()
            if srow:
                matched_series = dict(srow)

    if matched_series:
        series_hit = await _pick_from_series(
            matched_series,
            season_num=season_num,
            episode_num=episode_num,
            next_episode=next_episode,
            member_key=member_key,
        )
        if series_hit:
            return series_hit

    # 1. 本地优先：有关键词先精准匹配统一曲库/专辑/标签/书库/挂载目录
    if kw:
        async with get_db() as conn:
            cur = await conn.execute(
                """
                SELECT t.*, a.title AS album_title, a.category AS album_category, a.sub_tag, a.season_num, a.season_label, a.series_id
                FROM media_tracks t
                JOIN media_albums a ON t.album_id = a.id
                WHERE t.title LIKE ? OR a.title LIKE ? OR a.sub_tag LIKE ?
                ORDER BY
                    CASE WHEN t.title LIKE ? THEN 0 WHEN a.title LIKE ? THEN 1 ELSE 2 END,
                    a.season_num ASC, t.episode_num ASC, t.id ASC
                """,
                (f"%{kw}%", f"%{kw}%", f"%{kw}%", f"%{kw}%", f"%{kw}%"),
            )
            rows = [dict(r) for r in await cur.fetchall()]
            if season_num and rows:
                s_rows = [r for r in rows if int(r.get("season_num") or 1) == season_num]
                if s_rows:
                    rows = s_rows
            if episode_num and rows:
                ep_rows = [r for r in rows if int(r.get("episode_num") or 0) == episode_num]
                if ep_rows:
                    rows = ep_rows
            for r in rows:
                has_disk = bool(r.get("file_path") and Path(r["file_path"]).exists())
                has_text = bool((r.get("text_content") or "").strip())
                if has_disk or has_text:
                    r["media_kind"] = "track"
                    r["stream_url"] = f"/api/media/tracks/{r['id']}/stream"
                    r["is_cached"] = True
                    album_tracks = await _load_album_playable_tracks(int(r["album_id"]))
                    return {"type": "play_track", "source": "local", "track": r, "queue_tracks": album_tracks, "keyword": kw}

        ch = await pick_book_chapter(keyword=kw, age_stage=age_stage)
        if ch:
            ch["is_cached"] = True
            return {"type": "play_track", "source": "local", "track": ch, "queue_tracks": [ch], "keyword": kw}

        # 检查已挂载本地文件夹磁盘上尚未扫描的新文件
        disk_hit = await quick_find_and_ingest_local_keyword(kw)
        if disk_hit:
            disk_hit["is_cached"] = True
            return {"type": "play_track", "source": "local", "track": disk_hit, "queue_tracks": [disk_hit], "keyword": kw}
    else:
        # 无明确关键词，优先按分类与阶段播放本地统一专辑（带整张连播队列）
        local_tr = await pick_track_for_album(
            category=cat, keyword=None, age_stage=age_stage, resume=True, next_episode=next_episode
        )
        if local_tr:
            local_tr["is_cached"] = True
            album_tracks = await _load_album_playable_tracks(int(local_tr["album_id"]))
            return {"type": "play_track", "source": "local", "track": local_tr, "queue_tracks": album_tracks, "keyword": ""}
        if cat == "story":
            ch = await pick_book_chapter(keyword=None, age_stage=age_stage)
            if ch:
                ch["is_cached"] = True
                return {"type": "play_track", "source": "local", "track": ch, "queue_tracks": [ch], "keyword": ""}

    # 2. 本地未命中 -> 高速在线搜索并边播边自动缓存到本地语音缓存池
    if os.getenv("ECHOMIND_DISABLE_ONLINE_SEARCH") != "1":
        if kw:
            search_q = f"{kw} 故事" if cat == "story" and "故事" not in kw else kw
        else:
            default_queries = {
                "music": "经典儿童歌曲 儿歌",
                "story": "儿童睡前故事 音频",
                "english": "Super Simple Songs 儿歌",
                "podcast": "少儿科普故事 音频",
            }
            search_q = default_queries.get(cat, "经典儿歌")
        try:
            online_list = await search_online_audio(search_q, limit=3)
            if online_list:
                best = online_list[0]
                live_track = await resolve_or_prepare_online_stream(
                    title=best["title"],
                    url=best["url"],
                    category=cat,
                    age_stage=age_stage,
                )
                src_tag = "local" if live_track.get("is_cached") else "online_caching"
                return {"type": "play_track", "source": src_tag, "track": live_track, "queue_tracks": [live_track], "keyword": kw or search_q}
        except Exception:
            pass

    # 3. 断网无在线结果时的故事兜底
    if kw and cat == "story":
        alb_id, alb_title = await ensure_auto_cache_album("story", age_stage)
        story_text = f"从前在一个安静快乐的小镇里，大家都很喜欢关于{kw}的温暖冒险。每天用心观察世界，就能发现隐藏在生活里的小小奇迹。"
        dst, dur, norm = await synthesize_book_chapter_audio(0, 1, kw, story_text, "zh")
        tid = await insert_normalized_track(alb_id, f"{kw}（故事精选）", dst, source_url=f"offline://story/{kw}", text_content=story_text)
        dst.unlink(missing_ok=True)
        async with get_db() as conn:
            c = await conn.execute("SELECT * FROM media_tracks WHERE id = ?", (tid,))
            row = await c.fetchone()
            if row:
                tr = dict(row)
                tr["album_title"] = alb_title
                tr["media_kind"] = "track"
                tr["stream_url"] = f"/api/media/tracks/{tid}/stream"
                tr["is_cached"] = True
                return {"type": "play_track", "source": "local", "track": tr, "queue_tracks": [tr], "keyword": kw}

    return {"type": "no_track"}


async def _practice_english_item(phrase_or_row: str | dict[str, Any]) -> dict[str, Any] | None:
    async with get_db() as conn:
        if isinstance(phrase_or_row, str):
            cur = await conn.execute(
                "SELECT * FROM english_items WHERE LOWER(phrase) LIKE LOWER(?) OR zh_meaning LIKE ? LIMIT 1",
                (f"%{phrase_or_row}%", f"%{phrase_or_row}%"),
            )
            row = await cur.fetchone()
        else:
            row = phrase_or_row
        if not row:
            return None
        row_dict = dict(row)
        await conn.execute(
            "UPDATE english_items SET listen_count = listen_count + 1, last_played_at = ? WHERE id = ?",
            (now_iso(), row_dict["id"]),
        )
        await conn.commit()
        row_dict["listen_count"] = int(row_dict.get("listen_count", 0)) + 1
        return row_dict


async def _execute_tool_call(
    tool_name: str,
    args: dict[str, Any],
    speaker: SpeakerContext,
    device_id: str = "web-console",
) -> dict[str, Any]:
    if tool_name == "collect_media_online":
        q = str(args.get("query") or "").strip()
        if not q:
            return {"type": "noop"}
        ch_hint = args.get("channel_hint")
        max_items = int(args.get("max_items") or 5)
        job = await enqueue_ai_collect(
            query=q,
            channel_hint=ch_hint if ch_hint in ("story", "music", "english", "podcast") else None,
            max_items=max_items,
            device_id=device_id,
            notify_speaker=True,
            voice=speaker.tts_voice,
            rate=speaker.tts_rate,
        )
        return {"type": "collect_started", "job": job}

    if tool_name == "practice_english_audio":
        phrase = args.get("phrase", "")
        item = await _practice_english_item(phrase) if phrase else None
        if not item:
            stage = speaker.english_stage if speaker.english_stage in ("Pre_A1", "A1", "A2", "B1", "B2_PLUS") else "Pre_A1"
            async with get_db() as conn:
                cur = await conn.execute(
                    "SELECT * FROM english_items WHERE stage = ? ORDER BY listen_count ASC LIMIT 1",
                    (stage,),
                )
                row = await cur.fetchone()
                if not row:
                    cur = await conn.execute("SELECT * FROM english_items ORDER BY listen_count ASC LIMIT 1")
                    row = await cur.fetchone()
                if row:
                    item = await _practice_english_item(dict(row))
        if item:
            return {"type": "english_item", "item": item}
        return {"type": "noop"}

    if tool_name == "play_media":
        cat = args.get("category")
        kw = args.get("keyword")
        nxt = bool(args.get("next_episode", False))
        ep_n = parse_cn_number(args.get("episode_num"))
        sea_n = parse_cn_number(args.get("season_num"))
        lvl = args.get("level_code")
        mk = f"member:{speaker.member_id}" if speaker.member_id else None
        res = await resolve_voice_play_request(
            cat,
            kw,
            speaker.age_stage,
            next_episode=nxt,
            episode_num=ep_n,
            season_num=sea_n,
            level_code=lvl,
            member_key=mk,
        )
        if res.get("type") == "play_track":
            tr = res["track"]
            if tr.get("media_kind") == "track" and int(tr.get("id") or 0) > 0:
                keep_pos = float(tr.get("start_position_sec") or 0.0)
                await update_playback_progress(
                    album_id=int(tr["album_id"]),
                    track_id=int(tr["id"]),
                    position_sec=keep_pos,
                    increment_play=True,
                    member_key=mk,
                )
        return res

    if tool_name == "robot_motion":
        motion = SafeMotionGuard.sanitize(
            args.get("action", "nod"),
            args.get("duration_ms", 1200),
            args.get("speed", 30),
        )
        return {"type": "motion", "motion": motion}

    if tool_name == "save_memory":
        content = str(args.get("content", "")).strip()
        req_scope = args.get("scope", "family")
        if not content:
            return {"type": "noop"}
        target_member_id = speaker.member_id
        if speaker.safety_mode == "child_safe":
            scope = "growth" if req_scope == "personal" else "family"
            if scope == "family":
                target_member_id = None
        else:
            scope = "personal" if req_scope == "personal" else "family"
            if scope == "family":
                target_member_id = None

        async with get_db() as conn:
            await conn.execute(
                "INSERT INTO memories (member_id, scope, category, content, importance, created_at) VALUES (?, ?, 'voice', ?, 4, ?)",
                (target_member_id, scope, content, now_iso()),
            )
            await conn.commit()
        return {"type": "memory_saved", "scope": scope, "content": content}

    if tool_name == "create_schedule":
        time_str = str(args.get("cron_time", "20:30"))
        name = str(args.get("name", f"语音定时播控 {time_str}"))
        task_type = str(args.get("task_type", "bedtime_story"))
        cat_map = {"play_album": "music", "english_immersion": "english", "bedtime_story": "story"}
        target_cat = cat_map.get(task_type, "story")
        async with get_db() as conn:
            cur = await conn.execute("SELECT id FROM media_albums WHERE category = ? LIMIT 1", (target_cat,))
            alb = await cur.fetchone()
            album_id = alb["id"] if alb else None
            cur_d = await conn.execute("SELECT id FROM devices WHERE device_type = 'speaker_xiaoai' AND paired = 1 LIMIT 1")
            dev = await cur_d.fetchone()
            dev_id = dev["id"] if dev else None
            await conn.execute(
                """
                INSERT OR REPLACE INTO schedules
                (name, cron_time, days_of_week, task_type, target_device_id, album_id, target_volume, max_episodes, fade_out, enabled)
                VALUES (?, ?, '1,2,3,4,5,6,7', ?, ?, ?, 50, 1, ?, 1)
                """,
                (name, time_str, task_type, dev_id, album_id, 1 if task_type == "bedtime_story" else 0),
            )
            await conn.commit()
        return {"type": "schedule_saved", "name": name, "cron_time": time_str}

    return {"type": "noop"}


OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "play_media",
            "description": "当用户想在音箱播放音乐歌曲(music)、故事或有声书(story)、英语启蒙(english)或播客(podcast)时调用；支持指定第几季(season_num)、第几集(episode_num)和英语级别(level_code)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["music", "story", "english", "podcast"]},
                    "keyword": {"type": "string"},
                    "season_num": {"type": "integer"},
                    "episode_num": {"type": "integer"},
                    "level_code": {"type": "string", "enum": ["L1", "L2", "L3", "L4", "L5"]},
                    "next_episode": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "collect_media_online",
            "description": "当用户明确要求去网上采集、下载、抓取或收录某些故事、歌曲、英语或播客到服务器曲库，并希望完成后AI自动分类并通知结果时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要采集的内容名称，如 汪汪队第2季 或 周杰伦"},
                    "channel_hint": {"type": "string", "enum": ["music", "story", "english", "podcast"]},
                    "max_items": {"type": "integer", "description": "采集集数或首数，默认 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "practice_english_audio",
            "description": "当孩子想用音箱纯语音练英语、学习匹配其年龄段的英文词句或对话时调用。",
            "parameters": {
                "type": "object",
                "properties": {"phrase": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_schedule",
            "description": "当用户用语音设定每天几点的音箱定时播放任务时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "cron_time": {"type": "string"},
                    "task_type": {"type": "string", "enum": ["play_album", "english_immersion", "bedtime_story"]},
                },
                "required": ["name", "cron_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "当家人或孩子要求记住某件事、偏好或家庭备忘时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "scope": {"type": "string", "enum": ["family", "personal"]},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "robot_motion",
            "description": "仅当用户明确要求可选的 ESP32 机器人走动、点头、挥手、转圈或停下时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["nod", "wave", "wiggle", "wave_arms", "step_forward", "spin_slow", "stop"]},
                },
                "required": ["action"],
            },
        },
    },
]


def _stage_instruction(speaker: SpeakerContext) -> str:
    age_desc = f"当前成员年龄为 {speaker.age_label}（阶段 {speaker.age_stage}）" if speaker.age_label else f"当前阶段 {speaker.age_stage}"
    lvl = speaker.english_stage
    if lvl == "Pre_A1":
        return (
            f"{age_desc}，英语能力为 Pre-A1（零基础韵律磨耳朵）："
            "请用 1～2 句极短温暖的口语回复，结合拟声词自然带入 1 个具象英语单词，不要讲语法或拼写。"
        )
    if lvl == "A1":
        return (
            f"{age_desc}，英语能力为 A1（词汇与日常短句）："
            "请在对话中自然融入 1 个日常英文短句或问答，鼓励跟读重复。"
        )
    if lvl == "A2":
        return (
            f"{age_desc}，英语能力为 A2（桥梁阅读与问答）："
            "请用清晰简洁的中英双语交流，可提出简单英文问题引导思考，也可推荐科学或故事有声书。"
        )
    if lvl == "B1":
        return (
            f"{age_desc}，英语能力为 B1（独立章节听说与科普思考）："
            "请用自然流畅的英文或半英文沟通，探讨科普现象、故事主线并适时扩展地道表达。"
        )
    return (
        f"{age_desc}，英语能力为 B2+（原版进阶思辨对话）："
        "请优先使用地道、富有启发性的全英文对话，适合探讨文学、科技与观点表达，仅在必要时提供中文点拨。"
    )


def _build_system_prompt(
    assistant_name: str,
    speaker: SpeakerContext,
    memories: list[dict],
    items: list[dict],
    quiet_active: bool,
) -> str:
    mem_lines = "\n".join(f"- [{m['scope']}] {m['content']}" for m in memories[:8]) or "- 暂无"
    phrase_line = ", ".join(f"{it['phrase']}({it['zh_meaning']})" for it in items[:10])

    if speaker.role == "child" or speaker.safety_mode == "child_safe":
        quiet_hint = "\n【夜间睡眠免打扰生效中】：请用轻柔的声音提醒休息。" if quiet_active else ""
        return (
            f"你是家庭智能音箱助手「{assistant_name}」，通过声音陪伴各个成长阶段的孩子。\n"
            + _stage_instruction(speaker)
            + f"\n当前可用英语素材库：{phrase_line}\n"
            + f"可参考的安全记忆：\n{mem_lines}{quiet_hint}"
        )

    return (
        f"你是家庭智能音箱中枢助手「{assistant_name}」，当前正在和【{speaker.name}】对话（声纹隔离模式：{speaker.safety_mode}）。\n"
        "请简洁自然地响应点歌、有声书点播、设置每日定时播放、记个人/家庭备忘，或讨论孩子各阶段的阅读与英语计划。\n"
        f"当前授权可见的记忆：\n{mem_lines}"
    )


async def _offline_fallback_brain(
    assistant_name: str,
    user_text: str,
    speaker: SpeakerContext,
    memories: list[dict],
    items: list[dict],
    quiet_active: bool,
) -> BrainResponse:
    text = user_text.strip()
    lower = text.lower()
    scopes = ["family", f"personal:{speaker.nickname}"] if speaker.safety_mode == "adult_private" else ["family", "child_only"]

    if quiet_active and speaker.safety_mode == "child_safe":
        if any(k in text for k in ("走", "转", "跳", "玩", "唱", "歌", "闹")):
            return BrainResponse(
                reply_text=f"夜深啦，{speaker.nickname}该休息睡觉咯，{assistant_name}把声音调轻轻的陪你晚安～",
                motion_command=SafeMotionGuard.sanitize("quiet_lock"),
                memory_scope_used=scopes,
            )

    m_time = re.search(r"(\d{1,2})\s*[点时:：]\s*(半|\d{1,2})?", text)
    if any(k in text for k in ("每天", "定时", "闹钟")) and m_time:
        hour = int(m_time.group(1))
        minute_raw = m_time.group(2)
        if ("晚上" in text or "晚" in text) and hour < 12:
            hour += 12
        minute = 30 if minute_raw == "半" else (int(minute_raw) if minute_raw else 0)
        cron_time = f"{hour % 24:02d}:{minute % 60:02d}"
        task_type = "bedtime_story" if "故事" in text else ("english_immersion" if "英语" in text else "play_album")
        await _execute_tool_call(
            "create_schedule",
            {"name": f"语音定时：{text[:12]}", "cron_time": cron_time, "task_type": task_type},
            speaker,
        )
        return BrainResponse(
            reply_text=f"好呀，{assistant_name}已经设定好每天 {cron_time} 准时在音箱播放啦。",
            memory_scope_used=scopes,
        )

    if any(text.startswith(p) for p in ("记住", "帮我记", "备忘")) or "记得" in text:
        content = re.sub(r"^(请)?(帮我)?(记住|记一下|备忘)[：:，, ]*", "", text).strip() or text
        scope = "personal" if ("我" in text or speaker.safety_mode == "adult_private") else "family"
        res = await _execute_tool_call("save_memory", {"content": content, "scope": scope}, speaker)
        tag = "个人私密记忆" if res.get("scope") == "personal" else "家庭共享记忆"
        return BrainResponse(
            reply_text=f"记好啦！已存入【{speaker.nickname}】的{tag}里。",
            memory_scope_used=scopes,
        )

    if any(k in text for k in ("我的备忘", "我有什么", "爸爸", "妈妈", "秘密", "记了什么")):
        personal_items = [m["content"] for m in memories if m["scope"] == "personal"]
        family_items = [m["content"] for m in memories if m["scope"] == "family"]
        if speaker.safety_mode == "child_safe":
            fam_tip = family_items[0] if family_items else "暂无家庭共享安排"
            return BrainResponse(
                reply_text=f"{speaker.nickname}，当前处于儿童安全模式，只可查看你的成长记录与家庭约定（{fam_tip}），大人的私密备忘受声纹保护不会播报哦。",
                memory_scope_used=scopes,
            )
        summary = personal_items[0] if personal_items else (family_items[0] if family_items else "目前还没有记录")
        return BrainResponse(
            reply_text=f"{speaker.nickname}您好，您的专属记忆里记录着：{summary}",
            memory_scope_used=scopes,
        )

    play_intent = extract_play_intent(text)
    if play_intent and not any(k in text for k in ("怎么说", "怎么读", "英语单词")):
        res = await _execute_tool_call("play_media", play_intent, speaker)
        if res.get("type") == "play_track":
            tr = res["track"]
            q_tracks = res.get("queue_tracks") or [tr]
            if res.get("source") == "online_caching":
                reply = f"本地曲库暂未收录，已为您在线播放《{tr['title']}》，同时正在后台护耳缓存到本地曲库。"
            elif res.get("resumed") and tr.get("series_title"):
                sea_lbl = tr.get("season_label") or f"第{tr.get('season_num', 1)}季"
                reply = f"好的，接着上次的位置为您续播《{tr['series_title']}》{sea_lbl} 第{tr.get('episode_num', 1)}集：{tr['title']}。"
            elif tr.get("series_title"):
                sea_lbl = tr.get("season_label") or f"第{tr.get('season_num', 1)}季"
                reply = f"好的，为您播放《{tr['series_title']}》{sea_lbl} 第{tr.get('episode_num', 1)}集：{tr['title']}。"
            else:
                reply = f"好的，已在本地媒体库找到《{tr['title']}》，正在为您播放。"
            return BrainResponse(
                reply_text=reply,
                play_track=tr,
                queue_tracks=q_tracks,
                memory_scope_used=scopes,
            )
        return BrainResponse(
            reply_text="暂未找到匹配曲目，您可以对我说「帮我采集……」由我自动上网采集并分类，或在页面手动添加音频。",
            memory_scope_used=scopes,
        )

    for it in items:
        phrase_l = (it.get("phrase") or "").strip().lower()
        zh = (it.get("zh_meaning") or "").strip()
        hit_en = len(phrase_l) >= 2 and bool(re.search(rf"\b{re.escape(phrase_l)}\b", lower))
        hit_zh = len(zh) >= 2 and zh in text
        if hit_en or hit_zh:
            res = await _execute_tool_call("practice_english_audio", {"phrase": it["phrase"]}, speaker)
            chosen = res["item"]
            return BrainResponse(reply_text=chosen["audio_prompt"], learned_item=chosen, memory_scope_used=scopes)

    motion_map = {
        "往前走": ("step_forward", "机器人向前走两步"),
        "转圈": ("spin_slow", "机器人慢速转一圈"),
        "挥手": ("wave_arms", "机器人挥挥手"),
        "停": ("stop", "机器人停下来"),
        "点头": ("nod", "机器人点点头"),
    }
    for kw, (act, desc) in motion_map.items():
        if kw in text:
            res = await _execute_tool_call("robot_motion", {"action": act}, speaker)
            m = res["motion"]
            if not m["allowed"]:
                return BrainResponse(reply_text=m["blocked_reason"], motion_command=m, memory_scope_used=scopes)
            return BrainResponse(reply_text=f"收到，{desc}。", motion_command=m, memory_scope_used=scopes)

    if speaker.safety_mode == "adult_private":
        return BrainResponse(
            reply_text=f"我在听呢，{speaker.nickname}。您可以让我播放音乐有声书、设定定时播控，或记录个人备忘。",
            memory_scope_used=scopes,
        )

    # 根据英语阶段匹配互动回复
    stage = speaker.english_stage if speaker.english_stage in ("Pre_A1", "A1", "A2", "B1", "B2_PLUS") else "Pre_A1"
    candidates = [it for it in items if it["stage"] == stage] or items
    pick = min(candidates, key=lambda x: int(x.get("listen_count", 0))) if candidates else None
    if pick:
        await _practice_english_item(pick)
        if stage in ("B1", "B2_PLUS"):
            reply = f"Great to chat with you, {speaker.nickname}! Let's practice this level ({stage}) prompt: {pick['phrase']} — {pick['audio_prompt']}"
        else:
            reply = f"{assistant_name}听到啦！我们一起来练一句 {stage} 英语吧：{pick['audio_prompt']}"
        return BrainResponse(reply_text=reply, learned_item=pick, memory_scope_used=scopes)

    return BrainResponse(
        reply_text=f"{speaker.nickname}你好呀，我是{assistant_name}。想听歌、听有声书还是练习英语？",
        memory_scope_used=scopes,
    )


async def process_user_turn(
    user_text: str,
    speaker: SpeakerContext,
    device_id: str = "web-console",
) -> BrainResponse:
    settings = load_settings()
    memories, scopes = await fetch_accessible_memories(speaker)
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM english_items ORDER BY id ASC")
        items = [dict(r) for r in await cur.fetchall()]

    quiet_active = is_quiet_hours_active()
    response: BrainResponse | None = None

    # 0. 优先拦截音箱语音采集请求（后台自动采集 -> AI 自动分类 -> 完成后音箱主动播报通知）
    collect_intent = extract_collect_intent(user_text)
    if collect_intent:
        job = await enqueue_ai_collect(
            query=collect_intent["query"],
            channel_hint=collect_intent.get("channel_hint"),
            max_items=collect_intent.get("max_items", 5),
            device_id=device_id,
            notify_speaker=True,
            voice=speaker.tts_voice,
            rate=speaker.tts_rate,
        )
        prev = job.get("preview") or {}
        ch_zh = CHANNEL_LABELS_ZH.get(prev.get("channel") or "story", "媒体库")
        stitle = prev.get("series_title") or collect_intent["query"]
        slabel = prev.get("season_label") or ""
        response = BrainResponse(
            reply_text=f"好的，正在后台为您全网采集《{stitle}》{slabel}，完成后会自动分类到「{ch_zh}」并第一时间在音箱语音通知您哦！",
            background_job=job,
            memory_scope_used=scopes,
        )

    # 1. 优先拦截精准硬件播控指令（暂停 / 停止 / 切歌 / 跳集 / 音量 / 睡眠定时 / 续播）
    if response is None:
        ctrl_intent = extract_playback_control_intent(user_text)
        if ctrl_intent:
            response = await _execute_playback_control(ctrl_intent, device_id, speaker)

    if response is None and (settings.llm_api_key.strip() or settings.llm_provider == "ollama"):
        try:
            url = settings.llm_base_url.rstrip("/") + "/chat/completions"
            headers = {"Content-Type": "application/json"}
            if settings.llm_api_key.strip():
                headers["Authorization"] = f"Bearer {settings.llm_api_key.strip()}"

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": _build_system_prompt(settings.assistant_name, speaker, memories, items, quiet_active)},
                {"role": "user", "content": user_text},
            ]
            payload = {
                "model": settings.llm_model,
                "messages": messages,
                "tools": OPENAI_TOOLS,
                "temperature": 0.7,
                "max_tokens": 240,
            }
            async with httpx.AsyncClient(timeout=18.0) as client:
                r = await client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                choice = r.json()["choices"][0]["message"]
                tool_calls = choice.get("tool_calls") or []

                motion_cmd: dict[str, Any] = {}
                play_track = None
                queue_tracks: list[dict[str, Any]] = []
                learned_item = None
                bg_job = None

                if tool_calls:
                    messages.append(choice)
                    for tc in tool_calls:
                        fn_name = tc["function"]["name"]
                        fn_args = json.loads(tc["function"].get("arguments") or "{}")
                        tool_res = await _execute_tool_call(fn_name, fn_args, speaker, device_id=device_id)
                        if "motion" in tool_res:
                            motion_cmd = tool_res["motion"]
                        if tool_res.get("type") == "play_track":
                            play_track = tool_res["track"]
                            queue_tracks = tool_res.get("queue_tracks") or [play_track]
                        elif tool_res.get("type") == "english_item":
                            learned_item = tool_res["item"]
                        elif tool_res.get("type") == "collect_started":
                            bg_job = tool_res["job"]

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": json.dumps(tool_res, ensure_ascii=False, default=str),
                            }
                        )

                    r2 = await client.post(
                        url,
                        headers=headers,
                        json={"model": settings.llm_model, "messages": messages, "temperature": 0.7, "max_tokens": 220},
                    )
                    r2.raise_for_status()
                    reply_text = r2.json()["choices"][0]["message"].get("content", "").strip()
                else:
                    reply_text = (choice.get("content") or "").strip()

                response = BrainResponse(
                    reply_text=reply_text or f"{settings.assistant_name}收到啦！",
                    motion_command=motion_cmd,
                    play_track=play_track,
                    queue_tracks=queue_tracks,
                    learned_item=learned_item,
                    background_job=bg_job,
                    memory_scope_used=scopes,
                    used_llm=True,
                )
        except Exception:
            response = None

    if response is None:
        response = await _offline_fallback_brain(settings.assistant_name, user_text, speaker, memories, items, quiet_active)

    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO interaction_logs
            (device_id, speaker_member_id, speaker_name, speaker_confidence, safety_mode, user_text, assistant_text, played_track_title, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                speaker.member_id,
                speaker.name,
                speaker.confidence,
                speaker.safety_mode,
                user_text,
                response.reply_text,
                response.play_track["title"] if response.play_track else "",
                now_iso(),
            ),
        )
        await conn.commit()

    return response

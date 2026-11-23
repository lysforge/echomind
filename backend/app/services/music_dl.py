"""多源云音乐检索、榜单解析、音频流换源与云端批量下载入库服务（松耦合对接 go-music-dl）。"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, quote, urlparse

import httpx

from app.config import MEDIA_RAW_DIR, load_settings
from app.db import get_db, now_iso
from app.services.collector import insert_normalized_track

_BG_TASKS: set[asyncio.Task] = set()

DERIVATIVE_KEYWORDS = (
    "live",
    "演唱会",
    "伴奏",
    "instrumental",
    "inst",
    "remix",
    "cover",
    "翻唱",
    "dj",
    "改编",
    "片段",
    "剪辑",
    "伴奏版",
)

SUPPORTED_MUSIC_SOURCES = [
    {"id": "netease", "label": "网易云音乐"},
    {"id": "qq", "label": "QQ音乐"},
    {"id": "kugou", "label": "酷狗音乐"},
    {"id": "kuwo", "label": "酷我音乐"},
    {"id": "migu", "label": "咪咕音乐"},
    {"id": "bilibili", "label": "Bilibili"},
    {"id": "qianqian", "label": "千千音乐"},
    {"id": "joox", "label": "JOOX"},
]


def normalize_music_dl_base(raw_url: str | None = None) -> str:
    """将用户配置的容器或本机服务地址归一化为 go-music-dl /music 基础路径。"""
    u = (raw_url if raw_url is not None else load_settings().music_dl_url or "").strip().rstrip("/")
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = f"http://{u}"
    parsed = urlparse(u)
    path = parsed.path.rstrip("/")
    if not path:
        return f"{u}/music"
    return u


def _default_sources() -> list[str]:
    raw = (load_settings().music_dl_sources or "").strip()
    parts = [s.strip() for s in raw.split(",") if s.strip()]
    return parts or ["netease", "qq", "kugou", "kuwo", "migu", "bilibili"]


def _unescape_html(s: str) -> str:
    if not s:
        return ""
    out = html.unescape(s)
    # 二次解实体兼容双重转义如 &amp;#43;
    if "&#" in out or "&amp;" in out:
        out = html.unescape(out)
    return out


def _get_data_attr(attrs: str, key: str) -> str:
    for pat in (rf'\bdata-{re.escape(key)}="([^"]*)"', rf"\bdata-{re.escape(key)}='([^']*)'"):
        m = re.search(pat, attrs)
        if m:
            return _unescape_html(m.group(1))
    return ""


def parse_song_cards(page_html: str) -> list[dict[str, Any]]:
    """解析 go-music-dl 搜索结果、榜单页及歌单详情页中的 .song-card 歌曲节点。"""
    songs: list[dict[str, Any]] = []
    for m in re.finditer(r'<li\b([^>]*\bsong-card\b[^>]*)>', page_html):
        attrs = m.group(1)
        sid = _get_data_attr(attrs, "id")
        source = _get_data_attr(attrs, "source")
        if not sid or not source:
            continue
        extra_raw = _get_data_attr(attrs, "extra")
        extra: dict[str, Any] = {}
        if extra_raw:
            try:
                parsed = json.loads(extra_raw)
                if isinstance(parsed, dict):
                    extra = parsed
            except json.JSONDecodeError:
                extra = {}
        try:
            dur = int(float(_get_data_attr(attrs, "duration") or 0))
        except ValueError:
            dur = 0
        songs.append(
            {
                "id": sid,
                "source": source,
                "name": _get_data_attr(attrs, "name") or "未命名歌曲",
                "artist": _get_data_attr(attrs, "artist") or "",
                "album": _get_data_attr(attrs, "album") or "",
                "cover": _get_data_attr(attrs, "cover") or "",
                "duration": dur,
                "extra": extra,
            }
        )
    return songs


def parse_playlist_cards(page_html: str) -> list[dict[str, Any]]:
    """解析 go-music-dl 歌单/专辑搜索页卡片。"""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(r'<([a-zA-Z0-9]+)\b([^>]*\bdata-external-id=[^>]*)>', page_html):
        attrs = m.group(2)
        ext_id = _get_data_attr(attrs, "external-id")
        source = _get_data_attr(attrs, "source")
        if not ext_id or not source:
            continue
        key = f"{source}:{ext_id}"
        if key in seen:
            continue
        seen.add(key)
        try:
            cnt = int(_get_data_attr(attrs, "track-count") or 0)
        except ValueError:
            cnt = 0
        ctype = _get_data_attr(attrs, "content-type")
        items.append(
            {
                "id": ext_id,
                "source": source,
                "title": _get_data_attr(attrs, "name") or "未命名歌单",
                "cover": _get_data_attr(attrs, "cover") or "",
                "creator": _get_data_attr(attrs, "creator") or "",
                "track_count": cnt,
                "content_type": "album" if ctype == "album" else "playlist",
            }
        )
    return items


def parse_toplist_cards(page_html: str) -> list[dict[str, Any]]:
    """解析 go-music-dl /toplists 页面榜单卡片。"""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a\b([^>]*\btoplist-card\b[^>]*)>([\s\S]*?)</a>', page_html):
        attrs = m.group(1)
        inner = m.group(2) or ""
        hm = re.search(r'\bhref="([^"]+)"', attrs) or re.search(r"\bhref='([^']+)'", attrs)
        if not hm:
            continue
        href = _unescape_html(hm.group(1))
        qs = parse_qs(urlparse(href).query)
        source = (qs.get("source") or [""])[0].strip()
        tid = (qs.get("toplist_id") or [""])[0].strip()
        if not source or not tid:
            continue
        key = f"{source}:{tid}"
        if key in seen:
            continue
        seen.add(key)
        try:
            tcount = int((qs.get("track_count") or ["0"])[0] or 0)
        except ValueError:
            tcount = 0
        play_m = re.search(r'fa-headphones[^>]*>\s*</i>\s*([^<]+?)\s*</span>', inner)
        items.append(
            {
                "source": source,
                "toplist_id": tid,
                "name": _unescape_html((qs.get("toplist_name") or [tid])[0]),
                "update_frequency": _unescape_html((qs.get("update_frequency") or [""])[0]),
                "cover": _unescape_html((qs.get("cover") or [""])[0]),
                "description": _unescape_html((qs.get("description") or [""])[0]),
                "track_count": tcount,
                "play_count_text": _unescape_html(play_m.group(1).strip()) if play_m else "",
            }
        )
    return items


def parse_pagination(page_html: str) -> dict[str, int]:
    m = re.search(r"当前第\s*(\d+)\s*/\s*(\d+)\s*页，显示\s*(\d+)\s*-\s*(\d+)\s*/\s*(\d+)", page_html)
    if m:
        return {
            "page": int(m.group(1)),
            "total_pages": int(m.group(2)),
            "page_start": int(m.group(3)),
            "page_end": int(m.group(4)),
            "total": int(m.group(5)),
        }
    return {"page": 1, "total_pages": 1, "page_start": 0, "page_end": 0, "total": 0}


def sort_songs_by_relevance(songs: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    """原唱智能加权排序：歌名与歌手均命中大幅置顶，未显式要求时降权 Live/伴奏/翻唱/Remix。"""
    kw = (keyword or "").strip().lower()
    if not kw or not songs:
        return songs
    wants_deriv = any(dk in kw for dk in DERIVATIVE_KEYWORDS)
    tokens = [t for t in re.split(r"[\s的之与和&/\-_]+", kw) if t]

    def _score(s: dict[str, Any]) -> float:
        name = str(s.get("name") or "").strip().lower()
        artist = str(s.get("artist") or "").strip().lower()
        album = str(s.get("album") or "").strip().lower()
        if not name:
            return 0.0
        combined = f"{artist} {name}"
        combined_alt = f"{name} {artist}"
        score = 0.0
        kw_artist = bool(artist and len(artist) >= 2 and artist in kw)
        kw_name = bool(name and len(name) >= 1 and name in kw)
        tok_artist = any(len(t) >= 2 and t in artist for t in tokens)
        tok_name = any(len(t) >= 1 and t in name for t in tokens)

        if (kw_artist and kw_name) or (tok_artist and tok_name):
            score = 1200.0
            if name == kw or combined.replace(" ", "") == kw.replace(" ", "").replace("的", ""):
                score += 500.0
            elif kw_name and len(name) >= 2:
                score += 300.0
        elif name == kw or combined == kw or combined_alt == kw:
            score = 1000.0
        elif kw in name:
            score = 500.0
        elif kw_name or tok_name:
            score = 200.0
        elif kw_artist or tok_artist:
            score = 100.0

        if not wants_deriv and any(dk in name or dk in album for dk in DERIVATIVE_KEYWORDS):
            score -= 250.0
        if not re.search(r"[(\（\[\【].*?[)\）\]\】]", name):
            score += 30.0
        score -= len(name) * 0.1
        return score

    return sorted(songs, key=_score, reverse=True)


def build_upstream_download_url(
    song: dict[str, Any],
    base_url: str | None = None,
    stream_only: bool = True,
) -> str:
    base = normalize_music_dl_base(base_url)
    if not base:
        return ""
    extra_json = json.dumps(song.get("extra") or {}, ensure_ascii=False)
    parts = [
        f"id={quote(str(song.get('id') or ''))}",
        f"source={quote(str(song.get('source') or ''))}",
        f"name={quote(str(song.get('name') or ''))}",
        f"artist={quote(str(song.get('artist') or ''))}",
        f"album={quote(str(song.get('album') or ''))}",
        f"cover={quote(str(song.get('cover') or ''))}",
        f"extra={quote(extra_json)}",
        "stream=1" if stream_only else "embed=1",
    ]
    return f"{base}/download?{'&'.join(parts)}"


async def check_music_dl_health(url_override: str | None = None, timeout_sec: float = 3.5) -> dict[str, Any]:
    """探测 go-music-dl 多源音乐引擎健康状态与已启用平台。"""
    base = normalize_music_dl_base(url_override)
    if not base:
        return {"ok": False, "base_url": "", "sources": [], "latency_ms": 0, "error": "未配置多源音乐服务地址"}

    t0 = time.perf_counter()
    headers = {"X-Requested-With": "XMLHttpRequest"}
    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
            resp = await client.get(f"{base}/api/ai/index", headers=headers)
            latency = int((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    srcs = (data.get("sources") or {}).get("song") or []
                    return {
                        "ok": True,
                        "base_url": base,
                        "sources": srcs if isinstance(srcs, list) else _default_sources(),
                        "latency_ms": latency,
                        "error": "",
                    }
                except Exception:
                    pass
            resp2 = await client.get(f"{base}/healthz", headers=headers)
            if resp2.status_code == 200:
                return {
                    "ok": True,
                    "base_url": base,
                    "sources": _default_sources(),
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "error": "",
                }
            return {
                "ok": False,
                "base_url": base,
                "sources": [],
                "latency_ms": latency,
                "error": f"HTTP {resp.status_code}",
            }
    except Exception as exc:
        return {
            "ok": False,
            "base_url": base,
            "sources": [],
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(exc),
        }


async def cloud_search(
    q: str,
    search_type: Literal["song", "playlist", "album"] = "song",
    sources: list[str] | None = None,
    page: int = 1,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    """搜索多平台单曲、歌单或专辑。"""
    base = normalize_music_dl_base()
    if not base:
        return {"songs": [], "collections": [], "pagination": {"page": 1, "total_pages": 1, "total": 0}}

    src_list = [s.strip() for s in (sources or _default_sources()) if s.strip()]
    params: list[tuple[str, str]] = [("q", q.strip()), ("type", search_type), ("page", str(max(1, page)))]
    for s in src_list:
        params.append(("sources", s))

    async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
        resp = await client.get(f"{base}/search", params=params, headers={"X-Requested-With": "XMLHttpRequest"})
        resp.raise_for_status()
        body = resp.text

    pagination = parse_pagination(body)
    if search_type == "song":
        songs = sort_songs_by_relevance(parse_song_cards(body), q)
        if pagination["total"] == 0 and songs:
            pagination["total"] = len(songs)
        return {"songs": songs, "collections": [], "pagination": pagination}

    cols = parse_playlist_cards(body)
    if pagination["total"] == 0 and cols:
        pagination["total"] = len(cols)
    return {"songs": [], "collections": cols, "pagination": pagination}


async def cloud_toplists(sources: list[str] | None = None, timeout_sec: float = 15.0) -> list[dict[str, Any]]:
    base = normalize_music_dl_base()
    if not base:
        return []
    src_list = [s.strip() for s in (sources or _default_sources()) if s.strip()]
    params = [("sources", s) for s in src_list]
    async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
        resp = await client.get(f"{base}/toplists", params=params, headers={"X-Requested-With": "XMLHttpRequest"})
        resp.raise_for_status()
        return parse_toplist_cards(resp.text)


async def cloud_toplist_songs(source: str, toplist_id: str, timeout_sec: float = 18.0) -> list[dict[str, Any]]:
    base = normalize_music_dl_base()
    if not base:
        return []
    params = [("source", source), ("toplist_id", toplist_id), ("page_size", "200")]
    async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
        resp = await client.get(f"{base}/toplist_songs", params=params, headers={"X-Requested-With": "XMLHttpRequest"})
        resp.raise_for_status()
        return parse_song_cards(resp.text)


async def cloud_collection_songs(
    source: str,
    collection_id: str,
    kind: Literal["playlist", "album"] = "playlist",
    page: int = 1,
    timeout_sec: float = 18.0,
) -> list[dict[str, Any]]:
    base = normalize_music_dl_base()
    if not base:
        return []
    route = "album" if kind == "album" else "playlist"
    params = [("id", collection_id), ("source", source), ("page", str(max(1, page)))]
    async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
        resp = await client.get(f"{base}/{route}", params=params, headers={"X-Requested-With": "XMLHttpRequest"})
        resp.raise_for_status()
        return parse_song_cards(resp.text)


async def fetch_song_lyric(song: dict[str, Any], base_url: str | None = None, timeout_sec: float = 10.0) -> str:
    base = normalize_music_dl_base(base_url)
    if not base:
        return ""
    params = [
        ("id", str(song.get("id") or "")),
        ("source", str(song.get("source") or "")),
        ("name", str(song.get("name") or "")),
        ("artist", str(song.get("artist") or "")),
        ("album", str(song.get("album") or "")),
        ("duration", str(song.get("duration") or 0)),
        ("extra", json.dumps(song.get("extra") or {}, ensure_ascii=False)),
        ("format", "auto"),
    ]
    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
            resp = await client.get(f"{base}/download_lrc", params=params, headers={"X-Requested-With": "XMLHttpRequest"})
            if resp.status_code == 200 and len(resp.text.strip()) > 4:
                return resp.text.strip()
    except Exception:
        pass
    return ""


async def try_switch_source(
    name: str,
    artist: str = "",
    current_source: str = "",
    duration: int = 0,
    base_url: str | None = None,
) -> dict[str, Any] | None:
    """当首选音源因 VIP 权限或节点失效不可播放时，调用智能换源接口获取替代歌曲。"""
    base = normalize_music_dl_base(base_url)
    if not base or not name.strip():
        return None
    params = [("name", name.strip()), ("artist", artist.strip()), ("source", current_source.strip())]
    if duration > 0:
        params.append(("duration", str(duration)))
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{base}/switch_source", params=params, headers={"X-Requested-With": "XMLHttpRequest"})
            if resp.status_code != 200:
                return None
            data = resp.json()
            if isinstance(data, dict) and data.get("id") and data.get("source"):
                return {
                    "id": str(data["id"]),
                    "source": str(data["source"]),
                    "name": str(data.get("name") or name),
                    "artist": str(data.get("artist") or artist),
                    "album": str(data.get("album") or ""),
                    "cover": str(data.get("cover") or ""),
                    "duration": int(data.get("duration") or duration or 0),
                    "extra": data.get("extra") if isinstance(data.get("extra"), dict) else {},
                }
    except Exception:
        pass
    return None


async def _ensure_batch_target_album(
    album_id: int | None,
    new_album_title: str,
    category: str = "music",
    age_stage: str = "S6_ALL",
) -> tuple[int, str]:
    if album_id:
        async with get_db() as conn:
            cur = await conn.execute("SELECT id, title FROM media_albums WHERE id = ?", (album_id,))
            row = await cur.fetchone()
            if row:
                return int(row["id"]), str(row["title"])

    title = (new_album_title or "").strip() or "云端下载精选"
    cat = category if category in ("music", "story", "english", "podcast") else "music"
    stage = age_stage if age_stage in ("S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL") else "S6_ALL"
    async with get_db() as conn:
        cur = await conn.execute("SELECT id, title FROM media_albums WHERE title = ?", (title,))
        row = await cur.fetchone()
        if row:
            return int(row["id"]), str(row["title"])
        cur_ins = await conn.execute(
            """
            INSERT INTO media_albums
            (title, category, sub_tag, age_stage, english_level, play_mode, cover_emoji, language, is_inbox, description, created_at)
            VALUES (?, ?, '经典歌单', ?, 'Pre_A1', 'sequential', '💿', 'zh', 0, '从全网云音乐批量下载并校准入库的私有专辑', ?)
            """,
            (title, cat, stage, now_iso()),
        )
        await conn.commit()
        return int(cur_ins.lastrowid), title


async def _update_download_job(
    job_id: int,
    status: str,
    progress_text: str,
    tracks_added: int = 0,
    error_msg: str = "",
) -> None:
    async with get_db() as conn:
        await conn.execute(
            """
            UPDATE download_jobs
            SET status = ?, progress_text = ?, tracks_added = ?, error_msg = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, progress_text, tracks_added, error_msg, now_iso(), job_id),
        )
        await conn.commit()


async def _download_single_cloud_song(
    client: httpx.AsyncClient,
    song: dict[str, Any],
    base_url: str,
    target_album_id: int,
    job_dir: Path,
) -> Literal["added", "skipped", "failed"]:
    sid = str(song.get("id") or "").strip()
    source = str(song.get("source") or "").strip()
    name = str(song.get("name") or "").strip() or "未命名歌曲"
    artist = str(song.get("artist") or "").strip()
    if not sid or not source:
        return "failed"

    guid = f"mdl:{source}:{sid}"
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT id, file_path FROM media_tracks WHERE album_id = ? AND external_guid = ? LIMIT 1",
            (target_album_id, guid),
        )
        exist = await cur.fetchone()
        if exist and exist["file_path"] and Path(exist["file_path"]).exists():
            return "skipped"

    active_song = dict(song)
    audio_bytes = b""
    dl_url = build_upstream_download_url(active_song, base_url=base_url, stream_only=False)
    headers = {"X-Requested-With": "XMLHttpRequest"}

    try:
        r = await client.get(dl_url, headers=headers)
        if r.status_code == 200 and len(r.content) > 512:
            audio_bytes = r.content
    except Exception:
        audio_bytes = b""

    if not audio_bytes:
        alt = await try_switch_source(name=name, artist=artist, current_source=source, duration=int(active_song.get("duration") or 0), base_url=base_url)
        if alt:
            alt_url = build_upstream_download_url(alt, base_url=base_url, stream_only=False)
            try:
                r2 = await client.get(alt_url, headers=headers)
                if r2.status_code == 200 and len(r2.content) > 512:
                    audio_bytes = r2.content
                    active_song = alt
            except Exception:
                audio_bytes = b""

    if not audio_bytes:
        return "failed"

    tmp_file = job_dir / f"{uuid.uuid4().hex[:10]}.audio"
    try:
        tmp_file.write_bytes(audio_bytes)
        lyric = await fetch_song_lyric(active_song, base_url=base_url)
        display_title = f"{name} - {artist}" if artist else name
        await insert_normalized_track(
            album_id=target_album_id,
            title=display_title,
            raw_file=tmp_file,
            source_url=guid,
            external_guid=guid,
            text_content=lyric,
        )
        return "added"
    finally:
        tmp_file.unlink(missing_ok=True)


async def _run_batch_download_job(
    job_id: int,
    target_album_id: int,
    album_title: str,
    songs: list[dict[str, Any]],
    base_url: str,
    auto_group_by_artist: bool = False,
) -> None:
    from app.services.ai_curator import ensure_series_and_season

    job_dir = MEDIA_RAW_DIR / f"cloud_batch_{job_id}_{uuid.uuid4().hex[:6]}"
    job_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(3)
    total = len(songs)
    added = 0
    skipped = 0
    failed = 0
    lock = asyncio.Lock()

    try:
        async with httpx.AsyncClient(timeout=75.0, follow_redirects=True) as client:

            async def _worker(s: dict[str, Any]) -> None:
                nonlocal added, skipped, failed
                async with sem:
                    try:
                        dest_aid = target_album_id
                        if auto_group_by_artist:
                            raw_artist = str(s.get("artist") or "").strip()
                            primary_artist = re.split(r"[/、,&，]", raw_artist)[0].strip() if raw_artist else "群星精选"
                            alb_label = str(s.get("album") or "").strip() or "精选辑"
                            _, alb_obj = await ensure_series_and_season(
                                channel="music",
                                series_title=primary_artist,
                                season_num=1,
                                season_label=alb_label,
                                author=primary_artist,
                            )
                            dest_aid = int(alb_obj["id"])
                        outcome = await _download_single_cloud_song(client, s, base_url, dest_aid, job_dir)
                    except Exception:
                        outcome = "failed"
                    async with lock:
                        if outcome == "added":
                            added += 1
                        elif outcome == "skipped":
                            skipped += 1
                        else:
                            failed += 1
                        done_cnt = added + skipped + failed
                        await _update_download_job(
                            job_id,
                            "running",
                            f"《{album_title}》{done_cnt}/{total}（新增 {added}，已存在 {skipped}，失败 {failed}）",
                            tracks_added=added,
                        )

            await asyncio.gather(*(_worker(s) for s in songs))

        final_status = "failed" if (added == 0 and skipped == 0 and failed > 0) else "done"
        await _update_download_job(
            job_id,
            final_status,
            f"《{album_title}》批量入库完成：新增 {added} 首，跳过已存在 {skipped} 首，失败 {failed} 首",
            tracks_added=added,
            error_msg="全部曲目下载失败，请检查上游音源或 VIP Cookie 配置" if final_status == "failed" else "",
        )
    except Exception as exc:
        await _update_download_job(job_id, "failed", f"《{album_title}》下载任务异常中止", tracks_added=added, error_msg=str(exc)[:300])
    finally:
        for p in job_dir.glob("*"):
            p.unlink(missing_ok=True)
        if job_dir.exists():
            job_dir.rmdir()


async def enqueue_cloud_batch_download(
    songs: list[dict[str, Any]],
    album_id: int | None = None,
    series_id: int | None = None,
    new_series_title: str = "",
    season_label: str = "",
    new_album_title: str = "云端下载精选",
    auto_group_by_artist: bool = False,
    category: str = "music",
    age_stage: str = "S6_ALL",
) -> dict[str, Any]:
    """创建云端批量下歌并转码入库异步任务（支持按歌手自动三级分类或归入指定歌手合集→专辑）。"""
    from app.services.ai_curator import ensure_series_and_season

    base_url = normalize_music_dl_base()
    if not base_url:
        raise ValueError("尚未配置多源音乐服务地址")
    if not songs:
        raise ValueError("待下载曲目列表为空")

    if auto_group_by_artist:
        _, default_alb = await ensure_series_and_season(channel=category, series_title="云端精选", season_num=1, season_label="精选辑")
        target_aid = int(default_alb["id"])
        target_title = "按歌手自动三级分类"
    elif album_id:
        target_aid, target_title = await _ensure_batch_target_album(
            album_id=album_id,
            new_album_title=new_album_title,
            category=category,
            age_stage=age_stage,
        )
    elif series_id:
        async with get_db() as conn:
            cur_s = await conn.execute("SELECT * FROM media_series WHERE id = ?", (series_id,))
            srow = await cur_s.fetchone()
            if not srow:
                raise ValueError("目标歌手/合集系列不存在")
            cur_max = await conn.execute("SELECT COALESCE(MAX(season_num), 0) FROM media_albums WHERE series_id = ?", (series_id,))
            nxt = int((await cur_max.fetchone())[0] or 0) + 1
            _, alb_obj = await ensure_series_and_season(
                channel=srow["channel"],
                series_title=srow["title"],
                season_num=nxt if season_label.strip() else 1,
                season_label=season_label.strip() or "精选辑",
            )
            target_aid = int(alb_obj["id"])
            target_title = str(alb_obj["title"])
    elif new_series_title.strip():
        _, alb_obj = await ensure_series_and_season(
            channel=category,
            series_title=new_series_title.strip(),
            season_num=1,
            season_label=season_label.strip() or "精选辑",
        )
        target_aid = int(alb_obj["id"])
        target_title = str(alb_obj["title"])
    else:
        target_aid, target_title = await _ensure_batch_target_album(
            album_id=None,
            new_album_title=new_album_title,
            category=category,
            age_stage=age_stage,
        )
    ts = now_iso()
    async with get_db() as conn:
        cur = await conn.execute(
            """
            INSERT INTO download_jobs (job_type, source_url, target_album_id, status, progress_text, tracks_added, created_at, updated_at)
            VALUES ('source_sync', ?, ?, 'running', ?, 0, ?, ?)
            """,
            (f"cloud_batch://{target_aid}", target_aid, f"准备批量下载 {len(songs)} 首歌曲到《{target_title}》...", ts, ts),
        )
        job_id = int(cur.lastrowid)
        await conn.commit()

    task = asyncio.create_task(
        _run_batch_download_job(job_id, target_aid, target_title, list(songs), base_url, auto_group_by_artist=auto_group_by_artist)
    )
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)

    return {
        "job_id": job_id,
        "album_id": target_aid,
        "album_title": target_title,
        "total_requested": len(songs),
        "auto_group_by_artist": auto_group_by_artist,
        "status": "running",
    }

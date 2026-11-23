"""网盘 / OpenList / AList / NAS WebDAV 挂载、目录预览与三级树自动同步入库服务。"""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from app.config import MEDIA_RAW_DIR
from app.db import _default_season_label, get_db, now_iso
from app.services.ai_curator import ensure_series_and_season, extract_episode_number_from_title, parse_cn_number
from app.services.collector import AUDIO_EXTS, insert_normalized_track


def _build_webdav_url(base_url: str, remote_path: str) -> str:
    base = base_url.strip().rstrip("/")
    rp = "/" + remote_path.strip().lstrip("/")
    if rp == "/":
        return base + "/"
    return f"{base}{rp}"


def _parse_season_from_folder(folder_name: str, channel: str) -> tuple[int, str]:
    t = folder_name.strip()
    m = re.search(r"第\s*([一二两三四五六七八九十\d]+)\s*([季部辑册单元])", t)
    if m:
        n = parse_cn_number(m.group(1)) or 1
        return n, f"第{n}{m.group(2)}"
    m2 = re.search(r"[Ss](?:eason)?\s*0*(\d+)", t)
    if m2:
        n = max(1, int(m2.group(1)))
        return n, f"第{n}季"
    return 1, t or _default_season_label(channel, 1)


async def _propfind_children(
    client: httpx.AsyncClient,
    target_url: str,
    auth: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """执行标准 WebDAV PROPFIND (Depth: 1) 并解析直接子目录与文件列表。"""
    headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:propfind xmlns:D="DAV:"><D:prop><D:resourcetype/><D:getcontentlength/><D:displayname/></D:prop></D:propfind>'
    )
    resp = await client.request("PROPFIND", target_url, headers=headers, content=body, auth=auth)
    if resp.status_code not in (200, 207):
        raise RuntimeError(f"WebDAV PROPFIND 返回 HTTP {resp.status_code}")

    root = ET.fromstring(resp.text)
    target_path = unquote(urlparse(target_url).path).rstrip("/") or "/"
    entries: list[dict[str, Any]] = []

    for elem in root.iter():
        if not elem.tag.endswith("response"):
            continue
        href = ""
        is_dir = False
        size = 0
        for child in elem.iter():
            if child.tag.endswith("href") and child.text:
                href = child.text.strip()
            elif child.tag.endswith("collection"):
                is_dir = True
            elif child.tag.endswith("getcontentlength") and child.text:
                try:
                    size = int(child.text.strip())
                except ValueError:
                    size = 0
        if not href:
            continue
        full_href = urljoin(target_url if target_url.endswith("/") else target_url + "/", href)
        item_path = unquote(urlparse(full_href).path).rstrip("/") or "/"
        if item_path == target_path:
            continue
        name = Path(item_path).name
        if not name or name.startswith("."):
            continue
        entries.append({"name": name, "url": full_href, "path": item_path, "is_dir": is_dir, "size": size})
    return entries


async def preview_webdav_directory(
    base_url: str,
    remote_path: str = "/",
    username: str = "",
    password: str = "",
) -> list[dict[str, Any]]:
    """预览 WebDAV 远程目录结构，验证账号连通性并展示可导入音频目录。"""
    auth = (username, password) if username else None
    url = _build_webdav_url(base_url, remote_path)
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        return await _propfind_children(client, url, auth=auth)


async def sync_webdav_mount(mount_id: int, max_files: int = 80) -> dict[str, Any]:
    """
    递归扫描指定 WebDAV 挂载点并按「一级目录(系列) → 二级目录(第几季) → 音频文件(第几集)」自动入库。
    支持幂等去重（external_guid）。
    """
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM webdav_mounts WHERE id = ?", (mount_id,))
        row = await cur.fetchone()
        if not row:
            raise ValueError("WebDAV 挂载点不存在")
        mount = dict(row)

    auth = (mount["username"], mount["password"]) if mount.get("username") else None
    root_url = _build_webdav_url(mount["base_url"], mount.get("remote_path") or "/")
    channel = mount.get("channel") or "story"
    level_code = mount.get("level_code") or ("L1" if channel == "english" else "")
    limit = max(1, min(int(max_files or 80), 300))

    discovered_files: list[tuple[list[str], dict[str, Any]]] = []

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        async def _walk(cur_url: str, rel_dirs: list[str], depth: int) -> None:
            if len(discovered_files) >= limit or depth > 3:
                return
            children = await _propfind_children(client, cur_url, auth=auth)
            for item in sorted(children, key=lambda x: x["name"]):
                if len(discovered_files) >= limit:
                    return
                if item["is_dir"]:
                    await _walk(item["url"], [*rel_dirs, item["name"]], depth + 1)
                else:
                    ext = Path(item["name"]).suffix.lower()
                    if ext in AUDIO_EXTS:
                        discovered_files.append((rel_dirs, item))

        await _walk(root_url, [], 0)

        MEDIA_RAW_DIR.mkdir(parents=True, exist_ok=True)
        added = 0
        skipped = 0
        for rel_dirs, item in discovered_files:
            guid = f"webdav:{mount_id}:{item['path']}"
            async with get_db() as conn:
                chk = await conn.execute("SELECT id FROM media_tracks WHERE external_guid = ? LIMIT 1", (guid,))
                if await chk.fetchone():
                    skipped += 1
                    continue

            if len(rel_dirs) >= 2:
                series_title = rel_dirs[-2]
                season_num, season_label = _parse_season_from_folder(rel_dirs[-1], channel)
            elif len(rel_dirs) == 1:
                series_title = rel_dirs[0]
                season_num, season_label = 1, _default_season_label(channel, 1)
            else:
                series_title = mount["name"]
                season_num, season_label = 1, _default_season_label(channel, 1)

            _, album = await ensure_series_and_season(
                channel=channel,
                series_title=series_title,
                season_num=season_num,
                season_label=season_label,
                level_code=level_code,
            )
            ext = Path(item["name"]).suffix.lower() or ".mp3"
            tmp_file = MEDIA_RAW_DIR / f"wd_{mount_id}_{uuid.uuid4().hex[:8]}{ext}"
            try:
                resp = await client.get(item["url"], auth=auth)
                if resp.status_code < 400 and len(resp.content) > 256:
                    tmp_file.write_bytes(resp.content)
                    title = Path(item["name"]).stem
                    ep = extract_episode_number_from_title(title)
                    await insert_normalized_track(
                        album_id=int(album["id"]),
                        title=title,
                        raw_file=tmp_file,
                        source_url=item["url"],
                        episode_num=ep,
                        external_guid=guid,
                    )
                    added += 1
            finally:
                tmp_file.unlink(missing_ok=True)

    ts = now_iso()
    summary = f"同步完成：新增 {added} 条，跳过已存在 {skipped} 条（共发现 {len(discovered_files)} 个音频）"
    async with get_db() as conn:
        await conn.execute(
            "UPDATE webdav_mounts SET last_synced_at = ?, last_status = ?, tracks_synced = tracks_synced + ? WHERE id = ?",
            (ts, summary, added, mount_id),
        )
        await conn.commit()

    return {
        "mount_id": mount_id,
        "total_discovered": len(discovered_files),
        "tracks_added": added,
        "skipped": skipped,
        "summary": summary,
    }

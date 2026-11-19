"""管理员专属：播客源、采集源运营中心与全年龄段示范库按需初始化路由。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user, require_admin
from app.db import get_db, now_iso
from app.services.collector import list_source_episodes, probe_content_source, seed_sample_catalog, sync_content_source
from app.services.scheduler import scheduler_service

router = APIRouter(prefix="/api", tags=["content_sources"])


class SourceCreate(BaseModel):
    name: str
    source_type: Literal["podcast_rss", "ytdlp_playlist"] = "podcast_rss"
    url: str
    target_album_id: int | None = None
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] = "S6_ALL"
    english_level: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS", "adult"] = "Pre_A1"
    auto_sync: bool = True
    sync_interval_hours: int = 12
    max_items_per_sync: int = 5


class SourcePatch(BaseModel):
    name: str | None = None
    url: str | None = None
    target_album_id: int | None = None
    age_stage: Literal["S1_0_3", "S2_3_6", "S3_6_9", "S4_9_12", "S5_12_18", "S6_ALL"] | None = None
    english_level: Literal["Pre_A1", "A1", "A2", "B1", "B2_PLUS", "adult"] | None = None
    auto_sync: bool | None = None
    sync_interval_hours: int | None = None
    max_items_per_sync: int | None = None


class SourceProbeRequest(BaseModel):
    source_type: Literal["podcast_rss", "ytdlp_playlist"] = "podcast_rss"
    url: str


@router.get("/content-sources")
async def list_sources(_user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT s.*, a.title AS album_title
            FROM content_sources s
            LEFT JOIN media_albums a ON s.target_album_id = a.id
            ORDER BY s.id DESC
            """
        )
        return [dict(r) for r in await cur.fetchall()]


@router.post("/content-sources")
async def create_source(
    req: SourceCreate,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    if not req.name.strip() or not req.url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请填写合法的内容源名称与 http/https 地址")
    ts = now_iso()
    async with get_db() as conn:
        try:
            cur = await conn.execute(
                """
                INSERT INTO content_sources
                (name, source_type, url, target_album_id, age_stage, english_level, auto_sync, sync_interval_hours, max_items_per_sync, last_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '已配置，等待同步', ?)
                """,
                (
                    req.name.strip(),
                    req.source_type,
                    req.url.strip(),
                    req.target_album_id,
                    req.age_stage,
                    req.english_level,
                    1 if req.auto_sync else 0,
                    max(1, int(req.sync_interval_hours)),
                    max(1, min(30, int(req.max_items_per_sync))),
                    ts,
                ),
            )
            await conn.commit()
            sid = int(cur.lastrowid)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"创建内容源失败: {exc}")
    await scheduler_service.reload_jobs()
    return {"id": sid, "name": req.name.strip()}


@router.patch("/content-sources/{source_id}")
async def update_source(
    source_id: int,
    req: SourcePatch,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM content_sources WHERE id = ?", (source_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="内容源不存在")
        cur_data = dict(row)
        updates = req.model_dump(exclude_none=True)
        for k, v in updates.items():
            if k == "auto_sync":
                cur_data[k] = 1 if v else 0
            else:
                cur_data[k] = v
        await conn.execute(
            """
            UPDATE content_sources
            SET name = ?, url = ?, target_album_id = ?, age_stage = ?, english_level = ?,
                auto_sync = ?, sync_interval_hours = ?, max_items_per_sync = ?
            WHERE id = ?
            """,
            (
                cur_data["name"],
                cur_data["url"],
                cur_data["target_album_id"],
                cur_data["age_stage"],
                cur_data["english_level"],
                cur_data["auto_sync"],
                cur_data["sync_interval_hours"],
                cur_data["max_items_per_sync"],
                source_id,
            ),
        )
        await conn.commit()
    await scheduler_service.reload_jobs()
    return cur_data


@router.delete("/content-sources/{source_id}")
async def delete_source(
    source_id: int,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    async with get_db() as conn:
        await conn.execute("DELETE FROM content_sources WHERE id = ?", (source_id,))
        await conn.commit()
    await scheduler_service.reload_jobs()
    return {"status": "deleted"}


@router.post("/content-sources/probe")
async def probe_source_endpoint(
    req: SourceProbeRequest,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return await probe_content_source(req.source_type, req.url.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"探测失败: {exc}")


@router.post("/content-sources/{source_id}/sync")
async def sync_source_endpoint(
    source_id: int,
    background_tasks: BackgroundTasks,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM content_sources WHERE id = ?", (source_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="内容源不存在")

    async def _run():
        try:
            await sync_content_source(source_id)
        except Exception:
            pass

    background_tasks.add_task(_run)
    return {"status": "syncing", "message": "已提交后台增量同步任务"}


@router.get("/content-sources/presets")
async def get_source_presets(_user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    """供播客中心与管理员中心一键订阅的精选音频源模板。"""
    return [
        {
            "name": "BBC Global News Podcast（英语时事）",
            "source_type": "podcast_rss",
            "url": "https://podcasts.files.bbci.co.uk/p02nq0gn.rss",
            "age_stage": "S5_12_18",
            "english_level": "B2_PLUS",
            "description": "地道英音全球新闻精听，适合青少年及家长通勤收听。",
        },
        {
            "name": "NPR Short Wave（少儿/少年科学播客）",
            "source_type": "podcast_rss",
            "url": "https://feeds.npr.org/510351/podcast.xml",
            "age_stage": "S4_9_12",
            "english_level": "B1",
            "description": "每期 10 分钟趣味前沿科普发现，短小精悍适合音箱陪伴。",
        },
        {
            "name": "TED Talks Daily（原版思辨演讲）",
            "source_type": "podcast_rss",
            "url": "https://pa.tedcdn.com/feeds/talks.rss",
            "age_stage": "S5_12_18",
            "english_level": "B2_PLUS",
            "description": "全球前沿思想与英文演讲精华，开拓青少年国际视野。",
        },
        {
            "name": "声律启蒙与古诗词吟诵合集",
            "source_type": "ytdlp_playlist",
            "url": "https://www.bilibili.com/video/av116436143969318",
            "age_stage": "S2_3_6",
            "english_level": "Pre_A1",
            "description": "经典儿歌与韵律合集抓取源模板（支持自定义替换为任意 B 站/YouTube 合集）。",
        },
    ]


@router.get("/content-sources/{source_id}/episodes")
async def get_source_episodes_endpoint(
    source_id: int,
    limit: int = 20,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """实时探测播客单集并对齐本地已缓存曲目，供播客详情页直接点播。"""
    try:
        return await list_source_episodes(source_id, limit=min(max(limit, 1), 30))
    except ValueError:
        raise HTTPException(status_code=404, detail="内容源不存在")


@router.post("/admin/seed-sample-catalog")
async def admin_seed_sample_catalog(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """按需导入全年龄段（0-3/3-6/6-9/9-12/12-18）示范书籍、专辑、英语课与播客源模板。"""
    return await seed_sample_catalog()

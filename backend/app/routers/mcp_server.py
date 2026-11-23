"""标准 JSON-RPC 2.0 MCP Server 路由（供 xiaozhi-esp32-server 或外部 AI Agent 直接操控 EchoMind）。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request

from app.db import get_db
from app.gateways.manager import device_manager
from app.services.ai_curator import enqueue_ai_collect
from app.services.brain import process_user_turn, resolve_voice_play_request
from app.services.voiceprint import identify_speaker

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "echomind_play_series",
        "description": "播放或断点续播 EchoMind 中的故事系列、音乐合集、英语启蒙或播客，支持精准指定第几季和第几集。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "系列或歌曲名称，如 汪汪队、周杰伦、西游记"},
                "category": {"type": "string", "enum": ["story", "music", "english", "podcast"]},
                "season_num": {"type": "integer", "description": "第几季/第几单元（可选）"},
                "episode_num": {"type": "integer", "description": "第几集/第几课（可选）"},
                "level_code": {"type": "string", "enum": ["L1", "L2", "L3", "L4", "L5"]},
                "device_id": {"type": "string", "description": "目标音箱设备ID（可选，留空自动选首台在线音箱）"},
            },
        },
    },
    {
        "name": "echomind_collect_and_classify",
        "description": "后台全网采集故事、歌曲或英语音频，由 AI 自动按「系列 → 季 → 集」分类入库，完成后自动在音箱播报通知结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "采集内容名称，如 汪汪队第2季、周杰伦"},
                "channel_hint": {"type": "string", "enum": ["story", "music", "english", "podcast"]},
                "max_items": {"type": "integer", "description": "最大采集集数/首数，默认 5"},
                "device_id": {"type": "string", "description": "采集完成后播报通知的目标音箱ID（可选）"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "echomind_control_playback",
        "description": "控制家里音箱播放状态：暂停、继续、停止、上一集、下一集、跳集、重播、快进、快退、调节音量、设置睡眠定时。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command_text": {"type": "string", "description": "自然语言播控指令，如 暂停播放、跳到第5集、快进30秒、音量调到50、20分钟后停止"},
                "device_id": {"type": "string", "description": "目标音箱ID（可选）"},
            },
            "required": ["command_text"],
        },
    },
    {
        "name": "echomind_list_library",
        "description": "查询 EchoMind 媒体库中已有的系列合集、季数、总集数以及每个系列上次播放到的位置。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["all", "story", "music", "english", "podcast"]},
                "keyword": {"type": "string"},
            },
        },
    },
    {
        "name": "echomind_push_to_speaker",
        "description": "将指定系列（从上次续播位置开始）直接推送给一台或多台房间音箱跨季连播。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "series_title": {"type": "string"},
                "device_id": {"type": "string"},
                "sleep_minutes": {"type": "integer"},
                "sleep_episodes": {"type": "integer"},
            },
            "required": ["series_title"],
        },
    },
]


async def _resolve_default_device_id(device_id: str | None) -> str:
    if device_id and device_id.strip():
        return device_id.strip()
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM devices WHERE paired = 1 ORDER BY online DESC, created_at DESC LIMIT 1")
        row = await cur.fetchone()
        return str(row["id"]) if row else ""


async def _dispatch_mcp_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "echomind_list_library":
        ch = args.get("channel") or "all"
        kw = str(args.get("keyword") or "").strip().lower()
        async with get_db() as conn:
            if ch != "all":
                cur = await conn.execute("SELECT * FROM media_series WHERE channel = ? ORDER BY COALESCE(last_played_at,'') DESC, id DESC", (ch,))
            else:
                cur = await conn.execute("SELECT * FROM media_series ORDER BY COALESCE(last_played_at,'') DESC, id DESC")
            rows = [dict(r) for r in await cur.fetchall()]
            items = []
            for s in rows:
                if kw and kw not in s["title"].lower():
                    continue
                cur_a = await conn.execute(
                    "SELECT id, season_num, season_label, (SELECT COUNT(*) FROM media_tracks t WHERE t.album_id = media_albums.id) AS cnt FROM media_albums WHERE series_id = ? ORDER BY season_num ASC",
                    (s["id"],),
                )
                seas = [dict(x) for x in await cur_a.fetchall()]
                items.append(
                    {
                        "id": s["id"],
                        "title": s["title"],
                        "channel": s["channel"],
                        "level_code": s.get("level_code", ""),
                        "seasons": seas,
                        "total_tracks": sum(int(x["cnt"] or 0) for x in seas),
                        "last_position_sec": float(s.get("last_position_sec") or 0.0),
                    }
                )
        return {"count": len(items), "series": items[:30]}

    if name == "echomind_play_series":
        speaker = await identify_speaker()
        res = await resolve_voice_play_request(
            category=args.get("category"),
            keyword=args.get("keyword"),
            age_stage=speaker.age_stage,
            season_num=args.get("season_num"),
            episode_num=args.get("episode_num"),
            level_code=args.get("level_code"),
        )
        if res.get("type") != "play_track":
            return {"ok": False, "message": "未找到匹配的音频内容"}
        tr = res["track"]
        q_list = res.get("queue_tracks") or [tr]
        did = await _resolve_default_device_id(args.get("device_id"))
        if did:
            idx = next((i for i, x in enumerate(q_list) if x.get("id") == tr.get("id")), 0)
            await device_manager.push_queue_to_device(
                device_id=did,
                tracks=q_list,
                album_id=tr.get("album_id"),
                album_title=str(tr.get("album_title") or ""),
                start_index=idx,
                series_id=tr.get("series_id"),
                start_position_sec=float(tr.get("start_position_sec") or 0.0),
            )
        return {
            "ok": True,
            "device_id": did,
            "track_title": tr.get("title"),
            "series_title": tr.get("series_title") or tr.get("album_title"),
            "season_label": tr.get("season_label", ""),
            "episode_num": tr.get("episode_num", 1),
            "start_position_sec": float(tr.get("start_position_sec") or 0.0),
            "queue_size": len(q_list),
        }

    if name == "echomind_collect_and_classify":
        q = str(args.get("query") or "").strip()
        if not q:
            return {"ok": False, "message": "query 不能为空"}
        did = await _resolve_default_device_id(args.get("device_id"))
        job = await enqueue_ai_collect(
            query=q,
            channel_hint=args.get("channel_hint"),
            max_items=int(args.get("max_items") or 5),
            device_id=did,
            notify_speaker=bool(did),
        )
        return {"ok": True, "job": job, "notify_device_id": did}

    if name == "echomind_control_playback":
        cmd_text = str(args.get("command_text") or "").strip()
        if not cmd_text:
            return {"ok": False, "message": "command_text 不能为空"}
        did = await _resolve_default_device_id(args.get("device_id"))
        speaker = await identify_speaker()
        resp = await process_user_turn(cmd_text, speaker, device_id=did or "web-console")
        return {
            "ok": True,
            "device_id": did,
            "reply_text": resp.reply_text,
            "control_action": resp.control_action,
            "played_track": (resp.play_track or {}).get("title") if resp.play_track else None,
        }

    if name == "echomind_push_to_speaker":
        stitle = str(args.get("series_title") or "").strip()
        did = await _resolve_default_device_id(args.get("device_id"))
        if not did:
            return {"ok": False, "message": "当前没有已绑定的房间音箱"}
        async with get_db() as conn:
            cur = await conn.execute("SELECT * FROM media_series WHERE title LIKE ? LIMIT 1", (f"%{stitle}%",))
            srow = await cur.fetchone()
            if not srow:
                return {"ok": False, "message": f"未找到名为「{stitle}」的系列"}
            sdata = dict(srow)
            cur_a = await conn.execute(
                "SELECT * FROM media_albums WHERE series_id = ? ORDER BY season_num ASC, id ASC",
                (sdata["id"],),
            )
            seasons = [dict(r) for r in await cur_a.fetchall()]
            target_alb = next((a for a in seasons if a["id"] == sdata.get("last_album_id")), None) or (seasons[0] if seasons else None)
            if not target_alb:
                return {"ok": False, "message": "该系列下暂无季或单集"}
            cur_t = await conn.execute(
                "SELECT * FROM media_tracks WHERE album_id = ? ORDER BY episode_num ASC, id ASC",
                (target_alb["id"],),
            )
            tracks = [dict(r) for r in await cur_t.fetchall()]
        if not tracks:
            return {"ok": False, "message": "该系列下暂无音频"}
        start_idx = next((i for i, t in enumerate(tracks) if t["id"] == sdata.get("last_track_id")), 0)
        await device_manager.push_queue_to_device(
            device_id=did,
            tracks=tracks,
            album_id=int(target_alb["id"]),
            album_title=str(target_alb["title"]),
            start_index=start_idx,
            sleep_minutes=args.get("sleep_minutes"),
            sleep_episodes=args.get("sleep_episodes"),
            series_id=int(sdata["id"]),
            start_position_sec=float(sdata.get("last_position_sec") or 0.0),
        )
        return {
            "ok": True,
            "device_id": did,
            "series_title": sdata["title"],
            "season_label": target_alb.get("season_label", ""),
            "track_title": tracks[start_idx]["title"],
        }

    raise ValueError(f"未知 MCP 工具: {name}")


@router.get("/tools")
async def list_mcp_tools_http() -> dict[str, Any]:
    """供管理台与开发者直接查看已暴露的 MCP 工具清单。"""
    return {
        "server": "EchoMind MCP Server",
        "protocolVersion": "2024-11-05",
        "tools": MCP_TOOLS,
    }


@router.post("")
async def handle_mcp_jsonrpc(request: Request) -> dict[str, Any]:
    """标准 MCP JSON-RPC 2.0 HTTP 端点（兼容小智 ESP32 Server / Claude / 通用 MCP Client）。"""
    try:
        body = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON"}}

    req_id = body.get("id")
    method = str(body.get("method") or "")
    params = body.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echomind-mcp", "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}
    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        tool_args = params.get("arguments") or {}
        try:
            data = await _dispatch_mcp_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                    "structuredContent": data,
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"工具执行失败: {exc}"}],
                    "isError": True,
                },
            }

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

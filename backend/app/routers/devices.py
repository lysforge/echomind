"""智能音箱与终端硬件完整生命周期路由（添加、发现认领、音量护耳限幅、测试音、解绑删除、脚本下载）。"""

from __future__ import annotations

import json
import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.auth import get_current_user, require_admin
from app.config import ROOT_DIR, get_lan_ip, load_settings, save_settings
from app.db import get_db, now_iso
from app.gateways.manager import device_manager
from app.services.brain import SafeMotionGuard
from app.services.tts_asr import synthesize_speech
from app.services.xiaoai_bridge import xiaoai_bridge

router = APIRouter(prefix="/api/devices", tags=["devices"])


class DeviceCreate(BaseModel):
    name: str
    device_type: Literal["speaker_xiaoai", "esp32_robot"] = "speaker_xiaoai"
    room: str = "客厅"
    max_volume: int = 75
    wake_word: str = "你好小音"


class DeviceClaim(BaseModel):
    device_id: str | None = None
    pair_code: str | None = None
    name: str
    room: str = "客厅"
    max_volume: int = 75


class DevicePatch(BaseModel):
    name: str | None = None
    room: str | None = None
    volume: int | None = None
    max_volume: int | None = None
    wake_word: str | None = None
    motion_locked: bool | None = None


class DeviceControl(BaseModel):
    command: Literal["pause", "stop", "test_sound"]


class MotionRequest(BaseModel):
    action: str = "nod"
    duration_ms: int = 1000
    speed: int = 28


class AnnounceRequest(BaseModel):
    text: str


@router.get("")
async def list_devices(_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM devices WHERE paired = 1 ORDER BY created_at DESC")
        bound = [dict(r) for r in await cur.fetchall()]
        cur_p = await conn.execute("SELECT * FROM devices WHERE paired = 0 ORDER BY last_seen_at DESC")
        pending = [dict(r) for r in await cur_p.fetchall()]

    lan_ip = get_lan_ip()
    port = load_settings().server_port
    for dev in bound:
        dev["connect_cmd"] = (
            f"python3 echomind_xiaoai_agent.py --server ws://{lan_ip}:{port}/ws/speaker "
            f"--device-id {dev['id']} --token {dev['auth_token']}"
        )
    return {"devices": bound, "pending_devices": pending}


@router.post("")
async def create_device(
    req: DeviceCreate,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="设备名称不能为空")

    prefix = "spk" if req.device_type == "speaker_xiaoai" else "esp"
    device_id = f"{prefix}_{secrets.token_hex(4)}"
    auth_token = secrets.token_urlsafe(16)
    pair_code = f"{secrets.randbelow(900000) + 100000}"
    max_vol = max(20, min(100, int(req.max_volume)))
    ts = now_iso()

    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO devices
            (id, name, device_type, room, auth_token, pair_code, paired, online, volume, max_volume, wake_word, playing_title, client_ip, motion_locked, last_seen_at, created_at, capabilities_json)
            VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, '等待设备首次握手连接', '', 0, ?, ?, '{}')
            """,
            (
                device_id,
                req.name.strip(),
                req.device_type,
                req.room.strip() or "默认房间",
                auth_token,
                pair_code,
                min(50, max_vol),
                max_vol,
                req.wake_word.strip() or "你好小音",
                ts,
                ts,
            ),
        )
        await conn.commit()
        cur = await conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
        dev = dict(await cur.fetchone())

    lan_ip = get_lan_ip()
    port = load_settings().server_port
    dev["connect_cmd"] = (
        f"python3 echomind_xiaoai_agent.py --server ws://{lan_ip}:{port}/ws/speaker "
        f"--device-id {device_id} --token {auth_token}"
    )
    return dev


@router.post("/claim")
async def claim_pending_device(
    req: DeviceClaim,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """认领自动发现的未绑定设备（可通过 device_id 或 6 位配对码）。"""
    async with get_db() as conn:
        if req.device_id:
            cur = await conn.execute("SELECT * FROM devices WHERE id = ? AND paired = 0", (req.device_id,))
        elif req.pair_code:
            cur = await conn.execute("SELECT * FROM devices WHERE pair_code = ? AND paired = 0", (req.pair_code.strip(),))
        else:
            raise HTTPException(status_code=400, detail="请提供 device_id 或 6 位配对码")
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="未找到对应的待认领设备或配对码已失效")

        max_vol = max(20, min(100, int(req.max_volume)))
        await conn.execute(
            """
            UPDATE devices
            SET paired = 1, name = ?, room = ?, max_volume = ?, volume = MIN(volume, ?), playing_title = '已认领，待机中'
            WHERE id = ?
            """,
            (req.name.strip(), req.room.strip() or "客厅", max_vol, max_vol, row["id"]),
        )
        await conn.commit()
        cur2 = await conn.execute("SELECT * FROM devices WHERE id = ?", (row["id"],))
        dev = dict(await cur2.fetchone())

    await device_manager.notify_claimed(dev)
    return dev


@router.patch("/{device_id}")
async def update_device(
    device_id: str,
    req: DevicePatch,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="设备不存在")
        dev = dict(row)

        name = req.name.strip() if req.name is not None else dev["name"]
        room = req.room.strip() if req.room is not None else dev["room"]
        wake_word = req.wake_word.strip() if req.wake_word is not None else dev["wake_word"]
        max_vol = max(20, min(100, int(req.max_volume))) if req.max_volume is not None else int(dev["max_volume"])
        req_vol = int(req.volume) if req.volume is not None else int(dev["volume"])
        clamped_vol = max(0, min(req_vol, max_vol))
        locked = int(req.motion_locked) if req.motion_locked is not None else dev["motion_locked"]

        await conn.execute(
            """
            UPDATE devices
            SET name = ?, room = ?, wake_word = ?, max_volume = ?, volume = ?, motion_locked = ?
            WHERE id = ?
            """,
            (name, room, wake_word, max_vol, clamped_vol, locked, device_id),
        )
        await conn.commit()
        cur2 = await conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
        updated = dict(await cur2.fetchone())

    if req.volume is not None or req.max_volume is not None:
        await device_manager.set_device_volume(device_id, clamped_vol)
    return updated


@router.delete("/{device_id}")
async def delete_device(
    device_id: str,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """解绑并彻底删除设备，同时踢断活跃 WebSocket 并置空关联定时任务。"""
    await device_manager.unbind_and_disconnect(device_id)
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM devices WHERE id = ?", (device_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="设备不存在")
        await conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        await conn.commit()
    return {"status": "deleted", "device_id": device_id}


@router.post("/{device_id}/control")
async def control_device(
    device_id: str,
    req: DeviceControl,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if req.command == "test_sound":
        settings = load_settings()
        msg = f"叮咚，这里是{settings.home_name}的{settings.assistant_name}，智能音箱连接与音频测试正常。"
        tts_path = await synthesize_speech(msg, settings.tts_voice_adult, settings.tts_rate_adult)
        await device_manager.push_announcement(device_id=device_id, text=msg, tts_path=tts_path)
        return {"status": "ok", "command": "test_sound", "tts_url": f"/api/tts-cache/{tts_path.name}"}

    await device_manager.send_speaker_control(device_id, req.command)
    return {"status": "ok", "command": req.command}


@router.post("/{device_id}/announce")
async def announce_to_device(
    device_id: str,
    req: AnnounceRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="广播内容不能为空")
    settings = load_settings()
    tts_path = await synthesize_speech(text, voice=settings.tts_voice_child, rate=settings.tts_rate_child)
    await device_manager.push_announcement(device_id=device_id, text=text, tts_path=tts_path)
    return {"status": "sent", "device_id": device_id, "text": text, "tts_url": f"/api/tts-cache/{tts_path.name}"}


@router.post("/{device_id}/motion")
async def trigger_robot_motion(
    device_id: str,
    req: MotionRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    motion = SafeMotionGuard.sanitize(req.action, req.duration_ms, req.speed)
    locked = not bool(motion.get("allowed", True))
    await device_manager.update_device_state(
        device_id,
        playing_title="夜间免打扰锁止" if locked else f"执行安全动作：{motion['action']}",
        motion_locked=locked,
    )
    return {"device_id": device_id, "motion": motion, "motion_locked": locked}


@router.get("/{device_id}/bridge-script")
async def download_bridge_script(
    device_id: str,
    _user: dict[str, Any] = Depends(get_current_user),
):
    """生成并下载预填好本机 IP、device_id 与 auth_token 的专属音箱桥接客户端脚本。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="设备不存在")

    base_script = (ROOT_DIR / "clients" / "echomind_xiaoai_agent.py").read_text(encoding="utf-8")
    lan_ip = get_lan_ip()
    port = load_settings().server_port
    header_comment = (
        f"# 专属设备：{row['name']} ({row['id']})\n"
        f"# 直接运行：python3 echomind_agent_{row['id']}.py\n"
    )
    patched = base_script.replace(
        'parser.add_argument("--server", required=True',
        f'parser.add_argument("--server", default="ws://{lan_ip}:{port}/ws/speaker"',
    ).replace(
        'parser.add_argument("--device-id", default=os.uname().nodename',
        f'parser.add_argument("--device-id", default="{row["id"]}"',
    ).replace(
        'parser.add_argument("--token", default=""',
        f'parser.add_argument("--token", default="{row["auth_token"]}"',
    )
    return PlainTextResponse(
        content=header_comment + patched,
        headers={"Content-Disposition": f'attachment; filename="echomind_agent_{row["id"]}.py"'},
    )


# -------------------- 真·小米小爱音箱直连发现、绑定与语音轮询 --------------------


class XiaoAiDiscoverRequest(BaseModel):
    mi_user: str | None = None
    mi_pass: str | None = None
    public_base_url: str | None = None
    save_credentials: bool = True


class XiaoAiBindRequest(BaseModel):
    mi_device_id: str
    miot_did: str = ""
    name: str
    hardware: str = ""
    room: str = "客厅"
    max_volume: int = 75


class XiaoAiPollToggleRequest(BaseModel):
    enabled: bool
    poll_interval_sec: float | None = None
    trigger_keywords: str | None = None


@router.get("/xiaoai/status")
async def get_xiaoai_bridge_status(_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return await xiaoai_bridge.get_status_snapshot()


@router.post("/xiaoai/discover")
async def discover_xiaoai_devices(
    req: XiaoAiDiscoverRequest,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """登录小米账号并发现名下所有真实小爱音箱设备。"""
    s = load_settings()
    u = req.mi_user.strip() if req.mi_user else s.mi_user
    p = req.mi_pass.strip() if (req.mi_pass and "*" not in req.mi_pass) else s.mi_pass
    if not u or not p:
        raise HTTPException(status_code=400, detail="请填写小米账号（手机号/邮箱/小米ID）和密码")
    if req.save_credentials:
        s.mi_user = u
        s.mi_pass = p
        if req.public_base_url is not None:
            s.public_base_url = req.public_base_url.strip()
        save_settings(s)
    try:
        devices = await xiaoai_bridge.discover_devices(u, p)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"连接小米账号失败：{exc}")
    return {"devices": devices, "count": len(devices)}


@router.post("/xiaoai/bind")
async def bind_xiaoai_device(
    req: XiaoAiBindRequest,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """将发现的小米小爱真机直接绑定为 EchoMind 房间音箱（免装客户端脚本）。"""
    mi_did = req.mi_device_id.strip()
    if not mi_did:
        raise HTTPException(status_code=400, detail="mi_device_id 不能为空")
    dev_id = f"xiaoai_{mi_did[:18]}"
    cap_json = json.dumps(
        {
            "transport": "xiaoai_cloud",
            "mi_device_id": mi_did,
            "miot_did": req.miot_did.strip(),
            "hardware": req.hardware.strip(),
        },
        ensure_ascii=False,
    )
    ts = now_iso()
    max_v = max(20, min(100, int(req.max_volume)))
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,))
        if await cur.fetchone():
            await conn.execute(
                """
                UPDATE devices
                SET name = ?, room = ?, max_volume = ?, paired = 1, online = 1,
                    capabilities_json = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (req.name.strip() or "小爱音箱", req.room.strip() or "客厅", max_v, cap_json, ts, dev_id),
            )
        else:
            await conn.execute(
                """
                INSERT INTO devices
                (id, name, device_type, room, auth_token, pair_code, paired, online, volume, max_volume,
                 wake_word, playing_title, client_ip, motion_locked, last_seen_at, created_at, capabilities_json)
                VALUES (?, ?, 'speaker_xiaoai', ?, ?, '', 1, 1, 50, ?, '小爱同学', '小米云直连就绪', 'xiaomi-cloud', 0, ?, ?, ?)
                """,
                (dev_id, req.name.strip() or "小爱音箱", req.room.strip() or "客厅", secrets.token_urlsafe(12), max_v, ts, ts, cap_json),
            )
        await conn.commit()
        cur2 = await conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,))
        row = dict(await cur2.fetchone())
    xiaoai_bridge.ensure_polling_started()
    return row


@router.post("/xiaoai/poll-toggle")
async def toggle_xiaoai_polling(
    req: XiaoAiPollToggleRequest,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    s = load_settings()
    s.mi_poll_enabled = bool(req.enabled)
    if req.poll_interval_sec is not None:
        s.mi_poll_interval_sec = max(1.0, min(15.0, float(req.poll_interval_sec)))
    if req.trigger_keywords is not None:
        s.mi_trigger_keywords = req.trigger_keywords.strip()
    save_settings(s)
    if s.mi_poll_enabled:
        xiaoai_bridge.ensure_polling_started()
    return await xiaoai_bridge.get_status_snapshot()

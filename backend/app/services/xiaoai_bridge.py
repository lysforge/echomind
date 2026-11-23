"""真·小米小爱音箱直连引擎（基于 miservice_fork，支持真机发现、推送音频流、TTS播报、音量控制与语音轮询）。"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, get_lan_ip, load_settings
from app.db import get_db, now_iso

MI_TOKEN_STORE = DATA_DIR / "mi_token.json"

try:
    import aiohttp
    from miservice import MiAccount, MiNAService

    HAS_MISERVICE = True
except Exception:
    aiohttp = None  # type: ignore[assignment]
    MiAccount = None  # type: ignore[assignment]
    MiNAService = None  # type: ignore[assignment]
    HAS_MISERVICE = False


def resolve_public_base_url() -> str:
    """获取可供局域网或公网实体小爱音箱拉取音频流的完整 Base URL。"""
    s = load_settings()
    if s.public_base_url.strip():
        return s.public_base_url.strip().rstrip("/")
    return f"http://{get_lan_ip()}:{s.server_port}"


def build_speaker_accessible_url(path_or_url: str) -> str:
    if not path_or_url:
        return ""
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    base = resolve_public_base_url()
    return f"{base}{path_or_url if path_or_url.startswith('/') else '/' + path_or_url}"


def parse_xiaoai_capability(device: dict[str, Any]) -> dict[str, Any] | None:
    """判断 devices 行是否为小米云直连真机小爱，并返回其能力配置字典。"""
    raw = device.get("capabilities_json")
    if not raw:
        return None
    try:
        cap = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
    if isinstance(cap, dict) and cap.get("transport") == "xiaoai_cloud" and cap.get("mi_device_id"):
        return cap
    return None


class XiaoAiCloudBridge:
    """维护与小米音箱云端服务（MiNA）的异步连接、推送播控、状态进度同步与语音指令监听。"""

    def __init__(self) -> None:
        self._session: Any = None
        self._account: Any = None
        self._mina: Any = None
        self._auth_key: tuple[str, str] | None = None
        self._lock = asyncio.Lock()
        self._poll_task: asyncio.Task | None = None
        self._last_ask_ts: dict[str, int] = {}
        self._last_play_sent_at: dict[str, float] = {}
        self._recent_asks: list[dict[str, Any]] = []
        self._last_error: str = ""

    async def close(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            self._poll_task = None
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
        self._account = None
        self._mina = None
        self._auth_key = None

    async def _ensure_mina(self, mi_user: str | None = None, mi_pass: str | None = None) -> Any:
        if not HAS_MISERVICE:
            raise RuntimeError("未安装 miservice-fork，请安装后再连接小米小爱音箱")
        s = load_settings()
        user = (mi_user if mi_user is not None else s.mi_user).strip()
        pwd = (mi_pass if mi_pass is not None else s.mi_pass).strip()
        if not user or not pwd:
            raise RuntimeError("请先在设置中填写小米账号与密码")

        async with self._lock:
            if self._mina is not None and self._auth_key == (user, pwd) and self._session and not self._session.closed:
                return self._mina
            if self._session is not None:
                try:
                    await self._session.close()
                except Exception:
                    pass
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._session = aiohttp.ClientSession()
            self._account = MiAccount(self._session, user, pwd, str(MI_TOKEN_STORE))
            self._mina = MiNAService(self._account)
            self._auth_key = (user, pwd)
            return self._mina

    async def discover_devices(self, mi_user: str | None = None, mi_pass: str | None = None) -> list[dict[str, Any]]:
        """登录小米账号并拉取名下所有小爱音箱设备列表。"""
        mina = await self._ensure_mina(mi_user, mi_pass)
        raw_list = await mina.device_list()
        out: list[dict[str, Any]] = []
        for item in raw_list or []:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "mi_device_id": str(item.get("deviceID") or ""),
                    "miot_did": str(item.get("miotDID") or ""),
                    "name": str(item.get("alias") or item.get("name") or "小爱音箱"),
                    "hardware": str(item.get("hardware") or ""),
                    "mac": str(item.get("mac") or ""),
                    "presence": str(item.get("presence") or ""),
                    "online": str(item.get("presence") or "").lower() == "online",
                }
            )
        return out

    async def play_url(self, mi_device_id: str, track_url: str) -> bool:
        mina = await self._ensure_mina()
        full_url = build_speaker_accessible_url(track_url)
        self._last_play_sent_at[mi_device_id] = time.time()
        try:
            res = await mina.play_by_music_url(mi_device_id, full_url)
            if isinstance(res, dict) and res.get("code", 0) == 0:
                return True
        except Exception:
            pass
        res2 = await mina.play_by_url(mi_device_id, full_url)
        return bool(res2)

    async def speak(self, mi_device_id: str, text: str) -> bool:
        mina = await self._ensure_mina()
        res = await mina.text_to_speech(mi_device_id, text)
        return bool(res)

    async def set_volume(self, mi_device_id: str, volume: int) -> bool:
        mina = await self._ensure_mina()
        res = await mina.player_set_volume(mi_device_id, max(0, min(100, int(volume))))
        return bool(res)

    async def control(self, mi_device_id: str, command: str) -> bool:
        mina = await self._ensure_mina()
        if command == "pause":
            return bool(await mina.player_pause(mi_device_id))
        if command == "resume":
            return bool(await mina.player_play(mi_device_id))
        if command == "stop":
            return bool(await mina.player_stop(mi_device_id))
        return False

    async def get_player_status(self, mi_device_id: str) -> dict[str, Any]:
        """获取小爱音箱当前真实播放状态与播放秒数（status: 1=播放中, 2=暂停, 0=停止）。"""
        mina = await self._ensure_mina()
        raw = await mina.player_get_status(mi_device_id)
        if not isinstance(raw, dict):
            return {}
        data = raw.get("data") or {}
        info_raw = data.get("info")
        if isinstance(info_raw, str):
            try:
                info = json.loads(info_raw)
            except Exception:
                info = {}
        elif isinstance(info_raw, dict):
            info = info_raw
        else:
            info = {}
        # position 单位常为毫秒
        pos_ms = float(info.get("play_song_detail", {}).get("position") or info.get("position") or 0)
        pos_sec = pos_ms / 1000.0 if pos_ms > 1000 else pos_ms
        return {
            "status": int(info.get("status") or 0),
            "volume": int(info.get("volume") or 0),
            "position_sec": max(0.0, pos_sec),
            "raw": info,
        }

    async def _list_bound_xiaoai_devices(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        async with get_db() as conn:
            cur = await conn.execute("SELECT * FROM devices WHERE paired = 1 AND device_type = 'speaker_xiaoai'")
            rows = [dict(r) for r in await cur.fetchall()]
        out: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for r in rows:
            cap = parse_xiaoai_capability(r)
            if cap:
                out.append((r, cap))
        return out

    async def _poll_loop(self) -> None:
        from app.gateways.manager import device_manager
        from app.services.brain import process_user_turn
        from app.services.voiceprint import identify_speaker

        while True:
            s = load_settings()
            interval = max(1.0, float(s.mi_poll_interval_sec or 2.0))
            if not s.mi_poll_enabled or not s.mi_user.strip() or not s.mi_pass.strip():
                await asyncio.sleep(3.0)
                continue

            try:
                bound = await self._list_bound_xiaoai_devices()
                if not bound:
                    await asyncio.sleep(4.0)
                    continue
                mina = await self._ensure_mina()
                triggers = [k.strip() for k in (s.mi_trigger_keywords or "").split(",") if k.strip()]

                for dev, cap in bound:
                    dev_id = dev["id"]
                    mi_did = str(cap["mi_device_id"])

                    # 1. 拉取小爱最新语音提问，命中触发词交由 EchoMind 大脑处理
                    try:
                        ask_resp = await mina.get_latest_ask(mi_did)
                        records = ((ask_resp or {}).get("data") or {}).get("records") or []
                        if records and isinstance(records[0], dict):
                            rec = records[0]
                            rec_ts = int(rec.get("time") or 0)
                            query = str(rec.get("query") or "").strip()
                            prev_ts = self._last_ask_ts.get(mi_did)
                            if prev_ts is None:
                                # 首次初始化仅记水位线，不重放历史对话
                                self._last_ask_ts[mi_did] = rec_ts
                            elif rec_ts > prev_ts and query:
                                self._last_ask_ts[mi_did] = rec_ts
                                matched = (not triggers) or any(k in query for k in triggers)
                                self._recent_asks.insert(
                                    0,
                                    {
                                        "device_id": dev_id,
                                        "device_name": dev["name"],
                                        "query": query,
                                        "handled": matched,
                                        "time": now_iso(),
                                    },
                                )
                                self._recent_asks = self._recent_asks[:20]
                                if matched:
                                    speaker = await identify_speaker()
                                    brain_resp = await process_user_turn(query, speaker, device_id=dev_id)
                                    if brain_resp.reply_text:
                                        await self.speak(mi_did, brain_resp.reply_text)
                                    if brain_resp.play_track and not brain_resp.skip_device_push:
                                        q_list = brain_resp.queue_tracks or [brain_resp.play_track]
                                        idx = next(
                                            (
                                                i
                                                for i, t in enumerate(q_list)
                                                if t.get("id") == brain_resp.play_track.get("id")
                                            ),
                                            0,
                                        )
                                        await device_manager.push_queue_to_device(
                                            device_id=dev_id,
                                            tracks=q_list,
                                            album_id=brain_resp.play_track.get("album_id"),
                                            album_title=str(brain_resp.play_track.get("album_title") or ""),
                                            start_index=idx,
                                            series_id=brain_resp.play_track.get("series_id"),
                                            start_position_sec=float(brain_resp.play_track.get("start_position_sec") or 0.0),
                                        )
                    except Exception as exc:
                        self._last_error = f"轮询语音失败: {exc}"

                    # 2. 若小爱正处于 EchoMind 连播队列中，同步硬件秒数并在播完自动推下一集/跨季连播
                    sess = device_manager.playback_sessions.get(dev_id)
                    if sess and sess.get("status") == "playing":
                        last_sent = self._last_play_sent_at.get(mi_did, 0.0)
                        if time.time() - last_sent > 4.0:
                            try:
                                st = await self.get_player_status(mi_did)
                                if st.get("status") == 1 and st.get("position_sec", 0.0) > 1.0:
                                    await device_manager.report_hardware_progress(dev_id, st["position_sec"])
                                elif st.get("status") == 0:
                                    await device_manager.advance_device_queue(dev_id, delta=1, auto_triggered=True)
                            except Exception:
                                pass

                self._last_error = ""
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._last_error = str(exc)

            await asyncio.sleep(interval)

    def ensure_polling_started(self) -> None:
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def get_status_snapshot(self) -> dict[str, Any]:
        s = load_settings()
        bound = await self._list_bound_xiaoai_devices()
        return {
            "library_available": HAS_MISERVICE,
            "configured": bool(s.mi_user.strip() and s.mi_pass.strip()),
            "poll_enabled": bool(s.mi_poll_enabled),
            "poll_running": bool(self._poll_task and not self._poll_task.done()),
            "public_base_url": resolve_public_base_url(),
            "bound_count": len(bound),
            "bound_devices": [
                {"id": d["id"], "name": d["name"], "room": d["room"], "mi_device_id": c["mi_device_id"], "hardware": c.get("hardware", "")}
                for d, c in bound
            ],
            "recent_asks": self._recent_asks[:10],
            "last_error": self._last_error,
        }


xiaoai_bridge = XiaoAiCloudBridge()

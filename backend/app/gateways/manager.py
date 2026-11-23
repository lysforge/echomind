"""商业级设备连接池与发现/配对/音量护耳/踢下线控制器。"""

from __future__ import annotations

import asyncio
import json
import random
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from app.db import get_db, now_iso
from app.services.audio_norm import encode_file_to_opus_frames


def _resolve_stream_url(track: dict[str, Any] | None) -> str | None:
    if not track:
        return None
    if track.get("stream_url"):
        return str(track["stream_url"])
    if track.get("media_kind") == "book_chapter" or "book_id" in track:
        return f"/api/books/chapters/{track['id']}/stream"
    return f"/api/media/tracks/{track['id']}/stream"


class DeviceConnectionManager:
    def __init__(self) -> None:
        self.xiaozhi_conns: dict[str, dict[str, Any]] = {}
        self.speaker_conns: dict[str, WebSocket] = {}
        self.web_conns: set[WebSocket] = set()
        self.playback_sessions: dict[str, dict[str, Any]] = {}

    async def register_web(self, ws: WebSocket) -> None:
        self.web_conns.add(ws)

    def unregister_web(self, ws: WebSocket) -> None:
        self.web_conns.discard(ws)

    async def broadcast_web(self, event: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        msg = json.dumps(event, ensure_ascii=False)
        for ws in list(self.web_conns):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.web_conns.discard(ws)

    async def register_or_discover_device(
        self,
        device_id: str,
        device_type: str,
        default_name: str,
        client_ip: str = "",
        provided_token: str = "",
    ) -> tuple[bool, dict[str, Any]]:
        """
        处理硬件设备连接鉴权或自动发现：
        - 已认领设备且 token 合法（或免 token 模式）-> 返回 (True, device_dict)
        - 陌生设备 -> 插入/更新 paired=0 并生成 6 位配对码，返回 (False, device_dict)
        """
        ts = now_iso()
        async with get_db() as conn:
            cur = await conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            row = await cur.fetchone()
            if row:
                dev = dict(row)
                if dev["paired"] == 1:
                    if dev["auth_token"] and provided_token and dev["auth_token"] != provided_token:
                        raise PermissionError("设备认证 Token 不匹配")
                    await conn.execute(
                        "UPDATE devices SET online = 1, client_ip = ?, last_seen_at = ? WHERE id = ?",
                        (client_ip, ts, device_id),
                    )
                    await conn.commit()
                    dev["online"] = 1
                    dev["client_ip"] = client_ip
                    await self.broadcast_web({"type": "device_state", "device_id": device_id, **dev})
                    return True, dev

                # 未认领设备再次上线：复用或刷新配对码
                pair_code = dev.get("pair_code") or f"{secrets.randbelow(900000) + 100000}"
                await conn.execute(
                    "UPDATE devices SET online = 1, pair_code = ?, client_ip = ?, last_seen_at = ? WHERE id = ?",
                    (pair_code, client_ip, ts, device_id),
                )
                await conn.commit()
                dev["online"] = 1
                dev["pair_code"] = pair_code
                dev["client_ip"] = client_ip
                await self.broadcast_web({"type": "device_discovered", "device": dev})
                return False, dev

            # 全新未知设备接入：进入待认领池
            pair_code = f"{secrets.randbelow(900000) + 100000}"
            new_token = secrets.token_urlsafe(16)
            await conn.execute(
                """
                INSERT INTO devices
                (id, name, device_type, room, auth_token, pair_code, paired, online, volume, max_volume, wake_word, playing_title, client_ip, motion_locked, last_seen_at, created_at, capabilities_json)
                VALUES (?, ?, ?, '待分配房间', ?, ?, 0, 1, 50, 75, '你好小音', '待认领配对', ?, 0, ?, ?, '{}')
                """,
                (device_id, default_name, device_type, new_token, pair_code, client_ip, ts, ts),
            )
            await conn.commit()
            cur2 = await conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            dev = dict(await cur2.fetchone())

        await self.broadcast_web({"type": "device_discovered", "device": dev})
        return False, dev

    async def notify_claimed(self, device: dict[str, Any]) -> None:
        """通知在线的待认领设备已完成绑定。"""
        did = device["id"]
        spk_ws = self.speaker_conns.get(did)
        if spk_ws:
            try:
                await spk_ws.send_text(
                    json.dumps(
                        {"type": "claimed", "device_id": did, "name": device["name"], "room": device["room"]},
                        ensure_ascii=False,
                    )
                )
            except Exception:
                pass
        await self.broadcast_web({"type": "device_state", "device_id": did, **device})

    async def update_device_state(
        self,
        device_id: str,
        *,
        online: bool | None = None,
        playing_title: str | None = None,
        motion_locked: bool | None = None,
        volume: int | None = None,
    ) -> None:
        async with get_db() as conn:
            cur = await conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            row = await cur.fetchone()
            if not row:
                return
            max_v = int(row["max_volume"] or 75)
            new_vol = max(0, min(int(volume), max_v)) if volume is not None else row["volume"]
            fields = {
                "online": int(online) if online is not None else row["online"],
                "playing_title": playing_title if playing_title is not None else row["playing_title"],
                "motion_locked": int(motion_locked) if motion_locked is not None else row["motion_locked"],
                "volume": new_vol,
                "last_seen_at": now_iso(),
            }
            await conn.execute(
                """
                UPDATE devices
                SET online = ?, playing_title = ?, motion_locked = ?, volume = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (
                    fields["online"],
                    fields["playing_title"],
                    fields["motion_locked"],
                    fields["volume"],
                    fields["last_seen_at"],
                    device_id,
                ),
            )
            await conn.commit()

        await self.broadcast_web({"type": "device_state", "device_id": device_id, **fields})

    async def _get_xiaoai_mi_did(self, device_id: str) -> str | None:
        from app.services.xiaoai_bridge import parse_xiaoai_capability

        async with get_db() as conn:
            cur = await conn.execute("SELECT capabilities_json FROM devices WHERE id = ?", (device_id,))
            row = await cur.fetchone()
            if not row:
                return None
            cap = parse_xiaoai_capability(dict(row))
            return str(cap["mi_device_id"]) if cap else None

    async def set_device_volume(self, device_id: str, requested_volume: int) -> int:
        """调节设备音量并强制受护耳上限 max_volume 保护（支持通用 WS 与真小爱音箱）。"""
        async with get_db() as conn:
            cur = await conn.execute("SELECT volume, max_volume FROM devices WHERE id = ?", (device_id,))
            row = await cur.fetchone()
            if not row:
                return requested_volume
            max_v = int(row["max_volume"] or 75)
            clamped = max(0, min(int(requested_volume), max_v))
            await conn.execute("UPDATE devices SET volume = ? WHERE id = ?", (clamped, device_id))
            await conn.commit()

        spk_ws = self.speaker_conns.get(device_id)
        if spk_ws:
            try:
                await spk_ws.send_text(json.dumps({"type": "set_volume", "volume": clamped}))
            except Exception:
                pass
        mi_did = await self._get_xiaoai_mi_did(device_id)
        if mi_did:
            try:
                from app.services.xiaoai_bridge import xiaoai_bridge

                await xiaoai_bridge.set_volume(mi_did, clamped)
            except Exception:
                pass
        await self.broadcast_web({"type": "device_state", "device_id": device_id, "volume": clamped})
        return clamped

    async def unbind_and_disconnect(self, device_id: str) -> None:
        """删除设备时主动向在线硬件发解绑通知并关闭连接与连播会话。"""
        old = self.playback_sessions.pop(device_id, None)
        if old and old.get("auto_task"):
            old["auto_task"].cancel()
        spk_ws = self.speaker_conns.pop(device_id, None)
        if spk_ws:
            try:
                await spk_ws.send_text(json.dumps({"type": "unpaired"}))
                await spk_ws.close()
            except Exception:
                pass
        xz = self.xiaozhi_conns.pop(device_id, None)
        if xz:
            try:
                await xz["ws"].close()
            except Exception:
                pass

    async def cast_track_to_device(
        self,
        device_id: str,
        track: dict[str, Any],
        start_position_sec: float = 0.0,
    ) -> None:
        title = str(track.get("title", "未知音频"))
        track_url = _resolve_stream_url(track)
        pos = max(0.0, float(start_position_sec or 0.0))
        await self.update_device_state(device_id, playing_title=f"正在播放：{title}")

        await self.broadcast_web(
            {
                "type": "cast_track",
                "device_id": device_id,
                "track": track,
                "track_url": track_url,
                "start_position_sec": pos,
                "timestamp": now_iso(),
            }
        )

        spk_ws = self.speaker_conns.get(device_id)
        if spk_ws and track_url:
            try:
                await spk_ws.send_text(
                    json.dumps(
                        {
                            "type": "play_url",
                            "title": title,
                            "track_url": track_url,
                            "start_position_sec": pos,
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception:
                pass

        mi_did = await self._get_xiaoai_mi_did(device_id)
        if mi_did and track_url:
            try:
                from app.services.xiaoai_bridge import xiaoai_bridge

                await xiaoai_bridge.play_url(mi_did, track_url)
            except Exception:
                pass

        xz_entry = self.xiaozhi_conns.get(device_id)
        if xz_entry and track.get("file_path") and Path(track["file_path"]).exists():
            # 取消上一条正在向小智推流的任务，异步后台推送 Opus 并在播完后自动连播下一集
            prev_task = xz_entry.get("stream_task")
            if prev_task and not prev_task.done():
                xz_entry["abort"] = True
                prev_task.cancel()
            xz_entry["abort"] = False

            async def _stream_opus_to_xiaozhi() -> None:
                ws: WebSocket = xz_entry["ws"]
                session_id = xz_entry.get("session_id", "echomind-cast")
                sent_frames = 0
                aborted = False
                try:
                    frames = await encode_file_to_opus_frames(track["file_path"])
                    skip_frames = int(pos / 0.06) if pos > 1.0 else 0
                    frames_to_send = frames[skip_frames:] if skip_frames < len(frames) else frames
                    await ws.send_text(json.dumps({"type": "tts", "state": "start", "session_id": session_id}))
                    for pkt in frames_to_send:
                        if xz_entry.get("abort"):
                            aborted = True
                            break
                        await ws.send_bytes(pkt)
                        sent_frames += 1
                        await asyncio.sleep(0.055)
                    await ws.send_text(json.dumps({"type": "tts", "state": "stop", "session_id": session_id}))
                    if aborted:
                        elapsed = pos + sent_frames * 0.06
                        await self.report_hardware_progress(device_id, elapsed)
                    elif self.playback_sessions.get(device_id, {}).get("status") == "playing":
                        await self.advance_device_queue(device_id, delta=1, auto_triggered=True)
                except asyncio.CancelledError:
                    elapsed = pos + sent_frames * 0.06
                    if elapsed > 1.0:
                        await self.report_hardware_progress(device_id, elapsed)
                except Exception:
                    pass

            xz_entry["stream_task"] = asyncio.create_task(_stream_opus_to_xiaozhi())

    async def send_speaker_control(self, device_id: str, command: str) -> None:
        if command in ("pause", "stop"):
            await self.update_device_state(device_id, playing_title="已暂停" if command == "pause" else "待机中")
        spk_ws = self.speaker_conns.get(device_id)
        if spk_ws:
            try:
                await spk_ws.send_text(json.dumps({"type": "control", "command": command}))
            except Exception:
                pass
        mi_did = await self._get_xiaoai_mi_did(device_id)
        if mi_did:
            try:
                from app.services.xiaoai_bridge import xiaoai_bridge

                await xiaoai_bridge.control(mi_did, command)
            except Exception:
                pass
        xz_entry = self.xiaozhi_conns.get(device_id)
        if xz_entry and command in ("pause", "stop"):
            xz_entry["abort"] = True

    async def report_hardware_progress(self, device_id: str, position_sec: float) -> None:
        """接收音箱客户端/小爱真机/ESP32 上报的精确播放秒数，并持久化写入三级断点表。"""
        sess = self.playback_sessions.get(device_id)
        if not sess or not sess.get("queue"):
            return
        idx = int(sess.get("current_index") or 0)
        if not (0 <= idx < len(sess["queue"])):
            return
        pos = max(0.0, float(position_sec or 0.0))
        sess["current_position_sec"] = pos
        tr = sess["queue"][idx]
        aid = sess.get("album_id") or tr.get("album_id")
        tid = int(tr.get("id") or 0)
        if aid and tid > 0:
            await self._sync_series_album_progress(int(aid), tid, position_sec=pos, increment_play=False)

    def _cancel_session_watcher(self, device_id: str) -> None:
        sess = self.playback_sessions.get(device_id)
        if sess and sess.get("auto_task") and not sess["auto_task"].done():
            sess["auto_task"].cancel()
            sess["auto_task"] = None

    async def _auto_advance_watcher(self, device_id: str) -> None:
        """监控睡眠倒计时及曲目自然时长结束后自动推进下一集。"""
        try:
            while True:
                sess = self.playback_sessions.get(device_id)
                if not sess or sess.get("status") != "playing":
                    return
                now = time.time()
                sleep_until = sess.get("sleep_until_ts")
                cur_idx = int(sess.get("current_index") or 0)
                queue = sess.get("queue") or []
                cur_track = queue[cur_idx] if 0 <= cur_idx < len(queue) else None
                dur = float(cur_track.get("duration_sec") or 0.0) if cur_track else 0.0
                track_started = float(sess.get("started_at") or now)

                waits: list[float] = []
                if sleep_until:
                    waits.append(max(0.1, float(sleep_until) - now))
                if dur > 1.0:
                    waits.append(max(0.2, (track_started + dur + 1.0) - now))

                if not waits:
                    return
                delay = min(waits)
                await asyncio.sleep(delay)

                sess = self.playback_sessions.get(device_id)
                if not sess or sess.get("status") != "playing":
                    return
                now = time.time()
                if sess.get("sleep_until_ts") and now >= float(sess["sleep_until_ts"]) - 0.15:
                    await self.control_device_queue(device_id, "stop")
                    return
                if dur > 1.0 and now >= (float(sess.get("started_at") or now) + dur + 0.5):
                    await self.advance_device_queue(device_id, delta=1, auto_triggered=True)
                    return
        except asyncio.CancelledError:
            return

    async def _sync_series_album_progress(
        self,
        album_id: int | None,
        track_id: int,
        position_sec: float = 0.0,
        increment_play: bool = True,
    ) -> None:
        """统一同步单集、季/专辑与一级系列的最新播放位置。"""
        if not album_id or track_id <= 0:
            return
        ts = now_iso()
        pos = max(0.0, float(position_sec or 0.0))
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
                await conn.execute(
                    """
                    UPDATE media_series
                    SET last_album_id = ?, last_track_id = ?, last_position_sec = ?, last_played_at = ?
                    WHERE id = ?
                    """,
                    (album_id, track_id, pos, ts, int(arow["series_id"])),
                )
            await conn.commit()

    async def _find_next_season_in_series(
        self,
        series_id: int,
        current_album_id: int,
        current_season_num: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        """在同系列下查找下一季及其可播放单集队列，支持播完本季最后一集后自动跨季连播。"""
        async with get_db() as conn:
            cur = await conn.execute(
                """
                SELECT * FROM media_albums
                WHERE series_id = ? AND is_inbox = 0
                  AND (season_num > ? OR (season_num = ? AND id > ?))
                ORDER BY season_num ASC, id ASC
                """,
                (series_id, current_season_num, current_season_num, current_album_id),
            )
            candidates = [dict(r) for r in await cur.fetchall()]
            for alb in candidates:
                cur_t = await conn.execute(
                    "SELECT * FROM media_tracks WHERE album_id = ? ORDER BY episode_num ASC, id ASC",
                    (alb["id"],),
                )
                tracks = []
                for r in await cur_t.fetchall():
                    d = dict(r)
                    d["album_title"] = alb["title"]
                    d["media_kind"] = "track"
                    d["stream_url"] = f"/api/media/tracks/{d['id']}/stream"
                    tracks.append(d)
                if tracks:
                    return alb, tracks
        return None

    async def push_queue_to_device(
        self,
        device_id: str,
        tracks: list[dict[str, Any]],
        album_id: int | None = None,
        album_title: str = "",
        start_index: int = 0,
        loop_mode: str = "sequential",
        sleep_minutes: int | None = None,
        sleep_episodes: int | None = None,
        series_id: int | None = None,
        start_position_sec: float = 0.0,
    ) -> dict[str, Any]:
        """在服务端为指定音箱建立连播队列会话并立即下发首集播放（支持断点秒数与跨季元数据）。"""
        if not tracks:
            raise ValueError("推送队列为空")
        self._cancel_session_watcher(device_id)

        idx = max(0, min(start_index, len(tracks) - 1))
        sanitized: list[dict[str, Any]] = []
        for t in tracks:
            d = dict(t)
            d["stream_url"] = _resolve_stream_url(d)
            sanitized.append(d)

        resolved_album_id = album_id or sanitized[idx].get("album_id")
        resolved_series_id = series_id
        season_num = 1
        season_label = ""
        if resolved_album_id:
            async with get_db() as conn:
                cur_a = await conn.execute(
                    "SELECT series_id, season_num, season_label, title FROM media_albums WHERE id = ?",
                    (resolved_album_id,),
                )
                arow = await cur_a.fetchone()
                if arow:
                    if resolved_series_id is None and arow["series_id"]:
                        resolved_series_id = int(arow["series_id"])
                    season_num = int(arow["season_num"] or 1)
                    season_label = str(arow["season_label"] or "")
                    if not album_title:
                        album_title = str(arow["title"] or "")

        pos = max(0.0, float(start_position_sec or 0.0))
        sleep_until = (time.time() + max(1, int(sleep_minutes)) * 60) if sleep_minutes else None
        sess: dict[str, Any] = {
            "device_id": device_id,
            "series_id": resolved_series_id,
            "season_num": season_num,
            "season_label": season_label,
            "album_id": resolved_album_id,
            "album_title": album_title or str(sanitized[idx].get("album_title") or ""),
            "queue": sanitized,
            "current_index": idx,
            "start_position_sec": pos,
            "status": "playing",
            "loop_mode": loop_mode if loop_mode in ("sequential", "repeat_one", "shuffle") else "sequential",
            "sleep_until_ts": sleep_until,
            "sleep_max_episodes": int(sleep_episodes) if sleep_episodes and sleep_episodes > 0 else None,
            "episodes_played": 0,
            "started_at": time.time(),
            "auto_task": None,
        }
        self.playback_sessions[device_id] = sess

        cur_tr = sanitized[idx]
        if resolved_album_id and int(cur_tr.get("id") or 0) > 0:
            await self._sync_series_album_progress(int(resolved_album_id), int(cur_tr["id"]), position_sec=pos, increment_play=True)

        await self.cast_track_to_device(device_id, cur_tr, start_position_sec=pos)
        sess["auto_task"] = asyncio.create_task(self._auto_advance_watcher(device_id))
        await self.broadcast_web({"type": "playback_session", "device_id": device_id})
        return await self.get_room_playback_snapshot_by_id(device_id)

    async def advance_device_queue(
        self,
        device_id: str,
        delta: int = 1,
        auto_triggered: bool = False,
    ) -> dict[str, Any] | None:
        """推进或回退指定音箱的连播队列，支持按集数睡眠定时截停与同系列跨季自动顺延连播。"""
        sess = self.playback_sessions.get(device_id)
        if not sess or not sess.get("queue"):
            return None
        self._cancel_session_watcher(device_id)

        if auto_triggered:
            sess["episodes_played"] = int(sess.get("episodes_played") or 0) + 1
            max_eps = sess.get("sleep_max_episodes")
            if max_eps and sess["episodes_played"] >= int(max_eps):
                return await self.control_device_queue(device_id, "stop")

        queue = sess["queue"]
        cur = int(sess.get("current_index") or 0)
        loop_mode = sess.get("loop_mode", "sequential")

        # 同系列跨季无缝连播：顺序模式下播完本季最后一集，自动接续下一季第 1 集
        if (
            delta > 0
            and loop_mode == "sequential"
            and cur + delta >= len(queue)
            and sess.get("series_id")
            and sess.get("album_id")
        ):
            nxt_season = await self._find_next_season_in_series(
                series_id=int(sess["series_id"]),
                current_album_id=int(sess["album_id"]),
                current_season_num=int(sess.get("season_num") or 1),
            )
            if nxt_season:
                next_alb, next_tracks = nxt_season
                sess["album_id"] = int(next_alb["id"])
                sess["album_title"] = str(next_alb["title"])
                sess["season_num"] = int(next_alb.get("season_num") or 1)
                sess["season_label"] = str(next_alb.get("season_label") or "")
                sess["queue"] = next_tracks
                sess["current_index"] = 0
                sess["start_position_sec"] = 0.0
                sess["status"] = "playing"
                sess["started_at"] = time.time()
                next_tr = next_tracks[0]
                if int(next_tr.get("id") or 0) > 0:
                    await self._sync_series_album_progress(int(next_alb["id"]), int(next_tr["id"]), position_sec=0.0, increment_play=True)
                await self.cast_track_to_device(device_id, next_tr, start_position_sec=0.0)
                sess["auto_task"] = asyncio.create_task(self._auto_advance_watcher(device_id))
                await self.broadcast_web({"type": "playback_session", "device_id": device_id})
                return await self.get_room_playback_snapshot_by_id(device_id)

        if auto_triggered and loop_mode == "repeat_one":
            next_idx = cur
        elif loop_mode == "shuffle" and len(queue) > 1:
            choices = [i for i in range(len(queue)) if i != cur]
            next_idx = random.choice(choices)
        else:
            next_idx = (cur + delta) % len(queue)

        sess["current_index"] = next_idx
        sess["start_position_sec"] = 0.0
        sess["status"] = "playing"
        sess["started_at"] = time.time()
        next_tr = queue[next_idx]

        album_id = sess.get("album_id")
        if album_id and int(next_tr.get("id") or 0) > 0:
            await self._sync_series_album_progress(int(album_id), int(next_tr["id"]), position_sec=0.0, increment_play=True)

        await self.cast_track_to_device(device_id, next_tr, start_position_sec=0.0)
        sess["auto_task"] = asyncio.create_task(self._auto_advance_watcher(device_id))
        await self.broadcast_web({"type": "playback_session", "device_id": device_id})
        return await self.get_room_playback_snapshot_by_id(device_id)

    async def control_device_queue(
        self,
        device_id: str,
        action: str,
        index: int | None = None,
        delta_sec: float | None = None,
        loop_mode: str | None = None,
        sleep_minutes: int | None = None,
        sleep_episodes: int | None = None,
    ) -> dict[str, Any]:
        """操控音箱房间播控队列（暂停/恢复/停止/上下集/跳集/重播/快进快退/循环/睡眠定时）。"""
        sess = self.playback_sessions.get(device_id)

        if action == "next":
            res = await self.advance_device_queue(device_id, delta=1, auto_triggered=False)
            return res or await self.get_room_playback_snapshot_by_id(device_id)
        if action == "prev":
            res = await self.advance_device_queue(device_id, delta=-1, auto_triggered=False)
            return res or await self.get_room_playback_snapshot_by_id(device_id)

        if action == "replay" and sess and sess.get("queue"):
            self._cancel_session_watcher(device_id)
            idx = int(sess.get("current_index") or 0)
            sess["start_position_sec"] = 0.0
            sess["current_position_sec"] = 0.0
            sess["status"] = "playing"
            sess["started_at"] = time.time()
            tr = sess["queue"][idx]
            if sess.get("album_id") and int(tr.get("id") or 0) > 0:
                await self._sync_series_album_progress(int(sess["album_id"]), int(tr["id"]), position_sec=0.0, increment_play=True)
            await self.cast_track_to_device(device_id, tr, start_position_sec=0.0)
            sess["auto_task"] = asyncio.create_task(self._auto_advance_watcher(device_id))
        elif action == "seek_delta" and sess and sess.get("queue"):
            self._cancel_session_watcher(device_id)
            idx = int(sess.get("current_index") or 0)
            tr = sess["queue"][idx]
            est_pos = float(sess.get("current_position_sec") or (float(sess.get("start_position_sec") or 0.0) + max(0.0, time.time() - float(sess.get("started_at") or time.time()))))
            dur = float(tr.get("duration_sec") or 0.0)
            new_pos = max(0.0, est_pos + float(delta_sec or 0.0))
            if dur > 2.0:
                new_pos = min(new_pos, dur - 1.0)
            sess["start_position_sec"] = new_pos
            sess["current_position_sec"] = new_pos
            sess["status"] = "playing"
            sess["started_at"] = time.time()
            if sess.get("album_id") and int(tr.get("id") or 0) > 0:
                await self._sync_series_album_progress(int(sess["album_id"]), int(tr["id"]), position_sec=new_pos, increment_play=False)
            await self.cast_track_to_device(device_id, tr, start_position_sec=new_pos)
            sess["auto_task"] = asyncio.create_task(self._auto_advance_watcher(device_id))
        elif action == "jump" and sess and index is not None and 0 <= index < len(sess["queue"]):
            self._cancel_session_watcher(device_id)
            sess["current_index"] = index
            sess["start_position_sec"] = 0.0
            sess["current_position_sec"] = 0.0
            sess["status"] = "playing"
            sess["started_at"] = time.time()
            tr = sess["queue"][index]
            if sess.get("album_id") and int(tr.get("id") or 0) > 0:
                await self._sync_series_album_progress(int(sess["album_id"]), int(tr["id"]), position_sec=0.0, increment_play=True)
            await self.cast_track_to_device(device_id, tr, start_position_sec=0.0)
            sess["auto_task"] = asyncio.create_task(self._auto_advance_watcher(device_id))
        elif action == "pause":
            self._cancel_session_watcher(device_id)
            if sess:
                est_pos = float(sess.get("current_position_sec") or (float(sess.get("start_position_sec") or 0.0) + max(0.0, time.time() - float(sess.get("started_at") or time.time()))))
                sess["current_position_sec"] = est_pos
                sess["start_position_sec"] = est_pos
                sess["status"] = "paused"
                await self.report_hardware_progress(device_id, est_pos)
            await self.send_speaker_control(device_id, "pause")
        elif action == "stop":
            self._cancel_session_watcher(device_id)
            if sess:
                sess["status"] = "stopped"
                sess["sleep_until_ts"] = None
                sess["sleep_max_episodes"] = None
            await self.send_speaker_control(device_id, "stop")
        elif action == "resume":
            if sess and sess.get("queue"):
                self._cancel_session_watcher(device_id)
                idx = int(sess.get("current_index") or 0)
                resume_pos = float(sess.get("current_position_sec") or sess.get("start_position_sec") or 0.0)
                sess["status"] = "playing"
                sess["started_at"] = time.time()
                await self.cast_track_to_device(device_id, sess["queue"][idx], start_position_sec=resume_pos)
                sess["auto_task"] = asyncio.create_task(self._auto_advance_watcher(device_id))
        elif action == "set_loop" and sess and loop_mode in ("sequential", "repeat_one", "shuffle"):
            sess["loop_mode"] = loop_mode
        elif action == "set_sleep" and sess:
            self._cancel_session_watcher(device_id)
            sess["sleep_until_ts"] = (time.time() + max(1, int(sleep_minutes)) * 60) if sleep_minutes and sleep_minutes > 0 else None
            sess["sleep_max_episodes"] = int(sleep_episodes) if sleep_episodes and sleep_episodes > 0 else None
            sess["episodes_played"] = 0
            if sess.get("status") == "playing":
                sess["auto_task"] = asyncio.create_task(self._auto_advance_watcher(device_id))

        await self.broadcast_web({"type": "playback_session", "device_id": device_id})
        return await self.get_room_playback_snapshot_by_id(device_id)

    def get_room_playback_snapshot(self, dev: dict[str, Any]) -> dict[str, Any]:
        """将设备状态与其当前连播队列快照组合返回（剔除不可序列化协程对象）。"""
        did = dev["id"]
        sess = self.playback_sessions.get(did)
        res = dict(dev)
        if not sess:
            res["session"] = None
            return res

        now = time.time()
        sleep_until = sess.get("sleep_until_ts")
        rem_sec = max(0, int(sleep_until - now)) if sleep_until else None
        max_eps = sess.get("sleep_max_episodes")
        rem_eps = max(0, int(max_eps) - int(sess.get("episodes_played") or 0)) if max_eps else None
        cur_idx = int(sess.get("current_index") or 0)
        queue = sess.get("queue") or []
        cur_tr = queue[cur_idx] if 0 <= cur_idx < len(queue) else None

        res["session"] = {
            "series_id": sess.get("series_id"),
            "season_num": sess.get("season_num", 1),
            "season_label": sess.get("season_label", ""),
            "album_id": sess.get("album_id"),
            "album_title": sess.get("album_title", ""),
            "status": sess.get("status", "stopped"),
            "loop_mode": sess.get("loop_mode", "sequential"),
            "current_index": cur_idx,
            "start_position_sec": float(sess.get("start_position_sec") or 0.0),
            "current_track": {
                "id": cur_tr.get("id"),
                "title": cur_tr.get("title"),
                "episode_num": cur_tr.get("episode_num", cur_idx + 1),
                "duration_sec": cur_tr.get("duration_sec", 0),
                "stream_url": cur_tr.get("stream_url"),
            }
            if cur_tr
            else None,
            "queue": [
                {
                    "id": q.get("id"),
                    "title": q.get("title"),
                    "episode_num": q.get("episode_num", i + 1),
                    "duration_sec": q.get("duration_sec", 0),
                    "stream_url": q.get("stream_url"),
                }
                for i, q in enumerate(queue)
            ],
            "sleep_remaining_sec": rem_sec,
            "sleep_remaining_episodes": rem_eps,
        }
        return res

    async def get_room_playback_snapshot_by_id(self, device_id: str) -> dict[str, Any]:
        async with get_db() as conn:
            cur = await conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            row = await cur.fetchone()
            if not row:
                return {"id": device_id, "session": None}
            return self.get_room_playback_snapshot(dict(row))

    async def push_announcement(
        self,
        device_id: str,
        text: str,
        motion: dict[str, Any] | None = None,
        tts_path: Path | None = None,
        track: dict[str, Any] | None = None,
        restore_playback: bool = True,
    ) -> None:
        # 若音箱正在放故事/音乐，记下当前状态以便语音播报完成后自动无缝续播
        sess = self.playback_sessions.get(device_id)
        was_playing = bool(restore_playback and track is None and sess and sess.get("status") == "playing" and sess.get("queue"))
        resume_pos = 0.0
        resume_track: dict[str, Any] | None = None
        if was_playing and sess:
            idx = int(sess.get("current_index") or 0)
            if 0 <= idx < len(sess["queue"]):
                resume_track = sess["queue"][idx]
                resume_pos = float(
                    sess.get("current_position_sec")
                    or (float(sess.get("start_position_sec") or 0.0) + max(0.0, time.time() - float(sess.get("started_at") or time.time())))
                )

        playing = f"正在播放：{track['title']}" if track else f"语音播报：{text[:18]}"
        locked = not bool((motion or {"allowed": True}).get("allowed", True))
        await self.update_device_state(device_id, playing_title=playing, motion_locked=locked)

        tts_url = f"/api/tts-cache/{tts_path.name}" if tts_path else None
        track_url = _resolve_stream_url(track)

        await self.broadcast_web(
            {
                "type": "announcement",
                "device_id": device_id,
                "text": text,
                "motion": motion,
                "tts_url": tts_url,
                "track": track,
                "track_url": track_url,
                "restore_after": was_playing,
                "timestamp": now_iso(),
            }
        )

        spk_ws = self.speaker_conns.get(device_id)
        if spk_ws:
            try:
                await spk_ws.send_text(
                    json.dumps(
                        {
                            "type": "play",
                            "text": text,
                            "tts_url": tts_url,
                            "track_url": track_url,
                            "restore_after": was_playing,
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception:
                pass

        mi_did = await self._get_xiaoai_mi_did(device_id)
        if mi_did:
            try:
                from app.services.xiaoai_bridge import xiaoai_bridge

                await xiaoai_bridge.speak(mi_did, text)
                if was_playing and resume_track:
                    est_tts_sec = max(3.0, min(14.0, len(text) / 4.2 + 1.5))

                    async def _restore_xiaoai() -> None:
                        await asyncio.sleep(est_tts_sec)
                        cur_sess = self.playback_sessions.get(device_id)
                        if cur_sess and cur_sess.get("status") == "playing":
                            await self.cast_track_to_device(device_id, resume_track, start_position_sec=resume_pos)

                    asyncio.create_task(_restore_xiaoai())
            except Exception:
                pass

        xz_entry = self.xiaozhi_conns.get(device_id)
        if xz_entry:
            ws: WebSocket = xz_entry["ws"]
            session_id = xz_entry.get("session_id", "echomind-push")
            try:
                if tts_path and tts_path.exists():
                    prev_task = xz_entry.get("stream_task")
                    if prev_task and not prev_task.done():
                        xz_entry["abort"] = True
                        prev_task.cancel()
                    await ws.send_text(json.dumps({"type": "tts", "state": "start", "session_id": session_id}))
                    await ws.send_text(
                        json.dumps({"type": "tts", "state": "sentence_start", "text": text, "session_id": session_id}, ensure_ascii=False)
                    )
                    frames = await encode_file_to_opus_frames(tts_path)
                    for pkt in frames:
                        await ws.send_bytes(pkt)
                        await asyncio.sleep(0.055)
                    await ws.send_text(json.dumps({"type": "tts", "state": "stop", "session_id": session_id}))
                    if was_playing and resume_track:
                        await self.cast_track_to_device(device_id, resume_track, start_position_sec=resume_pos)
            except Exception:
                pass


device_manager = DeviceConnectionManager()

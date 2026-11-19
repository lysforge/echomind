"""ESP32 语音机器人（可选终端）小智协议网关：HTTP /xiaozhi/ota/ + WebSocket /xiaozhi/v1/（自动发现/配对）。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.config import get_lan_ip, load_settings
from app.gateways.manager import device_manager
from app.services.audio_norm import encode_file_to_opus_frames
from app.services.brain import SafeMotionGuard, process_user_turn
from app.services.tts_asr import synthesize_speech, transcribe_audio
from app.services.voiceprint import identify_speaker

router = APIRouter()


@router.api_route("/xiaozhi/ota/", methods=["GET", "POST"])
@router.api_route("/xiaozhi/ota", methods=["GET", "POST"])
async def xiaozhi_ota(request: Request) -> dict[str, Any]:
    settings = load_settings()
    lan_ip = get_lan_ip()
    host_header = request.headers.get("host")
    ws_host = host_header if host_header else f"{lan_ip}:{settings.server_port}"
    device_id = request.headers.get("device-id") or request.headers.get("Device-Id") or "esp32-unpaired"

    return {
        "server_time": {"timestamp": int(time.time() * 1000), "timezone_offset": 480},
        "firmware": {"version": "2.0.0-echomind", "url": ""},
        "websocket": {"url": f"ws://{ws_host}/xiaozhi/v1/", "token": ""},
        "device_id": device_id,
    }


@router.websocket("/xiaozhi/v1/")
async def xiaozhi_ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    headers = {k.lower(): v for k, v in websocket.headers.items()}
    device_id = headers.get("device-id") or websocket.query_params.get("device-id") or f"esp32_{id(websocket)}"
    token = headers.get("authorization", "").replace("Bearer ", "").strip() or websocket.query_params.get("token") or ""
    client_ip = websocket.client.host if websocket.client else ""
    session_id = str(uuid.uuid4())

    try:
        is_paired, dev = await device_manager.register_or_discover_device(
            device_id=device_id,
            device_type="esp32_robot",
            default_name=f"ESP32 终端 ({device_id})",
            client_ip=client_ip,
            provided_token=token,
        )
    except PermissionError:
        await websocket.close(code=4003)
        return

    conn_state: dict[str, Any] = {
        "ws": websocket,
        "session_id": session_id,
        "mcp_enabled": False,
        "mcp_tools": [],
        "abort": False,
        "paired": is_paired,
        "pair_code": dev.get("pair_code", ""),
        "audio_buffer": bytearray(),
    }
    device_manager.xiaozhi_conns[device_id] = conn_state
    if is_paired:
        await device_manager.update_device_state(device_id, online=True, playing_title="已连线，待机中")

    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                conn_state["audio_buffer"].extend(msg["bytes"])
                continue
            text_raw = msg.get("text")
            if not text_raw:
                continue
            try:
                data = json.loads(text_raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")
            if msg_type == "hello":
                features = data.get("features") or {}
                conn_state["mcp_enabled"] = bool(features.get("mcp"))
                welcome = {
                    "type": "hello",
                    "transport": "websocket",
                    "session_id": session_id,
                    "audio_params": data.get("audio_params") or {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
                }
                await websocket.send_text(json.dumps(welcome))
                if conn_state["mcp_enabled"]:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "mcp",
                                "payload": {
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "initialize",
                                    "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "EchoMind", "version": "2.0"}},
                                },
                            }
                        )
                    )
                    await websocket.send_text(
                        json.dumps({"type": "mcp", "payload": {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}})
                    )

            elif msg_type == "mcp":
                payload = data.get("payload") or {}
                if payload.get("id") == 2 and isinstance(payload.get("result"), dict):
                    tools = [t.get("name") for t in payload["result"].get("tools", []) if isinstance(t, dict) and t.get("name")]
                    conn_state["mcp_tools"] = tools

            elif msg_type == "abort":
                conn_state["abort"] = True
                conn_state["audio_buffer"].clear()

            elif msg_type == "listen":
                state = data.get("state")
                if state == "start":
                    conn_state["abort"] = False
                    conn_state["audio_buffer"].clear()
                elif state == "detect":
                    wake_text = str(data.get("text") or "你好").strip()
                    await _handle_robot_utterance(websocket, device_id, session_id, conn_state, wake_text)
                elif state == "stop":
                    raw_buf = bytes(conn_state["audio_buffer"])
                    conn_state["audio_buffer"].clear()
                    spoken_text = str(data.get("text") or "").strip()
                    if not spoken_text and len(raw_buf) > 400:
                        spoken_text = await transcribe_audio(raw_buf, input_ext=".ogg")
                    if spoken_text:
                        await _handle_robot_utterance(websocket, device_id, session_id, conn_state, spoken_text, raw_buf)
    except WebSocketDisconnect:
        pass
    finally:
        device_manager.xiaozhi_conns.pop(device_id, None)
        await device_manager.update_device_state(device_id, online=False, playing_title="离线")


async def _handle_robot_utterance(
    websocket: WebSocket,
    device_id: str,
    session_id: str,
    conn_state: dict[str, Any],
    user_text: str,
    audio_bytes: bytes | None = None,
) -> None:
    speaker = await identify_speaker(audio_bytes=audio_bytes)
    brain_resp = await process_user_turn(user_text, speaker, device_id=device_id)

    motion = brain_resp.motion_command or SafeMotionGuard.sanitize("nod")
    locked = not bool(motion.get("allowed", True))
    playing = f"正在播放：{brain_resp.play_track['title']}" if brain_resp.play_track else "语音交互中"
    await device_manager.update_device_state(device_id, online=True, playing_title=playing, motion_locked=locked)

    await websocket.send_text(json.dumps({"type": "stt", "text": user_text, "session_id": session_id}, ensure_ascii=False))

    tts_path = await synthesize_speech(brain_resp.reply_text, voice=speaker.tts_voice, rate=speaker.tts_rate)
    await websocket.send_text(json.dumps({"type": "tts", "state": "start", "session_id": session_id}))
    await websocket.send_text(
        json.dumps({"type": "tts", "state": "sentence_start", "text": brain_resp.reply_text, "session_id": session_id}, ensure_ascii=False)
    )
    try:
        frames = await encode_file_to_opus_frames(tts_path)
        for pkt in frames:
            if conn_state.get("abort"):
                break
            await websocket.send_bytes(pkt)
            await asyncio.sleep(0.055)
    except Exception:
        pass
    await websocket.send_text(json.dumps({"type": "tts", "state": "stop", "session_id": session_id}))

    if brain_resp.play_track and not conn_state.get("abort"):
        try:
            track_frames = await encode_file_to_opus_frames(brain_resp.play_track["file_path"])
            await websocket.send_text(json.dumps({"type": "tts", "state": "start", "session_id": session_id}))
            for pkt in track_frames:
                if conn_state.get("abort"):
                    break
                await websocket.send_bytes(pkt)
                await asyncio.sleep(0.055)
            await websocket.send_text(json.dumps({"type": "tts", "state": "stop", "session_id": session_id}))
        except Exception:
            pass

    if motion.get("allowed") and conn_state.get("mcp_tools"):
        await websocket.send_text(
            json.dumps(
                {
                    "type": "mcp",
                    "payload": {
                        "jsonrpc": "2.0",
                        "id": int(time.time()) % 100000,
                        "method": "tools/call",
                        "params": {
                            "name": conn_state["mcp_tools"][0],
                            "arguments": {
                                "action": motion.get("action"),
                                "duration_ms": motion.get("duration_ms"),
                                "speed": motion.get("speed"),
                            },
                        },
                    },
                },
                ensure_ascii=False,
            )
        )
